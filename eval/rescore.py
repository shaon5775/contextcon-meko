"""Re-check a finished live run without calling any model again.

    python eval/rescore.py                      # uses eval/results.csv + data/tickets.jsonl
    python eval/rescore.py --show-wrong         # also prints every answer still marked wrong

Use it after changing how facts are checked (data/tickets.jsonl keywords). Every answer that is still marked
wrong is printed so a person can read it and decide; the grader should never be loosened without that check.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.run_eval import missing_facts, summarize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(ROOT / "eval" / "results.csv"))
    ap.add_argument("--show-wrong", action="store_true")
    args = ap.parse_args()
    tickets = {t["id"]: t for t in (json.loads(x) for x in
               (ROOT / "data" / "tickets.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())}
    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    for r in rows:
        res = SimpleNamespace(summary_en=r["summary_en"], answer=r["answer"], issue_key=r["issue_key"])
        t = tickets[r["ticket_id"]]
        miss = missing_facts(res, t)
        r["correct"] = r["issue_key"] == t["issue"] and not miss
        r["missing_facts"] = "; ".join(miss)
        r["steps"] = (r.get("steps") or "").split(" | ")
        r["first_time"] = r["first_time"] == "True"
        for k in ("llm_calls", "input_tokens", "output_tokens", "total_tokens"):
            r[k] = int(r[k])
        r["latency_s"] = float(r["latency_s"])
        if args.show_wrong and not r["correct"]:
            why = f"issue {r['issue_key']} (expected {t['issue']})" if r["issue_key"] != t["issue"] else f"missing {miss}"
            print(f"\n--- {r['mode']} {r['ticket_id']} [{r['lang']}] {r['path']}: {why}")
            print("Q:", t["text"])
            print("SUMMARY:", r["summary_en"][:400])
            print("ANSWER:", r["answer"][:500])
    base = [r for r in rows if r["mode"] == "baseline"]
    meko = [r for r in rows if r["mode"] == "meko"]
    print("\n" + summarize(meko, base))


if __name__ == "__main__":
    main()
