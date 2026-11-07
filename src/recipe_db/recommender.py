from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass

from .pipeline import recipe_as_dict

ALIASES = {
    "달걀": "계란",
    "에그": "계란",
    "파": "대파",
    "쪽파": "대파",
    "다진마늘": "마늘",
    "다진 마늘": "마늘",
    "마늘가루": "마늘",
    "콘": "옥수수",
    "스위트콘": "옥수수",
    "모짜렐라": "치즈",
    "모짜렐라치즈": "치즈",
    "햇반": "밥",
    "즉석밥": "밥",
    "찬밥": "밥",
    "흰밥": "밥",
    "참치캔": "참치",
    "캔참치": "참치",
    "스팸": "햄",
    "리챔": "햄",
    "비엔나": "소시지",
    "비엔나소시지": "소시지",
    "고추가루": "고춧가루",
    "진간장": "간장",
    "양조간장": "간장",
    "국간장": "간장",
    "올리브오일": "올리브유",
    "오일": "식용유",
}

PANTRY_STAPLES = {
    "물",
    "소금",
    "후추",
    "설탕",
    "식용유",
    "참기름",
    "간장",
    "식초",
    "고춧가루",
}

STOP_WORDS = {
    "냉장고",
    "재료",
    "지금",
    "현재",
    "집에",
    "있어",
    "있어요",
    "있는데",
    "있음",
    "남았어",
    "남았어요",
    "가지고",
    "갖고",
    "이걸로",
    "요리",
    "레시피",
    "추천",
    "추천해줘",
    "추천해",
    "만들어",
    "만들",
    "수",
    "있는",
    "뭐",
    "무엇",
}

PARTICLE_SUFFIXES = (
    "으로는",
    "이랑",
    "하고",
    "으로",
    "에서",
    "부터",
    "까지",
    "랑",
    "이나",
    "나",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "도",
    "와",
    "과",
    "로",
    "에",
)


@dataclass(frozen=True)
class Recommendation:
    recipe_id: int
    video_id: str
    name: str
    source_url: str
    thumbnail_url: str | None
    matched_ingredients: list[str]
    pantry_ingredients: list[str]
    missing_ingredients: list[str]
    coverage: float
    score: float
    can_make_now: bool
    confidence: float
    needs_review: bool
    reason: str
    steps: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def canonicalize_ingredient(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z가-힣 ]", "", value.lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    for suffix in PARTICLE_SUFFIXES:
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix) + 1:
            cleaned = cleaned[: -len(suffix)].strip()
            break
    compact = cleaned.replace(" ", "")
    return ALIASES.get(cleaned, ALIASES.get(compact, cleaned))


def parse_ingredient_query(message: str) -> list[str]:
    normalized = re.sub(r"(?:그리고|그거랑|이거랑)", ",", message.lower())
    normalized = re.sub(r"([가-힣]{2,})(?:이랑|랑|하고)(?=[가-힣])", r"\1,", normalized)
    chunks = re.split(r"[,/·+\n]|\s+", normalized)
    ingredients: list[str] = []
    for chunk in chunks:
        candidate = canonicalize_ingredient(chunk)
        if not candidate or candidate in STOP_WORDS or len(candidate) < 1:
            continue
        if candidate not in ingredients:
            ingredients.append(candidate)
    return ingredients


def _recipe_ingredients(conn: sqlite3.Connection, recipe_id: int) -> list[str]:
    result: list[str] = []
    for row in conn.execute(
        "SELECT name FROM ingredients WHERE recipe_id = ? ORDER BY position", (recipe_id,)
    ):
        ingredient = canonicalize_ingredient(row["name"])
        if ingredient and ingredient not in result:
            result.append(ingredient)
    return result


def recommend(
    conn: sqlite3.Connection,
    message: str,
    *,
    limit: int = 10,
    assume_pantry: bool = True,
    max_missing: int | None = 5,
) -> tuple[list[str], list[Recommendation]]:
    available_list = parse_ingredient_query(message)
    available = set(available_list)
    assumed_pantry = PANTRY_STAPLES if assume_pantry else set()
    effective_available = available | assumed_pantry
    results: list[Recommendation] = []

    recipe_rows = conn.execute(
        """
        SELECT r.recipe_id, r.video_id, r.name, r.confidence, r.needs_review,
               v.url AS source_url, v.thumbnail_url
        FROM recipes r JOIN videos v ON v.video_id = r.video_id
        ORDER BY r.recipe_id
        """
    ).fetchall()
    for row in recipe_rows:
        recipe_ingredients = _recipe_ingredients(conn, row["recipe_id"])
        if not recipe_ingredients:
            continue
        ingredient_set = set(recipe_ingredients)
        user_matches = ingredient_set & available
        pantry_matches = (ingredient_set & assumed_pantry) - user_matches
        missing = ingredient_set - effective_available
        if not user_matches:
            continue
        if max_missing is not None and len(missing) > max_missing:
            continue

        non_pantry = ingredient_set - PANTRY_STAPLES
        relevant_matches = len(non_pantry & available)
        coverage = min((relevant_matches + len(pantry_matches)) / len(ingredient_set), 1.0)
        input_utilization = len(user_matches) / max(len(available), 1)
        confidence = float(row["confidence"])
        can_make_now = not missing
        score = (
            coverage * 0.55
            + min(len(user_matches) / 3, 1.0) * 0.15
            + input_utilization * 0.15
            + confidence * 0.15
            + (0.2 if can_make_now else 0)
        )
        matched_names = [item for item in recipe_ingredients if item in user_matches]
        pantry_names = [item for item in recipe_ingredients if item in pantry_matches]
        missing_names = [item for item in recipe_ingredients if item in missing]
        if can_make_now:
            reason = "보유 재료와 기본 양념만으로 만들 수 있어요."
        else:
            missing_summary = ", ".join(missing_names[:4]) + (
                f" 외 {len(missing_names) - 4}개" if len(missing_names) > 4 else ""
            )
            reason = (
                f"보유 재료 {len(matched_names)}개가 맞아요. "
                f"추가로 필요한 재료: {missing_summary}."
            )
        details = recipe_as_dict(conn, row["recipe_id"])
        results.append(
            Recommendation(
                recipe_id=row["recipe_id"],
                video_id=row["video_id"],
                name=row["name"],
                source_url=row["source_url"],
                thumbnail_url=row["thumbnail_url"],
                matched_ingredients=matched_names,
                pantry_ingredients=pantry_names,
                missing_ingredients=missing_names,
                coverage=round(coverage, 3),
                score=round(score, 3),
                can_make_now=can_make_now,
                confidence=confidence,
                needs_review=bool(row["needs_review"]),
                reason=reason,
                steps=details["steps"],
            )
        )

    results.sort(
        key=lambda item: (
            not item.can_make_now,
            len(item.missing_ingredients),
            -item.score,
            -len(item.matched_ingredients),
            item.name,
        )
    )
    return available_list, results[:limit]


def answer_recommendation(ingredients: list[str], results: list[Recommendation]) -> str:
    if not ingredients:
        return "보유한 재료를 쉼표로 구분해 입력해 주세요."
    if not results:
        return (
            f"{', '.join(ingredients)}로 찾았지만 맞는 레시피가 아직 없습니다. "
            "DB 수집이 진행되면 추천 범위가 넓어집니다."
        )
    ready = [item for item in results if item.can_make_now]
    if ready:
        names = ", ".join(item.name for item in ready[:3])
        return f"지금 재료로 바로 만들 수 있는 요리는 {names}입니다."
    top = results[0]
    return f"가장 가까운 추천은 {top.name}입니다. {top.reason}"

