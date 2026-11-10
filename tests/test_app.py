"""Offline UI check of app.py with Streamlit's AppTest (no keys, no microphone)."""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest


def _offline_app():
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    at.toggle[0].set_value(True).run()           # sidebar: "Offline demo (no API keys)"
    return at


def test_typed_question_is_answered_right_away_and_labelled():
    at = _offline_app()
    at.text_area(key="typed").set_value("My PM Kisan money stopped, name does not match Aadhaar").run()
    at.button(key="ask_typed").click().run()
    assert not at.exception
    assert any("My PM Kisan money stopped" in i.value for i in at.info)   # answer says which question it answers
    first = at.session_state["result"].answer
    assert first

    # A second, different question replaces the first answer in the SAME click (no one-step delay)
    at.text_area(key="typed").set_value("आमार बयस ৬৫, বিপিএল কার্ড আছে। বার্ধক্য ভাতা পাব কী?").run()
    at.button(key="ask_typed").click().run()
    assert not at.exception
    assert any("বার্ধক্য ভাতা" in i.value for i in at.info)

    # Voice is made only on request, for the current answer
    assert at.session_state["spoken"] is None
    at.button(key="hear").click().run()
    assert not at.exception
    assert at.session_state["spoken"] and at.session_state["spoken_for"] == at.session_state["asked"]


def test_caseworker_review_approve_then_reuse():
    at = _offline_app()
    q = "My PM Kisan money stopped, name does not match Aadhaar"
    at.text_area(key="typed").set_value(q).run()
    at.button(key="ask_typed").click().run()
    assert at.session_state["result"].path == "fresh"
    assert [i["status"] for i in at.session_state["queue"]] == ["pending"]

    at.radio(key="screen").set_value("👩‍💼 Caseworker review").run()
    assert not at.exception
    at.text_area(key="fix_0").set_value("Use 'Name Correction as per Aadhaar' on the PM-KISAN portal.").run()
    at.button(key="approve_0").click().run()
    assert not at.exception
    item = at.session_state["queue"][0]
    assert item["status"] == "approved" and item["memory_id"]
    assert any("Approved by" in s.value for s in at.success)

    at.radio(key="screen").set_value("🧑‍🌾 Citizen help desk").run()
    hindi = json.loads((Path(__file__).parent.parent / "data/tickets.jsonl").read_text(encoding="utf-8").splitlines()[1])["text"]
    at.text_area(key="typed").set_value(hindi).run()
    at.button(key="ask_typed").click().run()
    assert not at.exception
    assert at.session_state["result"].path == "reused"
    assert len(at.session_state["queue"]) == 1          # a reused answer needs no new review


def test_caseworker_review_blocks_phone_and_rejects():
    at = _offline_app()
    at.text_area(key="typed").set_value("My PM Kisan money stopped, name does not match Aadhaar").run()
    at.button(key="ask_typed").click().run()
    at.radio(key="screen").set_value("👩‍💼 Caseworker review").run()
    at.text_area(key="fix_0").set_value("Call Ramesh on 9876543210").run()
    assert at.error and at.button(key="approve_0").disabled
    at.text_input(key="reason_0").set_value("Wrong advice").run()
    at.button(key="reject_0").click().run()
    assert not at.exception
    assert at.session_state["queue"][0]["status"] == "rejected"
    assert any("Wrong advice" in w.value for w in at.warning)
