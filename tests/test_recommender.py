from recipe_db.db import connect, initialize
from recipe_db.recommender import canonicalize_ingredient, parse_ingredient_query, recommend


def _seed(conn) -> None:
    conn.execute(
        "INSERT INTO videos (video_id, title, url, status) VALUES ('exact', '김치볶음밥', 'https://youtu.be/exact', 'completed')"
    )
    conn.execute(
        "INSERT INTO videos (video_id, title, url, status) VALUES ('near', '계란말이', 'https://youtu.be/near', 'completed')"
    )
    exact_id = conn.execute(
        """
        INSERT INTO recipes (video_id, name, confidence, needs_review, source_kind)
        VALUES ('exact', '김치볶음밥', 0.9, 0, 'description')
        """
    ).lastrowid
    near_id = conn.execute(
        """
        INSERT INTO recipes (video_id, name, confidence, needs_review, source_kind)
        VALUES ('near', '계란말이', 0.8, 0, 'description')
        """
    ).lastrowid
    for position, name in enumerate(["밥", "김치", "계란", "식용유"], start=1):
        conn.execute(
            "INSERT INTO ingredients (recipe_id, position, name, raw_text) VALUES (?, ?, ?, ?)",
            (exact_id, position, name, name),
        )
    for position, name in enumerate(["계란", "대파", "당근"], start=1):
        conn.execute(
            "INSERT INTO ingredients (recipe_id, position, name, raw_text) VALUES (?, ?, ?, ?)",
            (near_id, position, name, name),
        )
    conn.commit()


def test_parses_natural_korean_ingredient_query() -> None:
    assert parse_ingredient_query("냉장고에 달걀이랑 김치, 찬밥 있어요") == [
        "계란",
        "김치",
        "밥",
    ]


def test_aliases_are_canonicalized() -> None:
    assert canonicalize_ingredient("달걀") == "계란"
    assert canonicalize_ingredient("콘") == "옥수수"
    assert canonicalize_ingredient("쥬키니") == "주키니"
    assert canonicalize_ingredient("애호박") == "애호박"


def test_exact_recipe_ranks_before_recipe_with_missing_items(tmp_path) -> None:
    with connect(tmp_path / "recipes.sqlite") as conn:
        initialize(conn)
        _seed(conn)
        parsed, results = recommend(conn, "달걀, 김치, 찬밥", max_missing=5)

    assert parsed == ["계란", "김치", "밥"]
    assert results[0].name == "김치볶음밥"
    assert results[0].can_make_now is True
    assert results[0].title_matched_ingredients == ["김치", "밥"]
    assert results[1].missing_ingredients == ["대파", "당근"]


def test_title_match_beats_incidental_caption_ingredient(tmp_path) -> None:
    with connect(tmp_path / "recipes.sqlite") as conn:
        initialize(conn)
        _seed(conn)
        parsed, results = recommend(conn, "계란", max_missing=5)

    assert parsed == ["계란"]
    assert results[0].name == "계란말이"
    assert results[0].title_matched_ingredients == ["계란"]


def test_title_match_is_not_filtered_by_many_aggregate_ingredients(tmp_path) -> None:
    with connect(tmp_path / "recipes.sqlite") as conn:
        initialize(conn)
        _seed(conn)
        conn.execute(
            "INSERT INTO videos (video_id, title, url, status) VALUES ('tuna', '참치 요리 5가지', 'https://youtu.be/tuna', 'completed')"
        )
        recipe_id = conn.execute(
            """
            INSERT INTO recipes (video_id, name, confidence, needs_review, source_kind)
            VALUES ('tuna', '참치 요리 5가지', 0.9, 1, 'caption')
            """
        ).lastrowid
        for position, name in enumerate(
            ["참치", "감자", "당근", "양파", "치즈", "마늘", "김치"], start=1
        ):
            conn.execute(
                "INSERT INTO ingredients (recipe_id, position, name, raw_text) VALUES (?, ?, ?, ?)",
                (recipe_id, position, name, name),
            )
        conn.commit()
        _, results = recommend(conn, "참치", max_missing=2)

    assert results[0].name == "참치 요리 5가지"
    assert "제목의 주재료와 직접 일치" in results[0].reason


def test_broad_pumpkin_query_finds_zucchini_even_with_many_missing_items(tmp_path) -> None:
    with connect(tmp_path / "recipes.sqlite") as conn:
        initialize(conn)
        _seed(conn)
        conn.execute(
            "INSERT INTO videos (video_id, title, url, status) VALUES ('stew', '매콤한 찌개', 'https://youtu.be/stew', 'completed')"
        )
        recipe_id = conn.execute(
            """
            INSERT INTO recipes (video_id, name, confidence, needs_review, source_kind)
            VALUES ('stew', '매콤한 찌개', 0.9, 0, 'description')
            """
        ).lastrowid
        for position, name in enumerate(
            ["애호박", "두부", "버섯", "양파", "대파", "고추장", "멸치액젓"], start=1
        ):
            conn.execute(
                "INSERT INTO ingredients (recipe_id, position, name, raw_text) VALUES (?, ?, ?, ?)",
                (recipe_id, position, name, name),
            )
        conn.commit()
        parsed, results = recommend(conn, "호박", max_missing=2)

    assert parsed == ["호박"]
    assert results[0].name == "매콤한 찌개"
    assert results[0].matched_ingredients == ["애호박"]
    assert "호박 재료군인 애호박" in results[0].reason


def test_specific_zucchini_query_does_not_match_sweet_pumpkin(tmp_path) -> None:
    with connect(tmp_path / "recipes.sqlite") as conn:
        initialize(conn)
        _seed(conn)
        conn.execute(
            "INSERT INTO videos (video_id, title, url, status) VALUES ('pumpkin', '단호박찜', 'https://youtu.be/pumpkin', 'completed')"
        )
        recipe_id = conn.execute(
            """
            INSERT INTO recipes (video_id, name, confidence, needs_review, source_kind)
            VALUES ('pumpkin', '단호박찜', 0.9, 0, 'description')
            """
        ).lastrowid
        conn.execute(
            "INSERT INTO ingredients (recipe_id, position, name, raw_text) VALUES (?, 1, '단호박', '단호박')",
            (recipe_id,),
        )
        conn.commit()
        parsed, results = recommend(conn, "애호박", max_missing=5)

    assert parsed == ["애호박"]
    assert all(result.name != "단호박찜" for result in results)

