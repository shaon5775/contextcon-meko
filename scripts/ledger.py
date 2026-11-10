"""Postgres ledger inside the Meko datapack (AMP), live.
    python -u scripts/ledger.py --create    # make the AMP cluster "saathi-ledger" if missing (checks budget), then test
    python -u scripts/ledger.py             # connect (re-allow this machine's IP if needed), run a 2-ticket test,
                                            # print the SQL audit and save it to Meko as audit-report.md (artifact_put)
    python -u scripts/ledger.py --audit     # only the audit
The DB password is derived from MEKO_API_KEY (never printed). Test rows use run_tag "ledger-live-<time>".
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import Settings, build  # noqa: E402
from saathi.desk import AGENT_CASEWORKER, AGENT_TRIAGE, HelpDesk  # noqa: E402
from saathi.ledger import PgLedger, audit_markdown  # noqa: E402


async def main() -> None:
    create = "--create" in sys.argv
    only_audit = "--audit" in sys.argv
    meko, llm, kb = build(offline=False)
    async with meko:
        conv = await meko.conversation_create(AGENT_TRIAGE, "ledger")
        ledger = await PgLedger.connect(meko, conv, Settings().meko_api_key, create=create)
        print("[ok] connected to the Postgres ledger inside the datapack")
        if not only_audit:
            tag = f"ledger-live-{int(time.time())}"
            desk = HelpDesk(meko, llm, kb, run_tag=tag)
            desk.ledger = ledger
            first = await desk.handle("My PM Kisan money stopped, the name does not match Aadhaar. What to do?", "L1")
            print(f"[1] {first.path} {first.total_tokens} tok")
            mem = await desk.approve(first, caseworker="ledger-test")
            print(f"[2] approved -> {mem}")
            again = await desk.handle("मेरा पीएम किसान का पैसा रुक गया, नाम आधार से मेल नहीं खाता", "L2")
            print(f"[3] {again.path} {again.total_tokens} tok")
        a = ledger.audit()
        md = audit_markdown(a)
        print(md)
        await meko.artifact_put("audit-report.md", md.encode(), "text/markdown", conv, AGENT_CASEWORKER)
        print("[ok] audit-report.md saved to Meko (artifact_put)")
        print("[RESULT] PASS" if a["tickets"] >= (0 if only_audit else 2) else "[RESULT] CHECK")


if __name__ == "__main__":
    asyncio.run(main())
