from __future__ import annotations

import json
from pathlib import Path

CURATED_PATH = Path(__file__).parents[1] / "exports" / "curated_recipes.json"


def test_tuna_video_is_split_into_five_reviewed_recipes() -> None:
    recipes = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
    tuna_recipes = [
        recipe for recipe in recipes if recipe["source_video_id"] == "6O3XC5LzBO0"
    ]

    assert len(tuna_recipes) == 5
    assert len({recipe["video_id"] for recipe in tuna_recipes}) == 5
    assert all(recipe["source_kind"] == "manually_curated" for recipe in tuna_recipes)
    assert all(recipe["needs_review"] is False for recipe in tuna_recipes)
    assert all(recipe["ingredients"] for recipe in tuna_recipes)
    assert all(len(recipe["steps"]) >= 5 for recipe in tuna_recipes)


def test_curated_steps_do_not_contain_known_garbled_caption_fragments() -> None:
    recipes = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
    recipe_text = " ".join(step for recipe in recipes for step in recipe["steps"])

    for fragment in ("김도사 고사가", "흡연 약불", "경찰 몰라", "마찰 뜨 값"):
        assert fragment not in recipe_text


def test_spam_stew_is_manually_reviewed_and_searchable() -> None:
    recipes = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
    spam_recipes = [
        recipe
        for recipe in recipes
        if any(ingredient["name"] == "스팸" for ingredient in recipe["ingredients"])
    ]

    assert len(spam_recipes) >= 1
    assert spam_recipes[0]["source_kind"] == "manually_curated"
    assert spam_recipes[0]["needs_review"] is False
    assert len(spam_recipes[0]["steps"]) >= 5
