"""Live check of the caseworker review flow on real Meko + Gemini (run in Colab, ~6 Gemini calls, ~1-2 min):
    ask (fresh) -> caseworker approves an edited fix + promote -> same issue in Hindi -> must be REUSED.
Also checks a rejected fix is logged but not saved. Uses a run tag, so older memories cannot interfere.
    python -u scripts/test_review_live.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import build  # noqa: E402
from saathi.desk import HelpDesk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TICKETS = [json.loads(x) for x in (ROOT / "data/tickets.jsonl").read_text(encoding="utf-8").splitlines()]


async def main() -> int:
    meko, llm, kb = build(offline=False)
    tag = f"review-live-{int(time.time())}"
    ok = True
    async with meko:
        desk = HelpDesk(meko, llm, kb, run_tag=tag)
        print(f"[run tag] {tag}")

        # 1. Fresh answer (English)
        first = await desk.handle(TICKETS[0]["text"], "R1")
        print(f"[1 fresh] path={first.path} tokens={first.total_tokens} conv={first.conversation_id}")
        print(f"          fix proposed: {first.general_fix[:200]}")
        ok &= first.path == "fresh"

        # 2. Caseworker edits + approves + promotes
        edited = (first.general_fix or first.summary_en) + " Confirm the change on the official PM-KISAN portal."
        mem_id = await desk.approve(first, caseworker="live-test", promote=True, edited_fix=edited)
        print(f"[2 approve] memory_id={mem_id}")
        print(f"[2 promote] {'OK' if not desk.last_promote_error else 'FAILED: ' + desk.last_promote_error}")
        ok &= bool(mem_id)

        # 3. Same issue in Hindi -> should reuse the approved fix
        second = await desk.handle(TICKETS[1]["text"], "R2")
        print(f"[3 repeat] path={second.path} reused={second.reused_memory_id} tokens={second.total_tokens}")
        print(f"           steps: {second.steps}")
        ok &= second.path == "reused" and second.reused_memory_id == mem_id

        # 4. Reject flow: different issue, rejected -> logged, not saved, next one stays fresh
        third = await desk.handle(TICKETS[13]["text"], "R3")
        await desk.reject(third, "live-test", "Live test: rejecting on purpose")
        print(f"[4 reject] logged in conversation {third.conversation_id} (path was {third.path})")

    print("[meko timings] " + ", ".join(f"{k} {sum(v)/len(v):.1f}s" for k, v in meko.timings.items()))
    print("[RESULT] " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
