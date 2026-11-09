"""Yojana Saathi help desk: triage → search-before-solving → specialist agent → caseworker review.

Two modes:
- use_memory=True  ("Meko mode"):  retrieval + shared, caseworker-verified memory in Meko.
- use_memory=False ("baseline"):   the whole rulebook is pasted into every prompt; nothing is remembered.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_TRIAGE = "yojana_saathi:triage"
AGENT_ELIGIBILITY = "yojana_saathi:eligibility"
AGENT_RESOLVER = "yojana_saathi:resolver"
AGENT_CASEWORKER = "yojana_saathi:caseworker"

ISSUE_KEYS = [
    "kisan_name_mismatch", "kisan_ekyc_otp", "kisan_aadhaar_seeding", "vayvandana_apply", "vayvandana_cghs",
    "oldage_pension_eligibility", "widow_pension_eligibility", "ujjwala_existing_lpg", "ujjwala_migrant_docs",
    "wb_women_support_change", "other",
]

TRIAGE_SYSTEM = f"""[agent:triage] You are the triage agent of Yojana Saathi, an Indian government-scheme help desk.
Read the citizen's question (it may be in Bengali, Hindi, English or Hinglish).
Return ONLY a JSON object with keys:
  scheme      - the scheme name in English (or "unknown")
  issue_key   - one of {ISSUE_KEYS}
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
  summary_en  - the same advice in one or two English sentences (for the caseworker)
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
    latency_s: float = 0.0
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


def _as_list(x: Any) -> list:
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for key in ("results", "chunks", "documents", "hits", "items"):
            if isinstance(x.get(key), list):
                return x[key]
    return []


class HelpDesk:
    def __init__(self, meko, llm, knowledge_text: str, use_memory: bool = True, reuse_min_score: float = 0.45):
        self.meko = meko
        self.llm = llm
        self.knowledge_text = knowledge_text
        self.use_memory = use_memory
        self.reuse_min_score = reuse_min_score

    # -------------------------------------------------------------- helpers
    async def _ask(self, res: TicketResult, name: str, system: str, prompt: str) -> dict:
        reply = self.llm.complete(system, prompt)
        res.llm_calls += 1
        res.input_tokens += reply.input_tokens
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
            same_issue = issue_key != "other" and meta.get("issue_key") == issue_key
            score = float(m.get("score") or 0)
            if same_issue or score >= self.reuse_min_score + 0.25:
                if best is None or score > float(best.get("score") or 0):
                    best = {**m, "metadata": meta}
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
        res.language = tri.get("language", "en")
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
                res.steps.append(f"Resolver reused approved fix {fix.get('id')} (score {fix.get('score')})")
            else:    # 3b. Solve fresh from retrieved official rules
                res.path = "fresh"
                if not kb:
                    kb = _as_list(await self.meko.kb_search(query, res.conversation_id, specialist, limit=4))
                context = "\n\n".join(f"[{_doc_of(c)}]\n{_text_of(c)}" for c in kb[:4]) or "(no documents found)"
                out = await self._ask(res, role, SPECIALIST_SYSTEM.format(agent=role, role=role, language=res.language),
                                      f"CONTEXT:\n{context}\n\nQUESTION: {text}")
                res.steps.append(f"{role.title()} agent solved fresh from {len(kb[:4])} knowledge chunks")
        else:  # Baseline: stuff the entire rulebook into the prompt, no memory
            res.path = "baseline"
            out = await self._ask(res, role, SPECIALIST_SYSTEM.format(agent=role, role=role, language=res.language),
                                  f"CONTEXT:\n{self.knowledge_text}\n\nQUESTION: {text}")
            res.steps.append(f"{role.title()} agent answered with the full rulebook in the prompt")

        res.answer = out.get("answer", "")
        res.summary_en = out.get("summary_en", "")
        res.sources = out.get("sources", []) or []
        res.latency_s = round(time.perf_counter() - t0, 3)

        # 4. Store the conversation turn with its reasoning, so the trace explains the decision
        if self.use_memory:
            await self.meko.add_turn(
                res.conversation_id, specialist, user=text, assistant=res.answer,
                reasoning=" | ".join(res.steps), plan=res.steps,
                metadata={"ticket": ticket_id, "path": res.path, "issue_key": res.issue_key,
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
        added = await self.meko.memory_add(text, res.conversation_id, AGENT_CASEWORKER, meta)
        mem_ids = [r.get("id") for r in _as_list(added) if r.get("id")]
        if promote and mem_ids:
            await self.meko.memory_promote(mem_ids, res.conversation_id, AGENT_CASEWORKER)
        return mem_ids[0] if mem_ids else None
