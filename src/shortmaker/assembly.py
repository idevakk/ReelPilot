"""Final assembly: hook + B-roll + voiceover + music + burned captions → MP4.

v2 — Advanced pipeline:

1. **Normalize** each clip with varied Ken Burns motion (zoom in/out, pan L/R).
2. **xfade transitions** between clips (fade, slide, flash, zoom, dissolve)
   chosen by beat energy — replaces the old hard-cut concat.
3. **Audio mix** with sidechain compression (voice ducks music).
4. **Burn enhanced captions** with vignette overlay for cinematic feel.

Output: 1080×1920, 30 fps, H.264 + AAC, faststart for direct upload.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import re
from rich.progress import Progress, TextColumn, BarColumn, TimeRemainingColumn

from . import effects
from .models import Beat, Captions, Script

from .config import settings

_s = settings()
if _s.video_resolution == "8k":
    WIDTH, HEIGHT = 4320, 7680
elif _s.video_resolution == "4k":
    WIDTH, HEIGHT = 2160, 3840
else:
    WIDTH, HEIGHT = 1080, 1920
FPS = _s.video_fps
HOOK_TAIL_S = 2.5

ENCODE_ARGS: list[str] = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
]

ENCODE_ARGS_FINAL: list[str] = [
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
]


def _run(cmd: list[str], desc: str | None = None, total_duration: float = 0.0) -> None:
    """Run an ffmpeg/ffprobe command. If desc is provided, show a progress bar."""
    if desc and total_duration > 0 and cmd[0] == "ffmpeg":
        cmd = [cmd[0], "-hide_banner", "-loglevel", "info", "-nostats"] + cmd[1:]
        process = subprocess.Popen(
            cmd, 
            stderr=subprocess.PIPE, 
            stdout=subprocess.DEVNULL, 
            universal_newlines=True, 
            encoding='utf-8', 
            errors='replace'
        )
        time_regex = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            transient=True
        ) as progress:
            task_id = progress.add_task(f"[cyan]{desc}...", total=total_duration)
            if process.stderr:
                for line in process.stderr:
                    match = time_regex.search(line)
                    if match:
                        h, m, s = match.groups()
                        current_time = int(h) * 3600 + int(m) * 60 + float(s)
                        progress.update(task_id, completed=min(current_time, total_duration))
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)
    else:
        if cmd[0] == "ffmpeg":
            cmd = [cmd[0], "-hide_banner", "-loglevel", "error"] + cmd[1:]
        subprocess.run(cmd, check=True)


def _ffprobe_duration(path: Path) -> float:
    """Probe a media file's duration in seconds via ffprobe."""
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], stderr=subprocess.STDOUT)
    return float(out.decode().strip() or "0")


# ─── step 1: normalise individual clips ──────────────────────────────────

def trim_hook(hook_path: Path, dest: Path,
              duration: float = HOOK_TAIL_S) -> Path:
    """Re-encode the last *duration* seconds of the hook clip."""
    src_dur = _ffprobe_duration(hook_path)
    eff = max(0.5, min(duration, max(0.0, src_dur - 0.1)))
    _run([
        "ffmpeg", "-y", "-sseof", f"-{eff}",
        "-i", str(hook_path),
        "-vf", (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"fps={FPS}"
        ),
        "-t", str(eff),
        "-an",
        *ENCODE_ARGS,
        str(dest),
    ], desc="Trimming Hook", total_duration=eff)
    return dest


def normalize_clip(src: Path, dest: Path, target_dur: float,
                   motion: str | None = None,
                   speed: str = "normal") -> Path:
    """Scale + crop + Ken Burns (varied motion) + optional speed ramp."""
    vf = effects.normalize_filter(target_dur, motion=motion, speed=speed)
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", vf,
        "-t", str(target_dur),
        "-an",
        *ENCODE_ARGS,
        str(dest),
    ], desc=f"Normalising b-roll", total_duration=target_dur)
    return dest


# ─── step 2: xfade transition chain ──────────────────────────────────────

def xfade_clips(clips: list[Path],
                clip_durations: list[float],
                energies: list[str],
                transition_hints: list[str],
                dest: Path) -> tuple[Path, float]:
    """Chain-xfade all clips with energy-aware transitions.

    Replaces the old ``concat_clips`` hard-cut demuxer with smooth
    inter-clip transitions.
    """
    if len(clips) < 2:
        # Single clip — just copy
        shutil.copy2(clips[0], dest)
        return dest, clip_durations[0]

    filter_body, _total_dur = effects.build_xfade_chain(
        clip_durations, energies, transition_hints,
    )

    cmd: list[str] = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    cmd += [
        "-filter_complex", filter_body,
        "-map", "[vout]",
        *ENCODE_ARGS,
        str(dest),
    ]
    _run(cmd, desc="Crossfading Clips", total_duration=_total_dur)
    return dest, _total_dur


# ─── step 3: audio mix ───────────────────────────────────────────────────

