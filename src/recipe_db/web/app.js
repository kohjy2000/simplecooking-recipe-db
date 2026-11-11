const form = document.querySelector("#recommend-form");
const response = document.querySelector("#response");
const results = document.querySelector("#results");
const answer = document.querySelector("#answer");
const parsed = document.querySelector("#parsed");
const buildVersion = document.querySelector('meta[name="app-build"]')?.content || "local";

const aliases = {
  달걀: "계란", 에그: "계란", 파: "대파", 쪽파: "대파", 다진마늘: "마늘",
  콘: "옥수수", 스위트콘: "옥수수", 모짜렐라: "치즈", 햇반: "밥",
  즉석밥: "밥", 찬밥: "밥", 흰밥: "밥", 참치캔: "참치", 캔참치: "참치",
  스팸: "햄", 리챔: "햄", 비엔나: "소시지", 고추가루: "고춧가루",
  진간장: "간장", 양조간장: "간장", 국간장: "간장", 올리브오일: "올리브유",
  오일: "식용유", 쥬키니: "주키니", 치킨: "닭",
};
const ingredientFamilies = {
  호박: new Set(["호박", "애호박", "단호박", "주키니"]),
  닭: new Set(["닭", "닭고기", "닭가슴살", "닭다리살", "닭다리", "닭봉", "닭날개", "통닭"]),
};
const preparationPrefixes = ["익힌 ", "삶은 ", "구운 ", "냉동 ", "생 ", "통"];
const cutSuffixes = [" 정육", "정육", "고기", "살"];
const pantryStaples = new Set([
  "물", "소금", "후추", "설탕", "식용유", "참기름", "간장", "식초", "고춧가루",
]);
const stopWords = new Set([
  "냉장고", "재료", "지금", "현재", "집", "있어", "있어요", "있는데", "있음",
  "남았어", "남았어요", "가지고", "갖고", "이걸로", "요리", "레시피", "추천",
  "추천해줘", "추천해", "만들어", "만들", "수", "있는", "뭐", "무엇",
]);
const suffixes = [
  "으로는", "이랑", "하고", "으로", "에서", "부터", "까지", "랑", "이나", "은",
  "는", "이", "가", "을", "를", "도", "와", "과", "로", "에",
];

const escapeHtml = (value) => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const canonicalize = (value) => {
  let cleaned = String(value).toLowerCase().replace(/[([{].*?[)\]}]/g, " ")
    .replace(/[^0-9a-zA-Z가-힣 ]/g, "").trim();
  cleaned = cleaned.replace(/\s+/g, " ");
  cleaned = cleaned.replace(/\s*\d+(?:\.\d+)?\s*(?:kg|g|mg|ml|l|개|캔|봉|팩|큰술|작은술|스푼|컵)\s*$/i, "").trim();
  for (const suffix of suffixes) {
    if (cleaned.endsWith(suffix) && cleaned.length > suffix.length + 1) {
      cleaned = cleaned.slice(0, -suffix.length).trim();
      break;
    }
  }
  return aliases[cleaned] || aliases[cleaned.replaceAll(" ", "")] || cleaned;
};

const parseIngredients = (message) => {
  const normalized = message.toLowerCase()
    .replace(/(?:그리고|그거랑|이거랑)/g, ",")
    .replace(/([가-힣]{2,})(?:이랑|랑|하고)(?=[가-힣])/g, "$1,");
  const values = normalized.split(/[,/·+\n]|\s+/).map(canonicalize)
    .filter((item) => item && !stopWords.has(item));
  return [...new Set(values)];
};

const titleMatches = (title, available) => {
  const compact = title.toLowerCase().replaceAll(" ", "");
  return available.filter((ingredient) => {
    const terms = [ingredient, ...Object.entries(aliases)
      .filter(([alias, canonical]) => canonical === ingredient && alias.length > 1)
      .map(([alias]) => alias), ...(ingredientFamilies[ingredient] || [])];
    return terms.some((term) => compact.includes(term.replaceAll(" ", "")));
  });
};

const ingredientForms = (value) => {
  const forms = new Set([value.trim()]);
  let changed = true;
  while (changed) {
    changed = false;
    [...forms].forEach((form) => {
      preparationPrefixes.forEach((prefix) => {
        if (form.startsWith(prefix) && form.length - prefix.length >= 2) {
          const reduced = form.slice(prefix.length).trim();
          if (!forms.has(reduced)) {
            forms.add(reduced);
            changed = true;
          }
        }
      });
      cutSuffixes.forEach((suffix) => {
        if (form.endsWith(suffix) && form.length - suffix.length >= 2) {
          const reduced = form.slice(0, -suffix.length).trim();
          if (!forms.has(reduced)) {
            forms.add(reduced);
            changed = true;
          }
        }
      });
    });
  }
  return forms;
};

