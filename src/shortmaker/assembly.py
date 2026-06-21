"""Final assembly: hook + B-roll + voiceover + music + burned captions -> MP4.

Pipeline is implemented as a series of FFmpeg invocations. The intermediate
work directory is created per-run via tempfile.mkdtemp and cleaned up
automatically, so back-to-back runs cannot collide.

Output: 1080x1920, 30fps, h264 + AAC, faststart-enabled for direct upload.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import Captions, Script

WIDTH, HEIGHT = 1080, 1920
FPS = 30
HOOK_TAIL_S = 2.5

# Shared between normalize_clip and burn_captions so a single quality tweak
# applies to both encode passes.
ENCODE_ARGS: list[str] = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
]


def _run(cmd: list[str]) -> None:
    """Run an ffmpeg/ffprobe command; raise on failure."""
    print("  ffmpeg:", " ".join(cmd))
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


def trim_hook(hook_path: Path, dest: Path, duration: float = HOOK_TAIL_S) -> Path:
    """Re-encode the last `duration` seconds of the hook to the assembly
    pipeline's shared codec/format so it can be `-c copy` concat'd with the
    normalized B-roll. Clamped to the source duration if the clip is shorter.
    """
    src_dur = _ffprobe_duration(hook_path)
    eff = max(0.5, min(duration, max(0.0, src_dur - 0.1)))
    _run([
        "ffmpeg", "-y", "-sseof", f"-{eff}",
        "-i", str(hook_path),
        "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
               f"crop={WIDTH}:{HEIGHT}",
        "-t", str(eff),
        "-an",
        *ENCODE_ARGS,
        str(dest),
    ])
    return dest


def _zoompan_filter(target_dur: float) -> str:
    """Slow zoom-in Ken Burns: 1.0 -> 1.08 over target_dur seconds.

    Operates at native 1080x1920 resolution; no up-scale before zoom.
    """
    frames = max(1, int(target_dur * FPS))
    return (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"zoompan=z='1.0+0.08*on/{frames}':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={WIDTH}x{HEIGHT}:fps={FPS}"
    )


def normalize_clip(src: Path, dest: Path, target_dur: float) -> Path:
    """Scale+crop+zoompan to 1080x1920 @ 30fps, trim to target_dur."""
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", _zoompan_filter(target_dur),
        "-t", str(target_dur),
        "-an",
        *ENCODE_ARGS,
        str(dest),
    ])
    return dest


def concat_clips(clips: list[Path], dest: Path) -> Path:
    """Concat already-matching-format video clips with the concat demuxer."""
    list_file = dest.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in clips),
        encoding="utf-8",
    )
    try:
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
              "-i", str(list_file), "-c", "copy", str(dest)])
    finally:
        list_file.unlink(missing_ok=True)
    return dest


def mix_audio(voice: Path, music: Path, total_dur: float, dest: Path) -> Path:
    """Mix voice at 0dB; duck music under voice via sidechaincompress.

    `sidechaincompress` is AA->A — it needs two audio inputs (signal,
    sidechain). The graph below feeds the voice as the sidechain so music
    is attenuated whenever voice is present.
    """
    filter_complex = (
        f"[0:a]volume=1.0[voice];"
        f"[1:a]atrim=0:{total_dur},"
        f"volume=0.35[mus];"
        f"[mus][voice]sidechaincompress=threshold=0.05:ratio=8:"
        f"attack=5:release=400:makeup=1[duck];"
        f"[voice][duck]amix=inputs=2:duration=first:dropout_transition=0[mix]"
    )
    _run([
        "ffmpeg", "-y",
        "-i", str(voice),
        "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", filter_complex,
        "-map", "[mix]",
        "-t", str(total_dur),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-ac", "2",
        str(dest),
    ])
    return dest


def _escape_ass_path(path: Path) -> str:
    """Escape a filesystem path for use as the `ass=` filter argument.

    ffmpeg's filter-graph parser splits on spaces, so any path with a
    space (e.g. `D:\\A1 Projects\\short-maker\\...`) must escape the
    space with a backslash. Drive colons and other special chars also
    need escaping. See ffmpeg docs: "Filtergraph syntax" -> "Escape
    special characters".
    """
    text = str(path).replace("\\", "/")
    # Order matters: backslash already normalized to `/`, then escape
    # every filter-graph special char individually.
    return (
        text
        .replace("\\", "\\\\")  # no-op after the normalize above
        .replace(":", "\\:")
        .replace(" ", "\\ ")
        .replace(",", "\\,")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


def burn_captions(video: Path, audio: Path, ass: Path, dest: Path) -> Path:
    """Combine final video + audio + burned ASS subtitles.

    The ASS file is copied to a colon-free Windows temp path before being
    passed to ffmpeg's `ass=` filter. This works around a ffmpeg 8.x
    filter-graph parsing issue where a Windows drive-letter colon
    (e.g. `D\:`) is not properly escaped and gets re-interpreted as an
    option separator, even though the backslash-colon escape is
    documented. A colon-free path sidesteps the issue entirely.
    """
    fd, tmp_str = tempfile.mkstemp(suffix=".ass", prefix="shortmaker_")
    os.close(fd)
    tmp_ass = Path(tmp_str)
    try:
        tmp_ass.write_bytes(ass.read_bytes())
        ass_arg = _escape_ass_path(tmp_ass)
        # Wrap the filename in escaped single quotes. ffmpeg 8.x's filter-graph
        # parser does NOT honor the `\:` escape for a Windows drive letter — it
        # treats `\:` as a separator and splits the filename at the first colon.
        # Quoting the whole argument with `\'...\''` tells the parser to treat
        # the content as a single value, so the `C:` in the temp path survives.
        ass_arg = f"\\'{ass_arg}\\'"
        vf = f"scale={WIDTH}:{HEIGHT},ass={ass_arg}"
        _run([
            "ffmpeg", "-y",
            "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", vf,
            *ENCODE_ARGS,
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-shortest",
            str(dest),
        ])
    finally:
        tmp_ass.unlink(missing_ok=True)
    return dest


def assemble(hook_path: Path, broll_clips: list[Path], voice: Path,
             music: Path, captions_ass: Path, beat_durations: list[float],
             out_path: Path) -> Path:
    """Full pipeline: normalize -> concat -> mix -> burn captions.

    The intermediate work directory is unique per invocation and cleaned up
    on success/failure to avoid cross-run collisions.
    """
    work = Path(tempfile.mkdtemp(prefix="shortmaker_", dir=out_path.parent))
    try:
        hook_trim = work / "hook_trim.mp4"
        trim_hook(hook_path, hook_trim, duration=HOOK_TAIL_S)

        normed: list[Path] = [hook_trim]
        for clip, dur in zip(broll_clips, beat_durations):
            out = work / f"norm_{clip.stem}.mp4"
            normalize_clip(clip, out, target_dur=dur)
            normed.append(out)

        concat = work / "concat.mp4"
        concat_clips(normed, concat)

        total_dur = sum(beat_durations) + HOOK_TAIL_S
        audio = work / "mixed.m4a"
        mix_audio(voice, music, total_dur=total_dur, dest=audio)

        burn_captions(concat, audio, captions_ass, out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out_path


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