"""Voice in, voice out, for citizens who cannot type.

    listen(audio_bytes) -> {"text": what the person said, in their own script, "language": "bn"}
    speak(text, language) -> WAV bytes of the answer read aloud (or None if speech is unavailable)

Both use Gemini (free tier). Gemini understands speech in most Indian languages, so the citizen can talk in
Bengali, Hindi, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Odia, Punjabi, Assamese, Urdu, English or
a mix. Spoken text then goes through the normal help desk (triage -> Meko memory -> answer).
"""
from __future__ import annotations

import io
import json
import os
import re
import wave

from .desk import _SAME_SCRIPT, _SCRIPTS, LANGUAGE_NAMES

LISTEN_MODEL = os.getenv("GEMINI_LISTEN_MODEL", "gemini-3.5-flash-lite")
SPEAK_MODEL = os.getenv("GEMINI_SPEAK_MODEL", "gemini-3.8-flash-lite-tts")
SPEAK_VOICE = os.getenv("GEMINI_SPEAK_VOICE", "Kore")

LISTEN_PROMPT = """Write down exactly what this person says, word for word. Do not translate and do not answer.
Use the NATIVE SCRIPT of the language spoken - never Latin letters for an Indian language:
Bengali -> বাংলা লিপি, Hindi/Marathi -> देवनागरी, Tamil -> தமிழ், Telugu -> తెలుగు, Gujarati -> ગુજરાતી,
Kannada -> ಕನ್ನಡ, Malayalam -> മലയാളം, Odia -> ଓଡ଼ିଆ, Punjabi -> ਗੁਰਮੁਖੀ, Urdu -> اردو.
Only English, or Hindi mixed with English words (Hinglish), may be written in Latin letters.
English words inside an Indian sentence (PM Kisan, Aadhaar, OTP) may stay in Latin letters.
Write the letters themselves (e.g. আমার, मेरे) - NEVER \\u escape codes.
{hint}Return ONLY JSON: {{"text": "...", "language": "<ISO 639-1 code, or hinglish>"}}"""


def script_mismatch(text: str, language: str) -> bool:
    """True when the text is mostly in another Indian script than the named language uses (e.g. ta in Telugu)."""
    own = {code for _, _, code in _SCRIPTS}
    if language not in own:
        return False
    counts = {code: sum(1 for ch in text if lo <= ch <= hi) for lo, hi, code in _SCRIPTS}
    code, n = max(counts.items(), key=lambda kv: kv[1])
    return bool(n) and code != language and language not in _SAME_SCRIPT.get(code, set())


def parse_heard(raw: str) -> dict:
    """Read the listen reply. Gemini sometimes escapes Indian letters as \\uXXXX and breaks one escape, which makes
    the JSON invalid (seen live for Bengali on 10 Nov 2026). Then pull text/language out leniently instead of
    showing the raw JSON to the citizen."""
    raw = raw or "{}"
    try:
        out = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return {"text": str(out.get("text", "")).strip(), "language": str(out.get("language", "")).strip().lower()}
    except (AttributeError, json.JSONDecodeError):
        pass
    m = re.search(r'"text"\s*:\s*"(.*)"\s*,\s*"language"\s*:\s*"([^"]*)"', raw, re.S)
    if not m:
        return {"text": raw.strip(), "language": ""}
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), m.group(1))
    text = re.sub(r"\\u[0-9a-fA-F]{0,3}", "", text).replace('\\"', '"').replace("\\n", " ")
    return {"text": re.sub(r"\s+", " ", text).strip(), "language": m.group(2).strip().lower()}


def _retry(call, tries: int = 5):
    """Free tier: wait and retry on rate limits / busy servers (same rule as the text model)."""
    import time
    for attempt in range(tries):
        try:
            return call()
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1 or not any(c in str(e) for c in ("429", "RESOURCE_EXHAUSTED", "503", "504",
                                                                     "UNAVAILABLE", "DEADLINE")):
                raise
            print(f"  (Gemini busy or rate-limited, retrying in {15 * (attempt + 1)}s)")
            time.sleep(15 * (attempt + 1))


def pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Gemini speech comes back as raw 16-bit PCM; browsers need a WAV header to play it."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def speakable(text: str) -> str:
    """Remove markdown symbols and URLs that sound strange when read aloud."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class GeminiVoice:
    def __init__(self, api_key: str):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=90_000, retry_options=types.HttpRetryOptions(attempts=2)))

    def listen(self, audio: bytes, mime_type: str = "audio/wav", language_hint: str = "") -> dict:
        """language_hint: optional code the user picked (e.g. "bn"); helps the model choose the script."""
        t = self.types
        name = LANGUAGE_NAMES.get(language_hint, language_hint)
        hint = f"The person is expected to speak {name}.\n" if language_hint else ""
        resp = _retry(lambda: self.client.models.generate_content(
            model=LISTEN_MODEL,
            contents=[t.Part.from_bytes(data=audio, mime_type=mime_type), LISTEN_PROMPT.format(hint=hint)],
            config=t.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
        ))
        out = parse_heard(resp.text or "{}")
        # Live 10 Nov 2026: Tamil speech came back as language "ta" but written in TELUGU letters. If the letters do
        # not match the language the model itself named, ask once more and tell it which language to write.
        if not language_hint and script_mismatch(out["text"], out["language"]):
            return self.listen(audio, mime_type, out["language"])
        return out

    def speak(self, text: str, language: str = "") -> bytes | None:
        """Read the answer aloud. Returns WAV bytes, or None if the speech model is not available."""
        t = self.types
        # Only the answer itself: an instruction like "Read this aloud slowly..." was spoken out loud in the live
        # English test (10 Nov 2026). The speech model picks the language from the text.
        prompt = speakable(text)
        try:
            resp = _retry(lambda: self.client.models.generate_content(
                model=SPEAK_MODEL, contents=prompt,
                config=t.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=t.SpeechConfig(voice_config=t.VoiceConfig(
                        prebuilt_voice_config=t.PrebuiltVoiceConfig(voice_name=SPEAK_VOICE)))),
            ))
            part = resp.candidates[0].content.parts[0]
            data = part.inline_data.data
            mime = (part.inline_data.mime_type or "").lower()
            rate = int(re.search(r"rate=(\d+)", mime).group(1)) if "rate=" in mime else 24000
            return data if mime.startswith("audio/wav") else pcm_to_wav(data, rate=rate)
        except Exception as e:  # noqa: BLE001 - speech is a bonus; the text answer is always shown
            print(f"  (speech unavailable: {str(e)[:160]})")
            return None


class MockVoice:
    """Offline stand-in: pretends the citizen said a fixed Bengali sentence."""

    def listen(self, audio: bytes, mime_type: str = "audio/wav", language_hint: str = "") -> dict:
        return {"text": "আমার পিএম কিষাণের টাকা আসছে না, বলছে আধারের সাথে নাম মিলছে না। কী করব?", "language": "bn"}

    def speak(self, text: str, language: str = "") -> bytes | None:
        return pcm_to_wav(b"\x00\x00" * 2400)   # 0.1 s of silence
