from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT,
    channel_name TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    published_at TEXT,
    duration_seconds INTEGER,
    playlist_position INTEGER,
    description TEXT,
    thumbnail_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'no_recipe', 'failed')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_videos_processing
ON videos(status, published_at, playlist_position);

CREATE TABLE IF NOT EXISTS recipes (
    recipe_id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL UNIQUE REFERENCES videos(video_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    summary TEXT,
    servings TEXT,
    prep_minutes INTEGER,
    cook_minutes INTEGER,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    needs_review INTEGER NOT NULL DEFAULT 1 CHECK (needs_review IN (0, 1)),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('description', 'caption', 'mixed')),
    source_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(recipe_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    section TEXT,
    name TEXT NOT NULL,
    amount TEXT,
    unit TEXT,
    note TEXT,
    raw_text TEXT NOT NULL,
    UNIQUE(recipe_id, position)
);

CREATE TABLE IF NOT EXISTS steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(recipe_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    instruction TEXT NOT NULL,
    UNIQUE(recipe_id, position)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    channel_url TEXT NOT NULL,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_discovered_videos(conn: sqlite3.Connection, videos: Iterable[dict[str, Any]]) -> int:
    count = 0
    for video in videos:
        before = conn.total_changes
        conn.execute(
            """
            INSERT INTO videos (
                video_id, channel_id, channel_name, title, url, published_at,
                duration_seconds, playlist_position, thumbnail_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                channel_id = COALESCE(excluded.channel_id, videos.channel_id),
                channel_name = COALESCE(excluded.channel_name, videos.channel_name),
                title = excluded.title,
                published_at = COALESCE(excluded.published_at, videos.published_at),
                duration_seconds = COALESCE(excluded.duration_seconds, videos.duration_seconds),
                playlist_position = COALESCE(excluded.playlist_position, videos.playlist_position),
                thumbnail_url = COALESCE(excluded.thumbnail_url, videos.thumbnail_url),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                video["video_id"],
                video.get("channel_id"),
                video.get("channel_name"),
                video["title"],
                video["url"],
                video.get("published_at"),
                video.get("duration_seconds"),
                video.get("playlist_position"),
                video.get("thumbnail_url"),
            ),
        )
        count += int(conn.total_changes > before)
    conn.commit()
    return count


def next_pending_videos(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM videos
            WHERE status = 'pending' OR (status = 'failed' AND retry_count < 3)
            ORDER BY
                CASE WHEN published_at IS NULL THEN 1 ELSE 0 END,
                published_at ASC,
                playlist_position DESC,
                video_id ASC
            LIMIT ?
            """,
            (limit,),
        )
    )

