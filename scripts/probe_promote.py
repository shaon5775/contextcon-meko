"""Probe: what does Meko return for a promoted fix? (no Gemini calls)
    python -u scripts/probe_promote.py <memory_id>
Prints every memory that context_search / memory_search return for the PM-KISAN name-mismatch query, with id,
score, agent and metadata, so we can see how a promoted memory looks."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import build  # noqa: E402
from saathi.desk import AGENT_TRIAGE, ISSUE_MEANING, _as_list  # noqa: E402

QUERY = f"PM-KISAN: {ISSUE_MEANING['kisan_name_mismatch']}. PM-KISAN money stopped because name does not match Aadhaar"


def show(label: str, items) -> None:
    print(f"== {label}: {len(items)} item(s)")
    for m in items:
        meta = m.get("metadata")
        print(f"  id={m.get('id')} score={m.get('score')} agent={m.get('agent_id')} keys={sorted(m)}")
        print(f"     metadata={json.dumps(meta)[:300] if meta is not None else None}")
        print(f"     text={str(m.get('memory') or m.get('text') or m.get('content'))[:160]}")


async def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    meko, _, _ = build(offline=False)
    async with meko:
        conv = await meko.conversation_create(AGENT_TRIAGE, "probe promote")
        ctx = await meko.context_search(QUERY, conv, AGENT_TRIAGE, limit=10)
        buckets = ctx.get("results", ctx) if isinstance(ctx, dict) else {}
        print("context_search top-level keys:", sorted(ctx) if isinstance(ctx, dict) else type(ctx))
        print("bucket keys:", sorted(buckets) if isinstance(buckets, dict) else type(buckets))
        print("context_search memory ids:", [m.get("id")[:8] for m in _as_list(buckets.get("memory"))])
        for scope in ():
            try:
                args = {"query": QUERY, "conversation_id": conv, "agent_id": AGENT_TRIAGE, "limit": 10}
                if scope:
                    args["scope"] = scope
                res = await meko.call("memory_search", **args)
                show(f"memory_search scope={scope}", _as_list(res))
            except Exception as e:  # noqa: BLE001
                print(f"== memory_search scope={scope}: ERROR {str(e)[:300]}")
        tools = await meko._session.list_tools()
        for t in tools.tools:
            if any(w in t.name for w in ("memory", "context", "conversation_add")):
                schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}
                print(f"-- tool {t.name}: {json.dumps(schema.get('properties', {}))[:1500]}")
        big = await meko.call("memory_search", query=QUERY, conversation_id=conv, agent_id=AGENT_TRIAGE, limit=50)
        items = _as_list(big)
        print(f"== memory_search limit=50: {len(items)} items")
        for rank, m in enumerate(items, 1):
            meta = m.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta)
            if meta.get("type") == "verified_fix" or m.get("id") == target:
                print(f"  rank {rank} id={m.get('id')} score={m.get('score'):.3f} tag={meta.get('run_tag')} "
                      f"issue={meta.get('issue_key')}")


if __name__ == "__main__":
    asyncio.run(main())
