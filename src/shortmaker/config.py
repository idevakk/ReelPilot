"""Configuration: env loading, paths, settings.

Directory creation is deferred to ``Settings.ensure_paths()`` so that simply
importing the package (e.g. from tests, REPL, or tooling) does not write to
the filesystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"
HOOKS_DIR = ASSETS_DIR / "hooks"
BROLL_DIR = ASSETS_DIR / "broll"
MUSIC_DIR = ASSETS_DIR / "music"
MUSIC_LIBRARY_DIR = MUSIC_DIR / "library"
OUTPUT_DIR = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "out")

_ASSET_DIRS: tuple[Path, ...] = (
    HOOKS_DIR, BROLL_DIR, MUSIC_DIR, MUSIC_LIBRARY_DIR, OUTPUT_DIR,
)


@dataclass(frozen=True)
class Settings:
    deepgram_api_key: str | None
    pexels_api_key: str | None
    pixabay_api_key: str | None
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    openai_reasoning_effort: str | None
    gemini_api_key: str | None
    gemini_base_url: str
    use_gemini_script: bool
    gemini_vision_model: str
    gemini_script_model: str

    # ── v2 quality knobs ──
    video_quality: str       # "draft" (fast) | "final" (slow, max quality)
    video_resolution: str    # "1080p", "4k", "8k"
    video_fps: int           # 30, 60
    transition_style: str    # "aggressive" (fast cuts) | "smooth" (longer fades)
    render_engine: str       # "intel" | "nvidia" | "cpu"
    caption_style: str       # "minimal" | "bold" | "animated"

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            deepgram_api_key=os.getenv("DEEPGRAM_API_KEY") or None,
            pexels_api_key=os.getenv("PEXELS_API_KEY") or None,
            pixabay_api_key=os.getenv("PIXABAY_API_KEY") or None,
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT") or None,
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_base_url=os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/").rstrip("/"),
            use_gemini_script=os.getenv("USE_GEMINI_SCRIPT", "false").lower() in ("true", "1", "yes"),
            gemini_vision_model=os.getenv("GEMINI_VISION_MODEL", "gemini-flash-latest"),
            gemini_script_model=os.getenv("GEMINI_SCRIPT_MODEL", "gemini-2.5-flash"),
            video_quality=os.getenv("VIDEO_QUALITY", "final"),
            video_resolution=os.getenv("VIDEO_RESOLUTION", "4k").lower(),
            video_fps=int(os.getenv("VIDEO_FPS", "60")),
            transition_style=os.getenv("TRANSITION_STYLE", "aggressive"),
            render_engine=os.getenv("RENDER_ENGINE", "intel"),
            caption_style=os.getenv("CAPTION_STYLE", "bold"),
        )

    def ensure_paths(self) -> None:
        """Create all asset directories on disk. Safe to call repeatedly."""
        for d in _ASSET_DIRS:
            d.mkdir(parents=True, exist_ok=True)


def settings() -> Settings:
    return Settings.load()