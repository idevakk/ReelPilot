"""Word-level timing via faster-whisper.

Loads the `small` int8 model on CPU by default to leave VRAM free for
other GPU work. Returns a list of WordCue objects with millisecond precision.
"""

from __future__ import annotations

from pathlib import Path

from .models import Captions, WordCue


def transcribe(wav_path: Path, model_size: str = "small",
               device: str = "cpu", compute_type: str = "int8") -> Captions:
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


def transcribe_to_json(wav_path: Path, json_out: Path,
                        model_size: str = "small") -> Captions:
    caps = transcribe(wav_path, model_size=model_size)
    json_out.write_text(caps.model_dump_json(indent=2), encoding="utf-8")
    return caps