from __future__ import annotations

import json

import pytest

from recipe_db import curator
from recipe_db.curator import (
    CurationError,
    merge_curation_shards,
    normalize_model_output,
    plan_curation,
)


def _raw_recipe() -> dict[str, object]:
    return {
        "video_id": "video123",
        "video_title": "간단한 참치 요리 2가지",
        "name": "간단한 참치 요리 2가지",
        "source_url": "https://www.youtube.com/watch?v=video123",
        "published_at": None,
        "ingredients": [{"name": "참치", "raw_text": "참치 1캔"}],
        "steps": ["참치와 밥을 섞어 볶습니다."],
    }


def _model_output() -> str:
    return json.dumps(
        {
            "recipes": [
                {
                    "name": "참치 볶음밥",
                    "summary": "참치와 밥을 볶는 간단한 요리입니다.",
                    "servings": 1,
                    "start_seconds": 10,
                    "ingredients": [
                        {"section": "재료", "name": "참치", "amount": "1", "unit": "캔"},
                        {"section": "재료", "name": "밥", "amount": "1", "unit": "공기"},
                    ],
                    "steps": [
                        "참치캔의 기름을 뺍니다.",
                        "팬에 참치와 밥을 넣습니다.",
                        "재료를 고루 섞어 볶습니다.",
                    ],
                    "tips": [],
                },
                {
                    "name": "참치 김치밥",
                    "summary": "참치와 김치를 밥에 섞는 요리입니다.",
                    "servings": 1,
                    "start_seconds": 90,
                    "ingredients": [
                        {"section": "재료", "name": "참치", "amount": "1", "unit": "캔"},
                        {"section": "재료", "name": "김치", "amount": None, "unit": None},
                        {"section": "재료", "name": "밥", "amount": "1", "unit": "공기"},
                    ],
                    "steps": [
                        "김치를 먹기 좋은 크기로 썹니다.",
                        "참치와 김치를 팬에서 볶습니다.",
                        "밥을 넣고 고루 섞어 마무리합니다.",
                    ],
                    "tips": ["참치는 마지막에 넣어 짧게 볶습니다."],
                },
            ]
        },
        ensure_ascii=False,
    )


def test_normalizes_and_splits_multi_recipe_video() -> None:
    recipes = normalize_model_output(
        _model_output(),
        raw_recipe=_raw_recipe(),
        source_text="참치 1캔 밥 1공기 김치 기름을 빼고 볶습니다",
        model="test-model",
        duration_seconds=200,
    )

    assert [recipe["video_id"] for recipe in recipes] == ["video123-01", "video123-02"]
    assert all(recipe["source_kind"] == "automated_curated" for recipe in recipes)
    assert recipes[1]["source_url"].endswith("&t=90s")
    assert recipes[0]["ingredients"][0]["raw_text"] == "참치 1 캔"


def test_removes_quantities_that_have_no_source_evidence() -> None:
    recipes = normalize_model_output(
        _model_output(),
        raw_recipe=_raw_recipe(),
        source_text="참치와 밥, 김치를 볶습니다",
        model="test-model",
    )

    assert recipes[0]["ingredients"][0]["amount"] is None
    assert recipes[0]["ingredients"][0]["unit"] is None
    assert recipes[0]["servings"] is None


def test_rejects_when_title_recipe_count_is_not_met() -> None:
    payload = json.loads(_model_output())
    payload["recipes"] = payload["recipes"][:1]

    with pytest.raises(CurationError, match="promises 2"):
        normalize_model_output(
            json.dumps(payload, ensure_ascii=False),
            raw_recipe=_raw_recipe(),
            source_text="참치 밥 김치",
            model="test-model",
        )


