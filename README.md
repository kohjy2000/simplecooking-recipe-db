# 냉장고 레시피 추천기

YouTube 채널 **자취요리신 simple cooking**의 공개 영상에서 제목, 설명, 한국어·영어 자막을 읽고
레시피를 구조화한 뒤, 보유 재료로 만들 수 있는 요리를 추천합니다. 영상과 오디오는 다운로드하거나
보관하지 않습니다. 공개 사이트에는 자동 정리와 품질검사를 모두 통과한 레시피만 표시합니다.

기본 채널: <https://www.youtube.com/@자취요리신simplecooking>

웹 앱: <https://kohjy2000.github.io/simplecooking-recipe-db/>

## 목표

사용자가 `계란이랑 양파, 김치가 있어`처럼 입력하면 다음 순서로 답합니다.

1. 자연어에서 재료를 찾아 `달걀 → 계란`, `콘 → 옥수수`처럼 정규화합니다.
2. 기본 양념 보유 여부를 반영해 각 레시피의 일치·부족 재료를 계산합니다.
3. 바로 만들 수 있는지, 부족 재료 수, 재료 일치율, 추출 신뢰도로 추천 순위를 정합니다.
4. 추천 이유와 원본 영상, 조리 단계를 함께 반환합니다.

재료 검색은 정확한 집합 연산이 임베딩 검색보다 신뢰하기 쉬우므로 현재 버전은 이를 우선 사용합니다.
향후 음식명·취향·조리 상황 같은 의미 검색을 벡터 검색으로 추가하면 하이브리드 RAG 구조가 됩니다.

## 동작 방식

1. 채널의 영상 목록을 발견해 `videos` 테이블에 저장합니다.
2. 게시일이 오래된 영상부터 아직 처리하지 않은 영상을 선택합니다.
3. 설명과 한국어 자막에서 원시 재료, 분량, 조리 단계를 추출합니다.
4. 로컬 공개 모델이 한국어·영어 자막을 함께 읽고, 한 영상에 여러 요리가 있으면 각각 분리합니다.
5. 레시피 개수, 재료 근거, 조리 단계 형식과 잡음 여부를 검사해 통과한 결과만 공개 DB에 넣습니다.
6. SQLite와 JSON/CSV 내보내기를 갱신하고 GitHub Pages를 재배포합니다.
7. 실패한 영상은 최대 3회 재시도하며, 통과하지 못한 결과는 공개하지 않습니다.

원문 자막 전체는 DB에 저장하지 않습니다. 추출된 레시피와 원본 영상 URL만 저장하므로 결과를
검수하고 출처로 돌아갈 수 있습니다.

YouTube가 익명 요청을 차단하면 여러 플레이어 클라이언트를 순서대로 재시도한 뒤 공개
Invidious API에서 영상 메타데이터와 자막을 가져옵니다. 대체 인스턴스는
`INVIDIOUS_BASE_URLS` 환경 변수에 쉼표로 구분해 지정할 수 있습니다.

## 빠른 시작

### Codex 클라우드 터미널에서 실행

```bash
cd /workspace/simplecooking-recipe-db
uv sync --frozen
uv run recipe-db serve
```

반드시 `pyproject.toml`이 있는 `/workspace/simplecooking-recipe-db` 안에서 실행해야 합니다.
클라우드 환경의 8000번 포트는 시스템 프로세스가 사용하므로 앱은 기본적으로 8765번 포트를 사용합니다.

### Mac에서 처음 실행

```bash
cd ~
gh repo clone kohjy2000/simplecooking-recipe-db
cd simplecooking-recipe-db
uv sync --frozen
uv run recipe-db serve
```

GitHub CLI가 없다면 `gh repo clone` 대신 다음 명령을 사용합니다.

```bash
git clone https://github.com/kohjy2000/simplecooking-recipe-db.git
```

실행 후 `http://127.0.0.1:8765`을 열면 웹 추천 화면을 사용할 수 있습니다.

다른 명령도 저장소 폴더 안에서 실행합니다.

