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
        amp = {t.name: {"description": t.description, "inputs": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)}
               for t in tools if any(w in t.name.lower() for w in WORDS)}
        out = Path(__file__).resolve().parent.parent / "eval" / "amp_tools.json"
        out.write_text(json.dumps(amp, indent=1), encoding="utf-8")
        print(f"(full schemas saved to {out})")
        for name in ("amp_core_budget", "amp_cluster_create", "amp_compute_create", "amp_compute_get"):
            if name not in amp:
                continue
            props = (amp[name]["inputs"] or {}).get("properties", {})
            req = (amp[name]["inputs"] or {}).get("required", [])
            print(f"\n== {name}  required={req}")
            for p, spec in props.items():
                print(f"   - {p}: {spec.get('type', '')} {str(spec.get('enum', ''))} :: {str(spec.get('description', ''))[:160]}")
            desc = (amp[name]["description"] or "").replace("\n", " ")
            print("   DESC:", desc[:1500])
        names = {t.name for t in tools}
        for name in SAFE_READS:
            if name in names:
                try:
                    print(f"\n>> {name}:", json.dumps(await meko.call(name))[:900])
                except Exception as e:  # noqa: BLE001
                    print(f"\n>> {name} failed: {str(e)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
