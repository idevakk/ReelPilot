"""CLI entry point: ``python -m reelpilot "topic"`` or ``reelpilot "topic"``.

v2 — Full auto-pilot:

    reelpilot                     # auto mode: random hook → generated topic
    reelpilot "topic"             # manual topic, auto hook
    reelpilot "topic" --hook X    # manual everything
    reelpilot --count 5           # batch auto: 5 videos
    reelpilot --list-hooks        # show available hooks
    reelpilot --cache-stats       # show cache statistics
"""

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
from rich.table import Table

from . import assembly, broll, cache, captions, hooks, matcher, music, script, stt, tts
from .config import OUTPUT_DIR, settings
from .models import Script as ScriptModel

app = typer.Typer(add_completion=False)
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
    if requested.lower() == "random":
        return hooks.random_hook()
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
    """Download B-roll for all beats concurrently."""
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


def _make_one_video(
    topic: str | None,
    hook_name: str,
    voice: str,
    out: Path | None,
    force_redownload: bool,
    duration: int = 30,
    bgm: str | None = None,
    video_num: int = 1,
) -> Path:
    """Core pipeline: generate one video and return the output path."""
    _require_ffmpeg()
    s = settings()
    s.ensure_paths()
    t0 = time.time()

    console.rule(f"[bold]reelpilot[/bold] — video #{video_num}")

    # ── Hook selection ──
    if topic is None:
        # AUTO MODE: random hook → generate topic
        if hook_name and hook_name.lower() not in ("auto", "random"):
            with console.status(f"[bold green]Using selected hook {hook_name}..."):
                from .hooks import by_name
                chosen_hook = by_name(hook_name)
        else:
            with console.status("[bold green]Picking random hook..."):
                chosen_hook = hooks.random_hook()
        console.print(f"[cyan]Hook:[/cyan] {chosen_hook.name} ({chosen_hook.description})")
    else:
        # MANUAL MODE: user-provided topic
        with console.status("[bold green]Picking hook..."):
            chosen_hook = _pick_hook(topic, hook_name, settings)
        console.print(f"[cyan]Hook:[/cyan] {chosen_hook.name} ({chosen_hook.description})")

    with console.status("[bold green]Ensuring hook clip..."):
        hook_path = hooks.ensure(chosen_hook, force=force_redownload)
    console.print(f"[dim]Hook cached at {hook_path}[/dim] ({_elapsed(t0)})")

    # ── AI Vision Context ──
    from . import cache, vision
    hook_desc = chosen_hook.description
    if s.gemini_api_key:
        ai_desc = cache.get_hook_description(chosen_hook.url)
        if not ai_desc:
            with console.status("[bold green]Analyzing hook video with Gemini Vision..."):
                ai_desc = vision.analyze_hook(hook_path, s.gemini_api_key, s.gemini_vision_model, s.gemini_base_url)
                if ai_desc:
                    cache.update_hook_description(chosen_hook.url, ai_desc)
        
        if ai_desc:
            console.print(f"[dim]AI Context: {ai_desc}[/dim]")
            hook_desc = ai_desc
            # Update the hook object so generate_topic can use it
            chosen_hook.description = ai_desc

    if topic is None:
        with console.status("[bold green]Generating viral topic..."):
            topic = script.generate_topic(chosen_hook, s)
        console.print(f"[cyan]Topic:[/cyan] {topic}")

    # ── Script ──
    with console.status("[bold green]Writing viral script..."):
        script_obj: ScriptModel = script.generate(
            topic=topic,
            hook_name=chosen_hook.name,
            hook_desc=hook_desc,
            settings=s,
            duration=duration,
        )
    console.print(
        f"[cyan]Script:[/cyan] {len(script_obj.beats)} beats, "
        f"~{script_obj.target_duration:.1f}s"
    )
    # Show beats with energy indicators
    for i, beat in enumerate(script_obj.beats):
        energy_icon = {"high": "*", "medium": "-", "low": "."}.get(beat.energy, " ")
        console.print(
            f"  {energy_icon} [{beat.role}] {beat.narration[:60]}{'...' if len(beat.narration) > 60 else ''}"
        )

    # -- Work directory --
    slug_name = f"{_slug(topic)}_{int(time.time())}"
    work_dir = OUTPUT_DIR / "_work" / slug_name
    work_dir.mkdir(parents=True, exist_ok=True)
    voice_wav = work_dir / "voice.wav"
    captions_json = work_dir / "captions.json"
    captions_ass = work_dir / "captions.ass"

    # ── TTS ──
    with console.status("[bold green]Synthesizing voiceover..."):
        voice_dur = tts.synthesize(
            script_obj.full_narration, voice_wav,
            api_key=s.deepgram_api_key, voice=voice,
            target_seconds=script_obj.target_duration,
        )
        cost = tts.estimate_cost_usd(script_obj.full_narration)
    console.print(f"[dim]Voiceover: {voice_dur:.1f}ms (est. ${cost:.4f} Deepgram)")

    # ── STT for word timings ──
    if s.deepgram_api_key:
        console.print("[yellow]Using Deepgram STT for ultra-fast word timings...[/yellow]")
    else:
        console.print("[yellow]Loading faster-whisper (first run downloads ~460 MB)…[/yellow]")
        
    with console.status("[bold green]Transcribing word timings..."):
        captions_obj = stt.transcribe_to_json(voice_wav, captions_json, api_key=s.deepgram_api_key)
    console.print(f"[cyan]Captions:[/cyan] {len(captions_obj.cues)} words")

    # ── Build ASS with emphasis ──
    with console.status("[bold green]Building enhanced captions..."):
        captions.build(captions_obj, captions_ass, beats=script_obj.beats)

    # ── B-roll (parallel) ──
    with console.status("[bold green]Fetching b-roll (parallel)..."):
        broll_results = _fetch_broll_parallel(script_obj.beats, s.pexels_api_key)
    broll_paths: list[Path] = []
    for beat, p in zip(script_obj.beats, broll_results):
        if p is None:
            console.print("[yellow]No b-roll for beat, using hook as fallback[/yellow]")
            p = hook_path
        broll_paths.append(p)
    console.print(f"[cyan]B-roll:[/cyan] {len(broll_paths)} clips")

    # ── Music ──
    with console.status("[bold green]Fetching music..."):
        music_path = music.fetch(
            topic, s.pixabay_api_key,
            target_seconds=script_obj.target_duration,
            bgm_file=bgm,
        )
    console.print(f"[cyan]Music:[/cyan] {music_path.name}")

    # ── Assembly (xfade + effects + vignette) ──
    if out:
        out_path = out
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = OUTPUT_DIR / slug_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slug_name}.mp4"

    console.print("[bold yellow]Stitching and rendering final video (this might take a few minutes)...[/bold yellow]")
    with console.status("[bold green]Assembling final MP4 (xfade + effects)..."):
        assembly.assemble(
            hook_path=hook_path,
            broll_clips=broll_paths,
            voice=voice_wav,
            music=music_path,
            captions_ass=captions_ass,
            beats=script_obj.beats,
            out_path=out_path,
            quality=s.video_quality,
        )

    # ── Sidecar + summary ──
    total_cost = script_obj.estimated_cost_usd + cost
    attributions = {
        "B-roll": "Pexels" if s.pexels_api_key else "cached/fallback",
        "Music": "Pixabay" if s.pixabay_api_key else ("local library" if music_path.parent.name == "library" else "fallback tone"),
        "Voice": f"Deepgram Aura ({voice})" if s.deepgram_api_key else "silent placeholder",
        "Script": f"{s.openai_model} via OpenAI-compatible API" if s.openai_api_key else "template fallback",
        "Transitions": "xfade (energy-aware)",
        "Effects": "Ken Burns varied + vignette",
        "--- Metrics ---": "-------------------------",
        "Total Time Taken": _elapsed(t0),
        "LLM Prompt Tokens": str(script_obj.prompt_tokens),
        "LLM Completion Tokens": str(script_obj.completion_tokens),
        "LLM Estimated Cost": f"${script_obj.estimated_cost_usd:.4f}",
        "Deepgram Voice Cost": f"${cost:.4f}",
        "Total Pipeline Cost": f"${total_cost:.4f}",
    }
    sidecar = assembly.write_sidecar(out_path, script_obj, captions_obj, attributions)

    console.print(Panel.fit(
        f"[bold green]Done[/bold green]\n"
        f"Video: {out_path}\n"
        f"Sidecar: {sidecar}\n"
        f"Total: {_elapsed(t0)}",
        border_style="green",
    ))

    return out_path