def test_repairs_small_model_json_syntax_errors() -> None:
    payload = _model_output().replace(
        '"summary": "참치와 밥을 볶는 간단한 요리입니다.",',
        '"summary": "참치와 밥을 "빠르게" 볶는 요리입니다.",',
        1,
    )

    recipes = normalize_model_output(
        payload,
        raw_recipe=_raw_recipe(),
        source_text="참치 1캔 밥 1공기 김치 기름을 빼고 빠르게 볶습니다",
        model="test-model",
    )

    assert len(recipes) == 2
    assert recipes[0]["name"] == "참치 볶음밥"


def test_accepts_two_step_simple_recipe() -> None:
    payload = json.loads(_model_output())
    payload["recipes"][0]["steps"] = payload["recipes"][0]["steps"][:2]

    recipes = normalize_model_output(
        json.dumps(payload, ensure_ascii=False),
        raw_recipe=_raw_recipe(),
        source_text="참치 1캔 밥 1공기 김치 기름을 빼고 볶습니다",
        model="test-model",
    )

    assert len(recipes[0]["steps"]) == 2


def test_folds_more_than_ten_steps_without_dropping_content() -> None:
    payload = json.loads(_model_output())
    payload["recipes"][0]["steps"] = [
        f"참치와 밥을 고루 볶는 과정 {index}입니다." for index in range(1, 12)
    ]

    recipes = normalize_model_output(
        json.dumps(payload, ensure_ascii=False),
        raw_recipe=_raw_recipe(),
        source_text="참치 1캔 밥 1공기 김치 기름을 빼고 볶습니다",
        model="test-model",
    )

    assert len(recipes[0]["steps"]) == 10
    assert "과정 1" in " ".join(recipes[0]["steps"])
    assert "과정 11" in " ".join(recipes[0]["steps"])


def test_splits_one_paragraph_into_multiple_steps() -> None:
    payload = json.loads(_model_output())
    payload["recipes"][0]["steps"] = [
        "참치캔의 기름을 뺍니다. 팬에 참치와 밥을 넣습니다. 재료를 고루 볶습니다."
    ]

    recipes = normalize_model_output(
        json.dumps(payload, ensure_ascii=False),
        raw_recipe=_raw_recipe(),
        source_text="참치 1캔 밥 1공기 김치 기름을 빼고 볶습니다",
        model="test-model",
    )

    assert len(recipes[0]["steps"]) == 3


def test_curate_batch_persists_public_recipes_and_state(tmp_path, monkeypatch) -> None:
    raw_path = tmp_path / "recipes.json"
    curated_path = tmp_path / "curated.json"
    state_path = tmp_path / "state.json"
    raw_path.write_text(json.dumps([_raw_recipe()], ensure_ascii=False), encoding="utf-8")
    curated_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(curator, "fetch_video", lambda _: {"duration": 200})
    monkeypatch.setattr(
        curator,
        "fetch_caption_tracks",
        lambda _: {
            "ko": (
                "[00:10] 참치와 밥을 볶고 밥을 섞습니다\n"
                "[01:30] 참치와 김치를 볶고 김치를 더합니다"
            )
        },
    )

    stats = curator.curate_batch(
        raw_path=raw_path,
        curated_path=curated_path,
        state_path=state_path,
        max_new=1,
        model="test-model",
        endpoint="http://unused",
        generate=lambda _: _model_output(),
    )

    assert stats == {"attempted": 1, "completed": 1, "failed": 0, "recipes_added": 2}
    assert len(json.loads(curated_path.read_text(encoding="utf-8"))) == 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["videos"]["video123"]["status"] == "completed"


def test_rejects_single_caption_mentions_from_noisy_transcript() -> None:
    payload = json.loads(_model_output())
    payload["recipes"] = payload["recipes"][:1]
    payload["recipes"][0]["ingredients"].append(
        {"section": "재료", "name": "배", "amount": None, "unit": None}
    )
    raw = _raw_recipe()
    raw["video_title"] = "참치 볶음밥"

    with pytest.raises(CurationError, match="weakly supported ingredients: 배"):
        normalize_model_output(
            json.dumps(payload, ensure_ascii=False),
            raw_recipe=raw,
            source_text="참치 볶음밥 배",
            caption_text="참치와 밥을 볶다가 배라는 음성이 한 번 잘못 인식됐습니다",
            model="test-model",
        )


