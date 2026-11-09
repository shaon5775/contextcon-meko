"""Yojana Saathi help desk: triage → search-before-solving → specialist agent → caseworker review.

Two modes:
- use_memory=True  ("Meko mode"):  retrieval + shared, caseworker-verified memory in Meko.
- use_memory=False ("baseline"):   the whole rulebook is pasted into every prompt; nothing is remembered.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_TRIAGE = "yojana_saathi:triage"
AGENT_ELIGIBILITY = "yojana_saathi:eligibility"
AGENT_RESOLVER = "yojana_saathi:resolver"
AGENT_CASEWORKER = "yojana_saathi:caseworker"

ISSUE_MEANING = {
    "kisan_name_mismatch": "PM-KISAN money stopped because the name does not match Aadhaar (spelling, name mismatch)",
    "kisan_ekyc_otp": "PM-KISAN eKYC fails because the OTP does not arrive (old or closed mobile number)",
    "kisan_aadhaar_seeding": "PM-KISAN payment failed: bank account not Aadhaar-seeded, NPCI mapper, DBT failure",
    "vayvandana_apply": "Ayushman Bharat card / Ayushman Vay Vandana for a person aged 70 or more: who can get it, "
                        "how to apply, the Rs 5 lakh senior health card",
    "vayvandana_cghs": "a 70+ senior who already has CGHS, ECHS or another government health scheme asks about Vay Vandana",
    "oldage_pension_eligibility": "old-age pension (NSAP / IGNOAPS, budhapa pension, bardhakya bhata) eligibility or how to apply",
    "widow_pension_eligibility": "widow pension (IGNWPS, bidhoba bhata) eligibility or documents",
    "ujjwala_existing_lpg": "PM Ujjwala free gas connection when the household ALREADY has an LPG connection",
    "ujjwala_migrant_docs": "PM Ujjwala for a migrant family without local address proof",
    "wb_women_support_change": "West Bengal Lakshmir Bhandar / Annapurna Bhandar monthly money for women",
    "other": "anything else",
}
ISSUE_KEYS = list(ISSUE_MEANING)
_ISSUE_LINES = "\n".join(f"    {k}: {v}" for k, v in ISSUE_MEANING.items())

TRIAGE_SYSTEM = f"""[agent:triage] You are the triage agent of Yojana Saathi, an Indian government-scheme help desk.
Read the citizen's question (it may be in Bengali, Hindi, English or Hinglish).
Return ONLY a JSON object with keys:
  scheme      - the scheme name in English (or "unknown")
  issue_key   - exactly one of these keys (pick the closest; use "other" only if none fits):
{_ISSUE_LINES}
  intent      - "eligibility" (which scheme / can I get it / how to apply) or "problem" (something failed or stopped)
  language    - the citizen's language: "bn", "hi", "en" or "hinglish"
  summary_en  - one short English sentence describing the need, with no names, phone or Aadhaar numbers
  profile     - object with any of: age, gender, state, bpl (true/false), occupation
"""

SPECIALIST_SYSTEM = """[agent:{agent}] You are the {role} agent of Yojana Saathi, an Indian government-scheme help desk.
Answer ONLY from the CONTEXT given. If the context does not cover it, say so and point to the official office.
Write the answer in the citizen's language ({language}), in simple words, as short numbered steps.
Always end by telling the citizen to confirm on the official portal or office, and never to pay middlemen.
Return ONLY a JSON object with keys:
  answer      - the reply to the citizen, in their language
  summary_en  - the same advice in one or two English sentences (for the caseworker). Keep the key facts
                (ages, eligible / not eligible, documents, where to go) and the official terms used in the
                CONTEXT (e.g. BPL, eKYC, Aadhaar seeding, Name Correction as per Aadhaar, self-declaration)
  issue_key   - the issue you solved (from triage)
  sources     - list of document names or memory ids you used
  confidence  - number 0..1
