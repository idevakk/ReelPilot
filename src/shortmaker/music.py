"""Background music via local library + Pixabay API fallback.

v2 improvements:
- Scans ``assets/music/library/`` for user-provided tracks first.
- Caches fetched music in SQLite to avoid re-downloading.
- Improved synthesized fallback tone with more musical quality.
"""

from __future__ import annotations

import math
import random
import sys
import wave
from pathlib import Path

import requests

from . import cache
from .audio import write_silence_wav
from .config import MUSIC_DIR, MUSIC_LIBRARY_DIR
from .http import stream_download

PIXABAY_MUSIC_URL = "https://pixabay.com/api/music/"


# ─── local library scan ──────────────────────────────────────────────────

def _scan_library() -> list[Path]:
    """Return all audio files in the user's local music library."""
    if not MUSIC_LIBRARY_DIR.exists():
        return []
    exts = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
    return sorted(
        p for p in MUSIC_LIBRARY_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in exts and p.stat().st_size > 1024
    )


def _pick_from_library(query: str | None = None) -> Path | None:
    """Pick a random track from the local library, optionally keyword-biased."""
    tracks = _scan_library()
    if not tracks:
        return None
    if query:
        # Try to match keywords in filename
        q_lower = query.lower()
        matches = [t for t in tracks if any(w in t.stem.lower() for w in q_lower.split())]
        if matches:
            return random.choice(matches)
    return random.choice(tracks)


# ─── improved synthesised tone ────────────────────────────────────────────

def _synthesize_tone(seconds: float, path: Path) -> None:
    """Generate a more musical ambient pad for the fallback path.

    Uses layered sine waves with slight detuning for a warm, lo-fi feel
    instead of the old harsh single-frequency tone.
    """
    import numpy as np

    sr = 44100
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)

    # Warm pad: root (110 Hz) + fifth (165 Hz) + octave (220 Hz), detuned
    pad = (
        0.06 * np.sin(2 * math.pi * 110.0 * t)
        + 0.04 * np.sin(2 * math.pi * 164.8 * t)   # slightly flat fifth
        + 0.03 * np.sin(2 * math.pi * 220.5 * t)    # slightly sharp octave
        + 0.02 * np.sin(2 * math.pi * 329.6 * t)    # major third above
    )

    # Gentle LFO tremolo
    lfo = 1.0 + 0.15 * np.sin(2 * math.pi * 0.3 * t)
    pad *= lfo

    # Fade in/out
    fade_samples = int(sr * 1.0)
    if len(pad) > fade_samples * 2:
        pad[:fade_samples] *= np.linspace(0, 1, fade_samples)
        pad[-fade_samples:] *= np.linspace(1, 0, fade_samples)

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


# ─── main entry point ────────────────────────────────────────────────────

def fetch(query: str, api_key: str | None,
          target_seconds: float = 30.0,
          mood: str | None = None,
          bgm_file: str | None = None) -> Path:
    """Fetch a music clip. Priority order:
    
    0. Explicit bgm_file (if provided)
    1. Local library (``assets/music/library/``)
    2. SQLite cache (previously downloaded)
    3. Pixabay API
    4. Synthesised fallback tone
    """
    
    # 0. Explicit request
    if bgm_file and bgm_file != "auto":
        explicit_path = MUSIC_LIBRARY_DIR / bgm_file
        if explicit_path.exists():
            return explicit_path

    # 1. Local library
    lib_track = _pick_from_library(query)
    if lib_track:
        return lib_track

    # 2. SQLite cache
    cached = cache.find_music(query=query, mood=mood, min_duration=target_seconds * 0.5)
    if cached:
        return cached.file_path

    # 3. Pixabay API
    if api_key:
        track = _try_pixabay(query, api_key, target_seconds, mood)
        if track:
            return track

    # 4. Fallback
    return _offline_tone(target_seconds)


def _try_pixabay(query: str, api_key: str,
                 target_seconds: float, mood: str | None) -> Path | None:
    """Attempt Pixabay music download; return None on any failure."""
    try:
        resp = requests.get(
            PIXABAY_MUSIC_URL,
            params={"key": api_key, "q": query, "per_page": 5},
            timeout=30,
        )
    except requests.RequestException as exc:
        sys.stderr.write(f"  Pixabay request error: {exc}\n")
        return None

    if not resp.ok:
        sys.stderr.write(f"  Pixabay {PIXABAY_MUSIC_URL} -> HTTP {resp.status_code}\n")
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    for hit in data.get("hits") or []:
        url = hit.get("audio_url")
        if not url:
            continue
        dest = MUSIC_DIR / f"{Path(url).stem}.mp3"
        try:
            stream_download(url, dest, timeout=60)
            cache.store_music(
                path=dest,
                query=query,
                duration_s=hit.get("duration"),
                source="pixabay",
                mood=mood,
            )
            return dest
        except Exception as exc:
            sys.stderr.write(f"  Pixabay download failed {url}: {exc}\n")
            continue

    return None