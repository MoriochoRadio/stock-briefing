"""data.json → LLM 분석 → briefings/YYYY-MM-DD.md
엔진 우선순위: GEMINI_API_KEY → ANTHROPIC_API_KEY → (둘 다 없으면) 데이터만으로 기본 브리핑
"""
import json
import os
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

PROMPT_TEMPLATE = """당신은 한국 개인투자자를 위한 아침 시장 브리핑 작성자다. 아래 데이터와 뉴스 헤드라인만 근거로 한국어 브리핑을 마크다운으로 작성하라.

[독자 프로필]
{profile}

[시세 데이터]
{quotes}

[뉴스 헤드라인]
{news}

[작성 규칙]
- 데이터에 없는 수치를 지어내지 말 것. 헤드라인으로 확인 안 되는 원인 분석은 "~로 추정"으로 표기.
- 뉴스 나열이 아니라 "관심종목에 어떤 의미인가" 중심으로 해석.
- 노이즈 제거: 가격에 의미 있는 이슈만. 투자 권유 금지.
- 구성 (제목은 쓰지 말 것, 본문부터):
  ## ⏱ 1분 요약  (핵심 3~5줄, 번호 목록)
  ## 🇺🇸 밤사이 미국장  (지수 표 포함, 관심종목별 등락·이유)
  ## 🇰🇷 한국장 영향 포인트  (미국장→한국장 연결고리: 반도체·환율·외국인 수급. 마지막에 "**연결고리 한 줄:**" 포함)
  ## 🤖 AI 업계 동향  (비상장 포함, 관련 헤드라인 있을 때만)
  ## 📅 오늘의 체크포인트
  ## 📚 오늘의 개념  (오늘 뉴스 속 용어 하나를 초보자용으로 해설)
"""


def load(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_prompt(data, cfg):
    quotes = []
    for group, label in [("indices", "지수/환율"), ("watchlist_us", "미국 관심종목"), ("watchlist_kr", "한국 관심종목")]:
        for q in data[group]:
            quotes.append(f"- [{label}] {q['name']}({q['ticker']}): {q['close']:,} ({q['change_pct']:+.2f}%, 기준일 {q['date']})")
    news = [f"- ({n['query']}) {n['title']}" for n in data["news"]]
    return PROMPT_TEMPLATE.format(
        profile=cfg["profile"]["style"],
        quotes="\n".join(quotes) or "(수집 실패)",
        news="\n".join(news) or "(수집 실패)",
    )


def call_gemini(prompt, cfg, key):
    model = cfg["llm"]["gemini_model"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": cfg["llm"]["max_output_tokens"],
            # thinking 토큰이 출력 한도를 잠식해 본문이 잘리는 것 방지
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.load(r)
    return res["candidates"][0]["content"]["parts"][0]["text"]


def call_anthropic(prompt, cfg, key):
    body = {
        "model": cfg["llm"]["anthropic_model"],
        "max_tokens": cfg["llm"]["max_output_tokens"],
        "messages": [{"role": "user", "content": prompt}],
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
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.load(r)
    return res["content"][0]["text"]


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


def main():
    cfg = yaml.safe_load(load(ROOT / "config.yaml"))
    data = json.loads(load(ROOT / "data.json"))
    prompt = build_prompt(data, cfg)

    gem, ant = os.environ.get("GEMINI_API_KEY"), os.environ.get("ANTHROPIC_API_KEY")
    if gem:
        body, engine = call_gemini(prompt, cfg, gem), "Gemini"
    elif ant:
        body, engine = call_anthropic(prompt, cfg, ant), "Claude"
    else:
        body, engine = fallback_briefing(data), "없음"
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