def test_rejects_generic_procedure_not_present_in_source() -> None:
    payload = json.loads(_model_output())
    payload["recipes"][0]["steps"][0] = "참치를 깨끗이 씻어 물기를 제거합니다."

    with pytest.raises(CurationError, match="unsupported procedural detail"):
        normalize_model_output(
            json.dumps(payload, ensure_ascii=False),
            raw_recipe=_raw_recipe(),
            source_text="참치 1캔 밥 1공기 김치 기름을 빼고 볶습니다",
            model="test-model",
        )


def test_curate_batch_prioritizes_untried_videos(tmp_path, monkeypatch) -> None:
    first = _raw_recipe()
    second = json.loads(json.dumps(first))
    second["video_id"] = "video456"
    second["source_url"] = "https://www.youtube.com/watch?v=video456"
    raw_path = tmp_path / "recipes.json"
    curated_path = tmp_path / "curated.json"
    state_path = tmp_path / "state.json"
    raw_path.write_text(json.dumps([first, second], ensure_ascii=False), encoding="utf-8")
    curated_path.write_text("[]", encoding="utf-8")
    state_path.write_text(
        json.dumps({"videos": {"video123": {"attempts": 1}}}), encoding="utf-8"
    )
    monkeypatch.setattr(curator, "fetch_video", lambda _: {"duration": 200})
    monkeypatch.setattr(
        curator,
        "fetch_caption_tracks",
        lambda _: {"ko": "참치 참치 밥 밥 김치 김치 기름을 빼고 볶습니다"},
    )

    curator.curate_batch(
        raw_path=raw_path,
        curated_path=curated_path,
        state_path=state_path,
        max_new=1,
        model="test-model",
        endpoint="http://unused",
        generate=lambda _: _model_output(),
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["videos"]["video123"]["attempts"] == 1
    assert state["videos"]["video456"]["status"] == "completed"


def test_curate_batch_prioritizes_requested_ingredient_coverage(tmp_path, monkeypatch) -> None:
    ordinary = _raw_recipe()
    priority = json.loads(json.dumps(ordinary))
    priority["video_id"] = "spam456"
    priority["video_title"] = "스팸 볶음밥"
    priority["source_url"] = "https://www.youtube.com/watch?v=spam456"
    raw_path = tmp_path / "recipes.json"
    curated_path = tmp_path / "curated.json"
    state_path = tmp_path / "state.json"
    raw_path.write_text(json.dumps([ordinary, priority], ensure_ascii=False), encoding="utf-8")
    curated_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(curator, "fetch_video", lambda _: {"duration": 200})
    monkeypatch.setattr(
        curator,
        "fetch_caption_tracks",
        lambda _: {"ko": "참치 참치 밥 밥 김치 김치 기름을 빼고 볶습니다"},
    )

    curator.curate_batch(
        raw_path=raw_path,
        curated_path=curated_path,
        state_path=state_path,
        max_new=1,
        model="test-model",
        endpoint="http://unused",
        generate=lambda _: _model_output(),
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "video123" not in state["videos"]
    assert state["videos"]["spam456"]["status"] == "completed"


def test_curate_batch_can_target_a_video(tmp_path, monkeypatch) -> None:
    first = _raw_recipe()
    second = json.loads(json.dumps(first))
    second["video_id"] = "video456"
    second["source_url"] = "https://www.youtube.com/watch?v=video456"
    raw_path = tmp_path / "recipes.json"
    curated_path = tmp_path / "curated.json"
    state_path = tmp_path / "state.json"
    raw_path.write_text(json.dumps([first, second], ensure_ascii=False), encoding="utf-8")
    curated_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(curator, "fetch_video", lambda _: {"duration": 200})
    monkeypatch.setattr(
        curator,
        "fetch_caption_tracks",
        lambda _: {"ko": "참치 밥 밥 김치 김치 기름을 빼고 볶습니다"},
    )

    curator.curate_batch(
        raw_path=raw_path,
        curated_path=curated_path,
        state_path=state_path,
        max_new=1,
        model="test-model",
        endpoint="http://unused",
        generate=lambda _: _model_output(),
        video_ids=["video456"],
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "video123" not in state["videos"]
    assert state["videos"]["video456"]["status"] == "completed"


def test_english_source_quote_supports_korean_ingredient_name() -> None:
    payload = json.loads(_model_output())
    payload["recipes"] = payload["recipes"][:1]
    payload["recipes"][0]["ingredients"] = [
        {
            "section": "재료",
            "name": "감자",
            "amount": None,
            "unit": None,
            "source_quote": "slice the potato",
        },
        {
            "section": "재료",
            "name": "당근",
            "amount": None,
            "unit": None,
            "source_quote": "add the carrot",
        },
    ]
    raw = _raw_recipe()
    raw["video_title"] = "간단한 채소 요리"
    source = "slice the potato and add the carrot to the pan"

    recipes = normalize_model_output(
        json.dumps(payload, ensure_ascii=False),
        raw_recipe=raw,
        source_text=source,
        caption_text=source,
        model="test-model",
    )

    assert [item["name"] for item in recipes[0]["ingredients"]] == ["감자", "당근"]


def test_english_quote_does_not_support_unrelated_garbled_name() -> None:
    payload = json.loads(_model_output())
    payload["recipes"] = payload["recipes"][:1]
    payload["recipes"][0]["ingredients"][0].update(
        {"name": "은주", "source_quote": "add the onion"}
    )
    raw = _raw_recipe()
    raw["video_title"] = "간단한 채소 요리"

    with pytest.raises(CurationError, match="weakly supported ingredients: 은주"):
        normalize_model_output(
            json.dumps(payload, ensure_ascii=False),
            raw_recipe=raw,
            source_text="add the onion 참치 밥 김치",
            caption_text="add the onion 참치 밥 김치",
            model="test-model",
        )


def test_plan_and_merge_parallel_curation_shards(tmp_path) -> None:
    raw_path = tmp_path / "raw.json"
    curated_path = tmp_path / "curated.json"
    state_path = tmp_path / "state.json"
    shards_dir = tmp_path / "shards"
    raw = []
    for video_id in ("done", "exhausted", "new"):
        recipe = _raw_recipe()
        recipe["video_id"] = video_id
        raw.append(recipe)
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    curated_path.write_text(
        json.dumps([{"video_id": "done-01", "source_video_id": "done"}]), encoding="utf-8"
    )
    state_path.write_text(
        json.dumps({"videos": {"exhausted": {"attempts": 4}}}), encoding="utf-8"
    )

    plan = plan_curation(
        raw_path=raw_path,
        curated_path=curated_path,
        state_path=state_path,
        max_shards=20,
    )
    assert plan == {"eligible": 1, "shard_count": 1, "shards": [0]}

    shard = shards_dir / "curated-shard-0"
    shard.mkdir(parents=True)
    shard_recipe = {"video_id": "new-01", "source_video_id": "new"}
    (shard / "curated.json").write_text(json.dumps([shard_recipe]), encoding="utf-8")
    (shard / "state.json").write_text(
        json.dumps({"videos": {"new": {"attempts": 1, "status": "completed"}}}),
        encoding="utf-8",
    )

    stats = merge_curation_shards(
        curated_path=curated_path,
        state_path=state_path,
        shards_dir=shards_dir,
    )
    assert stats["recipes_added"] == 1
    assert len(json.loads(curated_path.read_text(encoding="utf-8"))) == 2
