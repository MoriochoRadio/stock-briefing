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
    print(f"saved {out} — quotes:{len(data['indices'])+len(data['watchlist_us'])+len(data['watchlist_kr'])}, news:{len(data['news'])}")


if __name__ == "__main__":
    main()