def mix_audio(voice: Path, music: Path, total_dur: float,
              dest: Path) -> Path:
    """Mix voice at 0 dB; duck music under voice via sidechaincompress.

    v2: slightly louder music (0.40 vs 0.35) for energy, with tighter
    sidechain for cleaner ducking.
    """
    filter_complex = (
        f"[0:a]volume=1.0[voice];"
        f"[1:a]atrim=0:{total_dur},"
        f"volume=0.40[mus];"
        f"[mus][voice]sidechaincompress=threshold=0.04:ratio=10:"
        f"attack=3:release=300:makeup=1[duck];"
        f"[voice][duck]amix=inputs=2:duration=first:dropout_transition=0[mix]"
    )
    _run([
        "ffmpeg", "-y",
        "-i", str(voice),
        "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", filter_complex,
        "-map", "[mix]",
        "-t", str(total_dur),
        "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
        "-ac", "2",
        str(dest),
    ], desc="Mixing Audio", total_duration=total_dur)
    return dest


# ─── step 4: burn captions + vignette ────────────────────────────────────

def _escape_ass_path(path: Path) -> str:
    """Escape a filesystem path for ffmpeg's ``ass=`` filter argument."""
    text = str(path).replace("\\", "/")
    return (
        text
        .replace(":", "\\:")
        .replace(" ", "\\ ")
        .replace(",", "\\,")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


def burn_captions(video: Path, audio: Path, ass: Path, dest: Path,
                  total_dur: float, quality: str = "final") -> Path:
    """Combine video + audio + burned ASS subtitles + subtle vignette.

    v2: adds a soft vignette overlay for a cinematic feel.
    """
    fd, tmp_str = tempfile.mkstemp(suffix=".ass", prefix="shortmaker_")
    os.close(fd)
    tmp_ass = Path(tmp_str)

    encode = ENCODE_ARGS_FINAL if quality == "final" else ENCODE_ARGS

    try:
        tmp_ass.write_bytes(ass.read_bytes())
        ass_arg = _escape_ass_path(tmp_ass)
        ass_arg = f"\\'{ass_arg}\\'"
        # Scale → burn subs → subtle vignette for cinema feel
        vf = (
            f"scale={WIDTH}:{HEIGHT},"
            f"ass={ass_arg},"
            f"vignette=PI/5:eval=init"
        )
        _run([
            "ffmpeg", "-y",
            "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", vf,
            *encode,
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-shortest",
            str(dest),
        ], desc="Burning Captions", total_duration=total_dur)
    finally:
        tmp_ass.unlink(missing_ok=True)
    return dest


# ─── full pipeline ────────────────────────────────────────────────────────

def assemble(
    hook_path: Path,
    broll_clips: list[Path],
    voice: Path,
    music: Path,
    captions_ass: Path,
    beats: list[Beat],
    out_path: Path,
    quality: str = "final",
) -> Path:
    """Full pipeline: normalize → xfade → mix → burn captions.

    v2: accepts ``beats`` (with energy/transition_hint) instead of bare
    durations, enabling energy-aware transitions and varied Ken Burns.
    """
    work = Path(tempfile.mkdtemp(prefix="shortmaker_", dir=out_path.parent))
    try:
        # ── 1. Normalize hook ──
        hook_trim = work / "hook_trim.mp4"
        trim_hook(hook_path, hook_trim, duration=HOOK_TAIL_S)

        # ── 2. Normalize each b-roll clip with varied motion ──
        normed: list[Path] = [hook_trim]
        durations: list[float] = [HOOK_TAIL_S]
        energies: list[str] = ["high"]          # hook is always high energy
        hints: list[str] = ["flash"]            # hook → first body is a flash cut

        for clip, beat in zip(broll_clips, beats):
            out = work / f"norm_{clip.stem}.mp4"
            normalize_clip(
                clip, out,
                target_dur=beat.target_seconds,
                motion=None,   # random selection per clip
                speed=beat.speed,
            )
            normed.append(out)
            durations.append(beat.target_seconds)
            energies.append(beat.energy)
            hints.append(beat.transition_hint)

        # ── 3. xfade transition chain ──
        xfaded = work / "xfaded.mp4"
        xfaded, actual_dur = xfade_clips(normed, durations, energies, hints, xfaded)

        # ── 4. Audio mix ──
        audio = work / "mixed.m4a"
        mix_audio(voice, music, total_dur=actual_dur, dest=audio)

        # ── 5. Burn captions + vignette → final output ──
        burn_captions(xfaded, audio, captions_ass, out_path, actual_dur, quality=quality)

    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out_path


# ─── sidecar ──────────────────────────────────────────────────────────────

def write_sidecar(out_path: Path, script: Script, captions: Captions,
                  attributions: dict[str, str]) -> Path:
    sidecar = out_path.with_suffix(".txt")
    lines = [
        f"Topic: {script.topic}",
        f"Hook: {script.hook_name}",
        f"Duration (target): {script.target_duration:.1f}s",
        f"Beats: {len(script.beats)}",
        "",
        "=== Script ===",
        script.full_narration,
        "",
        "=== Captions (word timings) ===",
        json.dumps([c.model_dump() for c in captions.cues], indent=2),
        "",
        "=== Attributions ===",
    ]
    for k, v in attributions.items():
        lines.append(f"- {k}: {v}")
    sidecar.write_text("\n".join(lines), encoding="utf-8")
    return sidecar