"""data.json → LLM 분석 → briefings/YYYY-MM-DD.md
엔진 우선순위: GEMINI_API_KEY → ANTHROPIC_API_KEY → (둘 다 없으면) 데이터만으로 기본 브리핑
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# 일시적 오류(과부하·레이트리밋)로 한 번에 실패하지 않도록 재시도하는 코드들.
_RETRY_CODES = {429, 500, 502, 503, 529}


def _urlopen_json(req, timeout, tries=6):
    """urlopen + JSON 파싱. 일시적 HTTP 오류/네트워크 오류는 지수 백오프로 재시도.
    무료 LLM 엔드포인트의 일시 과부하(503) 창을 한 실행 안에서 넘기도록 넉넉히 재시도."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in _RETRY_CODES and i < tries - 1:
                wait = min(2 ** (i + 1), 32)  # 2,4,8,16,32초 (총 ~60초)
                print(f"[warn] LLM HTTP {e.code} — {wait}s 후 재시도 {i + 1}/{tries - 1}")
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            if i < tries - 1:
                wait = min(2 ** (i + 1), 32)
                print(f"[warn] LLM 네트워크 오류({e}) — {wait}s 후 재시도 {i + 1}/{tries - 1}")
                time.sleep(wait)
                continue
            raise
    # 모든 재시도 소진(방어적): None을 반환해 호출부가 NoneType 첨자 오류로 죽지 않게 명시적 실패.
    raise RuntimeError("LLM 요청 재시도 모두 소진")

PROMPT_TEMPLATE = """당신은 한국 개인투자자를 위한 아침 시장 브리핑을 쓰는 시니어 시장 분석가다. 규율 있는 거시·기술적 사고를 하되, 근거 없는 단정은 절대 하지 않는다. 아래 데이터와 뉴스 헤드라인만 근거로 한국어 브리핑을 마크다운으로 작성하라.

[독자 프로필]
{profile}

[시세 데이터 (종가·전일대비)]
{quotes}

[시장 분위기]
{mood}

[뉴스 헤드라인]
{news}

[분석 원칙]
- 제공된 데이터에 없는 수치(장중 고저, RSI·MACD 등 보조지표, 거래량 등)는 절대 지어내지 말 것. 오직 종가·등락률·시장 분위기·헤드라인이 담은 정보만 사용한다.
- 헤드라인으로 확인되지 않는 원인은 "~로 추정"이라고 명시하고, 상관(같이 움직임)과 인과(원인-결과)를 구분한다.
- 노이즈 제거: 가격에 의미 있는 이슈만 다룬다. 헤드라인 단순 나열 금지 — 항상 "이게 관심종목·지수에 어떤 의미인가"로 해석한다.
- 확증편향 경계: 하나의 서사에 끼워 맞추지 말 것. 반대 시나리오가 성립하면 함께 짚는다.
- 투자 권유·매수매도 단정 금지. 시사점은 단정이 아니라 "관찰 포인트" 수준으로 제시한다.

[구성] (제목 줄은 쓰지 말고 아래 소제목부터 본문 시작):
  ## ⏱ 1분 요약  (핵심 3~5줄, 번호 목록. 첫 줄에 오늘 시장 성격을 한 단어로 — 위험선호 / 중립 / 위험회피 중 하나 — 명시)
  ## 🇺🇸 밤사이 미국장  (지수 표 포함. 관심종목별 등락과 그 의미를 1~2줄씩 해석)
  ## 🇰🇷 한국장 영향 포인트  (미국장→한국장 전이 경로: 반도체·환율·외국인 수급 관점. 마지막에 "**연결고리 한 줄:**" 포함)
  ## 🤖 AI 업계 동향  (비상장 포함, 관련 헤드라인 있을 때만)
  ## 🧭 리스크 레이더  (오늘 주의할 변동성 요인·관찰 포인트 2~3개. 예정된 일정·지표·이벤트 우선)
  ## 📅 오늘의 체크포인트
  ## 📚 오늘의 개념  (오늘 뉴스 속 용어 하나를 초보자용으로 해설)
"""


