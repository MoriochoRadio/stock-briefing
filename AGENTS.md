# 프로젝트 가이드 (에이전트용)

> **단일 소스: [`CLAUDE.md`](./CLAUDE.md)** — 상세 구조·규칙은 그쪽을 정본으로 따른다. 아래는 요약.

GitHub Actions가 하루 4회(🌅07:00 밤사이 미국장 + 한국장 🟢09:10 개장·🟡12:30 장중·🔴15:40 마감) **반도체 중심** 증시 분석을 생성해 GitHub Pages로 배포. 마감엔 한국 심층 리포트 + 미국 반도체 연결 분석.
라이브: https://moriochoradio.github.io/stock-briefing/

## 핵심 구조 (상세는 CLAUDE.md)

- `scripts/fetch_data.py` — 시세·뉴스·공포탐욕 수집 → `site/src/data/*.json`
- `scripts/generate.py` — 모닝 브리핑 LLM(`run_llm()` 공유, 재시도·폴백) → `briefings/*.md`
- `scripts/intraday_kr.py` — 한국장 개장/장중/마감 + 미국 반도체 분석 → `intraday.json` (폴백 시 기존 실제 분석 보존)
- `scripts/ta.py` — 공유 기술적 지표 (`deep_report.py`도 import)
- `site/` — Astro 5. `Hero`(시점 반응형) · `IntradayTimeline` · `StockCharts` · `UsSemiReport`
- `.github/workflows/` — `daily.yml`(모닝) · `intraday_kr.yml`(한국장 3회)

## 반드시 지킬 규칙

1. **push 전 `git pull --rebase origin main`** (봇이 매일·장중 커밋). 충돌 시 `briefings/`·`site/src/data/*.json`은 원격 우선.
2. **base 경로 유지** — `astro.config.mjs`의 `BASE_PATH`/`SITE_URL` 구조와 내부 링크 base 처리.
3. **저비용 운영** — 기본 Gemini 무료 티어, 실행·호스팅 무료. 새 유료 서버·DB 금지. (Claude Opus 4.8은 `config.yaml` `provider: anthropic` 옵션, 유료.)
4. **검증 후 커밋** — `cd site && npm run build` / 스크립트는 `python -m py_compile`.
5. **워크플로 파일 push엔 `workflow` 스코프** 필요 (`gh auth refresh -s workflow`).
6. **LLM 견고성 유지** — `run_llm()` 재시도·폴백, 인트라데이 다운그레이드 방지 안전장치를 깨지 말 것.
