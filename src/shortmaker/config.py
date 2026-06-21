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

    # ── v2 quality knobs ──
    video_quality: str       # "draft" (fast) | "final" (slow, max quality)
    transition_style: str    # "aggressive" (fast cuts) | "smooth" (longer fades)
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
            video_quality=os.getenv("VIDEO_QUALITY", "final"),
            transition_style=os.getenv("TRANSITION_STYLE", "aggressive"),
            caption_style=os.getenv("CAPTION_STYLE", "bold"),
        )

    def ensure_paths(self) -> None:
        """Create all asset directories on disk. Safe to call repeatedly."""
        for d in _ASSET_DIRS:
            d.mkdir(parents=True, exist_ok=True)


def settings() -> Settings:
    return Settings.load()