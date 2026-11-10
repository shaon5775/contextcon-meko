"""Offline check of the Postgres-ledger logic, using the same tables in SQLite."""
import asyncio

from saathi.config import build
from saathi.desk import HelpDesk
from saathi.ledger import SqliteLedger, audit_markdown, derived_password, safe


def run(coro):
    return asyncio.run(coro)


def test_ledger_rows_and_audit():
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    desk.ledger = SqliteLedger()
    first = run(desk.handle("My PM Kisan money stopped, name does not match Aadhaar", "T1"))
    assert first.path == "fresh"
    run(desk.approve(first, caseworker="asha"))
    again = run(desk.handle("PM Kisan payment stopped because my name is different from Aadhaar", "T2"))
    run(desk.reject(again, "asha", "test"))
    a = desk.ledger.audit()
    assert a["tickets"] == 2 and a["fresh"] >= 1
    assert a["approved"] == 1 and a["rejected"] == 1
    assert a["by_issue"][0]["issue_key"] == "kisan_name_mismatch"
    md = audit_markdown(a)
    assert "audit report" in md and "kisan_name_mismatch" in md


def test_ledger_error_never_breaks_the_answer():
    class Broken:
        def log_ticket(self, *a, **k):
            raise RuntimeError("db down")
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    desk.ledger = Broken()
    res = run(desk.handle("My PM Kisan money stopped, name does not match Aadhaar", "T1"))
    assert res.answer and any("Ledger write failed" in s for s in res.steps)


def test_password_is_derived_and_never_logged():
    assert derived_password("abc") == derived_password("abc") != derived_password("abd")
    assert len(derived_password("abc")) == 32
    assert "hunter2" not in safe({"password": "hunter2", "nested": [{"db_password": "x", "host": "h"}]})