"""

REUSE_SYSTEM = """[agent:resolver] You are the resolver agent of Yojana Saathi. A caseworker already APPROVED the fix below
for this exact problem. Re-use it: explain it to this citizen in their language ({language}), in simple numbered steps.
Do not add new facts. End with: confirm at the official office, never pay middlemen.
Return ONLY a JSON object with keys: answer, summary_en, issue_key, sources, confidence.
"""


@dataclass
class TicketResult:
    ticket_id: str
    mode: str                     # "meko" or "baseline"
    path: str                     # "reused" | "fresh" | "baseline"
    issue_key: str
    intent: str
    language: str
    answer: str
    summary_en: str
    sources: list = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0       # agent time, excluding free-tier rate-limit waits
    waited_s: float = 0.0
    steps: list = field(default_factory=list)     # human-readable decision trace
    conversation_id: str | None = None
    reused_memory_id: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        return d


def _text_of(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("memory", "text", "content", "chunk", "page_content", "snippet"):
            if item.get(key):
                return str(item[key])
    return json.dumps(item, ensure_ascii=False)[:1200]


def _doc_of(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("document", "document_name", "filename", "source", "title", "document_id"):
            if item.get(key):
                return str(item[key])
    return "knowledge"


LANGUAGES = {"bn", "hi", "en", "hinglish"}
_HINGLISH_WORDS = {"mera", "meri", "mere", "kya", "hai", "hain", "nahi", "nahin", "paisa", "kaise", "kab",
                   "milega", "milta", "karu", "karun", "karna", "raha", "rahi", "gaya", "bhai", "ji", "ko"}


def detect_language(text: str, model_guess: str | None = None) -> str:
    """The citizen's language. Script is checked first because it is certain: Bengali letters → bn,
    Devanagari → hi. Latin text uses the model's guess if valid, else a small Hinglish word check."""
    bengali = sum(1 for ch in text if "ঀ" <= ch <= "৿")
    devanagari = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    if bengali or devanagari:
        return "bn" if bengali >= devanagari else "hi"
    guess = (model_guess or "").strip().lower()
    if guess in {"en", "hinglish"}:
        return guess
    words = set(re.findall(r"[a-z]+", text.lower()))
    return "hinglish" if len(words & _HINGLISH_WORDS) >= 2 else "en"


def _as_list(x: Any) -> list:
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for key in ("results", "chunks", "documents", "hits", "items"):
            if isinstance(x.get(key), list):
                return x[key]
    return []


