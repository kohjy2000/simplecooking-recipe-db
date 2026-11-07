from fastapi.testclient import TestClient
from test_recommender import _seed

from recipe_db.api import create_app
from recipe_db.db import connect, initialize


def test_recommendation_api(tmp_path) -> None:
    db_path = tmp_path / "recipes.sqlite"
    with connect(db_path) as conn:
        initialize(conn)
        _seed(conn)

    client = TestClient(create_app(db_path))
    response = client.post(
        "/api/recommend",
        json={"message": "계란, 김치, 밥", "assume_pantry": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parsed_ingredients"] == ["계란", "김치", "밥"]
    assert payload["results"][0]["name"] == "김치볶음밥"
    assert "바로 만들 수" in payload["answer"]