const ingredientsEquivalent = (left, right) => {
  const rightForms = ingredientForms(right);
  return [...ingredientForms(left)].some((form) => rightForms.has(form));
};

const ingredientIsAvailable = (ingredient, available) => [...available]
  .some((query) => ingredientsEquivalent(ingredient, query))
  || Object.entries(ingredientFamilies).some(([family, members]) => available.has(family)
    && [...members].some((member) => ingredient === member
      || (member.length > 1 && ingredient.includes(member))));

const subjectParticle = (value) => {
  const last = value.slice(-1);
  return last >= "가" && last <= "힣" && (last.charCodeAt(0) - "가".charCodeAt(0)) % 28 ? "이" : "가";
};

let staticRecipes;
const recommendInBrowser = async (message, assumePantry) => {
  if (!staticRecipes) {
    const curatedRequest = await fetch(
      `./curated_recipes.json?v=${encodeURIComponent(buildVersion)}`,
    );
    if (!curatedRequest.ok) {
      throw new Error("레시피 데이터를 불러오지 못했습니다.");
    }
    staticRecipes = await curatedRequest.json();
  }
  const ingredients = parseIngredients(message);
  const available = new Set(ingredients);
  const assumed = assumePantry ? pantryStaples : new Set();
  const effective = new Set([...available, ...assumed]);

  const recommendations = staticRecipes.map((recipe) => {
    const names = [...new Set(recipe.ingredients.map((item) => canonicalize(item.name)).filter(Boolean))];
    const exactMatches = names.filter((name) => [...available]
      .some((query) => ingredientsEquivalent(name, query)));
    const matched = names.filter((name) => ingredientIsAvailable(name, available));
    const pantry = names.filter((name) => !matched.includes(name)
      && ingredientIsAvailable(name, assumed));
    const missing = names.filter((name) => !ingredientIsAvailable(name, effective));
    const headingMatches = titleMatches(recipe.name, ingredients);
    const familyMatches = ingredients.filter((ingredient) => ingredientFamilies[ingredient]
      && names.some((name) => [...ingredientFamilies[ingredient]].some((member) => name === member
        || (member.length > 1 && name.includes(member)))));
    const coverage = Math.min((matched.length + pantry.length) / Math.max(names.length, 1), 1);
    const inputUse = Math.min(matched.length / Math.max(ingredients.length, 1), 1);
    const score = coverage * .35 + (headingMatches.length / Math.max(ingredients.length, 1)) * .25
      + Math.min(matched.length / 3, 1) * .15 + inputUse * .1 + recipe.confidence * .15
      + (missing.length === 0 ? .2 : 0);
    const missingSummary = `${missing.slice(0, 4).join(", ")}${missing.length > 4 ? ` 외 ${missing.length - 4}개` : ""}`;
    const directReason = headingMatches.length
      ? `${headingMatches.join(", ")}${subjectParticle(headingMatches.join(", "))} 요리 제목의 주재료와 직접 일치해요.${/\d+\s*(?:가지|개)/.test(recipe.name) ? " 여러 레시피를 묶은 영상이라 재료 목록은 전체 요리의 합계예요." : ""}`
      : null;
    const familyReason = familyMatches.length
      ? `${familyMatches.join(", ")} 재료군인 ${matched.join(", ")}이 들어 있어요.`
      : null;
    return {
      ...recipe,
      matched_ingredients: matched,
      pantry_ingredients: pantry,
      missing_ingredients: missing,
      title_matched_ingredients: headingMatches,
      coverage,
      score,
      can_make_now: missing.length === 0,
      reason: missing.length === 0
        ? "보유 재료와 기본 양념만으로 만들 수 있어요."
        : directReason || familyReason || `보유 재료 ${matched.length}개가 맞아요. 추가로 필요한 재료: ${missingSummary}.`,
      exact_matches: exactMatches,
      family_matches: familyMatches,
    };
  }).filter((item) => item.matched_ingredients.length > 0
    && (item.title_matched_ingredients.length > 0
      || item.exact_matches.length > 0
      || item.family_matches.length > 0
      || item.missing_ingredients.length <= 5));

  recommendations.sort((a, b) => b.title_matched_ingredients.length - a.title_matched_ingredients.length
    || Number(b.can_make_now) - Number(a.can_make_now)
    || b.score - a.score
    || a.missing_ingredients.length - b.missing_ingredients.length);
  const selected = recommendations.slice(0, 30);
  let responseText;
  if (!ingredients.length) responseText = "보유한 재료를 쉼표로 구분해 입력해 주세요.";
  else if (!selected.length) responseText = `${ingredients.join(", ")}로 찾았지만 맞는 레시피가 아직 없습니다.`;
  else if (selected.some((item) => item.can_make_now)) {
    responseText = `지금 재료로 바로 만들 수 있는 요리는 ${selected.filter((item) => item.can_make_now).slice(0, 3).map((item) => item.name).join(", ")}입니다.`;
  } else responseText = `가장 가까운 추천은 ${selected[0].name}입니다. ${selected[0].reason}`;
  return { parsed_ingredients: ingredients, answer: responseText, results: selected };
};