# ─── CLI command ──────────────────────────────────────────────────────────

@app.command()
def main(
    topic: Optional[str] = typer.Argument(
        None, help="Short video topic. Leave empty for full auto mode.",
    ),
    hook: str = typer.Option(
        "auto", "--hook", "-k",
        help="Hook name, 'auto', or 'random'.",
    ),
    count: int = typer.Option(
        1, "--count", "-n",
        help="Number of videos to generate (auto mode).",
    ),
    voice: str = typer.Option(
        tts.DEFAULT_VOICE, "--voice",
        help="Deepgram Aura voice id.",
    ),
    duration: int = typer.Option(
        30, "--duration", "-d",
        help="Target minimum duration in seconds (30 to 60).",
    ),
    bgm: str = typer.Option(
        "auto", "--bgm", "-m",
        help="Background music: 'auto' (random/download) or specific filename.",
    ),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o",
        help="Output MP4 path (only for single video).",
    ),
    force_redownload: bool = typer.Option(
        False, "--force",
        help="Re-download all assets.",
    ),
    list_hooks: bool = typer.Option(
        False, "--list-hooks",
        help="List available hooks and exit.",
    ),
    cache_stats: bool = typer.Option(
        False, "--cache-stats",
        help="Show cache statistics and exit.",
    ),
    cache_clear: bool = typer.Option(
        False, "--cache-clear",
        help="Clear the asset cache and exit.",
    ),
    web_ui: bool = typer.Option(
        False, "--web", "-w",
        help="Start the interactive web dashboard.",
    ),
) -> None:
    """Generate viral 9:16 short MP4s.

    \b
    Auto mode (no topic):
        reelpilot                     -> random hook + generated topic
        reelpilot --count 5           -> batch: 5 auto videos
    \b
    Manual mode:
        reelpilot "crazy dog dance"   -> your topic, best-fit hook
        reelpilot "topic" --hook X    -> your topic + specific hook
    """

    # ── Utility commands ──
    if web_ui:
        from .web import start
        console.print("[bold green]Starting Web UI on http://localhost:8000[/bold green]")
        start()
        return

    if list_hooks:
        table = Table(title="Available Hooks")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Tags", style="dim")
        for h in hooks.CATALOG:
            table.add_row(h.name, h.description, ", ".join(h.tags))
        console.print(table)
        return

    if cache_stats:
        stats = cache.get_stats()
        table = Table(title="Asset Cache")
        table.add_column("Type", style="cyan")
        table.add_column("Count", justify="right")
        for k, v in stats.items():
            table.add_row(k, str(v))
        console.print(table)
        return

    if cache_clear:
        cache.clear_all()
        console.print("[green]Cache cleared.[/green]")
        return

    # ── Video generation ──
    if topic is None:
        console.print(f"[bold magenta]*** Auto-pilot mode - generating {count} video(s)[/bold magenta]")

    outputs: list[Path] = []
    for i in range(count):
        out_i = out if count == 1 else None  # only use --out for single video
        result = _make_one_video(
            topic=topic,
            hook_name=hook,
            voice=voice,
            out=out_i,
            force_redownload=force_redownload,
            duration=duration,
            bgm=bgm,
            video_num=i + 1,
        )
        outputs.append(result)

    if count > 1:
        console.print(Panel.fit(
            f"[bold green]Batch complete: {count} videos[/bold green]\n"
            + "\n".join(str(p) for p in outputs),
            border_style="green",
        ))


if __name__ == "__main__":
    app()