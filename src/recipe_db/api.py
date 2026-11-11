from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import connect, initialize
from .pipeline import recipe_as_dict
from .recommender import answer_recommendation, recommend


class RecommendationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=30, ge=1, le=50)
    assume_pantry: bool = True
    max_missing: int | None = Field(default=5, ge=0, le=30)


def create_app(db_path: str | Path | None = None) -> FastAPI:
    resolved_db = Path(db_path or os.environ.get("RECIPE_DB_PATH", "data/recipes.sqlite"))
    web_dir = Path(__file__).with_name("web")
    api = FastAPI(title="냉장고 레시피 추천기", version="0.2.0")
    api.mount("/static", StaticFiles(directory=web_dir), name="static")

    @api.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @api.get("/api/health")
    def health() -> dict[str, object]:
        with connect(resolved_db) as conn:
            initialize(conn)
            recipes = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE status = 'pending'"
            ).fetchone()[0]
        return {"status": "ok", "recipes": recipes, "pending_videos": pending}

    @api.post("/api/recommend")
    def recommendations(request: RecommendationRequest) -> dict[str, object]:
        with connect(resolved_db) as conn:
            initialize(conn)
            ingredients, results = recommend(
                conn,
                request.message,
                limit=request.limit,
                assume_pantry=request.assume_pantry,
                max_missing=request.max_missing,
            )
        return {
            "query": request.message,
            "parsed_ingredients": ingredients,
            "answer": answer_recommendation(ingredients, results),
            "results": [item.to_dict() for item in results],
        }

    @api.get("/api/recipes/{recipe_id}")
    def recipe(recipe_id: int) -> dict[str, object]:
        with connect(resolved_db) as conn:
            initialize(conn)
            try:
                return recipe_as_dict(conn, recipe_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Recipe not found") from exc

    return api


app = create_app()

