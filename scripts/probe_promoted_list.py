"""Probe 2: list PROMOTED memories (memory_get_all promoted=True) and fetch one by id. No Gemini calls.
    python -u scripts/probe_promoted_list.py <memory_id> [<memory_id> ...]"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import build  # noqa: E402
from saathi.desk import AGENT_CASEWORKER, AGENT_TRIAGE  # noqa: E402


async def main() -> None:
    ids = sys.argv[1:]
    meko, _, _ = build(offline=False)
    async with meko:
        conv = await meko.conversation_create(AGENT_TRIAGE, "probe promoted list")
        res = await meko.call("memory_get_all", conversation_id=conv, agent_id=AGENT_CASEWORKER, promoted=True,
                              page_size=100)
        print("promoted reply keys:", sorted(res) if isinstance(res, dict) else type(res))
        rows = (res.get("promoted_memories") or []) if isinstance(res, dict) else res
        print(f"promoted rows: {len(rows)}  total={res.get('total') if isinstance(res, dict) else '?'}")
        for r in rows[:30]:
            print("  ", json.dumps(r)[:700])
            print("     text:", str(r.get("memory") or r.get("text"))[:120])
        for mid in ids:
            for agent in (AGENT_CASEWORKER, None):
                try:
                    one = await meko.call("memory_get_by_id", memory_id=mid, conversation_id=conv, agent_id=agent)
                    print(f"get_by_id {mid[:8]} agent={agent}:", json.dumps(one)[:500])
                except Exception as e:  # noqa: BLE001
                    print(f"get_by_id {mid[:8]} agent={agent}: ERROR {str(e)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
