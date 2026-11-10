"""Offline UI check of app.py with Streamlit's AppTest (no keys, no microphone)."""
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
