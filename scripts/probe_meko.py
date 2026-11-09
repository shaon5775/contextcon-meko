"""Print what the live Meko server offers and how it replies. Used to fit saathi/meko.py to the real API.

    python scripts/probe_meko.py            # input fields of the tools we use
    python scripts/probe_meko.py --call     # also calls read-only tools once and prints the raw replies
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import ROOT, Settings  # noqa: E402
from saathi.meko import MekoClient  # noqa: E402

USED = {"conversation_create", "conversation_add_message", "context_search", "knowledgebase_search",
        "memory_add", "memory_promote", "memory_search", "track_token_usage", "artifact_put",
        "knowledgebase_upload_document", "knowledgebase_document_status", "datapack_list", "datapack_describe"}


def attr(obj, *names):
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return None


def show(name, result) -> str:
    print(f"\n== {name}: isError={attr(result, 'is_error', 'isError')}")
    sc = attr(result, "structured_content", "structuredContent")
    if sc is not None:
        print("  structured:", json.dumps(sc, default=str, ensure_ascii=False)[:1500])
    text = ""
    for c in attr(result, "content") or []:
        t = getattr(c, "text", None) or repr(c)
        text += t
        print("  content:", t[:1500])
    return text


async def main() -> None:
    s = Settings()
    async with MekoClient(s.meko_api_key, s.meko_datapack_id) as m:
        sess = m._session
        tools = (await sess.list_tools()).tools
        for t in tools:
            if t.name in USED:
                schema = attr(t, "input_schema", "inputSchema") or {}
                print(f"\n## {t.name}  required={schema.get('required')}")
                print("  about:", (t.description or "")[:300].replace("\n", " "))
                print("  fields:", json.dumps(schema.get("properties", {}))[:900])
        if "--call" not in sys.argv:
            return
        dp = s.meko_datapack_id
        show("datapack_list", await sess.call_tool("datapack_list", {}))
        text = show("conversation_create", await sess.call_tool(
            "conversation_create", {"agent_id": "yojana_saathi:probe", "title": "probe", "datapack_id": dp}))
        try:
            cid = json.loads(text).get("id")
        except Exception:
            cid = text.strip().split()[-1] if text.strip() else None
        print("  -> conversation id guess:", cid)
        base = {"datapack_id": dp, "conversation_id": cid, "agent_id": "yojana_saathi:probe"}
        q = "PM-KISAN name does not match Aadhaar"
        show("context_search", await sess.call_tool("context_search", {**base, "query": q, "limit": 3}))
        show("knowledgebase_search", await sess.call_tool("knowledgebase_search", {**base, "query": q, "limit": 2}))
        show("memory_search", await sess.call_tool("memory_search", {**base, "query": q, "limit": 3}))
        show("track_token_usage", await sess.call_tool("track_token_usage", {
            "datapack_id": dp, "conversation_id": cid, "name": "probe", "model": "probe",
            "input_tokens": 1, "output_tokens": 1, "total_tokens": 2}))
        f = ROOT / "knowledge" / "common-dbt-issues.md"
        data = f.read_bytes()
        show("knowledgebase_upload_document (ticket only, nothing uploaded)", await sess.call_tool(
            "knowledgebase_upload_document", {**base, "filename": f.name, "size": len(data),
                                              "content_hash": hashlib.sha256(data).hexdigest()}))


if __name__ == "__main__":
    asyncio.run(main())
