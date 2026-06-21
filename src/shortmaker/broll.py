"""B-roll search + download via Pexels (portrait 9:16 by default)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Iterable

import requests

from .config import BROLL_DIR
from .http import stream_download

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
DEFAULT_PER_PAGE = 5


def _sha1_short(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


def _cache_path(keywords: Iterable[str]) -> Path:
    joined = "|".join(sorted(k.strip().lower() for k in keywords))
    return BROLL_DIR / f"{_sha1_short(joined)}.mp4"


def search(query: str, api_key: str | None, per_page: int = DEFAULT_PER_PAGE,
           orientation: str = "portrait") -> list[dict]:
    if not api_key:
        return []
    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
        "size": "medium",
    }
    resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("videos", [])


def _select_file(video: dict, target_seconds: float) -> str | None:
    """Pick the smallest portrait file whose source clip is long enough.

    Honors `target_seconds` by filtering the parent video by `duration` first
    (Pexels exposes per-video duration, not per-file). If no video meets the
    duration requirement we fall back to the shortest portrait file we can
    find rather than returning nothing — the ffmpeg `zoompan` filter will
    stretch the last frame as needed.
    """
    if video.get("duration", 0) + 0.5 < target_seconds:
        # Too short — caller will try the next video.
        return _pick_portrait_file(video)

    chosen = _pick_portrait_file(video, min_duration_ok=True)
    if chosen is not None:
        return chosen
    return _pick_portrait_file(video)


def _pick_portrait_file(video: dict, *, min_duration_ok: bool = False) -> str | None:
    files = [f for f in video.get("video_files", [])
             if f.get("link", "").endswith(".mp4")
             and f.get("width", 0) and f.get("height", 0)]
    portrait = [f for f in files if f["height"] > f["width"]]
    pool = portrait or files
    if not pool:
        return None
    # Prefer HD portrait, then SD portrait, then any portrait.
    hd = [f for f in pool if f["width"] >= 1080]
    src = hd or pool
    # Sort ascending by pixel count so we download the smallest sufficient file.
    src.sort(key=lambda f: f.get("width", 0) * f.get("height", 0))
    return src[0]["link"]


def download(query: str, api_key: str | None,
             target_seconds: float = 5.0,
             fallback_keywords: list[str] | None = None) -> Path | None:
    """Download one b-roll clip. Tries the query, then fallback keywords."""
    queries = [query] + list(fallback_keywords or [])
    for q in queries:
        dest = _cache_path([q])
        if dest.exists() and dest.stat().st_size > 1024:
            return dest
        try:
            videos = search(q, api_key)
        except Exception as exc:
            sys.stderr.write(f"  Pexels search failed for {q!r}: {exc}\n")
            continue
        for v in videos:
            url = _select_file(v, target_seconds)
            if not url:
                continue
            try:
                stream_download(url, dest, timeout=60)
                return dest
            except Exception as exc:
                sys.stderr.write(f"  download failed {url}: {exc}\n")
                continue
    return None