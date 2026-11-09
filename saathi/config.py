"""Settings come from environment variables (or a local .env file that is never committed)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


@dataclass
class Settings:
    meko_api_key: str = os.getenv("MEKO_API_KEY", "")
    meko_datapack_id: str = os.getenv("MEKO_DATAPACK_ID", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def load_knowledge() -> str:
    """All official-rules documents joined together (used by the baseline and the offline fake)."""
    parts = []
    for path in sorted((ROOT / "knowledge").glob("*.md")):
        parts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def knowledge_files() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((ROOT / "knowledge").glob("*.md"))}


def build(offline: bool = False, use_memory: bool = True):
    """Return (meko_client, llm, knowledge_text) ready for HelpDesk."""
    from .llm import GeminiLLM, MockLLM
    from .meko import FakeMeko, MekoClient

    knowledge = load_knowledge()
    if offline:
        return FakeMeko(knowledge=knowledge_files()), MockLLM(), knowledge
    s = Settings()
    meko = MekoClient(s.meko_api_key, s.meko_datapack_id)
    return meko, GeminiLLM(s.gemini_api_key, s.gemini_model), knowledge
