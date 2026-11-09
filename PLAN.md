# Yojana Saathi — project plan

**Hackathon:** ContextCon: Remember Everything (HackerEarth × Meko by YugabyteDB)
**Deadline:** 17 Jan 2027, 11:59 PM PT (18 Jan 2027, 1:29 PM IST)
**Builder:** Shaon Bandyopadhyay (solo)
**Theme:** Challenge 02, "Never Solve It Twice" (agentic support). Also eligible for the *Best use of shared memory* award.

## 1. The problem

Many families in India miss government benefits they are entitled to: pensions, health cover, LPG
connections, farmer income support. The reason is usually a small practical blocker, not
ineligibility:

- a name that doesn't match Aadhaar
- eKYC that never completed
- a bank account not seeded with Aadhaar
- not knowing which scheme applies to them

Help desks (CSC operators, NGO volunteers, panchayat staff, AI chatbots) solve **the same problems
again and again** because nobody keeps a shared record of what worked.

## 2. The product

**Yojana Saathi** ("scheme companion") is a multi-agent help desk. A citizen **speaks or types** in their own
language. The agents check what the whole desk already learned before they start solving.
When a caseworker approves a fix, every agent knows it from then on.

**Voice first, any Indian language.** Many rural users cannot type. They press the microphone and talk;
Gemini writes down what they said in their own script (Bengali, Hindi, Tamil, Telugu, Marathi, Gujarati,
Kannada, Malayalam, Odia, Punjabi, Assamese, Urdu, English, Hinglish), the help desk answers in the same
language, and the answer is read aloud. One approved fix in shared memory serves every language: a fix
learned from a Bengali speaker is reused for a Tamil speaker. Code: `saathi/voice.py`; check:
`scripts/test_voice.py`. Later: a phone (IVR) number for feature phones.

| Agent | Job | Meko features it uses |
|---|---|---|
| **Triage agent** | Understands the question (any language) and pulls out the scheme, the issue and the person's profile | `conversation_create`, `conversation_add_message` |
| **Memory check** (search before solving) | Looks for an already-approved fix or answer | `context_search` (memory + knowledge + past conversations in one call) |
| **Eligibility agent** | "Which scheme can I get?" answered from official rules | `knowledgebase_search` |
| **Resolver agent** | "My money stopped / my eKYC failed": step-by-step fix | `knowledgebase_search`, `memory_search` |
| **Caseworker review** (human in the loop) | A person approves or rejects the fix. Only approved fixes become shared memory | `memory_add` (verified fix), `memory_promote` (shared layer) |
| **Audit** | Shows why each answer was given and what it cost | `track_token_usage`, decision traces, `artifact_put` (audit report) |

**Governance:** raw citizen conversations and verified fixes are kept apart. Only caseworker-approved,
de-identified fixes are promoted to the shared layer. No Aadhaar numbers or phone numbers are stored.

## 3. How we prove it works (the "prove it" objective)

- **Dataset:** 36 synthetic citizen tickets (`data/tickets.jsonl`) in English, Hindi, Bengali and
  Hinglish, covering 10 recurring issues across 5 schemes. Most issues repeat 3–5 times in
  different words.
- **Baseline run:** the same agents *without* Meko. The whole rulebook is pasted into every prompt
  (context stuffing) and nothing is remembered.
- **Meko run:** retrieval plus shared memory. The first time an issue appears it is solved fresh;
  repeats reuse the approved fix.
- **Metrics per ticket:** LLM calls, input/output tokens, latency, steps, answer correctness
  (expected key facts present).
- **Output:** `eval/results.md` comparing first-time vs repeat resolution, baseline vs Meko.

## 4. Mapping to the judging criteria

| Criterion | Weight | How we score |
|---|---|---|
| Use of Meko | 30% | Conversations, memory, learnings (promote), knowledge base, artifacts, traces, token tracking: every part is used |
| Impact & usefulness | 25% | A real, large problem (missed welfare benefits). Users: CSC operators, NGOs, citizens. Multilingual |
| Technical execution | 20% | Clean Python package, tests, reproducible eval, Streamlit demo |
| Innovation | 15% | Caseworker-verified collective memory for public services; rule changes (e.g. state scheme replaced) handled by updating memory |
| Presentation | 10% | Under-5-minute video, README with architecture diagram and results table |

## 5. Timeline (solo, about 10 weeks)

| Week | Dates | Work |
|---|---|---|
| 1 | 9–15 Nov | ✅ Setup (accounts, repo, datapack). Code skeleton, knowledge files, tickets, offline tests |
| 2 | 16–22 Nov | Run live with Meko + Gemini on your machine/Colab. Upload knowledge base |
| 3 | 23–29 Nov | Caseworker review screen, memory promote, voice in/out tested with real speakers, more languages in tickets |
| 4 | 30 Nov–6 Dec | Evaluation: baseline vs Meko, results table |
| 5 | 7–13 Dec | Audit view from traces, audit report artifact |
| 6 | 14–20 Dec | Rule-change demo (scheme replaced → memory updated), polish UI |
| 7 | 21–27 Dec | Hardening, README, architecture diagram |
| 8 | 28 Dec–3 Jan | Slide deck (PDF, about 10 slides) + record demo video (under 5 min) |
| 9 | 4–10 Jan | Buffer: fixes, feedback from Discord |
| 10 | 11–17 Jan | Submit on HackerEarth (target: 15 Jan, 2 days early) |

## 6. What we submit (HackerEarth form, checked 9 Nov 2026)

| Field | Required | Our plan |
|---|---|---|
| Title, description | yes | "Yojana Saathi: never solve the same welfare problem twice" + summary from this README |
| Theme | yes | Challenge 2: Never Solve It Twice |
| Video URL (under 5 min) | yes | YouTube (unlisted) demo walkthrough |
| Presentation (PDF / PPTX, max 50 MB) | yes | About 10 slides: problem, users, architecture, Meko features used, live demo shots, results table, governance, business path |
| Repository URL | yes | github.com/shaon5775/contextcon-meko |
| Source code upload (zip, max 50 MB) | yes | zip of the repository |
| Instructions to run | no | Quick-start section of the README |
| Demo link | no | Hosted Streamlit demo, if time allows |

Challenge 02 must-haves we cover: support agents connected to Meko; 36 synthetic tickets with repeats (≥ 30 needed);
first-time vs repeat comparison of time, tokens and number of steps; a demo of one agent reusing a fix that another
agent learned; human approval before a fix is saved (encouraged).

## 7. Business path after the hackathon

- **Customers:** Common Service Centre (CSC) operators, NGOs working on welfare access, state
  e-governance and social-welfare departments, CSR programmes.
- **Model:** per-desk monthly subscription for CSCs/NGOs; licence for state departments.
- **Moat:** the verified-fix memory grows with every resolved case, and that is hard to copy.

## 8. Disclaimer

Scheme rules change. Every answer points citizens to the official portal or office to confirm.
All tickets are synthetic; no real citizen data is used.
