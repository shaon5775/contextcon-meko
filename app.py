"""Yojana Saathi demo UI.  Run:  streamlit run app.py"""
from __future__ import annotations

import asyncio

import streamlit as st

from saathi.config import build
from saathi.desk import HelpDesk

st.set_page_config(page_title="Yojana Saathi", page_icon="🤝", layout="wide")
st.title("🤝 Yojana Saathi")
st.caption("Government-scheme help desk where every approved fix is remembered by every agent. Built on Meko.")

with st.sidebar:
    offline = st.toggle("Offline demo (no API keys)", value=False,
                        help="Uses a fake Meko and a mock model so you can try the flow without keys.")
    use_memory = st.toggle("Use Meko shared memory", value=True,
                           help="Off = baseline: the whole rulebook goes into every prompt and nothing is remembered.")
    st.markdown("**Try:**\n- My PM Kisan money stopped, name does not match Aadhaar\n"
                "- আমার বয়স ৬৫, বিপিএল কার্ড আছে। বার্ধক্য ভাতা পাব কী?\n"
                "- मेरे दादाजी 75 साल के हैं, क्या उनको आयुष्मान कार्ड मिलेगा?")

if "offline_state" not in st.session_state:  # keep the fake store alive between clicks in offline mode
    st.session_state.offline_state = build(offline=True)


def make_desk() -> tuple:
    meko, llm, kb = st.session_state.offline_state if offline else build(offline=False)
    return meko, HelpDesk(meko, llm, kb, use_memory=use_memory)


async def ask(question: str):
    meko, desk = make_desk()
    async with meko:
        return await desk.handle(question, "ui")


async def approve(res, caseworker: str):
    meko, desk = make_desk()
    async with meko:
        return await desk.approve(res, caseworker=caseworker)


question = st.text_area("Citizen's question (Bengali, Hindi, English or Hinglish)", height=90)
if st.button("Ask Saathi", type="primary") and question.strip():
    with st.spinner("Agents are checking shared memory and official rules..."):
        st.session_state.result = asyncio.run(ask(question.strip()))

res = st.session_state.get("result")
if res:
    left, right = st.columns([3, 2])
    with left:
        badge = {"reused": "♻️ Reused an approved fix", "fresh": "🆕 Solved fresh from official rules",
                 "baseline": "📚 Baseline (full rulebook)"}[res.path]
        st.subheader(badge)
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
