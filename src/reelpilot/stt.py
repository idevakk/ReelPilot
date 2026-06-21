"""Word-level timing via Deepgram STT or faster-whisper.

Uses Deepgram Nova-2 if an API key is provided (significantly faster), 
otherwise falls back to local `faster-whisper` on CPU.
Returns a list of WordCue objects with millisecond precision.
"""

from __future__ import annotations

import json
from pathlib import Path
import requests

from .models import Captions, WordCue


def transcribe(wav_path: Path, api_key: str | None = None, model_size: str = "small",
               device: str = "cpu", compute_type: str = "int8") -> Captions:
    if api_key:
        return _transcribe_deepgram(wav_path, api_key)
    return _transcribe_whisper(wav_path, model_size, device, compute_type)


def _transcribe_deepgram(wav_path: Path, api_key: str) -> Captions:
    url = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true"
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "audio/wav"}
    with open(wav_path, "rb") as f:
        resp = requests.post(url, headers=headers, data=f, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    
    words = data["results"]["channels"][0]["alternatives"][0]["words"]
    cues: list[WordCue] = []
    for w in words:
        word = w.get("punctuated_word", w.get("word", "")).strip()
        if not word:
            continue
        cues.append(WordCue(word=word, start=float(w["start"]), end=float(w["end"])))
    
    return Captions(cues=cues)


def _transcribe_whisper(wav_path: Path, model_size: str, device: str, compute_type: str) -> Captions:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(
        str(wav_path),
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 150},
    )

    cues: list[WordCue] = []
    for seg in segments:
        if not seg.words:
            continue
        for w in seg.words:
            word = (w.word or "").strip()
            if not word:
                continue
            cues.append(WordCue(word=word, start=float(w.start), end=float(w.end)))

    return Captions(cues=cues)


def transcribe_to_json(wav_path: Path, json_out: Path, api_key: str | None = None,
                        model_size: str = "small") -> Captions:
    caps = transcribe(wav_path, api_key=api_key, model_size=model_size)
    json_out.write_text(caps.model_dump_json(indent=2), encoding="utf-8")
    return caps