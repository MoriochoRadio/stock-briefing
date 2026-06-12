# 📈 매일 아침 주식시장 브리핑 (완전 무료 자동화)

매일 한국시간 오전 7시, 미국·한국 증시 맞춤 브리핑을 자동 생성해 웹페이지로 배포합니다.
**서버·비용 0원**: GitHub Actions(실행) + Gemini 무료 티어(분석) + GitHub Pages(호스팅).

## 동작 구조

```
GitHub Actions (매일 07:00 KST)
 ├─ fetch_data.py   : yfinance 시세 + Google News RSS 헤드라인 수집 (무료, 키 불필요)
 ├─ generate.py     : Gemini가 데이터를 브리핑으로 분석·작성 → briefings/날짜.md
 ├─ build_site.py   : 마크다운 → HTML 변환, 목록 페이지 생성 → docs/
 └─ 자동 커밋 → GitHub Pages가 docs/를 웹에 배포
```

## 배포 방법 (5분)

1. **레포 만들기** — GitHub에서 새 레포(예: `stock-briefing`) 생성 후 이 폴더 전체를 푸시:
   ```bash
   cd stock-briefing-web
   git init && git add -A && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<아이디>/stock-briefing.git
   git push -u origin main
   ```

2. **Gemini API 키 발급 (무료, 카드 불필요)** — https://aistudio.google.com/apikey 에서 키 생성.
   ⚠️ 결제 등록하면 무료 티어가 사라지니 결제 등록하지 말 것.

3. **키 등록** — 레포 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `GEMINI_API_KEY`, Value: 발급받은 키
   - (선택) `ANTHROPIC_API_KEY`를 넣으면 Claude로 작성 — Gemini 키가 없을 때 사용됨

4. **Pages 켜기** — Settings → Pages → Source: `Deploy from a branch`, Branch: `main` / `/docs` 선택

5. **테스트 실행** — Actions 탭 → "Daily Stock Briefing" → Run workflow.
   완료 후 `https://<아이디>.github.io/stock-briefing/` 접속 → 끝!

## 커스터마이징

- **종목/키워드 변경**: `config.yaml`만 수정 (관심종목, 뉴스 검색어, 모델명)
- **시간 변경**: `.github/workflows/daily.yml`의 cron (UTC 기준, KST−9시간)
- **브리핑 톤/구성 변경**: `scripts/generate.py`의 `PROMPT_TEMPLATE`

## 참고

- 미국장 휴장일에도 실행되며, 시세 변동이 없으면 그대로 표기됩니다.
- GitHub Actions 무료 한도(공개 레포 무제한, 비공개 월 2,000분)에서 하루 1회 ~2분이면 충분합니다.
- cron은 몇 분 지연될 수 있습니다(GitHub 부하에 따라 5~30분).
- 본 브리핑은 투자 권유가 아닌 정보 제공입니다.
