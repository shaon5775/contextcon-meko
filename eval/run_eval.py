"""Compare the baseline (full rulebook in every prompt, no memory) with Meko (retrieval + shared memory).

    python eval/run_eval.py              # live: Meko + Gemini (needs .env)
    python eval/run_eval.py --offline    # no network: fake Meko + mock LLM (checks the pipeline)

The simulated caseworker approves a fresh answer only when it solved the right issue and contains the
expected key facts. Writes eval/results.csv and eval/results.md (also stored in Meko as an artifact).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import ROOT, build  # noqa: E402
from saathi.desk import AGENT_CASEWORKER, HelpDesk  # noqa: E402

OUT = ROOT / "eval"


def load_tickets() -> list[dict]:
    lines = (ROOT / "data" / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def missing_facts(res, ticket) -> list[str]:
    """Expected key facts not found. Each fact may list equivalent wordings: "bpl|below poverty line".
    A fact starting with "!" must NOT appear (e.g. "!not eligible" when the right answer is "eligible")."""
    text = f"{res.summary_en} {res.answer}".lower()
    missing = []
    for k in ticket["keywords"]:
        if k.startswith("!"):
            if any(alt.strip().lower() in text for alt in k[1:].split("|")):
                missing.append(k)
        elif not any(alt.strip().lower() in text for alt in k.split("|")):
            missing.append(k.split("|")[0])
    return missing


def is_correct(res, ticket) -> bool:
    return res.issue_key == ticket["issue"] and not missing_facts(res, ticket)


async def run_mode(use_memory: bool, offline: bool, tickets: list[dict]) -> list[dict]:
    meko, llm, knowledge = build(offline=offline, use_memory=use_memory)
    rows = []
    async with meko:
        run_tag = f"eval-{uuid.uuid4().hex[:8]}" if use_memory else None
        if run_tag:
            print(f"Meko run tag: {run_tag} (only fixes approved in this run are reused)")
        desk = HelpDesk(meko, llm, knowledge, use_memory=use_memory, run_tag=run_tag)
        if use_memory:   # every ticket + approval also becomes a row in the Postgres ledger inside the datapack
            try:
                if offline:
                    from saathi.ledger import SqliteLedger
                    desk.ledger = SqliteLedger()
                else:
                    from saathi.config import Settings
                    from saathi.desk import AGENT_TRIAGE
                    from saathi.ledger import PgLedger
                    lconv = await meko.conversation_create(AGENT_TRIAGE, "eval ledger")
                    desk.ledger = await PgLedger.connect(meko, lconv, Settings().meko_api_key)
                print("Postgres ledger: connected")
            except Exception as e:  # noqa: BLE001 - the evaluation still runs without it
                print(f"Postgres ledger: not used ({str(e)[:120]})")
        seen: set[str] = set()
        for t in tickets:
            res = await desk.handle(t["text"], t["id"])
            ok = is_correct(res, t)
            missing = missing_facts(res, t)
            approved = None
            if use_memory and res.path == "fresh" and ok:
                approved = await desk.approve(res, caseworker="simulated-caseworker")
            rows.append({**res.to_dict(), "expected_issue": t["issue"], "lang": t["lang"], "correct": ok,
                         "missing_facts": "; ".join(missing), "first_time": t["issue"] not in seen,
                         "approved_memory_id": approved})
            seen.add(t["issue"])
            why = "" if ok else (f"  (issue {res.issue_key})" if res.issue_key != t["issue"] else f"  (missing: {', '.join(missing)})")
            print(f"[{res.mode:8}] {t['id']} {res.path:8} tokens={res.total_tokens:6} correct={ok}{why}")
        timings = getattr(meko, "timings", None)
        if use_memory and timings:
            print("Meko call time (avg s):", ", ".join(f"{k}={sum(v) / len(v):.2f} x{len(v)}"
                                                   for k, v in sorted(timings.items())))
        if use_memory:
            report = summarize(rows, []).encode()
            conv = rows[-1]["conversation_id"] if rows else None
            if conv:
                await meko.artifact_put("meko-run-summary.md", report, "text/markdown", conv, AGENT_CASEWORKER)
            if getattr(desk, "ledger", None) is not None and conv:
                from saathi.ledger import audit_markdown
                audit = audit_markdown(desk.ledger.audit(run_tag=run_tag))
                print(audit)
                await meko.artifact_put("audit-report.md", audit.encode(), "text/markdown", conv, AGENT_CASEWORKER)
                (ROOT / "eval" / "audit-report.md").write_text(audit, encoding="utf-8")
    return rows


def _stats(rows: list[dict]) -> dict:
    n = len(rows) or 1
    return {
        "tickets": len(rows),
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "total_tokens": sum(r["total_tokens"] for r in rows),
        "tokens_per_ticket": round(sum(r["total_tokens"] for r in rows) / n),
        "avg_latency_s": round(sum(r["latency_s"] for r in rows) / n, 2),
        "avg_steps": round(sum(len(r["steps"]) for r in rows) / n, 1),
        "accuracy": f"{100 * sum(r['correct'] for r in rows) / n:.0f}%",
    }


def summarize(meko_rows: list[dict], base_rows: list[dict]) -> str:
    lines = ["# Yojana Saathi evaluation results", ""]
    table = [("Baseline (full rulebook, no memory)", base_rows), ("Meko (retrieval + shared memory)", meko_rows)]
    lines += ["| Run | Tickets | LLM calls | Total tokens | Tokens / ticket | Avg latency (s) | Avg steps | Accuracy |",
              "|---|---|---|---|---|---|---|---|"]
    for name, rows in table:
        if rows:
            s = _stats(rows)
            lines.append(f"| {name} | {s['tickets']} | {s['llm_calls']} | {s['total_tokens']:,} | "
                         f"{s['tokens_per_ticket']:,} | {s['avg_latency_s']} | {s['avg_steps']} | {s['accuracy']} |")
    if meko_rows:
        first = [r for r in meko_rows if r["first_time"]]
        repeat = [r for r in meko_rows if not r["first_time"]]
        reused = [r for r in repeat if r["path"] == "reused"]
        lines += ["", "## Meko: first-time vs repeat issues", "",
                  "| Group | Tickets | Tokens / ticket | Avg latency (s) | Avg steps | Accuracy |",
                  "|---|---|---|---|---|---|"]
        for name, rows in (("First time an issue is seen", first), ("Repeat issue", repeat)):
            if rows:
                s = _stats(rows)
                lines.append(f"| {name} | {s['tickets']} | {s['tokens_per_ticket']:,} | {s['avg_latency_s']} | "
                             f"{s['avg_steps']} | {s['accuracy']} |")
        lines += ["", f"Repeat issues answered by reusing a caseworker-approved fix: "
                      f"**{len(reused)} of {len(repeat)}**."]
    if meko_rows and base_rows:
        b, m = _stats(base_rows)["total_tokens"], _stats(meko_rows)["total_tokens"]
        if b:
            lines += ["", f"**Token reduction with Meko: {100 * (b - m) / b:.0f}%** "
                          f"({b:,} → {m:,} tokens for the same {len(meko_rows)} tickets)."]
    lines += ["", "Method: each ticket is triaged, then answered. Baseline pastes every knowledge document into the "
                  "specialist prompt and keeps no memory. Meko mode runs context_search first; if a caseworker-"
                  "approved fix for the same issue exists it is reused, otherwise the specialist answers from "
                  "retrieved chunks and the simulated caseworker approves correct answers into shared memory. "
                  "Correct = right issue + all expected key facts present."]
    return "\n".join(lines) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="fake Meko + mock LLM, no network")
    ap.add_argument("--limit", type=int, default=0, help="only the first N tickets")
    args = ap.parse_args()
    tickets = load_tickets()
    if args.limit:
        tickets = tickets[: args.limit]

    base = await run_mode(False, args.offline, tickets)
    meko = await run_mode(True, args.offline, tickets)

    OUT.mkdir(exist_ok=True)
    suffix = "-offline" if args.offline else ""
    with open(OUT / f"results{suffix}.csv", "w", newline="", encoding="utf-8") as f:
        keys = ["mode", "ticket_id", "lang", "path", "expected_issue", "issue_key", "first_time", "correct",
                "llm_calls", "input_tokens", "output_tokens", "total_tokens", "latency_s", "reused_memory_id",
                "approved_memory_id", "missing_facts", "summary_en", "answer", "steps"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows({**r, "steps": " | ".join(r.get("steps") or [])} for r in base + meko)
    md = summarize(meko, base)
    (OUT / f"results{suffix}.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    asyncio.run(main())
