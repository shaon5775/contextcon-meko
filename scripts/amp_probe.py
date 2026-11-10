"""READ-ONLY probe: which AMP (Postgres) tools does this Meko account expose, and with which inputs?
    python -u scripts/amp_probe.py
Prints tool names (all), then full input schemas of every tool whose name mentions amp / sql / postgres / database,
then calls the safe read-only list tools (amp_cluster_list, amp_core_budget) if they exist. Creates nothing.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import build  # noqa: E402

WORDS = ("amp", "sql", "postgres", "database", "branch", "compute", "cluster")
SAFE_READS = ("amp_core_budget", "amp_cluster_list")


async def main() -> None:
    meko, _, _ = build(offline=False)
    async with meko:
        tools = (await meko._session.list_tools()).tools
        print("ALL TOOLS:", ", ".join(sorted(t.name for t in tools)))
        for t in tools:
            if any(w in t.name.lower() for w in WORDS):
                print(f"\n== {t.name}\n   {(t.description or '').strip()[:400]}")
                print("   inputs:", json.dumps(t.inputSchema)[:900])
        names = {t.name for t in tools}
        for name in SAFE_READS:
            if name in names:
                try:
                    print(f"\n>> {name}:", json.dumps(await meko.call(name))[:900])
                except Exception as e:  # noqa: BLE001
                    print(f"\n>> {name} failed: {str(e)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
