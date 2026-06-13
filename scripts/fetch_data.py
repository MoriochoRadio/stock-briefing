"""시장 데이터 + 뉴스 헤드라인 수집 → data.json (LLM 불필요, 전부 무료 소스)"""
import json
import math
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_quotes(items):
    """최근 종가와 등락률. 실패하거나 값이 비정상(NaN)인 티커는 건너뜀."""
    out = []
    for item in items:
        try:
            hist = yf.Ticker(item["ticker"]).history(period="5d")
            if len(hist) < 2:
                continue
            last, prev = float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[-2])
            # 휴장/빈 응답 시 yfinance가 마지막 종가를 NaN으로 주는 경우가 있다.
            # NaN을 그대로 두면 history.json이 비표준 JSON이 되어 Astro 빌드가 깨지므로 건너뛴다.
            if not (math.isfinite(last) and math.isfinite(prev)) or prev == 0:
                print(f"[warn] {item['ticker']}: 종가 비정상(NaN/0) — 건너뜀")
                continue
            out.append({
                "name": item["name"],
                "ticker": item["ticker"],
                "close": round(last, 2),
                "change_pct": round((last / prev - 1) * 100, 2),
                "date": str(hist.index[-1].date()),
            })
        except Exception as e:
            print(f"[warn] {item['ticker']}: {e}")
    return out


def fetch_news(queries, per_query):
    """Google News RSS (무료, 키 불필요)"""
    out = []
    for q in queries:
        lang = q.get("lang", "ko")
        params = (
            {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}
            if lang == "ko"
            else {"hl": "en-US", "gl": "US", "ceid": "US:en"}
        )
        url = (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(q["q"])
            + "&" + urllib.parse.urlencode(params)
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                root = ET.fromstring(r.read())
            for it in root.iter("item"):
                title = it.findtext("title") or ""
                out.append({
                    "query": q["q"],
                    "title": title,
                    "link": it.findtext("link") or "",
                    "pub": it.findtext("pubDate") or "",
                })
                if sum(1 for n in out if n["query"] == q["q"]) >= per_query:
                    break
        except Exception as e:
            print(f"[warn] news '{q['q']}': {e}")
    return out


def _clean_snapshot(snap):
    """스냅샷에서 NaN/Infinity 종가를 가진 quote를 제거 (비표준 JSON 방지)."""
    clean = [
        q for q in snap.get("quotes", [])
        if isinstance(q.get("close"), (int, float)) and math.isfinite(q["close"])
        and isinstance(q.get("change_pct"), (int, float)) and math.isfinite(q["change_pct"])
    ]
    return {**snap, "quotes": clean}


def update_history(data, keep_days=120):
    """site/src/data/history.json에 일별 스냅샷 누적 (대시보드 카드·차트용)"""
    path = ROOT / "site" / "src" / "data" / "history.json"
    history = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            history = []
    # 과거에 잘못 기록된 NaN 항목까지 함께 정리해 자가 치유한다.
    history = [_clean_snapshot(h) for h in history]
    quotes = data["indices"] + data["watchlist_us"] + data["watchlist_kr"]
    snap = _clean_snapshot({"date": data["date_kst"], "quotes": quotes})
    history = [h for h in history if h["date"] != snap["date"]] + [snap]
    history = history[-keep_days:]
    path.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False: 혹시라도 NaN이 남으면 조용히 깨진 JSON을 쓰는 대신 즉시 실패시킨다.
    path.write_text(json.dumps(history, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"history: {len(history)} day(s)")


def build_series(cfg, period="1y"):
    """차트용 종목별 일봉 종가 시계열을 site/src/data/series.json에 기록.
    스파크라인·지수 추이 차트가 '작업 이후'가 아닌 실제 과거 데이터를 쓰도록 한다."""
    path = ROOT / "site" / "src" / "data" / "series.json"
    items = cfg["indices"] + cfg["watchlist_us"] + cfg["watchlist_kr"]
    out = {}
    for item in items:
        t = item["ticker"]
        try:
            hist = yf.Ticker(t).history(period=period)
            arr = []
            for ts, close in hist["Close"].items():
                c = float(close)
                if not math.isfinite(c):
                    continue
                arr.append([str(ts.date()), round(c, 2)])
            if len(arr) >= 2:
                out[t] = arr
        except Exception as e:
            print(f"[warn] series {t}: {e}")
    if out:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 빈 응답으로 일부 티커가 빠져도 기존 series.json을 통째로 날리지 않도록 병합
        if path.exists():
            try:
                prev = json.loads(path.read_text(encoding="utf-8"))
                for k, v in prev.items():
                    out.setdefault(k, v)
            except Exception:
                pass
        path.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        print(f"series: {len(out)} ticker(s)")


FNG_LABELS = {
    "extreme fear": "극단적 공포",
    "fear": "공포",
    "neutral": "중립",
    "greed": "탐욕",
    "extreme greed": "극단적 탐욕",
}


def fetch_fng():
    """CNN Fear & Greed Index (미국 기준). 봇 차단 회피용 브라우저 헤더 필요. 실패 시 None."""
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.cnn.com/markets/fear-and-greed",
        "Origin": "https://www.cnn.com",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read())
        fg = j["fear_and_greed"]
        rating = str(fg.get("rating", "")).lower()
        return {"score": round(float(fg["score"]), 1), "rating": rating, "label": FNG_LABELS.get(rating, rating)}
    except Exception as e:
        print(f"[warn] fng: {e}")
        return None


def build_sentiment(cfg, data):
    """상단 '시장 분위기'용 데이터: 섹터 ETF 등락(미/한) + CNN 탐욕지수.
    네트워크 실패로 일부가 비어도 직전 sentiment.json 값을 유지한다."""
    path = ROOT / "site" / "src" / "data" / "sentiment.json"
    prev = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    def slim(quotes):
        return [{"ticker": q["ticker"], "name": q["name"], "change_pct": q["change_pct"]} for q in quotes]

    us = slim(fetch_quotes(cfg.get("breadth_us", [])))
    kr = slim(fetch_quotes(cfg.get("breadth_kr", [])))
    fng = fetch_fng()

    out = {
        "asOf": data["date_kst"],
        "fng": fng or prev.get("fng"),
        "us": us or prev.get("us", []),
        "kr": kr or prev.get("kr", []),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"sentiment: us={len(out['us'])} kr={len(out['kr'])} fng={'ok' if out['fng'] else 'none'}")


def main():
    cfg = load_config()
    now = datetime.now(KST)
    data = {
        "generated_at": now.isoformat(),
        "date_kst": now.strftime("%Y-%m-%d"),
        "weekday_kr": "월화수목금토일"[now.weekday()],
        "indices": fetch_quotes(cfg["indices"]),
        "watchlist_us": fetch_quotes(cfg["watchlist_us"]),
        "watchlist_kr": fetch_quotes(cfg["watchlist_kr"]),
        "news": fetch_news(cfg["news_queries"], cfg.get("news_per_query", 5)),
    }
    out = ROOT / "data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if data["indices"] or data["watchlist_us"] or data["watchlist_kr"]:
        update_history(data)
    build_series(cfg)
    build_sentiment(cfg, data)
    print(f"saved {out} — quotes:{len(data['indices'])+len(data['watchlist_us'])+len(data['watchlist_kr'])}, news:{len(data['news'])}")


if __name__ == "__main__":
    main()