class HelpDesk:
    def __init__(self, meko, llm, knowledge_text: str, use_memory: bool = True,
                 same_issue_min_score: float = 0.2, any_issue_min_score: float = 0.7,
                 run_tag: str | None = None):
        """Reuse rule: a verified fix is reused when it is tagged with the SAME issue and its relevance score
        is at least `same_issue_min_score`, or when its score alone is at least `any_issue_min_score`.
        Both thresholds are calibrated on the live Meko scores (see eval/).
        `run_tag` (used by the evaluation) limits reuse to fixes approved in the same run, so every
        evaluation starts from empty memory without deleting anyone's real fixes."""
        self.meko = meko
        self.llm = llm
        self.knowledge_text = knowledge_text
        self.use_memory = use_memory
        self.same_issue_min_score = same_issue_min_score
        self.any_issue_min_score = any_issue_min_score
        self.run_tag = run_tag

    # -------------------------------------------------------------- helpers
    async def _ask(self, res: TicketResult, name: str, system: str, prompt: str) -> dict:
        reply = self.llm.complete(system, prompt)
        res.llm_calls += 1
        res.input_tokens += reply.input_tokens
        res.waited_s += getattr(reply, "waited_s", 0.0)
        res.output_tokens += reply.output_tokens
        if self.use_memory and res.conversation_id:
            await self.meko.track_tokens(res.conversation_id, name, reply.model, reply.input_tokens,
                                         reply.output_tokens)
        try:
            return reply.json()
        except (ValueError, json.JSONDecodeError):
            return {"answer": reply.text, "summary_en": reply.text[:300]}

    def _pick_verified_fix(self, memories: list, issue_key: str) -> dict | None:
        best = None
        for m in memories:
            meta = m.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            if meta.get("type") != "verified_fix":
                continue
            if self.run_tag and meta.get("run_tag") != self.run_tag:
                continue
            same_issue = issue_key != "other" and meta.get("issue_key") == issue_key
            score = float(m.get("score") or 0)
            if same_issue and score >= self.same_issue_min_score:
                why = f"same issue tag, score {score:.2f} ≥ {self.same_issue_min_score:.2f}"
            elif score >= self.any_issue_min_score:
                why = f"score {score:.2f} ≥ {self.any_issue_min_score:.2f}"
            else:
                continue
            if best is None or score > float(best.get("score") or 0):
                best = {**m, "metadata": meta, "why": why}
        return best

    # -------------------------------------------------------------- main flow
    async def handle(self, text: str, ticket_id: str = "ad-hoc") -> TicketResult:
        t0 = time.perf_counter()
        res = TicketResult(ticket_id=ticket_id, mode="meko" if self.use_memory else "baseline", path="",
                           issue_key="other", intent="", language="", answer="", summary_en="")
        if self.use_memory:
            res.conversation_id = await self.meko.conversation_create(AGENT_TRIAGE, f"Ticket {ticket_id}")

        # 1. Triage
        tri = await self._ask(res, "triage", TRIAGE_SYSTEM, f"QUESTION: {text}")
        res.issue_key = tri.get("issue_key", "other")
        res.intent = tri.get("intent", "problem")
        res.language = detect_language(text, tri.get("language"))
        res.steps.append(f"Triage: scheme={tri.get('scheme')}, issue={res.issue_key}, intent={res.intent}, "
                         f"language={res.language}")
        specialist, role = ((AGENT_ELIGIBILITY, "eligibility") if res.intent == "eligibility"
                            else (AGENT_RESOLVER, "resolver"))

        # 2. Search before solving (Meko mode only)
        if self.use_memory:
            query = f"{tri.get('scheme', '')} {res.issue_key.replace('_', ' ')}: {tri.get('summary_en', text)}"
            ctx = await self.meko.context_search(query, res.conversation_id, AGENT_TRIAGE, limit=5)
            buckets = ctx.get("results", ctx) if isinstance(ctx, dict) else {}
            memories = _as_list(buckets.get("memory"))
            kb = _as_list(buckets.get("knowledge_base"))
            fix = self._pick_verified_fix(memories, res.issue_key)
            res.steps.append(f"Memory check: {len(memories)} memories, {len(kb)} knowledge chunks; "
                             f"verified fix {'FOUND' if fix else 'not found'}")

            if fix:  # 3a. Reuse the caseworker-approved fix
                res.path = "reused"
                res.reused_memory_id = fix.get("id")
                out = await self._ask(res, "resolver_reuse", REUSE_SYSTEM.format(language=res.language),
                                      f"APPROVED FIX (memory {fix.get('id')}):\n{_text_of(fix)}\n\nQUESTION: {text}")
                res.steps.append(f"Resolver reused approved fix {fix.get('id')} ({fix['why']})")
            else:    # 3b. Solve fresh from retrieved official rules
                res.path = "fresh"
                if not kb:
                    kb = _as_list(await self.meko.kb_search(query, res.conversation_id, specialist, limit=4))
                context = "\n\n".join(f"[{_doc_of(c)}]\n{_text_of(c)}" for c in kb[:5]) or "(no documents found)"
                out = await self._ask(res, role, SPECIALIST_SYSTEM.format(agent=role, role=role, language=res.language),
                                      f"CONTEXT:\n{context}\n\nQUESTION: {text}")
                res.steps.append(f"{role.title()} agent solved fresh from {len(kb[:5])} knowledge chunks "
                                 f"({', '.join(sorted({_doc_of(c) for c in kb[:5]}))})")
        else:  # Baseline: stuff the entire rulebook into the prompt, no memory
            res.path = "baseline"
            out = await self._ask(res, role, SPECIALIST_SYSTEM.format(agent=role, role=role, language=res.language),
                                  f"CONTEXT:\n{self.knowledge_text}\n\nQUESTION: {text}")
            res.steps.append(f"{role.title()} agent answered with the full rulebook in the prompt")

        res.answer = out.get("answer", "")
        res.summary_en = out.get("summary_en", "")
        if res.path == "reused":
            # The caseworker summary of a reused answer is the approved fix itself, word for word,
            # so the audit shows exactly which verified advice was given.
            approved = re.sub(r"^VERIFIED FIX \[[^\]]*\]:\s*", "", _text_of(fix))
            res.summary_en = re.sub(r"\s*\(Approved by [^)]*\)\.?\s*$", "", approved)
        res.sources = out.get("sources", []) or []
        res.latency_s = round(time.perf_counter() - t0 - res.waited_s, 3)

        # 4. Store the conversation turn with its reasoning, so the trace explains the decision
        if self.use_memory:
            # Meko requires the agent that created the conversation (triage) to write its turns;
            # the specialist that actually answered is recorded in the metadata.
            await self.meko.add_turn(
                res.conversation_id, AGENT_TRIAGE, user=text, assistant=res.answer,
                reasoning=" | ".join(res.steps), plan=res.steps,
                metadata={"ticket": ticket_id, "answered_by": specialist, "path": res.path,
                          "issue_key": res.issue_key,
                          "reused_memory_id": res.reused_memory_id, "tokens": res.total_tokens},
            )
        return res

    async def approve(self, res: TicketResult, caseworker: str = "caseworker", promote: bool = False) -> str | None:
        """Human-in-the-loop: only an approved, de-identified fix becomes shared memory."""
        if not self.use_memory or res.path == "reused" or not res.summary_en:
            return None
        scheme_part = res.issue_key.replace("_", " ")
        text = f"VERIFIED FIX [{scheme_part}]: {res.summary_en} (Approved by {caseworker}.)"
        meta = {"type": "verified_fix", "issue_key": res.issue_key, "intent": res.intent,
                "approved_by": caseworker, "ticket": res.ticket_id, "sources": res.sources[:5]}
        if self.run_tag:
            meta["run_tag"] = self.run_tag
        added = await self.meko.memory_add(text, res.conversation_id, AGENT_CASEWORKER, meta)
        mem_ids = [r.get("id") for r in _as_list(added) if r.get("id")]
        if promote and mem_ids:
            await self.meko.memory_promote(mem_ids, res.conversation_id, AGENT_CASEWORKER)
        return mem_ids[0] if mem_ids else None
