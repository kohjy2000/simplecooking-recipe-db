from __future__ import annotations

import sqlite3
from typing import Any

from .db import next_pending_videos, upsert_discovered_videos
from .extractor import ExtractedRecipe, extract_recipe
from .youtube import discover_channel, fetch_korean_caption, fetch_video


def discover(conn: sqlite3.Connection, channel_url: str) -> int:
    return upsert_discovered_videos(conn, discover_channel(channel_url))


def _save_recipe(
    conn: sqlite3.Connection,
    video_id: str,
    metadata: dict[str, Any],
    recipe: ExtractedRecipe,
) -> None:
    conn.execute("DELETE FROM recipes WHERE video_id = ?", (video_id,))
    cursor = conn.execute(
        """
        INSERT INTO recipes (
            video_id, name, summary, servings, confidence, needs_review,
            source_kind, source_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video_id,
            recipe.name,
            recipe.summary,
            recipe.servings,
            recipe.confidence,
            int(recipe.needs_review),
            recipe.source_kind,
            recipe.source_hash,
        ),
    )
    recipe_id = int(cursor.lastrowid or 0)
    conn.executemany(
        """
        INSERT INTO ingredients (
            recipe_id, position, section, name, amount, unit, note, raw_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                recipe_id,
                position,
                ingredient.section,
                ingredient.name,
                ingredient.amount,
                ingredient.unit,
                ingredient.note,
                ingredient.raw_text,
            )
            for position, ingredient in enumerate(recipe.ingredients, start=1)
        ],
    )
    conn.executemany(
        "INSERT INTO steps (recipe_id, position, instruction) VALUES (?, ?, ?)",
        [(recipe_id, position, step) for position, step in enumerate(recipe.steps, start=1)],
    )
    status = "completed" if recipe.ingredients or recipe.steps else "no_recipe"
    conn.execute(
        """
        UPDATE videos SET
            channel_id = COALESCE(?, channel_id),
            channel_name = COALESCE(?, channel_name),
            title = COALESCE(?, title),
            description = ?,
            duration_seconds = COALESCE(?, duration_seconds),
            thumbnail_url = COALESCE(?, thumbnail_url),
            status = ?, last_error = NULL, processed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
        """,
        (
            metadata.get("channel_id"),
            metadata.get("channel"),
            metadata.get("title"),
            metadata.get("description") or "",
            metadata.get("duration"),
            metadata.get("thumbnail"),
            status,
            video_id,
        ),
    )


def process_pending(conn: sqlite3.Connection, max_new: int) -> dict[str, int]:
    stats = {"processed": 0, "completed": 0, "failed": 0}
    for video in next_pending_videos(conn, max_new):
        stats["processed"] += 1
        try:
            metadata = fetch_video(video["url"])
            caption = fetch_korean_caption(metadata)
            recipe = extract_recipe(
                metadata.get("title") or video["title"],
                metadata.get("description") or "",
                caption,
            )
            with conn:
                _save_recipe(conn, video["video_id"], metadata, recipe)
            if recipe.ingredients or recipe.steps:
                stats["completed"] += 1
        # A single malformed or unavailable video must not abort the remaining batch.
        except Exception as exc:  # noqa: BLE001
            with conn:
                conn.execute(
                    """
                    UPDATE videos SET status = 'failed', retry_count = retry_count + 1,
                        last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE video_id = ?
                    """,
                    (str(exc)[-2000:], video["video_id"]),
                )
            stats["failed"] += 1
    return stats


def recipe_as_dict(conn: sqlite3.Connection, recipe_id: int) -> dict[str, Any]:
    recipe = conn.execute(
        """
        SELECT r.*, v.url AS source_url, v.published_at, v.title AS video_title
        FROM recipes r JOIN videos v ON v.video_id = r.video_id
        WHERE r.recipe_id = ?
        """,
        (recipe_id,),
    ).fetchone()
    if recipe is None:
        raise KeyError(recipe_id)
    result = dict(recipe)
    result["needs_review"] = bool(result["needs_review"])
    result["ingredients"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT position, section, name, amount, unit, note, raw_text
            FROM ingredients WHERE recipe_id = ? ORDER BY position
            """,
            (recipe_id,),
        )
    ]
    result["steps"] = [
        row["instruction"]
        for row in conn.execute(
            "SELECT instruction FROM steps WHERE recipe_id = ? ORDER BY position",
            (recipe_id,),
        )
    ]
    for key in ("recipe_id", "created_at", "updated_at", "source_hash"):
        result.pop(key, None)
    return result

