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
    screen = st.radio("Screen", ["🧑‍🌾 Citizen help desk", "👩‍💼 Caseworker review"], key="screen")
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


async def _connect_ledger():
    from saathi.desk import AGENT_TRIAGE
    from saathi.ledger import PgLedger
    meko, _, _ = build(offline=False)
    async with meko:
        conv = await meko.conversation_create(AGENT_TRIAGE, "ledger (demo app)")
        return await PgLedger.connect(meko, conv, Settings().meko_api_key, create=False, log=lambda *a: None)


def _run_coro(make_coro):
    """asyncio.run(), also when called from inside a running event loop (e.g. the first question of a session opens
    the ledger from inside ask()): then the coroutine runs in its own thread with its own loop. Fix 15 Nov 2026."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(make_coro())).result()


def get_ledger():
    """The Postgres ledger INSIDE the Meko datapack (Meko AMP): one row per answer and per caseworker decision.
    Offline demo = the same tables in SQLite. Connected once per browser session; never blocks the help desk."""
    key = f"ledger_{'offline' if offline else 'live'}"
    if key not in st.session_state:
        if offline:
            from saathi.ledger import SqliteLedger
            st.session_state[key] = SqliteLedger()
        else:
            try:
                with st.spinner("Connecting to the Postgres ledger inside the Meko datapack (first time can take ~1 min)..."):
                    st.session_state[key] = _run_coro(_connect_ledger)
            except Exception as e:  # noqa: BLE001 - the help desk still works without the ledger
                st.session_state[key] = None
                st.session_state.ledger_error = str(e)[:200]
    return st.session_state[key]


def make_desk() -> tuple:
    meko, llm, kb = st.session_state.offline_state if offline else build(offline=False)
    desk = HelpDesk(meko, llm, kb, use_memory=use_memory)
    desk.ledger = get_ledger()
    return meko, desk


def voice():
    from saathi.voice import GeminiVoice, MockVoice
    return MockVoice() if offline else GeminiVoice(Settings().gemini_api_key)


async def ask(question: str):
    meko, desk = make_desk()
    async with meko:
        return await desk.handle(question, "ui")


async def approve(res, caseworker: str, fix: str, promote: bool):
    meko, desk = make_desk()
    async with meko:
        mem_id = await desk.approve(res, caseworker=caseworker, promote=promote, edited_fix=fix)
        return mem_id, getattr(desk, "last_promote_error", None)


async def reject(res, caseworker: str, reason: str):
    meko, desk = make_desk()
    async with meko:
        await desk.reject(res, caseworker, reason)


st.session_state.setdefault("queue", [])     # answers waiting for a caseworker: {"q", "res", "status", ...}


def run_question(q: str) -> None:
    """Answer one question now and remember which question the answer belongs to."""
    q = (q or "").strip()
    if not q:
        return
    st.session_state.result, st.session_state.spoken = None, None
    with st.spinner("Saathi is checking shared memory and the official rules..."):
        st.session_state.result = asyncio.run(ask(q))
    st.session_state.asked = q
    res = st.session_state.result
    if res.path == "fresh":   # a new fix: a person must check it before any agent may reuse it
        st.session_state.queue.append({"q": q, "res": res, "status": "pending"})
    # The voice is made only when the citizen presses "Hear the answer" (owner's test 10 Nov 2026: waiting for the
    # speech model after every question made the 2nd question look stuck on "Preparing the spoken answer...").


def citizen_screen() -> None:
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
            if res.path == "fresh" and use_memory:
                st.caption("🕒 New fix: sent to the **Caseworker review** screen. Agents reuse it only after a "
                           "person approves it.")
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


async def _save_audit(md: str):
    from saathi.desk import AGENT_CASEWORKER, AGENT_TRIAGE
    meko, _ = make_desk()
    async with meko:
        conv = await meko.conversation_create(AGENT_TRIAGE, "audit report")
        await meko.artifact_put("audit-report.md", md.encode(), "text/markdown", conv, AGENT_CASEWORKER)


def audit_box() -> None:
    """Live audit straight from SQL on the Postgres ledger inside the datapack."""
    from saathi.ledger import audit_markdown
    ledger = get_ledger()
    with st.container(border=True):
        st.markdown("**📊 Audit from Postgres** (the ledger table inside the Meko datapack)")
        if ledger is None:
            st.caption("Ledger not connected: " + st.session_state.get("ledger_error", "unknown error"))
            return
        try:
            a = ledger.audit()
        except Exception as e:  # noqa: BLE001
            st.caption(f"Could not read the ledger: {str(e)[:150]}")
            return
        c = st.columns(5)
        c[0].metric("Tickets", a["tickets"])
        c[1].metric("Reused a fix", f"{a['reused']} ({a['reuse_rate_pct']}%)")
        c[2].metric("Avg tokens fresh", int(a["avg_tokens_fresh"] or 0))
        c[3].metric("Avg tokens reused", int(a["avg_tokens_reused"] or 0))
        c[4].metric("Approved / rejected", f"{a['approved']} / {a['rejected']}")
        if st.button("💾 Save this audit report to Meko (artifact)", key="save_audit"):
            asyncio.run(_save_audit(audit_markdown(a)))
            st.success("audit-report.md saved to the Meko datapack.")


def review_screen() -> None:
    """Human in the loop: a caseworker checks each NEW fix, may correct it, then approves (-> shared memory) or
    rejects it (-> only the reason is logged in the trace; nothing is remembered)."""
    from saathi.desk import privacy_flags
    st.header("👩‍💼 Caseworker review")
    st.caption("Only fixes you approve go into shared memory. Every agent, in every language, reuses them from then on.")
    audit_box()
    name = st.text_input("Your name (caseworker)", value="caseworker", key="cw_name")
    promote = st.checkbox("Also promote approved fixes to the shared learnings layer (Meko memory_promote)",
                          value=True, key="cw_promote")
    queue = st.session_state.queue
    pending = [i for i, item in enumerate(queue) if item["status"] == "pending"]
    st.subheader(f"Waiting for review: {len(pending)}")
    if not pending:
        st.write("Nothing to review. New fixes appear here after the help desk solves a problem for the first time.")
    for i in pending:
        item = queue[i]
        res = item["res"]
        with st.container(border=True):
            st.markdown(f"**Citizen asked** ({language_name(res.language)}): {item['q']}")
            st.caption(f"Issue: `{res.issue_key}` · intent: {res.intent} · sources: {', '.join(res.sources) or '—'}")
            with st.expander("Answer the citizen got"):
                st.write(res.answer)
            fix = st.text_area("Fix to share with all agents (general, in English, no personal details). "
                               "Correct it if needed:", value=res.general_fix or res.summary_en,
                               key=f"fix_{i}", height=110)
            flags = privacy_flags(fix)
            if flags:
                st.error("Personal details found: " + "; ".join(flags) + ". Remove them before approving.")
            a, r = st.columns(2)
            if a.button("✅ Approve and share", key=f"approve_{i}", type="primary", disabled=bool(flags)):
                mem_id, promote_err = asyncio.run(approve(res, name, fix, promote))
                item.update(status="approved", by=name, memory_id=mem_id, fix=fix, promote_error=promote_err)
                st.rerun()
            reason = r.text_input("Reason (if rejecting)", key=f"reason_{i}")
            if r.button("❌ Reject", key=f"reject_{i}"):
                asyncio.run(reject(res, name, reason))
                item.update(status="rejected", by=name, reason=reason or "(no reason given)")
                st.rerun()

    done = [item for item in queue if item["status"] != "pending"]
    if done:
        st.subheader("Decisions so far")
        for item in reversed(done):
            if item["status"] == "approved":
                extra = (" · ⚠️ saved, but promote failed: " + item["promote_error"]) if item.get("promote_error") else ""
                st.success(f"✅ Approved by {item['by']} → shared memory `{item.get('memory_id')}`{extra}\n\n"
                           f"**Fix:** {item['fix']}")
            else:
                st.warning(f"❌ Rejected by {item['by']}: {item['reason']}\n\n**Question:** {item['q']}")


if screen.startswith("👩‍💼"):
    review_screen()
else:
    citizen_screen()

st.divider()
st.caption("Answers are guidance only. Always confirm on the official portal or office. Forms are free; never pay middlemen.")
