# 📈 반도체 중심 증시 트래커 (거의 무료 자동화)

[![Daily Stock Briefing](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/daily.yml/badge.svg)](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/daily.yml)
[![Korea Intraday](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/intraday_kr.yml/badge.svg)](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/intraday_kr.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

미국·한국 증시를 **하루 종일** 추적해 분석 리포트를 자동 생성·배포합니다. **반도체**(삼성전자·SK하이닉스 중심)에 집중하며, 한국장을 **장 시작·중간·종료**로 끊어 보고, 직전 **미국 반도체** 세션까지 연결지어 분석합니다.

**거의 0원 운영**: GitHub Actions(실행·무료) + Gemini 무료 티어(분석, thinking 켬) + GitHub Pages(호스팅·무료). 더 깊은 분석이 필요하면 `config.yaml`에서 Claude Opus 4.8(유료, 월 ~$3~4 · **Claude MAX 구독과는 별도 결제**)로 전환 가능.

🔗 **라이브**: https://moriochoradio.github.io/stock-briefing/

**기술 스택**: Python(yfinance, Google News RSS, pandas/numpy) · Gemini API(2.5 Flash, thinking) / Claude Opus 4.8(옵션) · Astro 5 · Tailwind CSS 4 · TradingView lightweight-charts · Lucide

## 하루 사이클 (KST, 평일)

| 시점 | 워크플로 | 내용 |
|---|---|---|
| 🌅 **07:00~** | `daily.yml` | 밤사이 **미국장** 모닝 브리핑 (화~토, 미국장 있는 날만) |
| 🟢 **09:30~11:00** | `intraday_kr.yml` (open) | 한국장 **개장** 스냅샷 |
| 🟡 **11:30~14:00** | `intraday_kr.yml` (mid) | **장중** 스냅샷 |
| 🔴 **15:35~** | `intraday_kr.yml` (close) | 한국장 **마감 심층 리포트** + **미국 반도체 연결 분석** |

> 개장·장중은 가벼운 스냅샷(시세·지표 변화·짧은 읽기), 마감은 풀 심층 리포트. GitHub cron은 혼잡 시 **수 시간까지 지연**될 수 있어, cron을 촘촘히 걸어두고 각 실행이 **실제 도착한 KST 시각**으로 phase(개장/장중/마감)를 스스로 판정합니다 — 구간 밖·중복·휴장(오늘 봉 없음)이면 LLM 호출 없이 즉시 스킵. 시세는 yfinance 기준 한국 주식 **약 15~20분 지연**입니다.

## 주요 화면 (메인)

- **시점 반응형 Hero** — 개장 전/오전장/오후장/마감/마감 후에 따라 하늘·해 색과 라벨이 바뀌고, 한국장 최신 시세를 반영 (브라우저에서 KST로 실시간 보정)
- **오늘 한국장 타임라인** — 개장→장중→마감 스냅샷이 하루 동안 채워지며, 삼성·SK하이닉스 기술적 지표(추세·RSI·MACD…) + LLM 분석
- **반도체 양대 추이** — 삼성·SK하이닉스 인터랙티브 차트(가격 + 이동평균 SMA20/60/120)
- **미국 반도체 연결** — 엔비디아·AMD·마이크론·TSMC·브로드컴·ASML + 필라델피아 반도체지수(SOX), 한국장과의 연결고리(디커플링·HBM 수요 등) 분석
- 그 외 — 오늘의 브리핑, 주요 헤드라인, 시장 분위기(공포·탐욕 지수), 관심종목 시세 카드, 지수 차트
- **대시보드** (`/dashboard`) — 벤토 그리드, 섹터 히트맵 · **아카이브** — 날짜별 과거 브리핑

## 동작 구조

**스크립트** (`scripts/`)
- `fetch_data.py` — yfinance 시세 + Google News RSS + CNN 공포·탐욕지수 수집 → `sentiment/series/news/history.json`
- `generate.py` — 모닝 브리핑 LLM 작성 → `briefings/날짜.md`. 엔진 호출은 `run_llm()`로 분리(재시도·엔진 폴백 내장, 인트라데이와 공유)
- `intraday_kr.py` — 한국장 개장/장중/마감 + (마감 시) 미국 반도체 분석 → `site/src/data/intraday.json`. LLM 실패해도 기존 실제 분석을 보존(다운그레이드 방지)
- `ta.py` — 공유 기술적 지표(RSI·MACD·ATR·SMA·볼린저·추세판정)
- `deep_report.py` — 로컬용 단발 심층 리포트(matplotlib 차트 PNG, `reports/`는 gitignore)

**워크플로** (`.github/workflows/`)
- `daily.yml` — 22:00 UTC(07:00 KST) 모닝 브리핑
- `intraday_kr.yml` — 30분 간격의 촘촘한 cron. PHASE는 스크립트가 실행 시점 KST로 자동 판정(`auto`) — cron 지연에도 라벨과 데이터가 어긋나지 않음. 캡처 없으면 커밋·빌드·배포 스킵
- 둘 다 `pages` concurrency 공유 + push 재시도 루프(동시 실행 경쟁 방지) + pip/npm 캐시

```
GitHub Actions → fetch/generate/intraday(Python) → *.json·*.md 커밋 → Astro 빌드 → GitHub Pages 배포
```

> 정기 실행(cron) 외에 **main에 코드를 push**하면 사이트가 재빌드·배포됩니다(데이터 수집·LLM은 건너뛰어 쿼터 절약).

## 배포 방법

1. **레포 만들기** — GitHub New repository → 이름 `stock-briefing`, **Public** (Actions 무료 무제한).
2. **코드 푸시**:
   ```bash
   cd stock-briefing-web
   git init && git add -A && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<아이디>/stock-briefing.git
   git push -u origin main
   ```
3. **Gemini API 키 발급 (무료, 카드 불필요)** — https://aistudio.google.com/apikey  ⚠️ 결제 등록 시 무료 티어가 사라짐.
   > 더 깊은 분석을 원하면 대신 **Anthropic 키**(https://console.anthropic.com/, 유료·월 ~$3~4 · Claude MAX 구독과 별도)를 발급하고 `config.yaml`의 `llm.provider`를 `"anthropic"`으로.
4. **시크릿 등록** — Settings → Secrets and variables → Actions → New repository secret
   - `GEMINI_API_KEY` (기본 엔진: Gemini 2.5 Flash)
   - (선택) `ANTHROPIC_API_KEY` + `config.yaml`의 `provider: anthropic` → Claude Opus 4.8
   - ⚠️ 워크플로 파일(`.github/workflows/`)을 수정·push하려면 토큰에 **`workflow` 스코프**가 필요합니다(`gh auth refresh -s workflow`).
5. **Pages 켜기** — Settings → Pages → Source: **GitHub Actions**.
6. **테스트 실행** — Actions 탭 → "Daily Stock Briefing" 또는 "Korea Intraday Snapshot"(입력 `phase`) → Run workflow → `https://<아이디>.github.io/stock-briefing/`.

## 커스터마이징

| 바꾸고 싶은 것 | 위치 |
|---|---|
| 관심종목·뉴스 키워드·LLM 엔진(`provider`)·모델·thinking 예산 | `config.yaml` |
| 점검 구간(개장/장중/마감) | `scripts/intraday_kr.py`의 `WINDOWS` (cron은 `intraday_kr.yml`, UTC = KST−9h) |
| 모닝 브리핑 시각 | `.github/workflows/daily.yml`의 cron |
| 브리핑·인트라데이 톤·구성(프롬프트) | `scripts/generate.py`, `scripts/intraday_kr.py` |
| 한국장 심층/미국 분석 대상 종목 | `scripts/intraday_kr.py`의 `PRIMARY`/`US_SEMI` |
| 사이트 디자인 | `site/src/` (Astro 컴포넌트·CSS) |

로컬 미리보기: `cd site && npm install && npm run dev` · 로컬 심층 리포트: `pip install -r requirements.txt && python scripts/deep_report.py`

## 참고

- 시세 카드·차트는 워크플로가 1회 이상 실행돼 데이터가 쌓이면 표시됩니다.
- 레포 이름을 `<아이디>.github.io`로 만들 경우 `daily.yml`의 `BASE_PATH`를 `"/"`로 수정.
- Gemini 무료 티어가 일시적으로 과부하(503)일 때가 있어, LLM 호출은 재시도(최대 6회)하고 그래도 실패하면 데이터 요약으로 안전하게 대체합니다(다음 실행에서 실제 분석으로 자동 복구).
- 본 리포트는 **투자 권유가 아닌 정보 제공**입니다. 데이터 출처: Yahoo Finance(yfinance), Google News, CNN Fear & Greed.

## 개발 (Claude Code)

이 레포는 [Claude Code](https://claude.com/claude-code)로 개발·유지보수합니다. 작업 규칙은 `CLAUDE.md` 참고.
핵심: **push 전 항상 `git pull --rebase`** (봇이 매일·장중 커밋하므로).

## 라이선스

[MIT](LICENSE)
