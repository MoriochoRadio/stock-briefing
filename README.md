# 📈 매일 아침 주식시장 브리핑 (완전 무료 자동화)

매일 한국시간 오전 7시, 미국·한국 증시 맞춤 브리핑을 자동 생성해 대시보드 웹사이트로 배포합니다.
**서버·비용 0원**: GitHub Actions(실행) + Gemini 무료 티어(분석) + GitHub Pages(호스팅) + Astro(사이트).

## 동작 구조

```
GitHub Actions (매일 07:00 KST)
 ├─ fetch_data.py : yfinance 시세 + Google News RSS 수집, 시세 히스토리 누적 (무료, 키 불필요)
 ├─ generate.py   : Gemini가 데이터를 브리핑으로 분석·작성 → briefings/날짜.md 커밋
 ├─ Astro 빌드    : site/ → 시세 카드 + 지수 차트 + 브리핑 + 아카이브 페이지
 └─ GitHub Pages 배포 → https://<아이디>.github.io/<레포명>/
```

## 배포 방법 (10분)

1. **레포 만들기** — GitHub에서 New repository → 이름 `stock-briefing`, **Public** (Actions 무료 무제한).

2. **코드 푸시**:
   ```bash
   cd stock-briefing-web
   git init && git add -A && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<아이디>/stock-briefing.git
   git push -u origin main
   ```

3. **Gemini API 키 발급 (무료, 카드 불필요)** — https://aistudio.google.com/apikey
   ⚠️ 결제 등록하면 무료 티어가 사라지니 결제 등록하지 말 것.

4. **키 등록** — 레포 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `GEMINI_API_KEY`, Value: 발급받은 키
   - (선택) `ANTHROPIC_API_KEY` 등록 시 Claude로 작성 (Gemini 키 없을 때 사용)

5. **Pages 켜기** — Settings → Pages → Source: **GitHub Actions** 선택.

6. **테스트 실행** — Actions 탭 → "Daily Stock Briefing" → Run workflow.
   완료 후 `https://<아이디>.github.io/stock-briefing/` 접속 → 끝!
   현재 레포의 경우 "https://moriochoradio.github.io/stock-briefing/"
## 커스터마이징

| 바꾸고 싶은 것 | 위치 |
|---|---|
| 관심종목·뉴스 키워드·LLM 모델 | `config.yaml` |
| 실행 시간 | `.github/workflows/daily.yml`의 cron (UTC, KST−9h) |
| 브리핑 톤·구성 | `scripts/generate.py`의 `PROMPT_TEMPLATE` |
| 사이트 디자인 | `site/src/` (Astro 컴포넌트·CSS) |

로컬 미리보기: `cd site && npm install && npm run dev`

## 참고

- 시세 카드·차트는 워크플로가 1회 이상 실행돼 히스토리가 쌓이면 표시됩니다 (차트는 2일 이상).
- 레포 이름을 `<아이디>.github.io`로 만들 경우 `daily.yml`의 `BASE_PATH`를 `"/"`로 수정.
- cron은 GitHub 부하에 따라 5~30분 지연될 수 있습니다.
- 본 브리핑은 투자 권유가 아닌 정보 제공입니다.
