# 프로젝트 가이드 (Claude Code용)

매일 07:00 KST에 GitHub Actions가 미국·한국 증시 브리핑을 생성해 GitHub Pages로 배포하는 프로젝트.
라이브: https://moriochoradio.github.io/stock-briefing/

## 구조

- `scripts/fetch_data.py` — yfinance 시세 + Google News RSS 수집 → `data.json`, 히스토리를 `site/src/data/history.json`에 누적
- `scripts/generate.py` — LLM(기본 Gemini 2.5 Flash + thinking, 옵션 Claude Opus 4.8)으로 브리핑 작성 → `briefings/YYYY-MM-DD.md`. 엔진 선택은 `config.yaml`의 `llm.provider`. 시세+시장분위기(공포탐욕·섹터)+뉴스를 프롬프트에 주입.
- `site/` — Astro 5 + Tailwind 4 + lightweight-charts + Lucide. 정적 빌드 → GitHub Pages
- `.github/workflows/daily.yml` — cron 22:00 UTC, 봇이 briefings/history를 커밋 후 사이트 빌드·배포

## 반드시 지킬 규칙

1. **push 전에 항상 `git pull --rebase origin main`** — Actions 봇이 매일 원격에 커밋하므로 그냥 push하면 거부됨. 충돌 시 `briefings/`와 `site/src/data/history.json`은 원격(봇) 버전 우선.
2. **base 경로 유지** — `astro.config.mjs`의 `BASE_PATH`/`SITE_URL` 환경변수 구조와 내부 링크의 base 처리(`import.meta.env.BASE_URL` + 트레일링 슬래시 보정)를 깨뜨리지 말 것.
3. **완전 무료 운영** — 기본 엔진은 Gemini 무료 티어. 실행(GitHub Actions)·호스팅(GitHub Pages)도 무료, 정적 빌드 유지. 새 유료 서버·DB 추가 금지. (Claude Opus 4.8 옵션은 유료 API — Claude MAX 구독과 별도 결제 — 이며 `config.yaml` `provider: anthropic`로 켠다.)
4. **검증 후 커밋** — 사이트 변경 시 `cd site && npm install && npm run build` 통과 확인.
5. 시세 카드·차트는 `history.json`이 2일 이상 쌓여야 표시됨 — 데이터 없다고 버그 아님.

## 자주 하는 작업

- 관심종목/뉴스 키워드 변경: `config.yaml`
- 브리핑 톤·구성: `scripts/generate.py`의 `PROMPT_TEMPLATE`
- 실행 시간: `daily.yml` cron (UTC = KST−9h)
