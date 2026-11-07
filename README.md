# 자취요리신 레시피 DB

YouTube 채널 **자취요리신 simple cooking**의 공개 영상에서 제목, 설명, 한국어 자막을 읽고
레시피를 구조화하는 증분 수집기입니다. 영상과 오디오는 다운로드하거나 보관하지 않습니다.

기본 채널: <https://www.youtube.com/@자취요리신simplecooking>

## 동작 방식

1. 채널의 영상 목록을 발견해 `videos` 테이블에 저장합니다.
2. 게시일이 오래된 영상부터 아직 처리하지 않은 영상을 선택합니다.
3. 설명과 한국어 자막에서 재료, 분량, 조리 단계를 추출합니다.
4. SQLite와 JSON/CSV 내보내기를 갱신합니다.
5. 실패한 영상은 최대 3회 재시도하고, 품질이 낮은 결과는 `needs_review=1`로 표시합니다.

원문 자막 전체는 DB에 저장하지 않습니다. 추출된 레시피와 원본 영상 URL만 저장하므로 결과를
검수하고 출처로 돌아갈 수 있습니다.

## 빠른 시작

```bash
uv sync --frozen
uv run recipe-db init
uv run recipe-db ingest --max-new 10
uv run recipe-db status
```

생성 파일:

- `data/recipes.sqlite`: 정규화된 SQLite 데이터베이스
- `exports/recipes.json`: 서비스/API용 JSON
- `exports/recipes.csv`: 스프레드시트용 CSV (UTF-8 BOM)

## GitHub Actions

`Ingest recipes` 워크플로는 매일 03:17 UTC에 최대 10개의 영상을 오래된 순으로 처리합니다.
GitHub의 **Actions → Ingest recipes → Run workflow**에서 한 번에 처리할 영상 수를 바꿔 수동 실행할
수도 있습니다. 실행 후 DB와 내보내기 파일을 커밋하고, 동일 파일을 30일 보관 아티팩트로 올립니다.

YouTube가 인증을 요구하면 저장소 Secret에 쿠키 파일 자체를 넣지 마세요. 로컬에서는
`YTDLP_COOKIES_FILE`에 Netscape 형식 쿠키 파일 경로를 지정할 수 있습니다. GitHub Actions의 인증
방식은 계정과 플랫폼 정책을 확인한 뒤 별도로 구성하는 편이 안전합니다.

## 스키마

- `videos`: 원본 영상, 처리 상태, 재시도 및 오류
- `recipes`: 영상별 레시피, 신뢰도, 검수 필요 여부
- `ingredients`: 순서가 있는 재료/분량/단위/섹션
- `steps`: 순서가 있는 조리 단계
- `ingestion_runs`: 실행별 발견/처리/성공/실패 통계

## 품질과 주의사항

- 자동 자막 오류와 자유 형식 설명 때문에 완전 자동 추출은 오차가 있습니다.
- `needs_review=1`인 레시피는 원본 URL과 대조해 검수하세요.
- 공개 데이터 접근과 사용은 YouTube 이용약관 및 콘텐츠 권리를 준수해야 합니다.
- 코드 라이선스와 원본 영상 콘텐츠의 권리는 별개입니다.

