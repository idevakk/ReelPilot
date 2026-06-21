"""Text-to-speech via Deepgram Aura REST API.

POSTs the full narration text, saves the returned WAV, and returns duration.
Falls back to a silent WAV of `target_seconds` if no API key is set so the
rest of the pipeline still works (for tests and offline runs).
"""

from __future__ import annotations

import math
import subprocess
import sys
import wave
from pathlib import Path

import requests

from .audio import write_silence_wav

DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak?model={model}"

DEFAULT_VOICE = "aura-2-luna-en"


def _probe_duration(path: Path) -> float:
    """Return the duration of `path` in seconds.

    Tries the stdlib `wave` module first (fast, no subprocess). Falls back
    to `ffprobe` for non-WAV containers. Returns 0.0 on any failure.
    """
    try:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as w:
                return w.getnframes() / w.getframerate()
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stderr=subprocess.STDOUT,
        )
        return float(out.decode().strip() or "0")
    except Exception:
        return 0.0


def synthesize(text: str, path: Path, api_key: str | None,
               voice: str = DEFAULT_VOICE, target_seconds: float = 30.0) -> float:
    """Synthesize text to WAV. Returns duration in seconds."""
    from .audio import write_silence_wav  # for the silent fallback

    if not api_key:
        write_silence_wav(target_seconds, path)
        return target_seconds

    url = DEEPGRAM_TTS_URL.format(model=voice)
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json={"text": text}, timeout=120)
        resp.raise_for_status()
        if not resp.content:
            raise ValueError("Deepgram returned an empty body")
        path.write_bytes(resp.content)
        return _probe_duration(path)
    except Exception as exc:
        # Fail soft: log and fall back to the silent WAV so the rest of the
        # pipeline can still produce a captioned video without voiceover.
        sys.stderr.write(
            f"  WARN: Deepgram TTS failed ({exc!r}); using silent placeholder.\n"
        )
        write_silence_wav(target_seconds, path)
        return target_seconds


def estimate_cost_usd(text: str, price_per_1k_chars: float = 0.015) -> float:
    """Deepgram Aura: ~$0.015 per 1k characters (Aura HD pricing)."""
    return math.ceil(len(text) / 1000) * price_per_1k_chars