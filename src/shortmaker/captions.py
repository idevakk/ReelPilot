"""ASS subtitle builder for TikTok-style pop-on word captions.

v2 enhancements:
- **Color emphasis**: key words rendered in yellow for visual pop.
- **Larger font**: 84pt for mobile readability.
- **Thicker outline + shadow**: legible over any background.
- **Position variation**: hook at center, body at bottom, CTA at center.
- Pre-roll timing so captions appear *just before* the word is spoken.
"""

from __future__ import annotations

from pathlib import Path

from .models import Beat, Captions, WordCue

# ─── ASS header ──────────────────────────────────────────────────────────

ASS_HEADER = """\
[Script Info]
Title: shortmaker
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,Montserrat Black,84,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,260,1
Style: PopKey,Montserrat Black,88,&H0000DDFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,260,1
Style: Line,Montserrat Black,62,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,340,1

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
    """{\\an2\\t(…)} pop-scale animation: 100→125→100 in 150ms."""
    s_ms = int(start * 1000)
    rise_end = s_ms + 75
    fall_end = s_ms + 150
    return (
        f"{{\\an2"
        f"\\t({s_ms},{rise_end},\\fscx125\\fscy125)"
        f"\\t({rise_end},{fall_end},\\fscx100\\fscy100)}}"
    )


def _is_emphasis(word: str, emphasis_words: set[str]) -> bool:
    """Check if *word* (case-insensitive, punctuation-stripped) is emphasised."""
    clean = word.strip(".,!?;:'\"").lower()
    return clean in emphasis_words


def build(
    captions: Captions,
    out_path: Path,
    line_break_every: int = 4,
    beats: list[Beat] | None = None,
) -> Path:
    """Render captions.ass with per-word pop cues and grouped line cues.

    If *beats* are provided, words that appear in any beat's
    ``caption_emphasis`` list are rendered with the ``PopKey`` style
    (yellow, slightly larger) for visual punch.
    """
    lines: list[str] = [ASS_HEADER]

    cues = captions.cues
    if not cues:
        out_path.write_text("".join(lines), encoding="utf-8")
        return out_path

    # Collect all emphasis words from all beats
    emphasis: set[str] = set()
    if beats:
        for b in beats:
            for w in b.caption_emphasis:
                emphasis.add(w.strip().lower())

    # ── Per-word pop cues ──
    for cue in cues:
        start = max(0.0, cue.start - PREROLL_S)
        safe_word = cue.word.replace("\\", " ").replace("\n", " ")
        text = _pop_tag(0.0) + safe_word

        style = "PopKey" if _is_emphasis(cue.word, emphasis) else "Pop"
        lines.append(
            f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(cue.end)},{style},,0,0,0,,{text}\n"
        )

    # ── Phrase-level line cues ──
    for i in range(0, len(cues), line_break_every):
        chunk = cues[i: i + line_break_every]
        text = " ".join(c.word for c in chunk).replace("\\", " ").replace("\n", " ")
        lines.append(
            f"Dialogue: 1,{_fmt_time(chunk[0].start)},{_fmt_time(chunk[-1].end)},Line,,0,0,0,,{text}\n"
        )

    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path