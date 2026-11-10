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
    assert len(meko.token_log) == 1                       # one usage record per ticket
    assert meko.token_log[0]["in"] + meko.token_log[0]["out"] == res.total_tokens


def test_reply_json_tolerates_code_fences():
    r = LLMReply(text='```json\n{"answer": "ok"}\n```', input_tokens=1, output_tokens=1, model="x")
    assert r.json() == {"answer": "ok"}


def test_language_detected_from_script():
    from saathi.desk import detect_language
    assert detect_language("আমার পিএম কিষাণের টাকা আসছে না", "auto") == "bn"
    assert detect_language("मेरा पीएम किसान का पैसा रुक गया है", "auto") == "hi"
    assert detect_language("Mera PM Kisan ka paisa nahi aa raha hai", "auto") == "hinglish"
    assert detect_language("My PM Kisan money has stopped", "auto") == "en"
    assert detect_language("আমার টাকা", "en") == "bn"          # script beats a wrong model guess


def test_weak_match_is_not_reused():
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    memories = [{"id": "m1", "score": 0.1, "memory": "x",
                 "metadata": {"type": "verified_fix", "issue_key": "kisan_name_mismatch"}}]
    assert desk._pick_verified_fix(memories, "kisan_name_mismatch") is None      # same issue, too weak
    memories[0]["score"] = 0.3
    assert desk._pick_verified_fix(memories, "kisan_name_mismatch")["id"] == "m1"  # same issue, strong enough
    assert desk._pick_verified_fix(memories, "kisan_ekyc_otp") is None           # other issue, not strong enough


def test_run_tag_ignores_fixes_from_other_runs():
    meko, llm, kb = build(offline=True)
    old = HelpDesk(meko, llm, kb)                        # a real fix approved earlier, no tag
    run(old.approve(run(old.handle(TICKETS[0]["text"], "T01"))))
    tagged = HelpDesk(meko, llm, kb, run_tag="eval-1")
    assert run(tagged.handle(TICKETS[1]["text"], "T02")).path == "fresh"   # old fix ignored
    run(tagged.approve(run(tagged.handle(TICKETS[0]["text"], "T01"))))
    assert run(tagged.handle(TICKETS[2]["text"], "T03")).path == "reused"  # same-run fix reused


def test_more_indian_scripts():
    from saathi.desk import detect_language
    assert detect_language("எனக்கு ஓய்வூதியம் வேண்டும்", "auto") == "ta"
    assert detect_language("నాకు పెన్షన్ కావాలి", None) == "te"
    assert detect_language("माझे पैसे आले नाहीत", "mr") == "mr"     # Devanagari + model says Marathi
    assert detect_language("আমাৰ টকা অহা নাই", "as") == "as"         # Bengali script + model says Assamese


def test_no_cross_issue_reuse():
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    mem = [{"id": "m1", "score": 0.95, "memory": "x",
            "metadata": {"type": "verified_fix", "issue_key": "vayvandana_apply"}}]
    assert desk._pick_verified_fix(mem, "vayvandana_cghs") is None      # other issue, even with a high score
    assert desk._pick_verified_fix(mem, "other")["id"] == "m1"           # unknown issue may use score alone


def test_shared_fix_is_the_general_version():
    meko, llm, kb = build(offline=True)
    desk = HelpDesk(meko, llm, kb)
    res = run(desk.handle(TICKETS[0]["text"], "T01"))
    res.general_fix = "Anyone whose PM-KISAN name does not match Aadhaar should use Name Correction as per Aadhaar."
    run(desk.approve(res))
    assert "Anyone whose" in meko.memories[-1]["memory"]


def test_voice_offline_round_trip():
    import wave, io
    from saathi.voice import MockVoice, pcm_to_wav, speakable
    v = MockVoice()
    heard = v.listen(b"fake-audio")
    assert heard["language"] == "bn" and heard["text"]
    res = run(HelpDesk(*build(offline=True)).handle(heard["text"], "voice"))
    assert res.language == "bn" and res.issue_key == "kisan_name_mismatch"
    with wave.open(io.BytesIO(v.speak(res.answer, res.language))) as w:
        assert w.getframerate() == 24000
    assert "http" not in speakable("Visit https://pmkisan.gov.in **now**")


def test_parse_heard_handles_broken_escapes():
    from saathi.voice import parse_heard
    # Real live reply (10 Nov 2026): Bengali letters as \u escapes, one escape cut off -> invalid JSON
    raw = ('{"text": "\\u0986\\u09ae\\u09be\\u09b0 PM Kisan-\\u09b0 \\u09a4\\u09be\\u0995\\u09be '
           'Aadhaar-\\u09c7\\u0 \\u09a8\\u09be\\u09ae", "language": "bn"}')
    out = parse_heard(raw)
    assert out["language"] == "bn"
    assert out["text"].startswith("আমার PM Kisan-র") and "\\u" not in out["text"]
    assert parse_heard('{"text": "मेरे दादा जी", "language": "HI"}') == {"text": "मेरे दादा जी", "language": "hi"}
    assert parse_heard("no json here")["text"] == "no json here"


def test_script_mismatch():
    from saathi.voice import script_mismatch
    # Real live case (10 Nov 2026): Tamil speech written in Telugu letters
    assert script_mismatch("ఎన్నమ్మాఊక్ ఎరుబత్తి రెండు వయత్", "ta")
    assert not script_mismatch("என் அம்மாவுக்கு எழுபத்திரண்டு வயது", "ta")
    assert not script_mismatch("আমার PM Kisan-এর টাকা", "bn")
    assert not script_mismatch("মোৰ নাম", "as")        # Assamese uses the Bengali script
    assert not script_mismatch("I am 63", "en")
