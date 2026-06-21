"""Shared audio utilities."""

from __future__ import annotations

import wave
from pathlib import Path


def write_silence_wav(seconds: float, path: Path, *, sample_rate: int = 22050) -> None:
    """Write a mono 16-bit silent WAV of the given duration.

    Used as the offline fallback for both TTS (Deepgram) and background music
    (Pixabay) so the rest of the pipeline can still run without network or
    API keys. Keep sample_rate in sync between callers — the sidechain
    filter in `assembly.mix_audio` expects matching rates.
    """
    n_samples = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_samples)