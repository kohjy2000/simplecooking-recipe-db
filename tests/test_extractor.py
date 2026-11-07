from recipe_db.extractor import clean_title, extract_recipe


def test_extracts_korean_ingredients_and_steps() -> None:
    description = """
오늘은 간단한 김치볶음밥입니다.

[재료]
- 밥 1공기
- 김치 150g
- 대파 1/2대
- 식용유 1큰술

[만드는 법]
1. 대파와 김치를 잘게 썰어 주세요.
2. 팬에 식용유를 넣고 대파를 볶습니다.
3. 김치와 밥을 넣고 골고루 볶아 완성합니다.
"""
    recipe = extract_recipe("김치볶음밥 만들기 | 자취요리", description)

    assert recipe.name == "김치볶음밥 만들기"
    assert [item.name for item in recipe.ingredients] == ["밥", "김치", "대파", "식용유"]
    assert recipe.ingredients[1].amount == "150"
    assert recipe.ingredients[1].unit == "g"
    assert len(recipe.steps) == 3
    assert recipe.confidence >= 0.65
    assert recipe.needs_review is False


def test_uses_caption_when_description_has_no_steps() -> None:
    caption = (
        "먼저 양파를 잘게 썰어 주세요. 팬에 기름을 넣고 양파를 볶습니다. "
        "계란을 넣고 완전히 익혀 완성합니다."
    )
    recipe = extract_recipe("양파 계란 볶음", "재료\n양파 1개\n계란 2개", caption)

    assert len(recipe.ingredients) == 2
    assert len(recipe.steps) == 3
    assert recipe.source_kind == "mixed"


def test_clean_title_removes_hashtags() -> None:
    assert clean_title("된장찌개 #shorts #레시피") == "된장찌개"

