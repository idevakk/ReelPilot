"""CLI entry point: `python -m shortmaker "topic"` or `shortmaker "topic"`."""

from __future__ import annotations

import concurrent.futures
import re
import shutil
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from . import assembly, broll, captions, hooks, matcher, music, script, stt, tts
from .config import OUTPUT_DIR, settings
from .models import Script

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _slug(text: str, max_len: int = 50) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "video"


def _elapsed(start: float) -> str:
    return f"{time.time() - start:.1f}s"


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg was not found on PATH. Install it with:\n"
            "  scoop install ffmpeg   (Windows)\n"
            "  choco install ffmpeg   (Windows)\n"
            "  brew install ffmpeg    (macOS)\n"
            "  apt install ffmpeg     (Linux)"
        )


def _pick_hook(topic: str, requested: str, s) -> hooks.Hook:
    if requested and requested.lower() != "auto":
        return hooks.by_name(requested)
    s_obj = s()
    candidates = [h for h, score in matcher.rank(topic)[:3]]
    candidates = matcher.rerank_with_llm(
        topic, candidates,
        api_key=s_obj.openai_api_key,
        base_url=s_obj.openai_base_url,
        model=s_obj.openai_model,
    )
    return candidates[0] if candidates else matcher.best(topic)


def _fetch_broll_parallel(beats, api_key: str | None,
                          max_workers: int = 4) -> list[Path | None]:
    """Download B-roll for all beats concurrently.

    Network-bound; no contention with faster-whisper or the LLM call which
    happen on different stages of the pipeline.
    """
    def _one(beat):
        kw = beat.broll_keywords[0] if beat.broll_keywords else beat.narration[:20]
        fb = beat.broll_keywords[1:] if len(beat.broll_keywords) > 1 else None
        return broll.download(
            query=kw, api_key=api_key,
            target_seconds=beat.target_seconds,
            fallback_keywords=fb,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_one, beats))


@app.command()
def main(
    topic: str = typer.Argument(..., help="Short video topic."),
    hook: str = typer.Option("auto", "--hook", "-k", help="Hook name or 'auto'."),
    voice: str = typer.Option(tts.DEFAULT_VOICE, "--voice", help="Deepgram Aura voice id."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output MP4 path."),
    force_redownload: bool = typer.Option(False, "--force", help="Re-download all assets."),
) -> None:
    """Generate a 9:16 short MP4 from a topic + Malloy hook."""
    _require_ffmpeg()
    s = settings()
    s.ensure_paths()
    t0 = time.time()

    console.rule("[bold]shortmaker[/bold]")

    with console.status("[bold green]Picking hook..."):
        chosen_hook = _pick_hook(topic, hook, settings)
    console.print(f"[cyan]Hook:[/cyan] {chosen_hook.name} ({chosen_hook.description})")

    with console.status("[bold green]Ensuring hook clip..."):
        hook_path = hooks.ensure(chosen_hook, force=force_redownload)
    console.print(f"[dim]Hook cached at {hook_path}[/dim] ({_elapsed(t0)})")

    with console.status("[bold green]Writing script..."):
        script_obj: Script = script.generate(
            topic=topic,
            hook_name=chosen_hook.name,
            hook_desc=chosen_hook.description,
            settings=s,
        )
    console.print(f"[cyan]Script:[/cyan] {len(script_obj.beats)} beats, "
                  f"~{script_obj.target_duration:.1f}s")

    work_dir = OUTPUT_DIR / "_work" / f"{_slug(topic)}_{int(time.time())}"
    work_dir.mkdir(parents=True, exist_ok=True)
    voice_wav = work_dir / "voice.wav"
    captions_json = work_dir / "captions.json"
    captions_ass = work_dir / "captions.ass"

    with console.status("[bold green]Synthesizing voiceover..."):
        voice_dur = tts.synthesize(
            script_obj.full_narration, voice_wav,
            api_key=s.deepgram_api_key, voice=voice, target_seconds=script_obj.target_duration,
        )
        cost = tts.estimate_cost_usd(script_obj.full_narration)
    console.print(f"[dim]Voiceover: {voice_dur:.1f}s (est. ${cost:.4f} Deepgram)")  # noqa: F541

    console.print("[yellow]Loading faster-whisper (first run downloads ~460 MB)…[/yellow]")
    with console.status("[bold green]Transcribing word timings..."):
        captions_obj = stt.transcribe_to_json(voice_wav, captions_json)
    console.print(f"[cyan]Captions:[/cyan] {len(captions_obj.cues)} words")

    with console.status("[bold green]Building ASS..."):
        captions.build(captions_obj, captions_ass)

    with console.status("[bold green]Fetching b-roll (parallel)..."):
        broll_results = _fetch_broll_parallel(script_obj.beats, s.pexels_api_key)
    broll_paths: list[Path] = []
    for beat, p in zip(script_obj.beats, broll_results):
        if p is None:
            console.print(f"[yellow]No b-roll for beat, using hook as fallback[/yellow]")
            p = hook_path
        broll_paths.append(p)
    console.print(f"[cyan]B-roll:[/cyan] {len(broll_paths)} clips")

    with console.status("[bold green]Fetching music..."):
        music_path = music.fetch(topic, s.pixabay_api_key, target_seconds=script_obj.target_duration)
    console.print(f"[cyan]Music:[/cyan] {music_path.name}")

    out_path = out or (OUTPUT_DIR / f"{_slug(topic)}_{int(time.time())}.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    beat_durations = [b.target_seconds for b in script_obj.beats]

    with console.status("[bold green]Assembling final MP4..."):
        assembly.assemble(
            hook_path=hook_path,
            broll_clips=broll_paths,
            voice=voice_wav,
            music=music_path,
            captions_ass=captions_ass,
            beat_durations=beat_durations,
            out_path=out_path,
        )

    attributions = {
        "B-roll": "Pexels" if s.pexels_api_key else "cached/fallback",
        "Music": "Pixabay" if s.pixabay_api_key else "fallback tone",
        "Voice": f"Deepgram Aura ({voice})" if s.deepgram_api_key else "silent placeholder",
        "Script": f"{s.openai_model} via OpenAI-compatible API" if s.openai_api_key else "template fallback",
    }
    sidecar = assembly.write_sidecar(out_path, script_obj, captions_obj, attributions)

    console.print(Panel.fit(
        f"[bold green]Done[/bold green]\n"
        f"Video: {out_path}\n"
        f"Sidecar: {sidecar}\n"
        f"Total: {_elapsed(t0)}",
        border_style="green",
    ))


if __name__ == "__main__":
    app()