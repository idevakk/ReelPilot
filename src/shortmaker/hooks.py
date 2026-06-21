"""Malloy transitional-hooks catalog + download/cache.

Hooks are served directly from Malloy's CDN. The list below was captured
from the public catalog page (https://www.malloy.sg/opt-in/transitional-hooks)
which is JS-paginated; we hardcode the visible set rather than scraping.

v2: each hook carries ``topic_seeds`` — viral topic *shapes* that pair
naturally with the hook's energy so ``generate_topic()`` can riff on them.
"""

from __future__ import annotations

import random
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
        topic_seeds=[
            "shocking facts that will blow your mind",
            "things you should never try at home",
            "wait for it… you won't believe the ending",
            "cold hard truths nobody wants to hear",
        ],
    ),
    Hook(
        name="Girl-Punching",
        url=f"{CDN_BASE}/Girl-Punching.mp4",
        description="Girl delivers a quick punch with comedic timing.",
        tags=["fight", "comedy", "shock", "reaction", "karate"],
        topic_seeds=[
            "things that hit different when you realize the truth",
            "this fact will punch you in the face",
            "tiny things with massive impact",
            "underrated skills that could save your life",
        ],
    ),
    Hook(
        name="Pogo-Stick-Fail",
        url=f"{CDN_BASE}/Pogo-Stick-Fail.mp4",
        description="Person bounces on a pogo stick then crashes.",
        tags=["fail", "crash", "comedy", "stunt"],
        topic_seeds=[
            "things that seem fun until they go horribly wrong",
            "biggest fails of everyday life",
            "why humans are hilariously bad at physics",
            "ups and downs you can relate to",
        ],
    ),
    Hook(
        name="Jump-in-Pool",
        url=f"{CDN_BASE}/Jump-in-Pool.mp4",
        description="Cliff or rope jump into a swimming pool.",
        tags=["water", "summer", "splash", "stunt", "fun"],
        topic_seeds=[
            "taking the leap on things that terrify you",
            "summer hacks that will change your life",
            "the craziest things people do for fun",
            "things that feel amazing once you actually try them",
        ],
    ),
    Hook(
        name="Front-Flip-Sand",
        url=f"{CDN_BASE}/Front-Flip-Sand.mp4",
        description="Beach front flip landing face-first in sand.",
        tags=["beach", "fail", "flip", "summer", "comedy"],
        topic_seeds=[
            "expectations vs reality of trying to be cool",
            "embarrassing moments everyone can relate to",
            "things that look easy but are actually impossible",
            "face-plant worthy mistakes we all make",
        ],
    ),
    Hook(
        name="Tree-Surprise",
        url=f"{CDN_BASE}/Tree-Surprise.mp4",
        description="Person jumps out from behind a tree to scare someone.",
        tags=["scare", "prank", "surprise", "forest"],
        topic_seeds=[
            "things hiding in plain sight that will shock you",
            "nature facts that sound made up but are real",
            "the most unexpected things found in forests",
            "secrets your surroundings are hiding from you",
        ],
    ),
    Hook(
        name="Wedding-Cry",
        url=f"{CDN_BASE}/Wedding-Cry.mp4",
        description="Emotional wedding moment, someone crying.",
        tags=["wedding", "emotional", "cry", "love"],
        topic_seeds=[
            "moments that hit you right in the feels",
            "small gestures that mean everything",
            "stories that will make you cry in 30 seconds",
            "the most beautiful things humans do for each other",
        ],
    ),
    Hook(
        name="UFC-Knockout",
        url=f"{CDN_BASE}/UFC-Knockout.mp4",
        description="MMA knockout punch, slow-mo style.",
        tags=["fight", "knockout", "mma", "shock", "sports"],
        topic_seeds=[
            "one-hit facts that knock out your old beliefs",
            "things so powerful they'll change how you think",
            "the most dominant forces in nature",
            "knockout moments in history you never heard of",
        ],
    ),
    Hook(
        name="Opposite-Cookie",
        url=f"{CDN_BASE}/Opposite-Cookie.mp4",
        description="Two people switch cookies, comedic reveal.",
        tags=["food", "comedy", "twist", "switch"],
        topic_seeds=[
            "things that are the opposite of what you think",
            "plot twists in everyday life",
            "foods that are secretly something else entirely",
            "the switch-up nobody saw coming",
        ],
    ),
]


def by_name(name: str) -> Hook:
    key = name.lower().replace("_", "-")
    for h in CATALOG:
        if h.name.lower() == key:
            return h
    raise KeyError(f"Unknown hook: {name}. Known: {[h.name for h in CATALOG]}")


import re

_scraped_hooks_cache: list[str] = []

def _scrape_hooks() -> list[str]:
    global _scraped_hooks_cache
    if _scraped_hooks_cache:
        return _scraped_hooks_cache
    
    urls = [
        "https://transitionalhooks.com/social-media-video-hook-library/",
        "https://transitionalhooks.com/social-media-video-hook-library/page/2/"
    ]
    videos = set()
    for url in urls:
        try:
            r = requests.get(url, timeout=10)
            found = re.findall(r'https://transitionalhooks\.com/wp-content/uploads/[^"\']+\.mp4', r.text)
            videos.update(found)
        except Exception:
            pass
    _scraped_hooks_cache = list(videos)
    return _scraped_hooks_cache

def random_hook() -> Hook:
    """Pick a random hook from the catalog or scraped from transitionalhooks.com."""
    scraped = _scrape_hooks()
    if scraped:
        url = random.choice(scraped)
        name = url.split("/")[-1].replace(".mp4", "")
        # Try to find it in the local catalog first to get better topic seeds
        for h in CATALOG:
            if h.url.endswith(url.split("/")[-1]):
                return h
        
        # Otherwise return a dynamically created hook
        desc = name.replace("-", " ")
        return Hook(
            name=name,
            url=url,
            description=desc,
            tags=[w.lower() for w in desc.split()],
            topic_seeds=[],
        )
    return random.choice(CATALOG)


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