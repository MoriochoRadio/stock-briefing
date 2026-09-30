"""시세·뉴스 '신선도' 안전장치 단위 테스트(네트워크·LLM 키 불필요).

- 뉴스: 최근 N시간 이내 기사만, 0건이면 경고
- 한국 시장: 장 마감 확정 전 오늘 봉(장중가)은 종가 기록(history·series)에서 제외, 과거 저장분 교정
- 인트라데이 프롬프트: 지표 None이어도 포맷이 죽지 않음
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_data  # noqa: E402
import intraday_kr  # noqa: E402

KST = fetch_data.KST


def kst(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


def daily(dates, closes, tz="Asia/Seoul"):
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(tz)
    c = [float(x) for x in closes]
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1000.0] * len(c)}, index=idx)


def rss(*pubs):
    items = "".join(
        f"<item><title>기사{i} - 매체</title><link>https://example.com/{i}</link>"
        + (f"<pubDate>{p}</pubDate>" if p is not None else "")
        + "</item>"
        for i, p in enumerate(pubs)
    )
    return f"<rss><channel>{items}</channel></rss>".encode("utf-8")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class NewsFreshnessTests(unittest.TestCase):
    NOW = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)

    def _fetch(self, bodies, queries, per_query=5, max_age_hours=72):
        urls = []

        def fake_urlopen(req, timeout=20):
            urls.append(req.full_url)
            return _Resp(bodies[len(urls) - 1])

        original = fetch_data.urllib.request.urlopen
        fetch_data.urllib.request.urlopen = fake_urlopen
        log = io.StringIO()
        try:
            with contextlib.redirect_stdout(log):
                out = fetch_data.fetch_news(queries, per_query, max_age_hours, now=self.NOW)
        finally:
            fetch_data.urllib.request.urlopen = original
        return out, urls, log.getvalue()

    def test_keeps_only_items_within_window(self):
        pub = lambda delta: format_datetime(self.NOW - delta, usegmt=True)  # noqa: E731
        body = rss(
            pub(timedelta(hours=1)),                      # 유지
            pub(timedelta(days=152)),                     # 152일 전 리포트 — 제외
            pub(timedelta(hours=72)),                     # 경계(정확히 72h) — 유지
            pub(timedelta(hours=72, seconds=1)),          # 경계 직후 — 제외
            "",                                           # 날짜 없음 — 제외
            "not a date",                                 # 형식 오류 — 제외
            None,                                         # pubDate 태그 없음 — 제외
            "Tue, 29 Sep 2026 20:29:59 GMT",              # 3.5시간 전 — 유지
        )
        out, urls, log = self._fetch([body], [{"q": "삼성전자 SK하이닉스 반도체", "lang": "ko"}])
        self.assertEqual([n["link"] for n in out], ["https://example.com/0", "https://example.com/2", "https://example.com/7"])
        self.assertTrue(all(n["query"] == "삼성전자 SK하이닉스 반도체" for n in out))  # 카테고리 매핑용 원래 검색어 유지
        self.assertIn("when%3A3d", urls[0])
        self.assertIn("제외", log)

    def test_per_query_cap_counts_only_fresh_items(self):
        fresh = format_datetime(self.NOW - timedelta(hours=2), usegmt=True)
        old = format_datetime(self.NOW - timedelta(days=20), usegmt=True)
        out, _, _ = self._fetch([rss(old, old, fresh, fresh, fresh)], [{"q": "Nvidia stock", "lang": "en"}], per_query=2)
        self.assertEqual([n["link"] for n in out], ["https://example.com/2", "https://example.com/3"])

    def test_zero_after_filter_warns_instead_of_silent(self):
        old = format_datetime(self.NOW - timedelta(days=15), usegmt=True)
        out, _, log = self._fetch([rss(old, old)], [{"q": "HBM 메모리 반도체 업황", "lang": "ko"}])
        self.assertEqual(out, [])
        self.assertIn("[warn] news 'HBM 메모리 반도체 업황': 최근 72h 이내 기사 0건", log)
        self.assertIn("[warn] news: 최근 72h 이내 기사 0건", log)


class KoreanCloseTests(unittest.TestCase):
    DATES = ["2026-09-28", "2026-09-29", "2026-09-30"]
    CLOSES = [270000, 272500, 269000]  # 09-30 = 장중가

    def test_unfinished_kr_bar_dropped_by_kst_time(self):
        df = daily(self.DATES, self.CLOSES)
        cases = [
            (kst(2026, 9, 30, 8, 50), "2026-09-29"),   # 개장 전 생성된 오늘 봉
            (kst(2026, 9, 30, 10, 16), "2026-09-29"),  # 지연된 모닝 cron(장중)
            (kst(2026, 9, 30, 15, 45), "2026-09-29"),  # 마감 직후(Yahoo 지연 반영 전)
            (kst(2026, 9, 30, 16, 59), "2026-09-29"),
            (kst(2026, 9, 30, 17, 0), "2026-09-30"),   # 확정 이후
            (kst(2026, 10, 1, 9, 30), "2026-09-30"),   # 다음 날: 어제 봉은 완결
        ]
        for now, expected in cases:
            with self.subTest(now=now.isoformat()):
                with contextlib.redirect_stdout(io.StringIO()):
                    for ticker in ("005930.KS", "^KS11", "035720.KQ"):
                        out = fetch_data._completed_bars(df, ticker, now)
                        self.assertEqual(str(out.index[-1].date()), expected)

    def test_non_kr_tickers_untouched(self):
        now = kst(2026, 9, 30, 10, 16)
        for ticker, tz in (("NVDA", "America/New_York"), ("KRW=X", "Europe/London")):
            df = daily(self.DATES, self.CLOSES, tz=tz)
            self.assertEqual(len(fetch_data._completed_bars(df, ticker, now)), 3)

    def _with_hist(self, frames, fn):
        original = fetch_data._hist
        fetch_data._hist = lambda ticker, period="5d": frames.get(ticker)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return fn()
        finally:
            fetch_data._hist = original

    def test_quotes_and_series_share_completed_close(self):
        frames = {
            "005930.KS": daily(self.DATES, self.CLOSES),
            "NVDA": daily(["2026-09-28", "2026-09-29"], [180, 181], tz="America/New_York"),
        }
        items = [{"ticker": "005930.KS", "name": "삼성전자"}, {"ticker": "NVDA", "name": "엔비디아"}]
        now = kst(2026, 9, 30, 10, 16)
        quotes = self._with_hist(frames, lambda: fetch_data.fetch_quotes(items, now))
        self.assertEqual(quotes[0], {"name": "삼성전자", "ticker": "005930.KS", "close": 272500.0,
                                     "change_pct": round((272500 / 270000 - 1) * 100, 2), "date": "2026-09-29"})
        self.assertEqual(quotes[1]["date"], "2026-09-29")

        with tempfile.TemporaryDirectory() as directory:
            old_root = fetch_data.ROOT
            fetch_data.ROOT = Path(directory)
            try:
                cfg = {"indices": [], "watchlist_us": items[1:], "watchlist_kr": items[:1]}
                fresh = self._with_hist(frames, lambda: fetch_data.build_series(cfg, now=now))
                written = json.loads((Path(directory) / "site/src/data/series.json").read_text(encoding="utf-8"))
            finally:
                fetch_data.ROOT = old_root
        self.assertEqual(fresh["005930.KS"][-1], ["2026-09-29", 272500.0])
        self.assertEqual(written["005930.KS"][-1], ["2026-09-29", 272500.0])

    def test_repair_replaces_intraday_close_saved_as_close(self):
        series = {
            "005930.KS": [["2026-09-28", 270000.0], ["2026-09-29", 272500.0], ["2026-09-30", 268750.0]],
            "^KS11": [["2026-09-28", 6889.74], ["2026-09-29", 6870.81]],
            "NVDA": [["2026-09-28", 180.0], ["2026-09-29", 181.0]],
        }
        history = [
            {"date": "2026-09-29", "quotes": [
                {"ticker": "005930.KS", "name": "삼성전자", "close": 273250, "change_pct": 1.2, "date": "2026-09-29"},  # 장중가
                {"ticker": "^KS11", "name": "코스피", "close": 6865.43, "change_pct": -0.35, "date": "2026-09-29"},
                {"ticker": "NVDA", "name": "엔비디아", "close": 175.0, "change_pct": 0.1, "date": "2026-09-29"},  # 미국은 대상 아님
            ]},
            {"date": "2026-09-30", "quotes": [
                {"ticker": "005930.KS", "name": "삼성전자", "close": 272500, "change_pct": 0.93, "date": "2026-09-29"},  # 개장 전 수집
            ]},
            {"date": "2026-09-25", "quotes": [
                {"ticker": "005930.KS", "name": "삼성전자", "close": 285500, "change_pct": 3.25, "date": "2026-09-25"},  # series에 없음
            ]},
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            fixed = fetch_data.repair_kr_closes(history, series)
        self.assertEqual(fixed, 2)
        samsung, kospi, nvda = history[0]["quotes"]
        self.assertEqual((samsung["close"], samsung["change_pct"]), (272500.0, 0.93))
        self.assertEqual((kospi["close"], kospi["change_pct"]), (6870.81, round((6870.81 / 6889.74 - 1) * 100, 2)))
        self.assertEqual(nvda["close"], 175.0)
        self.assertEqual(history[1]["quotes"][0]["close"], 272500)
        self.assertEqual(history[2]["quotes"][0]["close"], 285500)

    def test_repair_skips_split_sized_gaps_and_is_idempotent(self):
        series = {"005930.KS": [["2026-09-28", 5400.0], ["2026-09-29", 5450.0]]}  # 50:1 분할 후 기준
        history = [{"date": "2026-09-29", "quotes": [
            {"ticker": "005930.KS", "name": "삼성전자", "close": 273250, "change_pct": 1.2, "date": "2026-09-29"}]}]
        self.assertEqual(fetch_data.repair_kr_closes(history, series), 0)
        self.assertEqual(history[0]["quotes"][0]["close"], 273250)
        self.assertEqual(fetch_data.repair_kr_closes(history, None), 0)

    def test_update_history_repairs_past_and_writes_completed_today(self):
        with tempfile.TemporaryDirectory() as directory:
            old_root = fetch_data.ROOT
            fetch_data.ROOT = Path(directory)
            try:
                path = Path(directory) / "site/src/data/history.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps([{"date": "2026-09-29", "quotes": [
                    {"ticker": "000660.KS", "name": "SK하이닉스", "close": 1771000, "change_pct": 0.17, "date": "2026-09-29"}]}]), encoding="utf-8")
                data = {"date_kst": "2026-09-30", "indices": [], "watchlist_us": [], "watchlist_kr": [
                    {"ticker": "000660.KS", "name": "SK하이닉스", "close": 1765000.0, "change_pct": -0.17, "date": "2026-09-29"}]}
                series = {"000660.KS": [["2026-09-28", 1768000.0], ["2026-09-29", 1765000.0]]}
                with contextlib.redirect_stdout(io.StringIO()):
                    fetch_data.update_history(data, series=series)
                saved = json.loads(path.read_text(encoding="utf-8"))
            finally:
                fetch_data.ROOT = old_root
        self.assertEqual([s["date"] for s in saved], ["2026-09-29", "2026-09-30"])
        self.assertEqual(saved[0]["quotes"][0]["close"], 1765000.0)
        self.assertEqual(saved[0]["quotes"][0]["change_pct"], round((1765000 / 1768000 - 1) * 100, 2))
        self.assertEqual(saved[1]["quotes"][0]["date"], "2026-09-29")


class IntradayPromptGuardTests(unittest.TestCase):
    FULL = {"name": "삼성전자", "close": 271500.0, "change_pct": -0.37, "vs_open_pct": 0.18, "trend": "혼조",
            "vs_sma20_pct": 1.23, "rsi14": 55.4, "rsi_state": "강세권", "rsi_prev": 54.1, "macd_dir": "상승",
            "range_pos": 0.81, "vol_ratio": 1.07, "ret_20d": 3.2, "ret_60d": 12.5}

    def test_full_values_keep_previous_format(self):
        s = self.FULL
        expected = (
            f"- {s['name']}: 현재 {s['close']:,} ({s['change_pct']:+.2f}%, 개장대비 {s['vs_open_pct']:+.2f}%) "
            f"| 추세 {s['trend']}, 20일선대비 {s['vs_sma20_pct']:+.1f}% "
            f"| RSI {s['rsi14']:.1f}({s['rsi_state']}, 전일 {s['rsi_prev']:.1f}) "
            f"| MACD히스토 {s['macd_dir']} "
            f"| 52주 위치 {s['range_pos']*100:.0f}%, 거래량 평소의 {s['vol_ratio']:.2f}배 "
            f"| 20일 {s['ret_20d']:+.1f}%, 60일 {s['ret_60d']:+.1f}%"
        )
        self.assertEqual(intraday_kr.fmt_stock_for_prompt(s), expected)

    def test_none_indicators_do_not_crash_prompts_or_fallback(self):
        s = dict(self.FULL, vs_open_pct=None, rsi_prev=None, range_pos=None, vol_ratio=None,
                 ret_20d=None, ret_60d=None, vs_sma20_pct=None, rsi14=None)
        line = intraday_kr.fmt_stock_for_prompt(s)
        self.assertIn("개장대비 n/a", line)
        self.assertIn("52주 위치 n/a", line)
        self.assertIn("거래량 평소의 n/a", line)
        self.assertIn("RSI n/a", line)
        intraday_kr.light_prompt("개장", "10:00", [s], None)
        intraday_kr.close_prompt("15:40", [s], None, [])
        text = intraday_kr.fallback_text("open", [s, dict(s, change_pct=None)], None)
        self.assertIn("개장대비 n/a", text)
        self.assertIn("반도체 평균 등락 -0.37%", text)


if __name__ == "__main__":
    unittest.main()
