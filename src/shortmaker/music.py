"""Background music via the Pixabay Music API.

The Pixabay docs that ship with the public site confirm the image and video
endpoints; the music endpoint is not officially documented at the same URL.
We try the likely dedicated music endpoint, and fall back to a bundled
synthesized tone if it is unavailable.
"""

from __future__ import annotations

import math
import sys
import wave
from pathlib import Path

import requests

from .audio import write_silence_wav
from .config import MUSIC_DIR
from .http import stream_download

PIXABAY_MUSIC_URL = "https://pixabay.com/api/music/"


def _synthesize_tone(seconds: float, path: Path, freq: float = 220.0) -> None:
    """Generate a soft ambient tone for the offline fallback path."""
    import numpy as np  # only needed when the API is unavailable

    sr = 22050
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    pad = 0.1 * (np.sin(2 * math.pi * freq * t)
                 + 0.5 * np.sin(2 * math.pi * (freq * 1.5) * t))
    fade = int(sr * 0.5)
    pad[:fade] *= np.linspace(0, 1, fade)
    pad[-fade:] *= np.linspace(1, 0, fade)
    pcm = (pad * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)


def _offline_tone(seconds: float = 30.0) -> Path:
    dest = MUSIC_DIR / "fallback_tone.wav"
    if dest.exists():
        return dest
    try:
        _synthesize_tone(seconds, dest)
    except ImportError:
        write_silence_wav(seconds, dest)
    return dest


def fetch(query: str, api_key: str | None, target_seconds: float = 30.0) -> Path:
    """Fetch a music clip matching the topic. Returns a local MP3/WAV path."""
    if not api_key:
        return _offline_tone(target_seconds)

    try:
        resp = requests.get(
            PIXABAY_MUSIC_URL,
            params={"key": api_key, "q": query, "per_page": 3},
            timeout=30,
        )
    except requests.RequestException as exc:
        sys.stderr.write(f"  Pixabay request error: {exc}\n")
        return _offline_tone(target_seconds)

    if not resp.ok:
        sys.stderr.write(f"  Pixabay {PIXABAY_MUSIC_URL} -> HTTP {resp.status_code}\n")
        return _offline_tone(target_seconds)

    try:
        data = resp.json()
    except ValueError:
        return _offline_tone(target_seconds)

    for hit in data.get("hits") or []:
        url = hit.get("audio_url")
        if not url:
            continue
        dest = MUSIC_DIR / f"{Path(url).stem}.mp3"
        try:
            stream_download(url, dest, timeout=60)
            return dest
        except Exception as exc:
            sys.stderr.write(f"  Pixabay download failed {url}: {exc}\n")
            continue

    sys.stderr.write("  WARN: Pixabay music returned no audio_url; using fallback tone.\n")
    return _offline_tone(target_seconds)