"""Print what the live Meko server offers and how it replies. Used to fit saathi/meko.py to the real API.

    python scripts/probe_meko.py            # tool names + input fields of the tools we use
    python scripts/probe_meko.py --call     # also creates one test conversation and prints the raw reply
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import Settings  # noqa: E402
from saathi.meko import MekoClient  # noqa: E402

USED = {"conversation_create", "conversation_add_message", "context_search", "knowledgebase_search",
        "memory_add", "memory_promote", "memory_search", "track_token_usage", "artifact_put",
        "knowledgebase_upload_document", "knowledgebase_document_status"}


def show(result) -> None:
    print("  isError:", getattr(result, "isError", None))
    print("  structuredContent:", json.dumps(getattr(result, "structuredContent", None), default=str)[:1500])
    for c in getattr(result, "content", None) or []:
        print("  content:", (getattr(c, "text", None) or repr(c))[:1500])


async def main() -> None:
    s = Settings()
    async with MekoClient(s.meko_api_key, s.meko_datapack_id) as m:
        tools = (await m._session.list_tools()).tools
        print("ALL TOOLS:", ", ".join(sorted(t.name for t in tools)))
        for t in tools:
            if t.name in USED or "datapack" in t.name:
                schema = t.inputSchema or {}
                print(f"\n## {t.name}  required={schema.get('required')}")
                print("  fields:", json.dumps(schema.get("properties", {}))[:900])
        if "--call" in sys.argv:
            print("\n== conversation_create raw reply")
            show(await m._session.call_tool("conversation_create", {
                "agent_id": "yojana_saathi:probe", "title": "probe", "datapack_id": s.meko_datapack_id}))


if __name__ == "__main__":
    asyncio.run(main())
