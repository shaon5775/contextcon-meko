"""Language-model layer. Default: Google Gemini (free tier works). Mock model for offline tests."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class LLMReply:
    text: str
    input_tokens: int
    output_tokens: int
    model: str

    def json(self) -> dict:
        """Parse a JSON object from the reply, tolerating ```json fences."""
        raw = self.text.strip()
        match = re.search(r"\{.*\}", raw, re.S)
        return json.loads(match.group(0) if match else raw)


def rough_tokens(text: str) -> int:
    """~4 characters per token. Used only when a provider does not report usage."""
    return max(1, len(text) // 4)


class GeminiLLM:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        from google import genai

        if not api_key:
            raise ValueError("GEMINI_API_KEY is missing. Put it in your .env file.")
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def complete(self, system: str, prompt: str, want_json: bool = True) -> LLMReply:
        from google.genai import types

        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            response_mime_type="application/json" if want_json else "text/plain",
        )
        resp = self.client.models.generate_content(model=self.model, contents=prompt, config=cfg)
        usage = getattr(resp, "usage_metadata", None)
        return LLMReply(
            text=resp.text or "",
            input_tokens=getattr(usage, "prompt_token_count", None) or rough_tokens(system + prompt),
            output_tokens=getattr(usage, "candidates_token_count", None) or rough_tokens(resp.text or ""),
            model=self.model,
        )


# ------------------------------------------------------------------------------
# Mock model: deterministic rules so the whole pipeline can be tested offline.
# Token counts are estimated from prompt length, so baseline-vs-Meko comparisons
# in offline mode still reflect how much context each path sends.
# ------------------------------------------------------------------------------
ISSUE_RULES = [
    ("kisan_name_mismatch", r"name.*(match|mismatch|different|spelling)|नाम|নাম"),
    ("kisan_ekyc_otp", r"otp|ओटीपी|ওটিপি"),
    ("kisan_aadhaar_seeding", r"seed|सीडिंग|সিডিং|npci"),
    ("vayvandana_cghs", r"cghs|echs"),
    ("vayvandana_apply", r"ayushman|आयुष्मान|আয়ুষ্মান|বয় বন্দনা|health card"),
    ("widow_pension_eligibility", r"widow|विधवा|বিধবা|husband died|স্বামী মারা"),
    ("oldage_pension_eligibility", r"old age|pension|पेंशन|ভাতা"),
    ("ujjwala_migrant_docs", r"address proof|migrant|पता प्रमाण"),
    ("ujjwala_existing_lpg", r"gas|गैस|গ্যাস|ujjwala|उज्ज्वला|উজ্জ্বলা"),
    ("wb_women_support_change", r"lakshmi|लक्ष्मी|লক্ষ্মী"),
]
SCHEME_OF = {
    "kisan": "PM-KISAN", "vayvandana": "Ayushman Vay Vandana", "oldage": "NSAP old age pension",
    "widow": "NSAP widow pension", "ujjwala": "PM Ujjwala Yojana", "wb": "West Bengal women support",
}
FACTS = {
    "kisan_name_mismatch": "Do Name Correction as per Aadhaar on pmkisan.gov.in (face authentication) or biometric eKYC at a CSC.",
    "kisan_ekyc_otp": "OTP goes to the Aadhaar-linked mobile; update the mobile in Aadhaar or do biometric eKYC at a CSC.",
    "kisan_aadhaar_seeding": "Ask your bank branch for Aadhaar seeding (NPCI mapper) for DBT, or open an IPPB account.",
    "vayvandana_apply": "Anyone aged 70 or above can get the Vay Vandana card; there is no income limit. Apply on the Ayushman App with Aadhaar eKYC.",
    "vayvandana_cghs": "A CGHS or ECHS member must choose one: Vay Vandana or CGHS/ECHS.",
    "oldage_pension_eligibility": "IGNOAPS needs age 60 or above and a BPL household; apply at the block or municipality office.",
    "widow_pension_eligibility": "IGNWPS widow pension: widow aged 40-79, BPL; bring the husband's death certificate.",
    "ujjwala_existing_lpg": "A household that already has an LPG connection is not eligible for Ujjwala.",
    "ujjwala_migrant_docs": "Migrant families can give a self-declaration instead of address proof.",
    "wb_women_support_change": "Lakshmir Bhandar is replaced by Annapurna Bhandar from June 2026: Rs 3,000 a month for women aged 25 to 60; confirm at the block office.",
}


class MockLLM:
    model = "mock-llm"

    def complete(self, system: str, prompt: str, want_json: bool = True) -> LLMReply:
        tag = re.search(r"\[agent:(\w+)\]", system)
        agent = tag.group(1) if tag else "unknown"
        question = re.search(r"QUESTION:\s*(.*)", prompt, re.S)
        q = (question.group(1) if question else prompt).splitlines()[0].lower()
        issue = next((key for key, pat in ISSUE_RULES if re.search(pat, q)), "other")
        scheme = SCHEME_OF.get(issue.split("_")[0], "unknown")
        if agent == "triage":
            intent = "eligibility" if issue.endswith(("eligibility", "apply", "change", "docs", "lpg", "cghs")) else "problem"
            out = {"scheme": scheme, "issue_key": issue, "intent": intent, "language": "auto",
                   "summary_en": f"{scheme}: {issue.replace('_', ' ')}. {q[:80]}", "profile": {}}
        else:
            fact = FACTS.get(issue, "Please visit your nearest CSC.")
            out = {"answer": fact, "summary_en": fact, "issue_key": issue, "sources": ["mock"],
                   "confidence": 0.8}
        text = json.dumps(out, ensure_ascii=False)
        return LLMReply(text=text, input_tokens=rough_tokens(system + prompt),
                        output_tokens=rough_tokens(text), model=self.model)
