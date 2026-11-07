from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

INGREDIENT_HEADERS = re.compile(
    r"^\s*[\[【(<]?(재료|준비물|양념|소스|육수|토핑|고명|ingredients?)[\]】)>:]?\s*$",
    re.IGNORECASE,
)
STEP_HEADERS = re.compile(
    r"^\s*[\[【(<]?(만드는\s*법|조리법|레시피|조리\s*순서|과정|방법|directions?|steps?)[\]】)>:]?\s*$",
    re.IGNORECASE,
)
SECTION_HEADER = re.compile(r"^\s*[\[【(<].{1,20}[\]】)>]\s*$")
NUMBERED_STEP = re.compile(r"^\s*(?:step\s*)?(\d{1,2})\s*[.)\-:]\s*(.+)$", re.IGNORECASE)
BULLET = re.compile(r"^\s*(?:[-*•·▪▫▶✓✔]|\d{1,2}\s*[.)])\s*(.+)$")
AMOUNT = re.compile(
    r"(?P<amount>\d+(?:[./]\d+)?(?:\s*[-~]\s*\d+(?:[./]\d+)?)?|[한두세네반약조금적당량]+)\s*"
    r"(?P<unit>kg|g|mg|ml|l|L|큰술|작은술|스푼|숟가락|컵|공기|개|쪽|장|대|줄기|줌|꼬집|봉|캔|팩|마리|인분|T|t)?\b",
    re.IGNORECASE,
)
ACTION_SENTENCE = re.compile(
    r"(넣|볶|끓|썰|굽|섞|익|데치|삶|부어|붓|재우|간하|다지|올리|담|튀기|졸이|무치|갈아|완성)"
)
NOISE = re.compile(r"(구독|좋아요|알림|문의|협찬|광고|instagram|인스타|copyright)", re.IGNORECASE)


@dataclass(frozen=True)
class Ingredient:
    name: str
    amount: str | None
    unit: str | None
    note: str | None
    raw_text: str
    section: str | None = None


@dataclass(frozen=True)
class ExtractedRecipe:
    name: str
    summary: str | None
    servings: str | None
    ingredients: list[Ingredient]
    steps: list[str]
    confidence: float
    needs_review: bool
    source_kind: str
    source_hash: str


def clean_title(title: str) -> str:
    title = re.sub(r"\s*[|｜].*$", "", title).strip()
    title = re.sub(r"\s*#[\w가-힣]+", "", title).strip()
    title = re.sub(r"\s*[([{【].{0,30}(?:레시피|만들기|recipe).{0,20}[)\]}】]", "", title, flags=re.IGNORECASE)
    return title or "이름 미상 레시피"


def _clean_line(line: str) -> str:
    line = re.sub(r"https?://\S+", "", line)
    line = BULLET.sub(r"\1", line)
    return re.sub(r"\s+", " ", line).strip(" \t:-–—")


def _parse_ingredient(line: str, section: str | None) -> Ingredient | None:
    raw = _clean_line(line)
    if not raw or len(raw) > 120 or NOISE.search(raw):
        return None
    match = AMOUNT.search(raw)
    if not match:
        return None
    before = raw[: match.start()].strip(" ,:/")
    after = raw[match.end() :].strip(" ,:/()")
    if not before:
        after_match = re.match(r"([^,(/]{1,40})", after)
        if not after_match:
            return None
        before = after_match.group(1).strip()
        after = after[after_match.end() :].strip(" ,:/()")
    if len(before) > 45 or ACTION_SENTENCE.search(before):
        return None
    return Ingredient(
        name=before,
        amount=match.group("amount"),
        unit=match.group("unit"),
        note=after or None,
        raw_text=raw,
        section=section,
    )


def _description_parts(description: str) -> tuple[list[Ingredient], list[str]]:
    ingredients: list[Ingredient] = []
    steps: list[str] = []
    mode: str | None = None
    section: str | None = None
    for original in description.splitlines():
        line = original.strip()
        if not line:
            continue
        ingredient_header = INGREDIENT_HEADERS.match(line)
        if ingredient_header:
            mode = "ingredients"
            section = ingredient_header.group(1)
            continue
        if STEP_HEADERS.match(line):
            mode = "steps"
            continue
        numbered = NUMBERED_STEP.match(line)
        if numbered and (mode == "steps" or ACTION_SENTENCE.search(numbered.group(2))):
            text = _clean_line(numbered.group(2))
            if text and not NOISE.search(text):
                steps.append(text)
                mode = "steps"
            continue
        if SECTION_HEADER.match(line):
            if mode == "ingredients":
                section = _clean_line(line).strip("[]【】()<> ")
            continue
        if mode == "ingredients" or BULLET.match(line):
            parsed = _parse_ingredient(line, section)
            if parsed:
                ingredients.append(parsed)
                continue
        if mode == "steps" and ACTION_SENTENCE.search(line):
            text = _clean_line(line)
            if 5 <= len(text) <= 220 and not NOISE.search(text):
                steps.append(text)
    return _dedupe_ingredients(ingredients), _dedupe(steps)[:30]


def _caption_steps(caption: str) -> list[str]:
    if not caption:
        return []
    candidates = re.split(r"(?<=[.!?。])\s+|\n+", caption)
    if len(candidates) < 3:
        candidates = re.split(r"\s+(?=(?:이제|그리고|다음|먼저|마지막으로))", caption)
    steps: list[str] = []
    for candidate in candidates:
        text = re.sub(r"\s+", " ", candidate).strip()
        if 8 <= len(text) <= 220 and ACTION_SENTENCE.search(text) and not NOISE.search(text):
            steps.append(text)
    return _dedupe(steps)[:30]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = re.sub(r"\W", "", value).lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _dedupe_ingredients(values: list[Ingredient]) -> list[Ingredient]:
    seen: set[tuple[str, str | None, str | None]] = set()
    result: list[Ingredient] = []
    for value in values:
        key = (value.name.lower(), value.amount, value.unit)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _servings(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d+\s*(?:~|-)?\s*\d*)\s*인분", text)
    return f"{match.group(1).replace(' ', '')}인분" if match else None


def extract_recipe(title: str, description: str, caption: str = "") -> ExtractedRecipe:
    ingredients, description_steps = _description_parts(description)
    caption_steps = _caption_steps(caption) if len(description_steps) < 2 else []
    steps = description_steps or caption_steps
    if caption_steps and (description_steps or ingredients):
        source_kind = "mixed"
    elif description_steps or ingredients:
        source_kind = "description"
    else:
        source_kind = "caption"
    ingredient_score = min(len(ingredients) / 6, 1.0)
    step_score = min(len(steps) / 5, 1.0)
    confidence = round(0.15 + 0.45 * ingredient_score + 0.4 * step_score, 2)
    needs_review = len(ingredients) < 2 or len(steps) < 2 or confidence < 0.65
    combined = f"{description}\n{caption}"
    summary_line = next(
        (
            _clean_line(line)
            for line in description.splitlines()
            if 15 <= len(_clean_line(line)) <= 160 and not NOISE.search(line)
        ),
        None,
    )
    return ExtractedRecipe(
        name=clean_title(title),
        summary=summary_line,
        servings=_servings(combined),
        ingredients=ingredients,
        steps=steps,
        confidence=confidence,
        needs_review=needs_review,
        source_kind=source_kind,
        source_hash=hashlib.sha256(combined.encode("utf-8")).hexdigest(),
    )

