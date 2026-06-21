"""Shared HTTP download helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

import requests


def stream_download(url: str, dest: Path, *, timeout: int = 60,
                    headers: dict | None = None) -> None:
    """Stream `url` to `dest`, writing to a `.part` file first and renaming
    on success. Guarantees `dest` either contains the full payload or does
    not exist, so cache-check callers can trust a non-empty file.

    Raises on any HTTP error or network failure; the partial `.part` is
    left on disk for inspection.
    """
    with requests.get(url, stream=True, timeout=timeout, headers=headers) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as fh:
            shutil.copyfileobj(r.raw, fh)
        tmp.replace(dest)