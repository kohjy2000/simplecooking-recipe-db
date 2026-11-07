from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from .pipeline import recipe_as_dict


def export_all(conn: sqlite3.Connection, output_dir: str | Path) -> int:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    recipe_ids = [row[0] for row in conn.execute("SELECT recipe_id FROM recipes ORDER BY recipe_id")]
    recipes = [recipe_as_dict(conn, recipe_id) for recipe_id in recipe_ids]
    (target / "recipes.json").write_text(
        json.dumps(recipes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (target / "recipes.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "video_id",
                "name",
                "summary",
                "servings",
                "confidence",
                "needs_review",
                "published_at",
                "source_url",
                "ingredients",
                "steps",
            ],
        )
        writer.writeheader()
        for recipe in recipes:
            writer.writerow(
                {
                    key: recipe.get(key)
                    for key in writer.fieldnames
                    if key not in {"ingredients", "steps"}
                }
                | {
                    "ingredients": " | ".join(item["raw_text"] for item in recipe["ingredients"]),
                    "steps": " | ".join(recipe["steps"]),
                }
            )
    return len(recipes)

