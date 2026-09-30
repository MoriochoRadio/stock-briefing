"""시장 데이터 + 뉴스 헤드라인 수집 → data.json (LLM 불필요, 전부 무료 소스)"""
import json
import math
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _valid_close_rows(df, ticker=""):
    """종가가 비었거나(NaN) 0인 봉을 버리고 '마지막 유효 종가'까지만 남긴다.
    프리/애프터마켓 데이터가 있는 미국 종목은 Yahoo가 종가 없는 최신 봉을 붙여 주는 일이 있어,
    마지막 봉을 그대로 읽으면 종목 전체가 '비정상'으로 빠지거나(2026-09 미국 관심종목·섹터 ETF
    연속 누락) 지표 계산이 None이 된다. 기준일은 남은 마지막 봉의 날짜로 정직하게 표시된다."""
    close = df["Close"]
    ok = close.notna() & (close != 0)
    dropped = int((~ok).sum())
    if dropped:
        bad = ", ".join(str(ts.date()) for ts in df.index[(~ok).to_numpy()][-3:])
        print(f"[info] {ticker}: 종가 없는 봉 {dropped}개 제외({bad}) — 마지막 유효 종가 사용")
    return df[ok]


def _hist(ticker, period="5d", tries=3):
    """yfinance 일봉 조회 + 재시도 — 일시적 429/네트워크 오류로 카드·시리즈가 조용히
    빠지는 것을 줄인다. auto_adjust=False로 통일(전 스크립트가 같은 '실제 체결가' 기준).
    종가 없는(NaN) 봉은 제외해 모든 호출부가 마지막 유효 종가를 쓰게 한다. 실패 시 None."""
    for i in range(tries):
        try:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if df is not None and len(df):
                df = _valid_close_rows(df, ticker)
                if len(df):
                    return df
            print(f"[warn] {ticker}: 빈 응답/유효 종가 없음 ({i + 1}/{tries})")
        except Exception as e:
            print(f"[warn] {ticker}: {e} ({i + 1}/{tries})")
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return None


# 한국 시장 오늘 봉이 '종가'로 확정되는 시각(KST). 정규장 15:30 마감(수능일 16:30) + Yahoo 지연
# 15~20분 + 여유. 이보다 이르게 조회한 오늘 봉은 장중가다 — 모닝 cron(07:10)이 GitHub 지연으로
# 09~10시에 돌면서 장중가가 history.json에 그날 '종가'로 영구 저장되던 원인.
KR_CLOSE_FINAL = (17, 0)
KR_INDEX_TICKERS = {"^KS11", "^KQ11", "^KS200"}


def _is_kr_market(ticker):
    t = (ticker or "").upper()
    return t.endswith((".KS", ".KQ")) or t in KR_INDEX_TICKERS


def _completed_bars(df, ticker, now=None):
    """종가 기록용(history·series·섹터 등락): 한국 시장 티커는 장 마감 확정(KR_CLOSE_FINAL) 전에
    조회한 오늘 봉을 빼고 직전 완결 봉까지만 남긴다 → 기준일은 전일로 정직하게 표시된다.
    한국장 인트라데이 스냅샷은 일부러 장중 봉을 쓰므로 이 함수를 거치지 않고 _hist를 직접 쓴다."""
    if df is None or not len(df) or not _is_kr_market(ticker):
        return df
    now = now or datetime.now(KST)
    last = df.index[-1]
    last_day = (last.tz_convert(KST) if last.tzinfo else last).date()
    if last_day < now.date() or (now.hour, now.minute) >= KR_CLOSE_FINAL:
        return df
    print(f"[info] {ticker}: 오늘({last_day}) 봉은 장 마감 확정 전({now:%H:%M} KST) 장중가 — 종가 기록에서 제외, 직전 완결 봉 사용")
    return df.iloc[:-1]


def fetch_quotes(items, now=None):
    """최근 종가와 등락률. 실패하거나 값이 비정상(NaN)인 티커는 건너뜀.
    한국 시장 티커는 장 마감 확정 전이면 오늘 장중 봉 대신 직전 완결 봉(전일 종가) 기준."""
    out = []
    for item in items:
        try:
            hist = _completed_bars(_hist(item["ticker"]), item["ticker"], now)
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


