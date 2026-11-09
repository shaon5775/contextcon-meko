"""Upload every file in knowledge/ to the Meko datapack's knowledge base.

Run on your own machine or in Colab (needs internet):
    python scripts/upload_knowledge.py

Alternative without code: Meko Cloud → Datapacks → yojana-saathi-shaon5775 → Add Knowledge → upload the .md files.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from saathi.config import ROOT, Settings  # noqa: E402
from saathi.meko import MekoClient  # noqa: E402

AGENT = "yojana_saathi:librarian"


async def main() -> None:
    s = Settings()
    async with MekoClient(s.meko_api_key, s.meko_datapack_id) as meko:
        conv = await meko.conversation_create(AGENT, "Upload scheme knowledge")
        for path in sorted((ROOT / "knowledge").glob("*.md")):
            data = path.read_bytes()
            ticket = await meko.call(
                "knowledgebase_upload_document", filename=path.name, size=len(data),
                content_hash=hashlib.sha256(data).hexdigest(),
                content_head_base64=base64.b64encode(data[:3072]).decode(),
                conversation_id=conv, agent_id=AGENT,
            )
            if ticket.get("already_uploaded"):
                print(f"= {path.name}: already uploaded")
                continue
            files = {"file": (path.name, data, "text/markdown")}
            r = httpx.post(ticket["url"], data=ticket.get("fields", {}), files=files, timeout=60)
            print(f"↑ {path.name}: HTTP {r.status_code}")
            r.raise_for_status()
            key = ticket.get("key")
            for _ in range(30):
                st = await meko.call("knowledgebase_document_status", document_key=key, conversation_id=conv)
                state = st.get("state") or st.get("status")
                if state in ("completed", "failed", "oversized", "abandoned"):
                    print(f"  → {state}")
                    break
                time.sleep(4)


if __name__ == "__main__":
    asyncio.run(main())
