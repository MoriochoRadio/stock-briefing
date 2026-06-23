"""한국장 인트라데이 점검 — 개장/장중/마감 스냅샷 + LLM 분석 → site/src/data/intraday.json
PHASE: open(09:10) | mid(12:30) | close(15:40). close는 풀 심층 리포트, open/mid는 가벼운 읽기.
엔진은 generate.run_llm 공유(Gemini 무료 우선). 키 없으면 데이터 기반 폴백 텍스트.
시세는 yfinance(한국 주식 약 15~20분 지연)."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ta  # noqa: E402
from generate import run_llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
PHASES = {"open": "개장", "mid": "장중", "close": "마감"}

PRIMARY = [
    {"ticker": "005930.KS", "name": "삼성전자"},
    {"ticker": "000660.KS", "name": "SK하이닉스"},
]

# 미국 반도체 — 한국장 마감(close) 때 직전 미국 세션 기준으로 대략 분석(연결고리)
US_SEMI = [
    {"ticker": "NVDA", "name": "엔비디아"},
    {"ticker": "AMD", "name": "AMD"},
    {"ticker": "MU", "name": "마이크론"},
    {"ticker": "TSM", "name": "TSMC"},
    {"ticker": "AVGO", "name": "브로드컴"},
    {"ticker": "ASML", "name": "ASML"},
]
US_KEYS = ("ticker", "name", "close", "change_pct", "trend", "rsi14", "rsi_state",
           "macd_dir", "vs_sma20_pct", "ret_20d", "ret_60d", "range_pos", "asof")


def quote(ticker):
    try:
        df = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        c = df["Close"]
        return {"close": ta.f(c.iloc[-1]), "change_pct": ta.f((c.iloc[-1] / c.iloc[-2] - 1) * 100)}
    except Exception as e:
        print(f"[warn] quote {ticker}: {e}")
        return None


def fmt_stock_for_prompt(s):
    return (
        f"- {s['name']}: 현재 {s['close']:,} ({s['change_pct']:+.2f}%, 개장대비 {s['vs_open_pct']:+.2f}%) "
        f"| 추세 {s['trend']}, 20일선대비 {s['vs_sma20_pct']:+.1f}% "
        f"| RSI {s['rsi14']:.1f}({s['rsi_state']}, 전일 {s['rsi_prev']:.1f}) "
        f"| MACD히스토 {s['macd_dir']} "
        f"| 52주 위치 {s['range_pos']*100:.0f}%, 거래량 평소의 {s['vol_ratio']:.2f}배 "
        f"| 20일 {s['ret_20d']:+.1f}%, 60일 {s['ret_60d']:+.1f}%"
    )


def light_prompt(label, tnow, stocks, market):
    lines = "\n".join(fmt_stock_for_prompt(s) for s in stocks)
    mk = (f"코스피 {market['kospi']['change_pct']:+.2f}%, "
          f"원/달러 {market['krw']['close']:,.1f}({market['krw']['change_pct']:+.2f}%)") if market else "(없음)"
    return f"""당신은 한국 증시 장중 스냅샷을 쓰는 분석가다. 아래 지연 시세(약 15~20분 지연)와 지표만 근거로, 오늘 한국 반도체(삼성전자·SK하이닉스) 흐름을 한국어 2~4문장으로 간결히 써라. 데이터에 없는 수치 금지, 투자 권유 금지.

[시점] {label} 스냅샷 ({tnow} KST)
[종목 지표]
{lines}
[시장] {mk}

[작성 지침]
- 첫 문장에 현재 시장 성격을 한 단어(위험선호/중립/위험회피)로 명시.
- '개장 대비' 변화와 그 의미를 짚을 것(오늘 흐름이 강해지는지/꺾이는지).
- 마크다운 표·제목 쓰지 말 것. 평이한 문단으로."""


def close_prompt(tnow, stocks, market, us_ctx):
    lines = "\n".join(fmt_stock_for_prompt(s) for s in stocks)
    mk = (f"코스피 {market['kospi']['change_pct']:+.2f}%, "
          f"원/달러 {market['krw']['close']:,.1f}({market['krw']['change_pct']:+.2f}%)") if market else "(없음)"
    us = ", ".join(f"{c['name']} {c['change_pct']:+.2f}%" for c in us_ctx) if us_ctx else "(없음)"
    return f"""당신은 한국 반도체 시장을 분석하는 시니어 시장 분석가다. 규율 있는 기술적 사고를 하되 근거 없는 단정은 하지 않는다. 오늘 한국장 마감 기준, 아래 지연 시세와 지표만 근거로 한국어 심층 리포트를 평이한 문단(마크다운 표·제목 금지)으로 작성하라.

