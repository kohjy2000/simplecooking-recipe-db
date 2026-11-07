const form = document.querySelector("#recommend-form");
const response = document.querySelector("#response");
const results = document.querySelector("#results");
const answer = document.querySelector("#answer");
const parsed = document.querySelector("#parsed");

const escapeHtml = (value) => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const chip = (name, missing = false) =>
  `<span class="chip${missing ? " missing" : ""}">${escapeHtml(name)}</span>`;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "찾는 중…";
  results.innerHTML = "";
  try {
    const request = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: document.querySelector("#ingredients").value,
        assume_pantry: document.querySelector("#pantry").checked,
      }),
    });
    if (!request.ok) throw new Error("추천 요청에 실패했습니다.");
    const data = await request.json();
    response.hidden = false;
    answer.textContent = data.answer;
    parsed.textContent = `인식한 재료: ${data.parsed_ingredients.join(", ") || "없음"}`;
    results.innerHTML = data.results.map((item) => `
      <article class="card">
        <div class="card-top">
          <h2>${escapeHtml(item.name)}</h2>
          <span class="score">일치 ${Math.round(item.coverage * 100)}%</span>
        </div>
        <p class="reason">${escapeHtml(item.reason)}</p>
        <div class="chips">
          ${item.matched_ingredients.map((name) => chip(`✓ ${name}`)).join("")}
          ${item.missing_ingredients.map((name) => chip(`+ ${name}`, true)).join("")}
        </div>
        <div>
          <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">원본 영상 보기 ↗</a>
          ${item.needs_review ? '<span class="review"> · 자동 추출 결과, 검수 필요</span>' : ""}
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

