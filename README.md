# 🤝 Yojana Saathi: never solve the same welfare problem twice

**A multi-agent help desk for Indian government schemes, with shared, caseworker-verified memory on [Meko](https://mekodata.ai).**
Built for *ContextCon: Remember Everything* (HackerEarth × YugabyteDB), Challenge 02 "Never Solve It Twice".

Millions of families miss pensions, health cover, LPG connections and farmer support because of small,
fixable blockers: a name that doesn't match Aadhaar, an eKYC OTP that never arrives, a bank account
that isn't Aadhaar-seeded. Help desks solve these **again and again** because nobody shares what worked.

Yojana Saathi's agents **search before solving**. When a caseworker approves a fix, every agent knows it from then on,
in every language.

## How it works

```
Citizen question (bn / hi / en / Hinglish)
        │
        ▼
 Triage agent ──► Meko context_search (memory + knowledge base + past conversations, one call)
        │                    │
        │        approved fix for this issue? ──yes──► Resolver agent re-explains it  ♻️ (cheap, fast)
        │                    │no
        ▼                    ▼
 Eligibility / Resolver agent answers from retrieved official rules  🆕
        │
        ▼
 Caseworker review (human in the loop) ──approve──► memory_add (verified fix) ──► memory_promote (shared)
        │
        ▼
 conversation_add_message (+ reasoning & plan) · track_token_usage · artifact_put (eval report) → decision traces
```

| Agent | Meko features |
|---|---|
| Triage | `conversation_create`, `conversation_add_message` |
| Memory check | `context_search` |
| Eligibility / Resolver | `knowledgebase_search` over official scheme rules |
| Caseworker review | `memory_add`, `memory_promote`: only approved, de-identified fixes are shared |
| Audit | `track_token_usage`, decision traces, `artifact_put` |

Schemes covered so far: PM-KISAN, Ayushman Vay Vandana (70+), NSAP old-age and widow pensions, PM Ujjwala,
and West Bengal's women support (Lakshmir Bhandar → Annapurna Bhandar, a 2026 rule change).

## Results

Run `python eval/run_eval.py` to fill `eval/results.md`. It compares, on the same 36 multilingual tickets
(`data/tickets.jsonl`):

- **Baseline:** the full rulebook in every prompt, no memory.
- **Meko:** retrieval plus shared memory, with first-time vs repeat issues reported separately.

**Live run, 9 Nov 2026** (real Meko + Gemini `gemini-3.5-flash-lite`, 36 tickets, fresh run tag, simulated caseworker):

| Run | Tokens | Tokens / ticket | Avg latency (s) | Avg steps | Accuracy |
|---|---|---|---|---|---|
| Baseline (full rulebook, no memory) | 145,093 | 4,030 | 3.5 | 2.0 | 78% |
| Meko (retrieval + shared memory) | **61,221** | **1,701** | 19.4 | 3.0 | **86%** |

| Meko group | Tickets | Tokens / ticket | Accuracy |
|---|---|---|---|
| First time an issue is seen | 10 | 2,319 | 80% |
| Repeat issue | 26 | 1,463 | 88% |

- **58% fewer tokens** for the same tickets, with higher accuracy.
- 19 of 26 repeat tickets reused a fix that another agent had learned and a caseworker approved.
- Latency: almost all of Meko's extra time is `context_search` (about 14 s per call on the free tier in this run);
  model time is lower than the baseline. Free-tier rate-limit waits are excluded from latency.
- "Correct" = right issue + every expected key fact present (equivalent wordings accepted, see
  `data/tickets.jsonl`). `python eval/rescore.py --show-wrong` prints every answer marked wrong for a human check.

## Quick start

### Option A: Google Colab (easiest)
```python
!git clone https://github.com/shaon5775/contextcon-meko.git
%cd contextcon-meko
!pip -q install -r requirements.txt
import os
from google.colab import userdata          # add MEKO_API_KEY and GEMINI_API_KEY in Colab's 🔑 Secrets panel
os.environ["MEKO_API_KEY"] = userdata.get("MEKO_API_KEY")
os.environ["GEMINI_API_KEY"] = userdata.get("GEMINI_API_KEY")
os.environ["MEKO_DATAPACK_ID"] = "96019422-4248-457e-b36c-e0c3087daae0"
!python scripts/upload_knowledge.py       # once: puts knowledge/*.md into Meko
!python eval/run_eval.py                  # baseline vs Meko
```

### Option B: your own computer
```bash
git clone https://github.com/shaon5775/contextcon-meko.git && cd contextcon-meko
pip install -r requirements.txt
cp .env.example .env        # then fill in MEKO_API_KEY and GEMINI_API_KEY
python scripts/upload_knowledge.py
streamlit run app.py        # demo UI
python eval/run_eval.py     # evaluation
```

### No keys? Try it offline
```bash
pytest -q                          # 5 tests, fake Meko + mock model
python eval/run_eval.py --offline  # checks the whole pipeline without network
streamlit run app.py               # then switch on "Offline demo" in the sidebar
```

Keys: Meko → Settings → Security → API keys. Gemini → https://aistudio.google.com/apikey (free tier is enough).

## Project layout
```
saathi/meko.py      Meko MCP client (+ offline fake)
saathi/llm.py       Gemini model (+ mock model for tests)
saathi/desk.py      the agents and the help-desk flow
app.py              Streamlit demo
eval/run_eval.py    baseline vs Meko evaluation
knowledge/          official scheme rules (uploaded to Meko's knowledge base)
data/tickets.jsonl  36 synthetic citizen tickets (bn/hi/en/Hinglish)
PLAN.md             plan, judging-criteria mapping, timeline
```

## Privacy and safety
- All tickets are synthetic. No real citizen data.
- Triage strips names, phone and Aadhaar numbers from the English summary that goes into memory.
- Only caseworker-approved fixes become shared memory.
- Every answer tells citizens to confirm at the official office and never pay middlemen.

## Disclaimer
Scheme rules change often. This is a guidance tool, not an official government service.

Built by Shaon Bandyopadhyay, The Neotia University, Kolkata.