[시점] 마감 ({tnow} KST)
[삼성전자·SK하이닉스 지표]
{lines}
[국내 시장] {mk}
[미국 반도체 참고] {us}

[작성 원칙]
- 제공된 데이터에 없는 수치는 절대 지어내지 말 것. 상관과 인과를 구분, 불확실하면 "~로 추정".
- 확증편향 경계: 반대 시나리오가 성립하면 함께 제시.
- 투자 권유 금지. 시사점은 '관찰 포인트'로.

[구성] 아래 순서의 문단으로(각 문단 앞에 '▶ 소제목' 한 줄):
▶ 오늘 총평 — 시장 성격(위험선호/중립/위험회피) + 핵심 3줄
▶ 삼성전자 — 추세·모멘텀·과열/지지 해석
▶ SK하이닉스 — 추세·모멘텀·과열/지지 해석
▶ 수급·환율 연결고리 — 원/달러·외국인 수급(추정)·미국 반도체와의 디버전스
▶ 내일 관전 포인트 — 2~3개(무효화/관찰 레벨 포함)
▶ 한 줄 리스크"""


def fallback_text(phase, stocks, market):
    """LLM 키 없을 때 데이터 기반 기본 텍스트."""
    parts = []
    chg = sum(s["change_pct"] for s in stocks) / len(stocks) if stocks else 0
    mood = "위험회피" if chg <= -1 else "위험선호" if chg >= 1 else "중립"
    parts.append(f"[{PHASES.get(phase, phase)}] 현재 시장 성격: {mood} (반도체 평균 등락 {chg:+.2f}%).")
    for s in stocks:
        parts.append(
            f"{s['name']}: {s['close']:,} ({s['change_pct']:+.2f}%, 개장대비 {s['vs_open_pct']:+.2f}%), "
            f"{s['trend']}·RSI {s['rsi14']:.0f}({s['rsi_state']})·MACD {s['macd_dir']}."
        )
    if market:
        parts.append(f"코스피 {market['kospi']['change_pct']:+.2f}%, 원/달러 {market['krw']['close']:,.1f}.")
    parts.append("(LLM 미설정 — 데이터 요약만 표시)")
    return "\n".join(parts)


STOCK_KEYS = ("ticker", "name", "close", "change_pct", "vs_open_pct", "trend",
              "vs_sma20_pct", "rsi14", "rsi_prev", "rsi_state", "macd_dir", "macd_hist",
              "bb_pctb", "atr_pct", "range_pos", "vol_ratio", "ret_20d", "ret_60d",
              "sma20", "sma60", "hi52", "lo52", "asof")


def build_us_semi(cfg, kr_stocks):
    """미국 반도체(직전 세션) 대략 분석 + 한국 반도체와의 연결고리. close 단계에서 호출."""
    stocks = []
    for item in US_SEMI:
        try:
            df = yf.Ticker(item["ticker"]).history(period="1y", auto_adjust=False)
            m = ta.compute_metrics(df)
            if not m:
                continue
            m.update(ticker=item["ticker"], name=item["name"])
            stocks.append({k: m.get(k) for k in US_KEYS})
        except Exception as e:
            print(f"[warn] US {item['ticker']}: {e}")
    if not stocks:
        return None
    sox = quote("^SOX")

    def line(s):
        return (f"- {s['name']}: ${s['close']:,.2f} ({s['change_pct']:+.2f}%), {s['trend']}, "
                f"RSI {s['rsi14']:.0f}({s['rsi_state']}), MACD {s['macd_dir']}, "
                f"20일선대비 {s['vs_sma20_pct']:+.1f}%, 20일 {s['ret_20d']:+.1f}%")
    us_lines = "\n".join(line(s) for s in stocks)
    sox_line = f"필라델피아 반도체지수(SOX) {sox['change_pct']:+.2f}%" if sox else "(SOX 없음)"
    kr_line = ", ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in kr_stocks) if kr_stocks else "(없음)"

    prompt = f"""당신은 미국 반도체 섹터를 한국 투자자 관점에서 짚어주는 분석가다. 아래 직전 미국 세션 종가·지표만 근거로, 한국어로 '대략적인' 분석을 2~3문단 작성하라(한국장처럼 종목별 깊은 분석은 불필요, 큰 그림 중심). 데이터에 없는 수치 금지, 투자 권유 금지.

[미국 반도체 지표]
{us_lines}
[지수] {sox_line}
[오늘 한국 반도체] {kr_line}

