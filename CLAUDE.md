# 프로젝트 가이드 (Claude Code용)

GitHub Actions가 하루 4회(🌅07:00 밤사이 미국장 + 한국장 🟢09:10 개장·🟡12:30 장중·🔴15:40 마감) **반도체 중심** 증시 분석을 생성해 GitHub Pages로 배포하는 프로젝트. 마감엔 한국 심층 리포트 + 미국 반도체 연결 분석까지.
라이브: https://moriochoradio.github.io/stock-briefing/

## 구조

- `scripts/fetch_data.py` — yfinance 시세 + Google News RSS 수집 → `data.json`, 히스토리를 `site/src/data/history.json`에 누적
- `scripts/generate.py` — 모닝 브리핑(밤사이 미국장). LLM(기본 Gemini 2.5 Flash + thinking, 옵션 Claude Opus 4.8) → `briefings/YYYY-MM-DD.md`. 엔진 선택은 `config.yaml`의 `llm.provider`. 엔진 호출은 `run_llm()`로 분리(인트라데이와 공유). 시세+시장분위기(공포탐욕·섹터)+뉴스 주입.
- `scripts/intraday_kr.py` — **한국장 인트라데이**(개장/장중/마감) 점검. PHASE=open|mid|close. 삼성·SK하이닉스 지표 + LLM 분석 → `site/src/data/intraday.json`(당일 타임라인 누적, 날짜 바뀌면 리셋). close는 풀 심층 리포트 + **미국 반도체 연결 분석**(`PRIMARY`/`US_SEMI`). LLM이 폴백이면 **기존 실제 분석을 보존**(다운그레이드 방지). 시세는 yfinance(한국 ~15~20분 지연).
- `scripts/ta.py` — 공유 기술적 지표(RSI·MACD·ATR·SMA·BB·추세판정). `compute_metrics(df)`. (`deep_report.py`도 이걸 import — 중복 금지.)
- `scripts/deep_report.py` — 로컬용 단발 심층 리포트(차트 PNG 포함, matplotlib). `reports/`는 gitignore.
- `site/` — Astro 5 + Tailwind 4 + lightweight-charts + Lucide. 정적 빌드 → GitHub Pages. 메인 컴포넌트: `Hero.astro`(시점 반응형, `data-phase`를 브라우저 KST로 보정) · `IntradayTimeline.astro`(intraday.json) · `StockCharts.astro`(series.json 인터랙티브 차트) · `UsSemiReport.astro`(intraday.json의 `us_semi`).
- `.github/workflows/daily.yml` — cron 22:00 UTC(07:00 KST), 모닝 브리핑.
- `.github/workflows/intraday_kr.yml` — cron 00:10/03:30/06:40 UTC(09:10/12:30/15:40 KST, 평일), `github.event.schedule`로 PHASE 매핑. intraday.json 커밋 후 재배포. 둘 다 `pages` concurrency 공유.

## 반드시 지킬 규칙

1. **push 전에 항상 `git pull --rebase origin main`** — Actions 봇이 매일 원격에 커밋하므로 그냥 push하면 거부됨. 충돌 시 `briefings/`와 `site/src/data/history.json`은 원격(봇) 버전 우선.
2. **base 경로 유지** — `astro.config.mjs`의 `BASE_PATH`/`SITE_URL` 환경변수 구조와 내부 링크의 base 처리(`import.meta.env.BASE_URL` + 트레일링 슬래시 보정)를 깨뜨리지 말 것.
3. **완전 무료 운영** — 기본 엔진은 Gemini 무료 티어. 실행(GitHub Actions)·호스팅(GitHub Pages)도 무료, 정적 빌드 유지. 새 유료 서버·DB 추가 금지. (Claude Opus 4.8 옵션은 유료 API — Claude MAX 구독과 별도 결제 — 이며 `config.yaml` `provider: anthropic`로 켠다.)
4. **검증 후 커밋** — 사이트 변경 시 `cd site && npm install && npm run build` 통과 확인. 스크립트 변경 시 `python -m py_compile`.
5. 시세 카드·차트는 데이터가 쌓여야 표시됨 — 데이터 없다고 버그 아님.
6. **워크플로 파일 push엔 `workflow` 스코프** 필요 — `.github/workflows/*` 수정 후 push가 거부되면 `gh auth refresh -s workflow`.
7. **LLM 견고성 유지** — 엔진 호출은 `run_llm()`(재시도·엔진 폴백). 인트라데이는 LLM 폴백 시 기존 실제 분석 보존. 이 안전장치를 깨지 말 것.

## 자주 하는 작업

- 관심종목·뉴스 키워드·LLM 엔진(`provider`)·모델·thinking 예산: `config.yaml`
- 한국 심층/미국 분석 대상 종목: `scripts/intraday_kr.py`의 `PRIMARY`/`US_SEMI`
- 브리핑·인트라데이 톤·구성(프롬프트): `scripts/generate.py`, `scripts/intraday_kr.py`
- 점검 시각: `intraday_kr.yml`/`daily.yml` cron (UTC = KST−9h)
- 인터랙티브 차트 대상: `site/src/components/StockCharts.astro`의 `TARGETS`
