"""Malloy transitional-hooks catalog + download/cache.

Hooks are served directly from Malloy's CDN. The list below was captured
from the public catalog page (https://www.malloy.sg/opt-in/transitional-hooks)
which is JS-paginated; we hardcode the visible set rather than scraping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

from .config import HOOKS_DIR
from .http import stream_download
from .models import Hook

CDN_BASE = "https://malloy-files-c0ddahgefecthmcs.z03.azurefd.net/web/transitional_videos"

CATALOG: list[Hook] = [
    Hook(
        name="Snowball-Splash",
        url=f"{CDN_BASE}/Snowball-Splash.mp4",
        description="Snowball thrown into a face, water splash.",
        tags=["snow", "winter", "shock", "splash", "fail", "prank", "reaction"],
    ),
    Hook(
        name="Girl-Punching",
        url=f"{CDN_BASE}/Girl-Punching.mp4",
        description="Girl delivers a quick punch with comedic timing.",
        tags=["fight", "comedy", "shock", "reaction", "karate"],
    ),
    Hook(
        name="Pogo-Stick-Fail",
        url=f"{CDN_BASE}/Pogo-Stick-Fail.mp4",
        description="Person bounces on a pogo stick then crashes.",
        tags=["fail", "crash", "comedy", "stunt"],
    ),
    Hook(
        name="Jump-in-Pool",
        url=f"{CDN_BASE}/Jump-in-Pool.mp4",
        description="Cliff or rope jump into a swimming pool.",
        tags=["water", "summer", "splash", "stunt", "fun"],
    ),
    Hook(
        name="Front-Flip-Sand",
        url=f"{CDN_BASE}/Front-Flip-Sand.mp4",
        description="Beach front flip landing face-first in sand.",
        tags=["beach", "fail", "flip", "summer", "comedy"],
    ),
    Hook(
        name="Tree-Surprise",
        url=f"{CDN_BASE}/Tree-Surprise.mp4",
        description="Person jumps out from behind a tree to scare someone.",
        tags=["scare", "prank", "surprise", "forest"],
    ),
    Hook(
        name="Wedding-Cry",
        url=f"{CDN_BASE}/Wedding-Cry.mp4",
        description="Emotional wedding moment, someone crying.",
        tags=["wedding", "emotional", "cry", "love"],
    ),
    Hook(
        name="UFC-Knockout",
        url=f"{CDN_BASE}/UFC-Knockout.mp4",
        description="MMA knockout punch, slow-mo style.",
        tags=["fight", "knockout", "mma", "shock", "sports"],
    ),
    Hook(
        name="Opposite-Cookie",
        url=f"{CDN_BASE}/Opposite-Cookie.mp4",
        description="Two people switch cookies, comedic reveal.",
        tags=["food", "comedy", "twist", "switch"],
    ),
]


def by_name(name: str) -> Hook:
    key = name.lower().replace("_", "-")
    for h in CATALOG:
        if h.name.lower() == key:
            return h
    raise KeyError(f"Unknown hook: {name}. Known: {[h.name for h in CATALOG]}")


def cache_path(hook: Hook) -> Path:
    return HOOKS_DIR / f"{hook.name}.mp4"


def is_cached(hook: Hook) -> bool:
    p = cache_path(hook)
    return p.exists() and p.stat().st_size > 1024


def ensure(hook: Hook, force: bool = False) -> Path:
    """Download hook MP4 if not already cached. Returns local path."""
    dest = cache_path(hook)
    if not force and is_cached(hook):
        return dest
    sys.stdout.write(f"Downloading hook {hook.name} -> {dest}\n")
    sys.stdout.flush()
    stream_download(hook.url, dest, timeout=60)
    return dest


def fetch_all(progress: bool = True) -> list[Path]:
    """Download every hook in the catalog. Used by scripts/fetch_hooks.py."""
    paths: list[Path] = []
    for h in CATALOG:
        try:
            paths.append(ensure(h))
        except Exception as exc:  # pragma: no cover - network dependent
            if progress:
                print(f"  ! failed {h.name}: {exc}")
    return paths