def _pub_datetime(pub):
    """RSS pubDate(RFC 822, 예: 'Tue, 29 Sep 2026 20:29:59 GMT') → aware datetime. 없거나 형식이 다르면 None."""
    try:
        dt = parsedate_to_datetime(pub)
    except Exception:
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_news(queries, per_query, max_age_hours=72, now=None):
    """Google News RSS (무료, 키 불필요). 최근 max_age_hours 이내 기사만 쓴다.
    Google News 검색은 관련도순이라 몇 달 된 기사(예: 152일 전 리포트)가 섞여 브리핑이 현재 분석처럼
    인용하는 일이 있었다 — 검색어에 when:Nd를 붙이고, pubDate로 한 번 더 거른다(날짜 없는 기사도 제외).
    기본 72h = 주말 이틀을 사이에 둔 브리핑에도 직전 흐름의 기사가 남는 폭(config news_max_age_hours)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    when = f" when:{max(1, math.ceil(max_age_hours / 24))}d"
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
            + urllib.parse.quote(q["q"] + when)
            + "&" + urllib.parse.urlencode(params)
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                root = ET.fromstring(r.read())
            count = stale = 0  # 쿼리별 지역 카운터(기존 O(n²) 전체 재집계 대신)
            for it in root.iter("item"):
                pub = it.findtext("pubDate") or ""
                published = _pub_datetime(pub)
                if published is None or published < cutoff:
                    stale += 1
                    continue
                title = it.findtext("title") or ""
                out.append({
                    "query": q["q"],
                    "title": title,
                    "link": it.findtext("link") or "",
                    "pub": pub,
                })
                count += 1
                if count >= per_query:
                    break
            if not count:
                print(f"[warn] news '{q['q']}': 최근 {max_age_hours}h 이내 기사 0건"
                      f"(오래됐거나 날짜 없는 기사 {stale}건 제외) — 이 주제는 브리핑 근거에서 빠짐")
            elif stale:
                print(f"[info] news '{q['q']}': {max_age_hours}h 넘은/날짜 없는 기사 {stale}건 제외")
        except Exception as e:
            print(f"[warn] news '{q['q']}': {e}")
    if queries and not out:
        print(f"[warn] news: 최근 {max_age_hours}h 이내 기사 0건 — 브리핑·헤드라인이 기사 근거 없이 작성됨")
    return out


def _clean_snapshot(snap):
    """스냅샷에서 NaN/Infinity 종가를 가진 quote를 제거 (비표준 JSON 방지)."""
    clean = [
        q for q in snap.get("quotes", [])
        if isinstance(q.get("close"), (int, float)) and math.isfinite(q["close"])
        and isinstance(q.get("change_pct"), (int, float)) and math.isfinite(q["change_pct"])
    ]
    return {**snap, "quotes": clean}


def build_quality(cfg, data):
    """프론트엔드가 데이터 완전성·기준일·지연 가능성을 투명하게 표시하도록 품질 메타데이터를 생성한다.

    미국장과 한국장은 종가 기준일이 서로 다를 수 있으므로, 단순히 오늘 날짜와 비교해
    '오래된 데이터'라고 단정하지 않는다. 대신 각 그룹의 실제 기준일과 수집 성공률을
    함께 기록해 독자가 해석할 수 있게 한다.
    """
    groups = {}
    for key, label in (
        ("indices", "지수·환율"),
        ("watchlist_us", "미국 관심종목"),
        ("watchlist_kr", "한국 관심종목"),
    ):
        expected = cfg.get(key, [])
        quotes = data.get(key, [])
        dates = sorted({str(q.get("date")) for q in quotes if q.get("date")})
        coverage = round((len(quotes) / len(expected)) * 100, 1) if expected else 100.0
        groups[key] = {
            "label": label,
            "expected": len(expected),
            "received": len(quotes),
            "coveragePct": coverage,
            "asOfDates": dates,
            "status": "complete" if len(quotes) == len(expected) else "partial",
        }

    return {
        "generatedAt": data["generated_at"],
        "dateKst": data["date_kst"],
        "source": "Yahoo Finance via yfinance",
        "quoteNotice": "종가·등락률은 Yahoo Finance(yfinance) 기준이며, 거래소 공식 실시간 시세가 아니고 지연·정정될 수 있습니다.",
        "newsSource": "Google News RSS",
        "newsQueries": len(cfg.get("news_queries", [])),
        "newsCollected": len(data.get("news", [])),
        "groups": groups,
    }


def track_zero_streaks(prev, rows, today):
    """그룹별 '수집 0건' 연속 기록 — 하루짜리 실패는 알림 대상이 아니고, 며칠째 0건이면
    (Yahoo/yfinance 변경 등) 사람이 봐야 하므로 health_check가 이 값으로 판단한다.
    rows: {그룹: (라벨, 받은 수, 기대 수)}. 같은 KST 날짜 재실행은 한 번만 센다.
    반환: 0건인 그룹만 {그룹: {label, expected, days, since, last}}."""
    out = {}
    for key, (label, received, expected) in rows.items():
        if not expected or received:
            continue
        p = (prev or {}).get(key) or {}
        days = p.get("days", 1) if p.get("last") == today else p.get("days", 0) + 1
        out[key] = {"label": label, "expected": expected, "days": days,
                    "since": p.get("since") or today, "last": today}
    return out


def write_quality(cfg, data, breadth_received=None):
    """품질 메타데이터를 별도 JSON으로 기록해 페이지가 브리핑 본문과 독립적으로 읽게 한다.
    breadth_received: 섹터 ETF 바스켓의 이번 수집 건수(폴백 재사용 전) — 연속 0건 추적용."""
    path = ROOT / "site" / "src" / "data" / "quality.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    quality = build_quality(cfg, data)
    rows = {key: (g["label"], g["received"], g["expected"]) for key, g in quality["groups"].items()}
    for key, label in (("breadth_us", "미국 섹터 ETF"), ("breadth_kr", "한국 섹터 ETF")):
        if breadth_received and key in breadth_received:
            rows[key] = (label, breadth_received[key], len(cfg.get(key, [])))
    quality["zeroStreaks"] = track_zero_streaks(prev.get("zeroStreaks"), rows, data["date_kst"])
    for s in quality["zeroStreaks"].values():
        print(f"[warn] {s['label']} 수집 0/{s['expected']} — {s['days']}일 연속({s['since']}~)")
    path.write_text(json.dumps(quality, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    partial = sum(1 for group in quality["groups"].values() if group["status"] == "partial")
    print(f"quality: {len(quality['groups']) - partial}/{len(quality['groups'])} group(s) complete")
    return quality


def repair_kr_closes(history, series, max_gap=0.3):
    """예전 실행이 한국장 중에 돌아 '오늘 장중가'를 그날 종가로 저장한 한국 시장 시세를 Yahoo 확정
    종가로 고친다(자가 치유 — 추가 네트워크 없이 이번 실행의 series 일봉을 재사용).
    series: 이번 실행에서 새로 받은 완결 일봉 {ticker: [[YYYY-MM-DD, close], ...]}.
    대상은 수집일과 시세 기준일이 같은 한국 티커뿐(장 시작 전 수집분은 이미 전일 확정 종가).
    종가가 다를 때만 고치고, 차이가 30%(가격제한폭)를 넘으면 액면분할 등 기준 변경으로 보고 건너뛴다."""
    fixed = 0
    for snap in history:
        for q in snap.get("quotes", []):
            ticker = q.get("ticker")
            if not _is_kr_market(ticker) or q.get("date") != snap.get("date"):
                continue
            arr = (series or {}).get(ticker) or []
            i = next((k for k, (d, _) in enumerate(arr) if d == q["date"]), None)
            if not i:  # 해당 날짜가 없거나 전일 봉이 없으면 등락률을 다시 셀 수 없다
                continue
            close, prev = arr[i][1], arr[i - 1][1]
            if close == q["close"] or not prev or abs(close / q["close"] - 1) > max_gap:
                continue
            q["close"], q["change_pct"] = close, round((close / prev - 1) * 100, 2)
            fixed += 1
    if fixed:
        print(f"[fix] history: 장중가로 저장됐던 한국 시장 시세 {fixed}건을 Yahoo 확정 종가로 교정")
    return fixed


def update_history(data, keep_days=120, series=None):
    """site/src/data/history.json에 일별 스냅샷 누적 (대시보드 카드·차트용).
    series(이번 실행의 완결 일봉)가 있으면 과거 장중가 저장분을 확정 종가로 교정한다."""
    path = ROOT / "site" / "src" / "data" / "history.json"
    history = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            history = []
    # 과거에 잘못 기록된 NaN 항목까지 함께 정리해 자가 치유한다.
    history = [_clean_snapshot(h) for h in history]
    repair_kr_closes(history, series)
    quotes = data["indices"] + data["watchlist_us"] + data["watchlist_kr"]
    snap = _clean_snapshot({"date": data["date_kst"], "quotes": quotes})
    history = [h for h in history if h["date"] != snap["date"]] + [snap]
    history = history[-keep_days:]
    path.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False: 혹시라도 NaN이 남으면 조용히 깨진 JSON을 쓰는 대신 즉시 실패시킨다.
    path.write_text(json.dumps(history, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"history: {len(history)} day(s)")


def build_series(cfg, period="1y", now=None):
    """차트용 종목별 일봉 종가 시계열을 site/src/data/series.json에 기록.
    스파크라인·지수 추이 차트가 '작업 이후'가 아닌 실제 과거 데이터를 쓰도록 한다.
    history와 같은 기준(한국 시장은 장 마감 확정 전 오늘 봉 제외)을 쓴다.
    반환: 이번 실행에서 새로 받은 시계열(기존 파일 병합 전) — history 교정용."""
    path = ROOT / "site" / "src" / "data" / "series.json"
    items = cfg["indices"] + cfg["watchlist_us"] + cfg["watchlist_kr"]
    out = {}
    for item in items:
        t = item["ticker"]
        try:
            hist = _completed_bars(_hist(t, period=period), t, now)
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
    fresh = dict(out)
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
    return fresh


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
    네트워크 실패로 일부가 비어도 직전 sentiment.json 값을 유지하되, 재사용한 섹터는
    usStale/krStale와 원래 기준일(usAsOf/krAsOf)을 남겨 옛 값이 오늘 것처럼 보이지 않게 한다.
    반환: 이번 실행의 실제 수집 건수(연속 0건 추적용)."""
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

    today = data["date_kst"]
    out = {
        "asOf": today,
        "fng": fng or prev.get("fng"),
    }
    for key, fresh in (("us", us), ("kr", kr)):
        if fresh:
            out[key], out[f"{key}AsOf"], out[f"{key}Stale"] = fresh, today, False
            continue
        old = prev.get(key, [])
        out[key] = old
        out[f"{key}AsOf"] = (prev.get(f"{key}AsOf") or prev.get("asOf")) if old else None
        out[f"{key}Stale"] = bool(old)
        if old:
            print(f"[warn] sentiment {key}: 이번 수집 0건 — {out[f'{key}AsOf']} 기준 값 재사용(stale)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"sentiment: us={len(us)}/{len(out['us'])} kr={len(kr)}/{len(out['kr'])} fng={'ok' if out['fng'] else 'none'}")
    return {"breadth_us": len(us), "breadth_kr": len(kr)}


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


def build_event_ledger(data, keep_days=120, per_day=12):
    """수집 시점의 헤드라인을 날짜별 이벤트 기록으로 보존한다.

    뉴스 기사 제목·출처·카테고리·링크만 기록하며, 가격 변동의 원인이나 중요도를
    자동 추정하지 않는다. 같은 KST 날짜에는 최신 수집 결과로 교체해 장중 재실행에도
    한 날짜의 이벤트 묶음만 남긴다.
    """
    path = ROOT / "site" / "src" / "data" / "event_ledger.json"
    previous = []
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
        except Exception:
            previous = []
    seen, items = set(), []
    for raw in data.get("news", []):
        title, parsed_source = _split_source(raw.get("title", ""))
        source = raw.get("source") or parsed_source
        if not title or title in seen:
            continue
        seen.add(title)
        items.append({
            "title": title,
            "source": source,
            "link": raw.get("link", ""),
            "pub": raw.get("pub", ""),
            "category": raw.get("category") or raw.get("cat") or _news_category(raw.get("query", "")),
        })
        if len(items) >= per_day:
            break
    entry = {
        "date": data["date_kst"],
        "generatedAt": data.get("generated_at", ""),
        "items": items,
    }
    entries = [record for record in previous if record.get("date") != entry["date"]] + [entry]
    entries = sorted((record for record in entries if record.get("date")), key=lambda record: record["date"])[-keep_days:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"event ledger: {len(entries)} day(s), latest={len(items)} item(s)")


def main():
    cfg = load_config()
    now = datetime.now(KST)
    data = {
        "generated_at": now.isoformat(),
        "date_kst": now.strftime("%Y-%m-%d"),
        "weekday_kr": "월화수목금토일"[now.weekday()],
        "indices": fetch_quotes(cfg["indices"], now),
        "watchlist_us": fetch_quotes(cfg["watchlist_us"], now),
        "watchlist_kr": fetch_quotes(cfg["watchlist_kr"], now),
        "news": fetch_news(cfg["news_queries"], cfg.get("news_per_query", 5), cfg.get("news_max_age_hours", 72)),
    }
    out = ROOT / "data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    # series를 먼저 받아, 같은 완결 일봉으로 history의 과거 장중가 저장분까지 교정한다.
    series = build_series(cfg, now=now)
    if data["indices"] or data["watchlist_us"] or data["watchlist_kr"]:
        update_history(data, series=series)
    breadth = build_sentiment(cfg, data)
    build_news(data)
    build_event_ledger(data)
    write_quality(cfg, data, breadth)
    print(f"saved {out} — quotes:{len(data['indices'])+len(data['watchlist_us'])+len(data['watchlist_kr'])}, news:{len(data['news'])}")


if __name__ == "__main__":
    main()
