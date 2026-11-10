from __future__ import annotations

import json

import pytest

from recipe_db import curator
from recipe_db.curator import CurationError, normalize_model_output


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
