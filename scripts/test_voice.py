"""Live round-trip check of the voice feature (needs GEMINI_API_KEY):

    python scripts/test_voice.py

For each language: Gemini reads a citizen's question aloud (speak) -> that audio is written down again
(listen) -> we compare. Saves the audio files in eval/voice_samples/ so a person can listen to them.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi.voice import GeminiVoice  # noqa: E402

SAMPLES = {
    "bn": "আমার পিএম কিষাণের টাকা আসছে না, বলছে আধারের সাথে নাম মিলছে না। কী করব?",
    "hi": "मेरे दादाजी पचहत्तर साल के हैं, क्या उनको आयुष्मान कार्ड मिलेगा?",
    "ta": "என் அம்மாவுக்கு எழுபத்திரண்டு வயது. அவருக்கு ஆயுஷ்மான் அட்டை கிடைக்குமா?",
    "en": "I am sixty three and my family is on the BPL list. Can I get old age pension?",
}


def main() -> None:
    voice = GeminiVoice(os.environ["GEMINI_API_KEY"])
    out = Path(__file__).resolve().parent.parent / "eval" / "voice_samples"
    out.mkdir(parents=True, exist_ok=True)
    for lang, text in SAMPLES.items():
        t0 = time.perf_counter()
        wav = voice.speak(text, lang)
        t1 = time.perf_counter()
        if not wav:
            print(f"[{lang}] speak FAILED")
            continue
        (out / f"{lang}.wav").write_bytes(wav)
        heard = voice.listen(wav, "audio/wav")
        t2 = time.perf_counter()
        print(f"[{lang}] speak {t1 - t0:.1f}s ({len(wav) // 1000} KB)  listen {t2 - t1:.1f}s  language={heard['language']}")
        print(f"   said : {text}")
        print(f"   heard: {heard['text']}")


if __name__ == "__main__":
    main()
