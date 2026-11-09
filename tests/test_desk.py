"""Offline tests: fake Meko + mock LLM. Run with `pytest -q`."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.config import build  # noqa: E402
from saathi.desk import HelpDesk  # noqa: E402
from saathi.llm import LLMReply  # noqa: E402

TICKETS = [json.loads(x) for x in (Path(__file__).parent.parent / "data/tickets.jsonl").read_text(encoding="utf-8").splitlines()]


def run(coro):
    return asyncio.run(coro)


def test_repeat_issue_reuses_approved_fix():
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    first = run(desk.handle(TICKETS[0]["text"], "T01"))
    assert first.path == "fresh"
    assert run(desk.approve(first)) is not None
    second = run(desk.handle(TICKETS[1]["text"], "T02"))  # same issue, in Hindi
    assert second.path == "reused"
    assert second.reused_memory_id == meko.memories[0]["id"]
    assert second.total_tokens < first.total_tokens


def test_unapproved_fix_is_not_reused():
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    run(desk.handle(TICKETS[0]["text"], "T01"))          # no approval
    assert run(desk.handle(TICKETS[1]["text"], "T02")).path == "fresh"


def test_baseline_uses_no_meko_and_more_tokens():
    meko, llm, kb = build(offline=True)
    base = HelpDesk(meko, llm, kb, use_memory=False)
    res = run(base.handle(TICKETS[0]["text"], "T01"))
    assert res.path == "baseline" and meko.calls == []
    fresh = run(HelpDesk(meko, llm, kb).handle(TICKETS[0]["text"], "T01"))
    assert res.total_tokens > fresh.total_tokens


def test_meko_features_used_and_tokens_tracked():
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    res = run(desk.handle(TICKETS[13]["text"], "T14"))
    run(desk.approve(res, promote=True))
    for tool in ("conversation_create", "context_search", "track_token_usage", "conversation_add_message",
                 "memory_add", "memory_promote"):
        assert tool in meko.calls
    assert len(meko.token_log) == res.llm_calls


def test_reply_json_tolerates_code_fences():
    r = LLMReply(text='```json\n{"answer": "ok"}\n```', input_tokens=1, output_tokens=1, model="x")
    assert r.json() == {"answer": "ok"}
