"""B-roll search + download via Pexels (portrait 9:16 by default).

v2: queries the local SQLite cache before hitting the API.  On cache hit
the clip is returned immediately at zero API cost.  After a successful
download the asset is stored in the cache with full metadata.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Iterable

import requests

from . import cache
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
    """Pick the smallest portrait file whose source clip is long enough."""
    if video.get("duration", 0) + 0.5 < target_seconds:
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
    hd = [f for f in pool if f["width"] >= 1080]
    src = hd or pool
    src.sort(key=lambda f: f.get("width", 0) * f.get("height", 0))
    return src[0]["link"]


def download(query: str, api_key: str | None,
             target_seconds: float = 5.0,
             fallback_keywords: list[str] | None = None) -> Path | None:
    """Download one b-roll clip. Checks local cache first, then API."""
    queries = [query] + list(fallback_keywords or [])

    # ── 1. check SQLite cache ─────────────────────────────────
    for q in queries:
        cached = cache.find_broll([q], min_duration=target_seconds * 0.5)
        if cached:
            return cached[0].file_path

    # ── 2. check file-system cache (legacy SHA1 paths) ────────
    for q in queries:
        dest = _cache_path([q])
        if dest.exists() and dest.stat().st_size > 1024:
            # Backfill into SQLite so future lookups are faster
            cache.store_broll(dest, q, [q])
            return dest

    # ── 3. fetch from Pexels API ──────────────────────────────
    for q in queries:
        dest = _cache_path([q])
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
                # Store in SQLite cache with metadata
                cache.store_broll(
                    path=dest,
                    query=q,
                    keywords=queries,
                    duration_s=v.get("duration"),
                    source="pexels",
                    source_id=str(v.get("id", "")),
                    width=v.get("width"),
                    height=v.get("height"),
                    tags=[q],
                )
                return dest
            except Exception as exc:
                sys.stderr.write(f"  download failed {url}: {exc}\n")
                continue
    return None