const requestRecommendations = async (message, assumePantry) => {
  try {
    const request = await fetch("./api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, assume_pantry: assumePantry }),
    });
    if (request.ok) return await request.json();
  } catch (_) {
    // The static GitHub Pages build intentionally has no API server.
  }
  return recommendInBrowser(message, assumePantry);
};

const chip = (name, missing = false) =>
  `<span class="chip${missing ? " missing" : ""}">${escapeHtml(name)}</span>`;

const ingredientText = (ingredient) => {
  const quantity = [ingredient.amount, ingredient.unit].filter(Boolean).join("");
  const note = ingredient.note ? ` · ${ingredient.note}` : "";
  return `${ingredient.name}${quantity ? ` ${quantity}` : ""}${note}`;
};

const recipeText = (item, index) => {
  if (!item.source_kind?.endsWith("_curated") || !item.steps?.length) return "";
  const ingredients = item.ingredients.map((ingredient) =>
    `<li>${escapeHtml(ingredientText(ingredient))}</li>`).join("");
  const steps = item.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("");
  const tips = (item.tips || []).map((tip) => `<li>${escapeHtml(tip)}</li>`).join("");
  return `
    <details class="recipe-copy"${index === 0 ? " open" : ""}>
      <summary>재료와 만드는 법 ${index === 0 ? "" : "펼쳐보기"}</summary>
      <div class="recipe-grid">
        <section>
          <h3>재료${item.servings ? ` · ${escapeHtml(item.servings)}인분` : ""}</h3>
          <ul class="ingredient-list">${ingredients}</ul>
        </section>
        <section>
          <h3>만드는 법</h3>
          <ol class="step-list">${steps}</ol>
        </section>
      </div>
      ${tips ? `<aside class="tip"><strong>조리 팁</strong><ul>${tips}</ul></aside>` : ""}
    </details>`;
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "찾는 중…";
  results.innerHTML = "";
  try {
    const data = await requestRecommendations(
      document.querySelector("#ingredients").value,
      document.querySelector("#pantry").checked,
    );
    response.hidden = false;
    answer.textContent = data.answer;
    parsed.textContent = `인식한 재료: ${data.parsed_ingredients.join(", ") || "없음"}`;
    results.innerHTML = data.results.map((item, index) => `
      <article class="card">
        <div class="card-top">
          <h2>${escapeHtml(item.name)}</h2>
          <span class="score">일치 ${Math.round(item.coverage * 100)}%</span>
        </div>
        ${item.summary ? `<p class="summary">${escapeHtml(item.summary)}</p>` : ""}
        <p class="reason">${escapeHtml(item.reason)}</p>
        <div class="chips">
          ${item.matched_ingredients.map((name) => chip(`✓ ${name}`)).join("")}
          ${item.missing_ingredients.slice(0, 5).map((name) => chip(`+ ${name}`, true)).join("")}
          ${item.missing_ingredients.length > 5 ? chip(`외 ${item.missing_ingredients.length - 5}개`, true) : ""}
        </div>
        ${recipeText(item, index)}
        <div>
          <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">원본 영상 보기 ↗</a>
          ${item.source_kind === "manually_curated" ? '<span class="curated"> · 영상 내용 직접 정리 완료</span>' : ""}
          ${item.source_kind === "automated_curated" ? '<span class="curated"> · 자동 정리·품질검사 완료</span>' : ""}
          ${item.needs_review ? '<span class="review"> · 재료 자동 추출 결과, 검수 필요</span>' : ""}
        </div>
      </article>
    `).join("");
  } catch (error) {
    response.hidden = false;
    answer.textContent = error.message;
    parsed.textContent = "";
  } finally {
    button.disabled = false;
    button.textContent = "추천받기";
  }
});

