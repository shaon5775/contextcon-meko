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


def is_correct(res, ticket) -> bool:
    text = f"{res.summary_en} {res.answer}".lower()
    return res.issue_key == ticket["issue"] and all(k.lower() in text for k in ticket["keywords"])


async def run_mode(use_memory: bool, offline: bool, tickets: list[dict]) -> list[dict]:
    meko, llm, knowledge = build(offline=offline, use_memory=use_memory)
    rows = []
    async with meko:
        run_tag = f"eval-{uuid.uuid4().hex[:8]}" if use_memory else None
        if run_tag:
            print(f"Meko run tag: {run_tag} (only fixes approved in this run are reused)")
        desk = HelpDesk(meko, llm, knowledge, use_memory=use_memory, run_tag=run_tag)
        seen: set[str] = set()
        for t in tickets:
            res = await desk.handle(t["text"], t["id"])
            ok = is_correct(res, t)
            approved = None
            if use_memory and res.path == "fresh" and ok:
                approved = await desk.approve(res, caseworker="simulated-caseworker")
            rows.append({**res.to_dict(), "expected_issue": t["issue"], "lang": t["lang"], "correct": ok,
                         "first_time": t["issue"] not in seen, "approved_memory_id": approved})
            seen.add(t["issue"])
            print(f"[{res.mode:8}] {t['id']} {res.path:8} tokens={res.total_tokens:6} correct={ok}")
        if use_memory:
            report = summarize(rows, []).encode()
            conv = rows[-1]["conversation_id"] if rows else None
            if conv:
                await meko.artifact_put("meko-run-summary.md", report, "text/markdown", conv, AGENT_CASEWORKER)
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
                "approved_memory_id"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(base + meko)
    md = summarize(meko, base)
    (OUT / f"results{suffix}.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    asyncio.run(main())
