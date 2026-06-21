"""Advanced video effects for viral short-form content.

Provides Ken Burns motion variations, xfade transition chain builder,
speed-ramp filters, and per-clip colour grading — all expressed as
ffmpeg filter strings so they plug directly into ``assembly.py``.
"""

from __future__ import annotations

import random

from .config import settings

_s = settings()
if _s.video_resolution == "8k":
    WIDTH, HEIGHT = 4320, 7680
elif _s.video_resolution == "4k":
    WIDTH, HEIGHT = 2160, 3840
else:
    WIDTH, HEIGHT = 1080, 1920
FPS = _s.video_fps

# ── transition pools keyed by energy ──────────────────────────────────────

TRANSITIONS: dict[str, list[str]] = {
    "high":   ["fadewhite", "pixelize", "radial", "zoomin", "circlecrop"],
    "medium": ["fade", "slideleft", "slideright", "smoothup", "circleopen"],
    "low":    ["fade", "dissolve", "fadeblack"],
}

TRANSITION_DURATIONS: dict[str, float] = {
    "high":   0.20,
    "medium": 0.30,
    "low":    0.45,
}

# ── Ken Burns motion catalogue ───────────────────────────────────────────

MOTION_TYPES = [
    "zoom_in", "zoom_out",
    "pan_left", "pan_right", "pan_up",
    "zoom_in_tl", "zoom_in_br",
]


# ── public helpers ───────────────────────────────────────────────────────

def pick_transition(energy: str = "medium",
                    hint: str = "auto") -> tuple[str, float]:
    """Choose a transition name + duration from *energy* and optional *hint*.

    *hint* values: ``auto``, ``flash``, ``slide``, ``fade``, ``zoom``, ``whip``.
    """
    dur = TRANSITION_DURATIONS.get(energy, 0.30)

    if hint not in ("auto", ""):
        mapping: dict[str, str | list[str]] = {
            "flash": "fadewhite",
            "slide": ["slideleft", "slideright", "slideup"],
            "fade":  "fade",
            "zoom":  "zoomin",
            "whip":  ["wipeleft", "wiperight"],
        }
        val = mapping.get(hint, "fade")
        name = random.choice(val) if isinstance(val, list) else val
        return name, dur

    pool = TRANSITIONS.get(energy, TRANSITIONS["medium"])
    return random.choice(pool), dur


def ken_burns_filter(target_dur: float,
                     motion: str | None = None) -> str:
    """Build a zoompan filter string with varied motion.

    The old pipeline always did centre-zoom-in.  This version randomly
    selects from seven distinct motions so consecutive clips feel alive.
    """
    if motion is None:
        motion = random.choice(MOTION_TYPES)

    frames = max(1, int(target_dur * FPS))
    z = 0.10  # total zoom travel (10 %)

    templates: dict[str, str] = {
        "zoom_in": (
            f"zoompan=z='1.0+{z}*on/{frames}':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS}"
        ),
        "zoom_out": (
            f"zoompan=z='{1.0 + z}-{z}*on/{frames}':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS}"
        ),
        "pan_left": (
            f"zoompan=z='1.05':d={frames}:"
            f"x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS}"
        ),
        "pan_right": (
            f"zoompan=z='1.05':d={frames}:"
            f"x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS}"
        ),
        "pan_up": (
            f"zoompan=z='1.05':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{frames})':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS}"
        ),
        "zoom_in_tl": (
            f"zoompan=z='1.0+{z}*on/{frames}':d={frames}:"
            f"x='0':y='0':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS}"
        ),
        "zoom_in_br": (
            f"zoompan=z='1.0+{z}*on/{frames}':d={frames}:"
            f"x='iw-(iw/zoom)':y='ih-(ih/zoom)':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS}"
        ),
    }
    return templates.get(motion, templates["zoom_in"])


def normalize_filter(target_dur: float,
                     motion: str | None = None,
                     speed: str = "normal") -> str:
    """Full per-clip normalization: scale → crop → Ken Burns [→ speed ramp]."""
    parts = [
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase",
        f"crop={WIDTH}:{HEIGHT}",
        ken_burns_filter(target_dur, motion),
    ]
    sp = speed_filter(speed)
    if sp:
        parts.append(sp)
    return ",".join(parts)


def speed_filter(speed: str) -> str | None:
    """Return a ``setpts`` expression for the requested tempo, or *None*."""
    if speed == "slow":
        return "setpts=1.4*PTS"    # slight slow-mo
    if speed == "fast":
        return "setpts=0.75*PTS"   # snappy
    return None


# ── xfade chain builder ──────────────────────────────────────────────────

def build_xfade_chain(
    clip_durations: list[float],
    energies: list[str] | None = None,
    transition_hints: list[str] | None = None,
) -> tuple[str, float]:
    """Return ``(filter_complex_body, total_output_duration)``.

    *clip_durations* are the actual durations of the pre-normalised clips
    (index 0 is the hook trim, indices 1..N are the body/cta b-roll clips).

    The generated filter expects each clip supplied as ``-i clip_i.mp4`` so
    stream labels are ``[0:v]``, ``[1:v]``, …  The final output label is
    always ``[vout]``.
    """
    n = len(clip_durations)
    _e = energies or ["medium"] * n
    _h = transition_hints or ["auto"] * n

    if n == 0:
        return "color=c=black:s=1080x1920:d=1[vout]", 1.0
    if n == 1:
        return "[0:v]null[vout]", clip_durations[0]

    parts: list[str] = []
    cumulative = clip_durations[0]

    for i in range(1, n):
        # Pick transition for the incoming clip's energy
        trans, dur = pick_transition(
            _e[i] if i < len(_e) else "medium",
            _h[i] if i < len(_h) else "auto",
        )
        # Clamp so we never exceed half the shorter neighbour
        dur = min(dur, cumulative * 0.4, clip_durations[i] * 0.4)
        dur = max(dur, 0.05)
        offset = max(0.05, cumulative - dur)

        src = "[0:v]" if i == 1 else f"[x{i - 1}]"
        dst = "[vout]" if i == n - 1 else f"[x{i}]"

        parts.append(
            f"{src}[{i}:v]xfade=transition={trans}"
            f":duration={dur:.3f}:offset={offset:.3f}{dst}"
        )
        cumulative = cumulative + clip_durations[i] - dur

    return ";\n".join(parts), cumulative
