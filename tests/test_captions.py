"""ASS caption builder tests."""

from pathlib import Path

from reelpilot.captions import build
from reelpilot.models import Captions, WordCue


def test_build_writes_valid_ass_header(tmp_path: Path):
    caps = Captions(cues=[
        WordCue(word="Hello", start=0.0, end=0.4),
        WordCue(word="world", start=0.5, end=1.0),
    ])
    out = build(caps, tmp_path / "captions.ass")
    text = out.read_text(encoding="utf-8")
    assert "[Script Info]" in text
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    assert "Dialogue:" in text
    # Two pop cues + one phrase-level cue
    assert text.count(",Pop,,0,0,0,") == 2
    assert text.count(",Line,,0,0,0,") == 1
    # Style names defined in header
    assert "Style: Pop," in text
    assert "Style: Line," in text


def test_build_empty_cues(tmp_path: Path):
    out = build(Captions(cues=[]), tmp_path / "empty.ass")
    assert out.exists()
    assert "[Script Info]" in out.read_text(encoding="utf-8")


def test_build_handles_special_chars(tmp_path: Path):
    caps = Captions(cues=[WordCue(word='back\\slash "quote"', start=0, end=0.5)])
    text = build(caps, tmp_path / "x.ass").read_text(encoding="utf-8")
    assert "back" in text
    assert "slash" in text