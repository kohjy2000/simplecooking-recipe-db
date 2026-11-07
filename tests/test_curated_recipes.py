from __future__ import annotations

import json
from pathlib import Path

CURATED_PATH = Path(__file__).parents[1] / "exports" / "curated_recipes.json"


def test_tuna_video_is_split_into_five_reviewed_recipes() -> None:
    recipes = json.loads(CURATED_PATH.read_text(encoding="utf-8"))

    assert len(recipes) == 5
    assert {recipe["source_video_id"] for recipe in recipes} == {"6O3XC5LzBO0"}
    assert len({recipe["video_id"] for recipe in recipes}) == 5
    assert all(recipe["source_kind"] == "manually_curated" for recipe in recipes)
    assert all(recipe["needs_review"] is False for recipe in recipes)
    assert all(recipe["ingredients"] for recipe in recipes)
    assert all(len(recipe["steps"]) >= 5 for recipe in recipes)


def test_curated_steps_do_not_contain_known_garbled_caption_fragments() -> None:
    recipes = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
    recipe_text = " ".join(step for recipe in recipes for step in recipe["steps"])

    for fragment in ("김도사 고사가", "흡연 약불", "경찰 몰라", "마찰 뜨 값"):
        assert fragment not in recipe_text
