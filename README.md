# 🤝 Yojana Saathi: never solve the same welfare problem twice

**A multi-agent help desk for Indian government schemes, with shared, caseworker-verified memory on [Meko](https://mekodata.ai).**
Built for *ContextCon: Remember Everything* (HackerEarth × YugabyteDB), Challenge 02 "Never Solve It Twice".

Millions of families miss pensions, health cover, LPG connections and farmer support because of small,
fixable blockers: a name that doesn't match Aadhaar, an eKYC OTP that never arrives, a bank account
that isn't Aadhaar-seeded. Help desks solve these **again and again** because nobody shares what worked.

Yojana Saathi's agents **search before solving**. When a caseworker approves a fix, every agent knows it from then on,
in every language. Citizens who cannot type can simply **speak**; the answer is read back to them aloud.

## How it works

```
Citizen speaks 🎤 or types (Bengali, Hindi, Tamil, ... any Indian language)
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
| Ledger | `amp_core_budget`, `amp_cluster_list/create`, `amp_branch_list`, `amp_compute_list/create`: a real Postgres database inside the datapack |

### Postgres inside the datapack

Memory tells the agents *what* the approved fix is. A help desk also needs hard numbers: how many tickets, how
many were reused, what each one cost, who approved what. Those live in a real Postgres database that Meko runs
**inside the same datapack** (AMP).

- `saathi/ledger.py` finds the cluster `saathi-ledger` (or creates it with `amp_cluster_create`, after checking
  `amp_core_budget`), finds the `main` branch and its writer endpoint, and connects with `psycopg`. The endpoint is
  `ingress_external` with an allow-list of the caller's own IP (`/32`); if the IP changed (a new Colab runtime), it
  makes a fresh writer endpoint. The database password is derived from the Meko key and is never printed.
- Two tables: `tickets` (one row per answer: language, issue, fresh/reused, tokens, LLM calls, latency, which
  approved memory was reused, conversation id) and `reviews` (one row per caseworker approve/reject, with the new
  memory id).
- The desk writes a row after every answer and every review. If the database is unreachable the answer still goes
  out; the step list just notes "Ledger write failed".
- The **audit report is plain SQL** (`AUDIT_SQL` in `saathi/ledger.py`): reuse rate, average tokens fresh vs
  reused, approvals, and a per-issue table. The caseworker screen shows it live ("📊 Audit from Postgres") and can
  save it to Meko with `artifact_put`; `eval/run_eval.py` saves it as `audit-report.md` after every run.
- Offline, the same SQL runs on SQLite, so the tests need no keys.

```bash
python scripts/ledger.py --create   # once: create the cluster + writer endpoint
python scripts/ledger.py            # live check: 2 tickets + 1 approval → SQL audit → artifact_put
python scripts/ledger.py --audit    # print the audit report only
```

Schemes covered so far: PM-KISAN, Ayushman Vay Vandana (70+), NSAP old-age and widow pensions, PM Ujjwala,
and West Bengal's women support (Lakshmir Bhandar → Annapurna Bhandar, a 2026 rule change).

## Results

Run `python eval/run_eval.py` to fill `eval/results.md`. It compares, on the same 36 multilingual tickets
(`data/tickets.jsonl`):

- **Baseline:** the full rulebook in every prompt, no memory.
- **Meko:** retrieval plus shared memory, with first-time vs repeat issues reported separately.

**Latest live run (run 4, 10 Nov 2026):** real Meko + Gemini `gemini-3.5-flash-lite`, 36 tickets, fresh run tag,
simulated caseworker.

| Run | Tokens | Tokens / ticket | Avg latency (s) | Avg steps | Accuracy |
|---|---|---|---|---|---|
| Baseline (full rulebook, no memory) | 150,139 | 4,171 | 4.45 | 2.0 | 94% |
| Meko (retrieval + shared memory) | **72,430** | **2,012** | 7.43 | 3.0 | **100%** |

| Meko group | Tickets | Tokens / ticket | Avg latency (s) | Accuracy |
|---|---|---|---|---|
| First time an issue is seen | 10 | 2,748 | 7.7 | 100% |
| Repeat issue | 26 | 1,729 | 7.33 | 100% |

- **52% fewer tokens** for the same 36 tickets, and **every answer correct** (36/36) vs 94% for the baseline.
- Repeat tickets cost **37% less** than first-time tickets, because the approved fix is reused instead of re-solved.
- Run 3's two misses (T25, T26) are fixed: shared fixes now always keep the required documents (e.g. the
  husband's death certificate). The shorter triage prompt (2,008 → 1,342 characters) won back token savings.
- Latency: Meko `context_search` averaged **2.6 s** per call in run 4 (it was ~14 s in run 3 on the same free tier).
  Rate-limit waits are excluded. Baseline misses: T14, T21.
- **Voice round trip (10 Nov, live):** speak → listen came back correctly in Bengali, Hindi, Tamil and English, each in
  its own script (`scripts/test_voice.py`).
- "Correct" = right issue + every expected key fact present (equivalent wordings accepted, `!` = must not appear;
  see `data/tickets.jsonl`). Each expected fact was set to match what the question actually asks, after reading
  every wrong answer by hand. `python eval/rescore.py --show-wrong` prints every answer marked wrong.

| Run (9 Nov) | What changed | Baseline acc. | Meko acc. | Token saving |
|---|---|---|---|---|
| 1 | first live run | 75% | 53% | 62% |
| 2 | triage issue meanings, reused summary = approved fix, synonyms | 78% | 86% | 58% |
| 3 | same-issue reuse only, de-identified shared fixes, JSON retry, per-question facts | 97% | 94% | 47% |
| 4 (10 Nov) | shared fixes keep required documents; shorter triage prompt | 94% | **100%** | **52%** |
| 5 (10 Nov) | Meko half only, with the Postgres ledger on (`--meko-only`) | (run 4) | **100%** | **63%** vs run 4 baseline |

**Run 5 (10 Nov 2026, live, Postgres ledger on):** 36/36 correct, 55,270 tokens (1,535 per ticket). First-time
issues cost 2,731 tokens, repeats 1,075 (**61% less**), and **26 of 26** repeats reused an approved fix. The baseline
was not re-run (Gemini's free tier was slow that evening), so the 63% compares with run 4's baseline (150,139).
The SQL audit from the ledger (`eval/audit-report.md`, also stored in Meko with `artifact_put`):

| Ledger audit | Value |
|---|---|
| Tickets / reused / fresh | 36 / 26 / 10 (reuse rate 72%) |
| Average tokens, fresh vs reused | 2,731 vs 1,075 |
| Caseworker decisions | 10 approved, 0 rejected |

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
pytest -q                          # 26 tests, fake Meko + mock model
python eval/run_eval.py --offline  # checks the whole pipeline without network
streamlit run app.py               # then switch on "Offline demo" in the sidebar
```

Keys: Meko → Settings → Security → API keys. Gemini → https://aistudio.google.com/apikey (free tier is enough).

## Project layout
```
saathi/meko.py      Meko MCP client (+ offline fake)
saathi/llm.py       Gemini model (+ mock model for tests)
saathi/desk.py      the agents and the help-desk flow
saathi/ledger.py    Postgres ledger inside the datapack (AMP) + SQL audit (SQLite offline)
saathi/voice.py     speak / listen with Gemini
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
