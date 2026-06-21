"""Local asset cache backed by SQLite.

Stores metadata about downloaded b-roll clips, music tracks, and TTS audio
so repeat runs can reuse assets without hitting external APIs.  The DB lives
at ``assets/cache.db`` — portable and inspectable with any SQLite browser.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import ASSETS_DIR

DB_PATH = ASSETS_DIR / "cache.db"

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection (WAL mode for concurrent reads)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), timeout=10)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _init_tables(_local.conn)
    return _local.conn


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS broll (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            query         TEXT    NOT NULL,
            keywords_json TEXT    NOT NULL DEFAULT '[]',
            source        TEXT    DEFAULT 'pexels',
            source_id     TEXT,
            file_path     TEXT    NOT NULL,
            duration_s    REAL,
            width         INTEGER,
            height        INTEGER,
            orientation   TEXT    DEFAULT 'portrait',
            tags_json     TEXT    DEFAULT '[]',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_broll_query ON broll(query);

        CREATE TABLE IF NOT EXISTS music (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT    NOT NULL,
            source      TEXT    DEFAULT 'local',
            file_path   TEXT    NOT NULL,
            duration_s  REAL,
            mood        TEXT,
            genre       TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_music_query ON music(query);
        CREATE INDEX IF NOT EXISTS idx_music_mood  ON music(mood);

        CREATE TABLE IF NOT EXISTS tts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text_hash   TEXT    NOT NULL,
            voice_model TEXT    NOT NULL,
            file_path   TEXT    NOT NULL,
            duration_s  REAL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_tts_hash ON tts(text_hash);

        CREATE TABLE IF NOT EXISTS hooks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT    NOT NULL UNIQUE,
            file_path   TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Lightweight result type
# ---------------------------------------------------------------------------

@dataclass
class CachedAsset:
    id: int
    file_path: Path
    duration_s: float | None
    query: str
    metadata: dict


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

def store_hook_urls(urls: list[str]) -> None:
    conn = _conn()
    conn.executemany(
        "INSERT OR IGNORE INTO hooks (url) VALUES (?)",
        [(u,) for u in urls]
    )
    conn.commit()

def get_random_hook_url() -> str | None:
    conn = _conn()
    row = conn.execute("SELECT url FROM hooks ORDER BY RANDOM() LIMIT 1").fetchone()
    return row["url"] if row else None

def get_hook_path(url: str) -> Path | None:
    conn = _conn()
    row = conn.execute("SELECT file_path FROM hooks WHERE url = ?", (url,)).fetchone()
    if row and row["file_path"]:
        p = Path(row["file_path"])
        if p.exists() and p.stat().st_size > 1024:
            return p
    return None

def update_hook_path(url: str, path: Path) -> None:
    conn = _conn()
    conn.execute("UPDATE hooks SET file_path = ? WHERE url = ?", (str(path), url))
    conn.commit()


# ---------------------------------------------------------------------------
# B-Roll
# ---------------------------------------------------------------------------

def find_broll(keywords: list[str], min_duration: float = 0.0) -> list[CachedAsset]:
    """Search the local cache for b-roll matching *any* of the keywords."""
    conn = _conn()
    seen_ids: set[int] = set()
    results: list[CachedAsset] = []
    for kw in keywords:
        pattern = f"%{kw.lower().strip()}%"
        rows = conn.execute(
            """SELECT * FROM broll
               WHERE (LOWER(query) LIKE ? OR LOWER(keywords_json) LIKE ?)
                 AND (duration_s IS NULL OR duration_s >= ?)
               ORDER BY created_at DESC LIMIT 5""",
            (pattern, pattern, min_duration),
        ).fetchall()
        for row in rows:
            if row["id"] in seen_ids:
                continue
            p = Path(row["file_path"])
            if p.exists() and p.stat().st_size > 1024:
                seen_ids.add(row["id"])
                results.append(CachedAsset(
                    id=row["id"],
                    file_path=p,
                    duration_s=row["duration_s"],
                    query=row["query"],
                    metadata={
                        "source": row["source"],
                        "tags": json.loads(row["tags_json"] or "[]"),
                    },
                ))
    return results


def store_broll(
    path: Path,
    query: str,
    keywords: list[str],
    duration_s: float | None = None,
    source: str = "pexels",
    source_id: str | None = None,
    width: int | None = None,
    height: int | None = None,
    tags: list[str] | None = None,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO broll
           (query, keywords_json, source, source_id, file_path,
            duration_s, width, height, tags_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            query,
            json.dumps(keywords),
            source,
            source_id,
            str(path),
            duration_s,
            width,
            height,
            json.dumps(tags or []),
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

def find_music(
    query: str | None = None,
    mood: str | None = None,
    min_duration: float = 0.0,
) -> CachedAsset | None:
    conn = _conn()
    conditions = ["(duration_s IS NULL OR duration_s >= ?)"]
    params: list = [min_duration]
    if query:
        conditions.append("LOWER(query) LIKE ?")
        params.append(f"%{query.lower()}%")
    if mood:
        conditions.append("LOWER(mood) LIKE ?")
        params.append(f"%{mood.lower()}%")
    where = " AND ".join(conditions)
    row = conn.execute(
        f"SELECT * FROM music WHERE {where} ORDER BY RANDOM() LIMIT 1",
        params,
    ).fetchone()
    if row:
        p = Path(row["file_path"])
        if p.exists() and p.stat().st_size > 1024:
            return CachedAsset(
                id=row["id"],
                file_path=p,
                duration_s=row["duration_s"],
                query=row["query"],
                metadata={"source": row["source"], "mood": row["mood"]},
            )
    return None


def store_music(
    path: Path,
    query: str,
    duration_s: float | None = None,
    source: str = "local",
    mood: str | None = None,
    genre: str | None = None,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO music (query, source, file_path, duration_s, mood, genre)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (query, source, str(path), duration_s, mood, genre),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

def find_tts(text_hash: str, voice_model: str) -> CachedAsset | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM tts WHERE text_hash = ? AND voice_model = ? LIMIT 1",
        (text_hash, voice_model),
    ).fetchone()
    if row:
        p = Path(row["file_path"])
        if p.exists() and p.stat().st_size > 1024:
            return CachedAsset(
                id=row["id"],
                file_path=p,
                duration_s=row["duration_s"],
                query=text_hash,
                metadata={"voice": row["voice_model"]},
            )
    return None


def store_tts(
    path: Path,
    text_hash: str,
    voice_model: str,
    duration_s: float | None = None,
) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO tts (text_hash, voice_model, file_path, duration_s) VALUES (?, ?, ?, ?)",
        (text_hash, voice_model, str(path), duration_s),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def get_stats() -> dict[str, int]:
    conn = _conn()
    stats: dict[str, int] = {}
    for table in ("broll", "music", "tts", "hooks"):
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
        stats[table] = row["cnt"] if row else 0
    return stats


def clear_all() -> None:
    conn = _conn()
    for table in ("broll", "music", "tts", "hooks"):
        conn.execute(f"DELETE FROM {table}")  # noqa: S608
    conn.commit()
