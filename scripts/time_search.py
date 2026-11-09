"""Time Meko retrieval settings on the live datapack (read-only: searches only, nothing is written).

    python scripts/time_search.py
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import Settings  # noqa: E402
from saathi.meko import MekoClient  # noqa: E402

AGENT = "yojana_saathi:triage"
QUERIES = ["PM-KISAN: name does not match Aadhaar", "Ayushman Vay Vandana card for a person aged 72",
           "Old-age pension eligibility, BPL household", "PM Ujjwala when the household already has LPG"]


async def timed(meko, tool, **args):
    t0 = time.perf_counter()
    res = await meko.call(tool, **args)
    return time.perf_counter() - t0, res


async def main() -> None:
    s = Settings()
    async with MekoClient(s.meko_api_key, s.meko_datapack_id) as meko:
        conv = await meko.conversation_create(AGENT, "search timing")
        settings = [
            ("context_search auto, limit 5", "context_search", {"limit": 5}),
            ("context_search auto, limit 3", "context_search", {"limit": 3}),
            ("context_search memory only", "context_search", {"limit": 5, "force_source": "memory"}),
            ("context_search knowledge only", "context_search", {"limit": 5, "force_source": "knowledge_base"}),
            ("memory_search", "memory_search", {"limit": 5}),
            ("knowledgebase_search", "knowledgebase_search", {"limit": 5}),
        ]
        for label, tool, extra in settings:
            times = []
            for q in QUERIES:
                dt, _ = await timed(meko, tool, query=q, conversation_id=conv, agent_id=AGENT, **extra)
                times.append(dt)
            print(f"{label:34} median {statistics.median(times):5.2f} s   (all: {', '.join(f'{x:.1f}' for x in times)})")


if __name__ == "__main__":
    asyncio.run(main())
