"""시장 데이터 + 뉴스 헤드라인 수집 → data.json (LLM 불필요, 전부 무료 소스)"""
import json
import math
import time
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


def _hist(ticker, period="5d", tries=3):
    """yfinance 일봉 조회 + 재시도 — 일시적 429/네트워크 오류로 카드·시리즈가 조용히
    빠지는 것을 줄인다. auto_adjust=False로 통일(전 스크립트가 같은 '실제 체결가' 기준).
    실패 시 None."""
    for i in range(tries):
        try:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if df is not None and len(df):
                return df
            print(f"[warn] {ticker}: 빈 응답 ({i + 1}/{tries})")
        except Exception as e:
            print(f"[warn] {ticker}: {e} ({i + 1}/{tries})")
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return None


def fetch_quotes(items):
    """최근 종가와 등락률. 실패하거나 값이 비정상(NaN)인 티커는 건너뜀."""
    out = []
    for item in items:
        try:
            hist = _hist(item["ticker"])
            if hist is None or len(hist) < 2:
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
            count = 0  # 쿼리별 지역 카운터(기존 O(n²) 전체 재집계 대신)
            for it in root.iter("item"):
                title = it.findtext("title") or ""
                out.append({
                    "query": q["q"],
                    "title": title,
                    "link": it.findtext("link") or "",
                    "pub": it.findtext("pubDate") or "",
                })
                count += 1
                if count >= per_query:
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
            hist = _hist(t, period=period)
            if hist is None:
                continue
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
        # 빈 응답으로 일부 티커가 빠져도 기존 series.json을 통째로 날리지 않도록 병합.
        # 단, config에서 뺀 티커가 영구 잔류하지 않도록 현재 티커 집합으로 한정한다.
        current = {item["ticker"] for item in items}
        if path.exists():
            try:
                prev = json.loads(path.read_text(encoding="utf-8"))
                for k, v in prev.items():
                    if k in current:
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


def _news_category(query):
    """반도체 집중 카테고리(분야) 매핑."""
    q = (query or "").lower()
    if "환율" in query or "krw" in q:
        return "환율"
    if any(k in query for k in ["삼성", "하이닉스"]):
        return "국내반도체"
    if "hbm" in q or "메모리" in query:
        return "메모리·HBM"
    if "수출" in query or "수급" in query:
        return "수출·수급"
    if "nvidia" in q:
        return "엔비디아"
    if any(k in q for k in ["amd", "micron", "tsmc"]):
        return "미국반도체"
    if "asml" in q or "broadcom" in q:
        return "장비·인프라"
    if any(k in q for k in ["capex", "datacenter", "ai", "chip demand"]):
        return "AI·수요"
    if "반도체" in query or "semiconductor" in q:
        return "반도체"
    if "증시" in query or "stock" in q or "market" in q:
        return "해외증시"
    return "마켓"


def _split_source(title):
    """Google News 제목은 'Headline - Source' 형식 → 헤드라인/출처 분리."""
    i = title.rfind(" - ")
    if i > 0:
        return title[:i].strip(), title[i + 3:].strip()
    return title.strip(), ""


def build_news(data, limit=10):
    """수집한 헤드라인을 사이트 노출용 news.json으로 기록(카테고리 라운드로빈으로 다양성 확보)."""
    path = ROOT / "site" / "src" / "data" / "news.json"
    groups = {}
    for n in data.get("news", []):
        groups.setdefault(n.get("query", ""), []).append(n)
    # 쿼리별로 한 건씩 번갈아 뽑아 한쪽 주제 쏠림 방지
    ordered, i = [], 0
    while any(i < len(v) for v in groups.values()):
        for lst in groups.values():
            if i < len(lst):
                ordered.append(lst[i])
        i += 1
    seen, items = set(), []
    for n in ordered:
        headline, source = _split_source(n.get("title", ""))
        if not headline or headline in seen:
            continue
        seen.add(headline)
        items.append({
            "title": headline,
            "source": source,
            "link": n.get("link", ""),
            "pub": n.get("pub", ""),
            "cat": _news_category(n.get("query", "")),
        })
        if len(items) >= limit:
            break
    out = {"asOf": data["date_kst"], "items": items}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"news: {len(items)} headline(s)")


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
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if data["indices"] or data["watchlist_us"] or data["watchlist_kr"]:
        update_history(data)
    build_series(cfg)
    build_sentiment(cfg, data)
    build_news(data)
    print(f"saved {out} — quotes:{len(data['indices'])+len(data['watchlist_us'])+len(data['watchlist_kr'])}, news:{len(data['news'])}")


if __name__ == "__main__":
    main()