[작성 지침]
- 첫 문장에 미국 반도체 섹터의 전반 성격(위험선호/중립/위험회피)을 한 단어로.
- 큰 그림: 엔비디아·SOX를 축으로 섹터 추세와 모멘텀을 요약.
- 핵심: 오늘 한국 반도체(삼성·SK하이닉스)와의 '연결고리'를 분명히(동조/디커플링, HBM·메모리 수요, 내일 한국장 시사점).
- 마크다운 표·제목 금지. 평이한 문단으로."""
    body, engine = run_llm(prompt, cfg)
    if not body:
        avg = sum(s["change_pct"] for s in stocks) / len(stocks)
        mood = "위험회피" if avg <= -1 else "위험선호" if avg >= 1 else "중립"
        body = (f"미국 반도체 섹터 성격: {mood}(평균 {avg:+.2f}%). " + sox_line + ". "
                + "; ".join(f"{s['name']} {s['change_pct']:+.2f}%({s['trend']})" for s in stocks)
                + ". (LLM 미설정 — 데이터 요약만 표시)")
        engine = "없음"
    return {"asof": stocks[0].get("asof"), "sox": sox, "stocks": stocks,
            "read": body.strip(), "engine": engine}


def main():
    phase = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PHASE", "close")).strip().lower()
    if phase not in PHASES:
        phase = "close"
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    tnow = now.strftime("%H:%M")

    stocks = []
    for item in PRIMARY:
        try:
            df = yf.Ticker(item["ticker"]).history(period="1y", auto_adjust=False)
            m = ta.compute_metrics(df)
            if not m:
                continue
            m.update(ticker=item["ticker"], name=item["name"])
            stocks.append({k: m.get(k) for k in STOCK_KEYS})
        except Exception as e:
            print(f"[warn] {item['ticker']}: {e}")
    if not stocks:
        print("[abort] 종목 데이터 없음"); return

    delayed = any(s.get("asof") != today for s in stocks)  # 휴장/지연이면 True

    market = {"kospi": quote("^KS11"), "krw": quote("KRW=X")}
    if not (market["kospi"] and market["krw"]):
        market = None
    us_ctx = []
    if phase == "close":
        for t, n in [("NVDA", "엔비디아"), ("^SOX", "필라델피아 반도체"), ("TSM", "TSMC")]:
            q = quote(t)
            if q:
                us_ctx.append({"name": n, "change_pct": q["change_pct"]})

    if phase == "close":
        prompt = close_prompt(tnow, stocks, market, us_ctx)
    else:
        prompt = light_prompt(PHASES[phase], tnow, stocks, market)
    body, engine = run_llm(prompt, cfg)
    if not body:
        body, engine = fallback_text(phase, stocks, market), "없음"
    print(f"phase={phase} engine={engine} delayed={delayed}")

    path = ROOT / "site" / "src" / "data" / "intraday.json"
    cur = {}
    if path.exists():
        try:
            cur = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    if cur.get("date") != today:
        cur = {"date": today, "snapshots": []}

    snap = {
        "phase": phase, "label": PHASES[phase], "time": tnow,
        "delayed": delayed, "engine": engine,
        "stocks": stocks, "read": body.strip(),
    }
    if phase == "close":
        snap["us_context"] = us_ctx

    # 다운그레이드 방지: 이번 호출이 폴백(없음)인데 같은 단계의 기존 실제 분석이 있으면,
    # 시세·지표만 갱신하고 분석문(read)은 기존 실제 분석을 유지한다(재실행이 실제→폴백으로 떨어지지 않게).
    if engine == "없음":
        prev = next((s for s in cur.get("snapshots", []) if s.get("phase") == phase and s.get("engine") not in (None, "없음")), None)
        if prev:
            snap["read"] = prev["read"]
            snap["engine"] = prev["engine"]
            print(f"[keep] {phase} 기존 실제 분석 유지(이번 LLM 폴백)")

    snaps = [s for s in cur.get("snapshots", []) if s.get("phase") != phase]
    snaps.append(snap)
    order = {"open": 0, "mid": 1, "close": 2}
    snaps.sort(key=lambda s: order.get(s["phase"], 9))
    cur.update(date=today, updated_kst=f"{today} {tnow}", market=market, snapshots=snaps)

    # 한국장 마감 시, 직전 미국 반도체 세션을 한국과 연결지어 대략 분석
    if phase == "close":
        us = build_us_semi(cfg, stocks)
        if us:
            prev_us = cur.get("us_semi")
            if us["engine"] == "없음" and prev_us and prev_us.get("engine") not in (None, "없음"):
                us["read"] = prev_us["read"]
                us["engine"] = prev_us["engine"]
                print("[keep] us_semi 기존 실제 분석 유지(이번 LLM 폴백)")
            cur["us_semi"] = us
            print(f"us_semi engine={us['engine']} stocks={len(us['stocks'])}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"saved {path} - {len(snaps)} snapshot(s)")


if __name__ == "__main__":
    main()