def load(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_sentiment():
    """site/src/data/sentiment.json (CNN 공포탐욕지수 + 섹터 ETF 등락)을 읽어온다. 없으면 {}."""
    path = ROOT / "site" / "src" / "data" / "sentiment.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def build_mood(sent):
    """공포탐욕 지수 + 분야별(섹터) 강약 상·하위를 LLM이 쓸 수 있게 요약 문자열로."""
    if not sent:
        return "(시장 분위기 데이터 없음)"
    lines = []
    fng = sent.get("fng")
    if fng:
        lines.append(f"- 미국 공포·탐욕 지수: {fng.get('score')} ({fng.get('label', fng.get('rating', ''))})")

    def _ranked(label, arr):
        rows = [s for s in (arr or []) if isinstance(s.get("change_pct"), (int, float))]
        if not rows:
            return
        rows.sort(key=lambda s: s["change_pct"], reverse=True)
        top = ", ".join(f"{s['name']}({s['change_pct']:+.2f}%)" for s in rows[:3])
        bot = ", ".join(f"{s['name']}({s['change_pct']:+.2f}%)" for s in rows[-3:])
        lines.append(f"- {label} 강세 상위: {top}")
        lines.append(f"- {label} 약세 하위: {bot}")

    _ranked("미국 섹터", sent.get("us"))
    _ranked("한국 섹터", sent.get("kr"))
    return "\n".join(lines) or "(시장 분위기 데이터 없음)"


def build_prompt(data, cfg):
    quotes = []
    for group, label in [("indices", "지수/환율"), ("watchlist_us", "미국 관심종목"), ("watchlist_kr", "한국 관심종목")]:
        for q in data[group]:
            quotes.append(f"- [{label}] {q['name']}({q['ticker']}): {q['close']:,} ({q['change_pct']:+.2f}%, 기준일 {q['date']})")
    news = [f"- ({n['query']}) {n['title']}" for n in data["news"]]
    return PROMPT_TEMPLATE.format(
        profile=cfg["profile"]["style"],
        quotes="\n".join(quotes) or "(수집 실패)",
        mood=build_mood(load_sentiment()),
        news="\n".join(news) or "(수집 실패)",
    )


def call_gemini(prompt, cfg, key):
    model = cfg["llm"]["gemini_model"]
    # 키는 URL 쿼리 대신 헤더로 전달 — 예외 메시지·프록시 로그에 URL이 찍혀도 키가 새지 않는다
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    # thinking 예산: >0이면 추론을 켜 분석 깊이를 높인다(무료). thinking 토큰도 출력 한도를
    # 소비하므로 max_output_tokens보다 작게 둔다. 0=끔, -1=동적.
    budget = cfg["llm"].get("gemini_thinking_budget", 0)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": cfg["llm"]["max_output_tokens"],
            "thinkingConfig": {"thinkingBudget": budget},
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    # 추론을 켜면 생성에 시간이 더 걸릴 수 있어 타임아웃을 늘린다.
    res = _urlopen_json(req, timeout=240)
    # 추론 응답은 본문이 여러 part로 나뉠 수 있으므로 thought가 아닌 text part만 모두 합친다.
    parts = res["candidates"][0]["content"].get("parts", [])
    texts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
    return "\n".join(texts).strip()


def call_anthropic(prompt, cfg, key):
    model = cfg["llm"]["anthropic_model"]
    body = {
        "model": model,
        "max_tokens": cfg["llm"]["max_output_tokens"],
        "messages": [{"role": "user", "content": prompt}],
        # adaptive thinking: 모델이 인과·맥락을 스스로 충분히 추론한 뒤 답하도록 한다.
        # Opus 4.8/4.7/Sonnet 4.6에서 지원. effort=high로 분석 깊이를 끌어올린다.
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    # thinking이 켜지면 응답 생성에 시간이 더 걸릴 수 있어 타임아웃을 늘린다.
    res = _urlopen_json(req, timeout=300)
    # adaptive thinking이 켜지면 content[0]가 thinking 블록일 수 있으므로
    # text 블록만 추려서 합친다 (content[0]["text"] 직접 접근은 깨질 수 있음).
    texts = [b.get("text", "") for b in res.get("content", []) if b.get("type") == "text"]
    return "\n".join(t for t in texts if t).strip()


def fallback_briefing(data):
    """LLM 키가 없을 때: 데이터만으로 표 중심 브리핑"""
    lines = ["## ⏱ 시세 요약 (LLM 미설정 — 데이터만 표시)\n"]
    lines.append("| 구분 | 종가 | 등락 |\n|---|---|---|")
    for group in ("indices", "watchlist_us", "watchlist_kr"):
        for q in data[group]:
            lines.append(f"| {q['name']} | {q['close']:,} | {q['change_pct']:+.2f}% |")
    lines.append("\n## 주요 헤드라인\n")
    for n in data["news"][:15]:
        lines.append(f"- [{n['title']}]({n['link']})")
    return "\n".join(lines)


def run_llm(prompt, cfg):
    """설정된 provider 우선순위로 LLM을 호출해 (본문, 엔진명) 반환.
    한 엔진이 실패(재시도 후에도 오류)하면 다른 엔진으로 폴백하고, 모두 실패/무키면 (None, "없음").
    예외를 삼켜 워크플로가 죽지 않게 한다(호출부는 None이면 데이터 요약으로 대체).
    인트라데이 등 다른 스크립트도 같은 엔진 설정을 공유하도록 분리."""
    gem, ant = os.environ.get("GEMINI_API_KEY"), os.environ.get("ANTHROPIC_API_KEY")
    provider = cfg["llm"].get("provider", "anthropic")

    engines = []  # (이름, 키, 호출함수)
    if ant:
        engines.append(("anthropic", ant, lambda: (call_anthropic(prompt, cfg, ant), f"Claude ({cfg['llm']['anthropic_model']})")))
    if gem:
        engines.append(("gemini", gem, lambda: (call_gemini(prompt, cfg, gem), f"Gemini ({cfg['llm']['gemini_model']})")))
    # provider로 지정된 엔진을 맨 앞으로
    engines.sort(key=lambda e: 0 if e[0] == provider else 1)

    for name, _key, fn in engines:
        try:
            return fn()
        except Exception as e:
            print(f"[warn] {name} 호출 최종 실패({e}) — 다음 엔진/폴백으로")
            continue
    return None, "없음"


def main():
    cfg = yaml.safe_load(load(ROOT / "config.yaml"))
    data = json.loads(load(ROOT / "data.json"))
    prompt = build_prompt(data, cfg)

    body, engine = run_llm(prompt, cfg)
    if body is None:
        body = fallback_briefing(data)
    print(f"engine: {engine}")

    date = data["date_kst"]
    md = f"# 📈 아침 시장 브리핑 — {date} ({data['weekday_kr']})\n\n{body}\n\n---\n*자동 생성 브리핑 (엔진: {engine}). 투자 권유가 아닌 정보 제공입니다.*\n"
    out_dir = ROOT / "briefings"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{date}.md"
    out.write_text(md, encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
