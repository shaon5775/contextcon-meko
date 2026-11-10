"""Yojana Saathi demo UI.  Run:  streamlit run app.py"""
from __future__ import annotations

import asyncio

import streamlit as st

from saathi.config import Settings, build
from saathi.desk import HelpDesk, language_name

st.set_page_config(page_title="Yojana Saathi", page_icon="🤝", layout="wide")
st.title("🤝 Yojana Saathi")
st.caption("Government-scheme help desk where every approved fix is remembered by every agent. Built on Meko. "
           "Speak or type in any Indian language.")

with st.sidebar:
    offline = st.toggle("Offline demo (no API keys)", value=False,
                        help="Uses a fake Meko, a mock model and a pretend voice so you can try the flow without keys.")
    use_memory = st.toggle("Use Meko shared memory", value=True,
                           help="Off = baseline: the whole rulebook goes into every prompt and nothing is remembered.")
    read_aloud = st.toggle("🔊 Read the answer aloud", value=True)
    st.markdown("**Try saying or typing:**\n- My PM Kisan money stopped, name does not match Aadhaar\n"
                "- আমার বয়স ৬৫, বিপিএল কার্ড আছে। বার্ধক্য ভাতা পাব কী?\n"
                "- मेरे दादाजी 75 साल के हैं, क्या उनको आयुष्मान कार्ड मिलेगा?")

if "offline_state" not in st.session_state:  # keep the fake store alive between clicks in offline mode
    st.session_state.offline_state = build(offline=True)


def make_desk() -> tuple:
    meko, llm, kb = st.session_state.offline_state if offline else build(offline=False)
    return meko, HelpDesk(meko, llm, kb, use_memory=use_memory)


def voice():
    from saathi.voice import GeminiVoice, MockVoice
    return MockVoice() if offline else GeminiVoice(Settings().gemini_api_key)


async def ask(question: str):
    meko, desk = make_desk()
    async with meko:
        return await desk.handle(question, "ui")


async def approve(res, caseworker: str):
    meko, desk = make_desk()
    async with meko:
        return await desk.approve(res, caseworker=caseworker)


def run_question(q: str) -> None:
    """Answer one question now and remember which question the answer belongs to."""
    q = (q or "").strip()
    if not q:
        return
    st.session_state.result, st.session_state.spoken = None, None
    with st.spinner("Saathi is checking shared memory and the official rules..."):
        st.session_state.result = asyncio.run(ask(q))
    st.session_state.asked = q
    # The voice is made only when the citizen presses "Hear the answer" (owner's test 10 Nov 2026: waiting for the
    # speech model after every question made the 2nd question look stuck on "Preparing the spoken answer...").


# ---- 1. The citizen speaks (or types) -------------------------------------------------------------------
# Voice flow (owner's test, 10 Nov 2026): the old flow showed each answer one step late. Now each tab has its own
# "Ask Saathi" button that answers exactly the text shown above it, in the same click, and the answer is labelled
# with its question. Tap the mic, speak, tap again -> the words appear -> press Ask Saathi.
speak_tab, type_tab = st.tabs(["🎤 Speak", "⌨️ Type"])
with speak_tab:
    codes = ["", "bn", "hi", "en", "ta", "te", "mr", "gu", "kn", "ml", "or", "pa", "as", "ur"]
    hint = st.selectbox("Your language (optional)", codes,
                        format_func=lambda c: "Detect automatically" if not c else language_name(c))
    st.markdown("**1.** Tap the 🎤 microphone and say your problem. **2.** Tap it again to stop. "
                "**3.** Check the words, then press **Ask Saathi**.")
    audio = st.audio_input("🎤 Tap to speak, tap again to stop")
    if audio is not None:
        key = (hash(audio.getvalue()), hint)
        if st.session_state.get("heard_key") != key:          # a NEW recording: write down what was said
            with st.spinner("Listening..."):
                heard = voice().listen(audio.getvalue(), audio.type or "audio/wav", hint)
            st.session_state.heard_key = key
            # A keyed text_area ignores `value=` after its first run, so write the words into its state.
            st.session_state.heard_text = heard.get("text", "")
        st.text_area("We heard (you can correct it):", key="heard_text", height=80)
        if st.button("Ask Saathi", type="primary", key="ask_voice"):
            run_question(st.session_state.get("heard_text", ""))
with type_tab:
    typed = st.text_area("Citizen's question (any Indian language, English or Hinglish)", height=90, key="typed")
    if st.button("Ask Saathi", type="primary", key="ask_typed"):
        run_question(typed)

# ---- 2. The answer, read aloud, with the reasons -----------------------------------------------------------
res = st.session_state.get("result")
if res:
    st.info(f"**Question:** {st.session_state.get('asked', '')}")
    left, right = st.columns([3, 2])
    with left:
        badge = {"reused": "♻️ Reused an approved fix", "fresh": "🆕 Solved fresh from official rules",
                 "baseline": "📚 Baseline (full rulebook)"}[res.path]
        st.subheader(badge)
        st.caption(f"Language: {language_name(res.language)}")
        if read_aloud and res.answer:
            if st.session_state.get("spoken") and st.session_state.get("spoken_for") == st.session_state.get("asked"):
                st.audio(st.session_state.spoken, format="audio/wav")
            elif st.button("🔊 Hear the answer", key="hear"):
                with st.spinner("Making the voice (a few seconds)..."):
                    st.session_state.spoken = voice().speak(res.answer, res.language)
                    st.session_state.spoken_for = st.session_state.get("asked")
                if st.session_state.spoken:
                    st.audio(st.session_state.spoken, format="audio/wav", autoplay=True)
                else:
                    st.warning("The voice service is busy right now. Please read the answer below, or try again.")
        st.write(res.answer)
        st.caption(f"Caseworker summary: {res.summary_en}")
        if res.path == "fresh":
            name = st.text_input("Caseworker name", value="caseworker")
            if st.button("✅ Approve this fix for all agents"):
                mem_id = asyncio.run(approve(res, name))
                st.success(f"Saved to shared memory ({mem_id}). The next agent with this problem will reuse it.")
    with right:
        st.subheader("Why the agents did this")
        for i, step in enumerate(res.steps, 1):
            st.markdown(f"{i}. {step}")
        c1, c2, c3 = st.columns(3)
        c1.metric("LLM calls", res.llm_calls)
        c2.metric("Tokens", f"{res.total_tokens:,}")
        c3.metric("Seconds", res.latency_s)
        if res.conversation_id:
            st.caption(f"Meko conversation / trace id: `{res.conversation_id}`")

st.divider()
st.caption("Answers are guidance only. Always confirm on the official portal or office. Forms are free; never pay middlemen.")