```bash
uv run recipe-db init
uv run recipe-db ingest --max-new 10
uv run recipe-db curate --max-new 3
uv run recipe-db status
uv run recipe-db recommend "계란, 김치, 밥"
```

### 추천 API

```bash
curl -X POST http://127.0.0.1:8765/api/recommend \
  -H 'Content-Type: application/json' \
  -d '{"message":"계란이랑 김치, 밥이 있어요","assume_pantry":true}'
```

응답에는 인식한 재료, 자연어 답변, 추천 점수, 일치·부족 재료, 원본 영상과 조리 단계가 포함됩니다.

생성 파일:

- `data/recipes.sqlite`: 정규화된 SQLite 데이터베이스
- `exports/recipes.json`: 서비스/API용 JSON
- `exports/recipes.csv`: 스프레드시트용 CSV (UTF-8 BOM)
- `exports/curated_recipes.json`: 품질검사를 통과해 공개되는 레시피 JSON
- `exports/curation_state.json`: 영상별 자동 정리 성공·실패·재시도 상태

## GitHub Actions

`Ingest recipes` 워크플로는 매일 03:17 UTC에 최대 50개의 영상을 오래된 순으로 처리합니다.
GitHub의 **Actions → Ingest recipes → Run workflow**에서 한 번에 처리할 영상 수를 바꿔 수동 실행할
수도 있습니다. 실행 후 DB와 내보내기 파일을 커밋하고, 동일 파일을 30일 보관 아티팩트로 올립니다.

`Bulk curate all recipes` 워크플로는 매일 06:17 UTC에 실행됩니다. 별도 API 키나 OpenAI API 과금
없이 GitHub Actions에서 `qwen2.5:3b` 공개 모델을 최대 20개 작업으로 병렬 실행해 아직 공개되지 않은
원시 레시피 전체를 처리합니다. 제목·영상 설명·자막 원문 인용으로 재료 근거를 확인하며, 작업별 결과를
격리한 뒤 마지막 단계에서 하나의 공개 DB로 병합합니다. 근거가 약하거나 깨진 결과는 공개하지 않고
최대 3회까지 재시도합니다. 공개 레시피가 바뀔 때만 사이트를 자동 재배포합니다.

`Curate public recipes`는 특정 영상 재검수와 모델 비교를 위한 수동 실행용 워크플로로 유지합니다.

YouTube가 인증을 요구하면 저장소 Secret에 쿠키 파일 자체를 넣지 마세요. 로컬에서는
`YTDLP_COOKIES_FILE`에 Netscape 형식 쿠키 파일 경로를 지정할 수 있습니다. GitHub Actions의 인증
방식은 계정과 플랫폼 정책을 확인한 뒤 별도로 구성하는 편이 안전합니다.

## 스키마

- `videos`: 원본 영상, 처리 상태, 재시도 및 오류
- `recipes`: 영상별 레시피, 신뢰도, 검수 필요 여부
- `ingredients`: 순서가 있는 재료/분량/단위/섹션
- `steps`: 순서가 있는 조리 단계
- `ingestion_runs`: 실행별 발견/처리/성공/실패 통계

추천기는 공개용 `curated_recipes.json`의 재료를 조회 시점에 표준 재료명으로 정규화합니다.
소금·후추·식용유 등은 기본 양념으로 선택할 수 있습니다. 원시 자동 추출 자료는 내부 처리 큐로만
사용하며 공개 추천 결과에는 나타나지 않습니다.

## 품질과 주의사항

- 자동 자막 오류와 자유 형식 설명 때문에 자동 정리도 오차 가능성이 있습니다.
- 형식·근거 검사를 통과하지 못한 결과는 공개하지 않고 최대 3회 다시 처리합니다.
- 로컬 공개 모델은 별도 사용료가 없지만 GitHub Actions 실행 시간과 캐시 저장공간을 사용합니다.
- 공개 데이터 접근과 사용은 YouTube 이용약관 및 콘텐츠 권리를 준수해야 합니다.
- 코드 라이선스와 원본 영상 콘텐츠의 권리는 별개입니다.

