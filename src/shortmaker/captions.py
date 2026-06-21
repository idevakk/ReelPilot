"""ASS subtitle builder for TikTok-style pop-on word captions.

Each word is rendered as its own line (Dialogue) with a quick scale tween.
We add a small pre-roll (~30ms) so captions appear *just before* the word
is spoken, which matches TikTok viewer expectation.
"""

from __future__ import annotations

from pathlib import Path

from .models import Captions, WordCue

ASS_HEADER = """[Script Info]
Title: shortmaker
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,Montserrat Black,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,260,1
Style: Line,Montserrat Black,62,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,340,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

PREROLL_S = 0.03


def _fmt_time(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _pop_tag(start: float) -> str:
    """{\\an2\\t(start,start+80,start+160)} style pop animation."""
    s_ms = int(start * 1000)
    rise_end = s_ms + 80
    fall_end = s_ms + 160
    # Pop scale 100 -> 120 -> 100 across 160ms at the word start.
    return (
        f"{{\\an2"
        f"\\t({s_ms},{rise_end},\\fscx120\\fscy120)"
        f"\\t({rise_end},{fall_end},\\fscx100\\fscy100)}}"
    )


def build(captions: Captions, out_path: Path, line_break_every: int = 4) -> Path:
    """Render captions.ass with one Dialogue per word plus grouped line cues."""
    lines: list[str] = [ASS_HEADER]

    cues = captions.cues
    if not cues:
        out_path.write_text("".join(lines), encoding="utf-8")
        return out_path

    # Per-word pop cues
    for cue in cues:
        start = max(0.0, cue.start - PREROLL_S)
        text = _pop_tag(0.0) + cue.word.replace("\\", " ").replace("\n", " ")
        lines.append(
            f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(cue.end)},Pop,,0,0,0,,{text}\n"
        )

    # Phrase-level line cues for readers who prefer sentence chunks.
    for i in range(0, len(cues), line_break_every):
        chunk = cues[i: i + line_break_every]
        text = " ".join(c.word for c in chunk).replace("\\", " ").replace("\n", " ")
        lines.append(
            f"Dialogue: 1,{_fmt_time(chunk[0].start)},{_fmt_time(chunk[-1].end)},Line,,0,0,0,,{text}\n"
        )

    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path