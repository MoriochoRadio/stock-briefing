"""최신 세션 봉 누락(Yahoo가 종가 NaN으로 주거나 봉을 빼고 줌) 대비 단위 테스트 — 네트워크·LLM 불필요.

실제 사례(2026-10-14~28, 11-04~05): 미국 개별주·섹터 ETF의 직전 세션 봉이 종가 NaN, 코스피 지수는
어제 봉이 아예 빠짐 → 기준일이 하루 밀린 값이 '밤사이' 값처럼 쓰이고(10-13엔 인트라데이 등락률이
이틀 전 대비로 계산). 여기선 합성 DataFrame으로 재시도·기준일 표기·등락 기준 검증을 확인한다.
"""
import contextlib
import io
import math
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_data  # noqa: E402
import generate  # noqa: E402
import intraday_kr  # noqa: E402

KST = fetch_data.KST
NAN = float("nan")


def kst(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


def daily(dates, closes, tz="America/New_York"):
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(tz)
    c = [float(x) for x in closes]
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1000.0] * len(c)}, index=idx)


class FakeYahoo:
    """yf.Ticker 대역. responses[(ticker, period)] 또는 [(ticker, "*")] = [df, ...]를 호출 순서대로
    돌려준다(목록 끝나면 마지막 것 반복). meta[ticker] = (period="1d" 응답 df, chartPreviousClose)."""

    def __init__(self, responses, meta=None):
        self.responses, self.meta, self.calls = responses, meta or {}, []

    def __call__(self, ticker):
        fake = self

        class _T:
            history_metadata = {}

            def history(self, period="5d", auto_adjust=False):
                fake.calls.append((ticker, period))
                if period == "1d" and ticker in fake.meta:
                    df, prev = fake.meta[ticker]
                    self.history_metadata = {"chartPreviousClose": prev}
                    return df
                seq = fake.responses.get((ticker, period)) or fake.responses.get((ticker, "*")) or [None]
                n = sum(1 for c in fake.calls if c == (ticker, period))
                return seq[min(n, len(seq)) - 1]

        return _T()


class _Patch:
    """yf.Ticker·time.sleep 대역 + 실행 단위 상태 초기화 + 로그 캡처."""

    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.orig = (fetch_data.yf.Ticker, fetch_data.time.sleep)
        fetch_data.yf.Ticker = self.fake
        fetch_data.time.sleep = lambda s: None
        fetch_data._GAP_UNRESOLVED.clear()
        self.log = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.log)
        self.redirect.__enter__()
        return self

    def __exit__(self, *exc):
        self.redirect.__exit__(*exc)
        fetch_data.yf.Ticker, fetch_data.time.sleep = self.orig
        fetch_data._GAP_UNRESOLVED.clear()
        return False


# 2026-11-05 11:21 KST(= 11-04 21:21 EST) — 실제로 NVDA 등 11-04 봉이 종가 NaN이던 실행 시각
RUN = kst(2026, 11, 5, 11, 21)
US_DATES = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"]


class ExpectedSessionTests(unittest.TestCase):
    def test_calendar(self):
        cases = [
            ("NVDA", kst(2026, 11, 5, 11, 21), date(2026, 11, 4)),
            ("^GSPC", kst(2026, 11, 3, 7, 10), date(2026, 11, 2)),       # 화 07:10 → 월 미국장
            ("NVDA", kst(2026, 11, 2, 7, 10), date(2026, 10, 30)),       # 월 07:10 → 금 미국장
            ("NVDA", kst(2026, 11, 5, 6, 30), date(2026, 11, 3)),        # 11-04 16:30 ET: 아직 확정 전
            ("005930.KS", kst(2026, 11, 5, 11, 21), date(2026, 11, 4)),  # 장중 → 어제
            ("^KS11", kst(2026, 11, 5, 17, 30), date(2026, 11, 5)),      # 확정 이후 → 오늘
            ("XLK", kst(2026, 11, 8, 12, 0), date(2026, 11, 6)),         # 일요일 → 금
        ]
        for ticker, now, expected in cases:
            with self.subTest(ticker=ticker, now=now.isoformat()):
                self.assertEqual(fetch_data._expected_session(ticker, now), expected)
        self.assertIsNone(fetch_data._expected_session("KRW=X", RUN))


class HistRetryTests(unittest.TestCase):
    def test_nan_latest_bar_recovered_by_retry(self):
        bad = daily(US_DATES, [202.06, 206.69, 201.0, NAN])
        good = daily(US_DATES, [202.06, 206.69, 201.0, 207.5])
        fake = FakeYahoo({("NVDA", "5d"): [bad, bad], ("NVDA", "1mo"): [good]})
        with _Patch(fake) as p:
            df = fetch_data._hist("NVDA", "5d", now=RUN)
        self.assertEqual(str(df.index[-1].date()), "2026-11-04")
        self.assertEqual(float(df["Close"].iloc[-1]), 207.5)
        self.assertNotIn("missing_session", df.attrs)
        # 재시도 2회(간격 GAP_BACKOFF), 마지막은 더 넓은 기간
        self.assertEqual(fake.calls, [("NVDA", "5d"), ("NVDA", "5d"), ("NVDA", "1mo")])
        self.assertIn("[gap-fixed] NVDA", p.log.getvalue())

    def test_still_missing_keeps_previous_bar_with_true_date_and_skips_peers(self):
        bad = daily(US_DATES, [202.06, 206.69, 201.0, NAN])
        fake = FakeYahoo({("NVDA", "*"): [bad], ("AMD", "*"): [bad]})
        with _Patch(fake) as p:
            df = fetch_data._hist("NVDA", "5d", now=RUN)
            df2 = fetch_data._hist("AMD", "5d", now=RUN)
        self.assertEqual(str(df.index[-1].date()), "2026-11-03")  # 직전 봉, 진짜 날짜
        self.assertEqual(df.attrs["missing_session"], "2026-11-04")
        self.assertEqual(df2.attrs["missing_session"], "2026-11-04")
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "NVDA"), 3)  # 원 요청 + 재시도 2
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "AMD"), 1)   # 같은 시장·세션은 재시도 생략
        self.assertIn("재시도 생략", p.log.getvalue())

    def test_complete_response_makes_single_request(self):
        good = daily(US_DATES, [1, 2, 3, 4])
        fake = FakeYahoo({("NVDA", "5d"): [good]})
        with _Patch(fake):
            df = fetch_data._hist("NVDA", "5d", now=RUN)
        self.assertEqual(len(fake.calls), 1)
        self.assertNotIn("missing_session", df.attrs)

    def test_kr_yesterday_bar_omitted_while_today_present(self):
        # 2026-10-14 10:11 KST 코스피: 10-13 봉이 빠지고 10-12·10-14(장중)만 옴
        bad = daily(["2026-10-08", "2026-10-12", "2026-10-14"], [6625.93, 6384.24, 6050.0], tz="Asia/Seoul")
        fake = FakeYahoo({("^KS11", "*"): [bad]})
        with _Patch(fake):
            df = fetch_data._hist("^KS11", "5d", now=kst(2026, 10, 14, 10, 11))
        self.assertEqual(df.attrs["missing_session"], "2026-10-13")
        self.assertEqual(len(fake.calls), 3)

    def test_fetch_quotes_labels_previous_bar_with_its_own_date(self):
        bad = daily(US_DATES, [202.06, 206.69, 201.0, NAN])
        fake = FakeYahoo({("NVDA", "*"): [bad]})
        with _Patch(fake):
            quotes = fetch_data.fetch_quotes([{"ticker": "NVDA", "name": "엔비디아"}], RUN)
        self.assertEqual(quotes[0]["date"], "2026-11-03")
        self.assertEqual(quotes[0]["close"], 201.0)
        self.assertEqual(quotes[0]["change_pct"], round((201.0 / 206.69 - 1) * 100, 2))


class AnnotateLagTests(unittest.TestCase):
    def _quotes(self):
        # 2026-11-05 실행의 실제 기준일 분포(history.json)
        return [
            {"ticker": "^DJI", "name": "다우", "date": "2026-11-04"},
            {"ticker": "^KS11", "name": "코스피", "date": "2026-11-03"},
            {"ticker": "KRW=X", "name": "원/달러", "date": "2026-11-05"},
            {"ticker": "NVDA", "name": "엔비디아", "date": "2026-11-03"},
            {"ticker": "005930.KS", "name": "삼성전자", "date": "2026-11-04"},
        ]

    def test_marks_only_tickers_behind_their_market(self):
        quotes = self._quotes()
        with contextlib.redirect_stdout(io.StringIO()):
            lagging = fetch_data.annotate_lag(quotes, RUN)
        self.assertEqual([q["ticker"] for q in lagging], ["^KS11", "NVDA"])
        by = {q["ticker"]: q for q in quotes}
        self.assertEqual(by["NVDA"]["expected_date"], "2026-11-04")
        self.assertEqual(by["^KS11"]["expected_date"], "2026-11-04")
        self.assertNotIn("lagging", by["^DJI"])
        self.assertNotIn("lagging", by["KRW=X"])  # 환율은 세션 달력 대상 아님

    def test_market_holiday_is_not_lag(self):
        # 평일 달력상 11-04가 기대 세션이지만 미국 시세 누구도 11-04가 없으면 휴장(또는 전면 누락) — 표시 안 함
        quotes = [{"ticker": "^DJI", "date": "2026-11-03"}, {"ticker": "NVDA", "date": "2026-11-03"}]
        self.assertEqual(fetch_data.annotate_lag(quotes, RUN), [])

    def test_quality_and_prompt_say_true_date(self):
        quotes = self._quotes()
        with contextlib.redirect_stdout(io.StringIO()):
            fetch_data.annotate_lag(quotes, RUN)
        data = {"generated_at": RUN.isoformat(), "date_kst": "2026-11-05", "weekday_kr": "목",
                "indices": [dict(q, close=1.0, change_pct=0.1) for q in quotes[:3]],
                "watchlist_us": [dict(quotes[3], close=201.0, change_pct=-2.75)],
                "watchlist_kr": [dict(quotes[4], close=218000.0, change_pct=-0.68)], "news": []}
        cfg = {"indices": quotes[:3], "watchlist_us": quotes[3:4], "watchlist_kr": quotes[4:],
               "profile": {"style": "테스트"}}
        quality = fetch_data.build_quality(cfg, data)
        self.assertEqual(quality["groups"]["watchlist_us"]["lagging"],
                         [{"ticker": "NVDA", "name": "엔비디아", "asOf": "2026-11-03", "expected": "2026-11-04"}])
        self.assertEqual(quality["groups"]["watchlist_kr"]["lagging"], [])
        prompt, _ = generate.build_prompt(data, cfg)
        lines = prompt.splitlines()
        line = next(x for x in lines if "(NVDA)" in x)
        self.assertIn("기준일 2026-11-03 ⚠ 최신 세션 미수신", line)
        self.assertIn("2026-11-04 세션", line)
        self.assertIn("밤사이 움직임 아님", line)
        self.assertIn("기준일 2026-11-04)", next(x for x in lines if "(^DJI)" in x))
        table = generate.fallback_briefing(data)
        self.assertIn("| 엔비디아 | 201.0 | -2.75% | 2026-11-03 (최신 2026-11-04 세션 미수신) |", table)

    def test_mood_mentions_lagging_etf_dates(self):
        mood = generate.build_mood({"us": [{"name": "기술", "change_pct": 1.0}], "usLagDates": ["2026-11-03"]})
        self.assertIn("2026-11-03 기준 — 최신 세션 미수신", mood)


class ChangeBaseTests(unittest.TestCase):
    def test_consecutive_bars_use_bar_without_network(self):
        df = daily(["2026-11-12", "2026-11-13", "2026-11-16"], [5342.73, 5290.53, 5148.27], tz="Asia/Seoul")
        fake = FakeYahoo({})
        with _Patch(fake):
            self.assertEqual(fetch_data.prev_close_base(df, "^KS11"), (5290.53, "bar"))  # 월요일 → 금요일 봉
        self.assertEqual(fake.calls, [])

    def test_missing_yesterday_uses_yahoo_previous_close(self):
        df = daily(["2026-10-08", "2026-10-12", "2026-10-14"], [6625.93, 6384.24, 6050.0], tz="Asia/Seoul")
        one = daily(["2026-10-14"], [6050.0], tz="Asia/Seoul")
        fake = FakeYahoo({}, meta={"^KS11": (one, 6035.35)})
        with _Patch(fake):
            self.assertEqual(fetch_data.prev_close_base(df, "^KS11"), (6035.35, "meta"))

    def test_meta_for_other_session_is_rejected(self):
        df = daily(["2026-10-08", "2026-10-12", "2026-10-14"], [6625.93, 6384.24, 6050.0], tz="Asia/Seoul")
        one = daily(["2026-10-15"], [6000.0], tz="Asia/Seoul")  # 다른 세션 기준 직전 종가 — 쓰면 안 됨
        fake = FakeYahoo({}, meta={"^KS11": (one, 6050.0)})
        with _Patch(fake):
            self.assertEqual(fetch_data.prev_close_base(df, "^KS11"), (6384.24, "unverified"))

    def test_intraday_quote_and_metrics_use_correct_previous_close(self):
        # 10-13 사례 재현: 오늘(10-14) 장중 봉은 있는데 어제(10-13) 봉이 빠짐 → 예전엔 이틀 전(10-12) 대비로 계산
        df = daily(["2026-10-08", "2026-10-12", "2026-10-14"], [6625.93, 6384.24, 6050.0], tz="Asia/Seoul")
        one = daily(["2026-10-14"], [6050.0], tz="Asia/Seoul")
        fake = FakeYahoo({}, meta={"^KS11": (one, 6035.35)})
        orig = intraday_kr._hist
        intraday_kr._hist = lambda ticker, period="5d", **kw: df
        try:
            with _Patch(fake):
                q = intraday_kr.quote("^KS11")
                m = intraday_kr.verify_change_base(df, "^KS11", {"close": 6050.0, "prev": 6384.24, "change_pct": -5.23})
        finally:
            intraday_kr._hist = orig
        expected = (6050.0 / 6035.35 - 1) * 100
        self.assertTrue(math.isclose(q["change_pct"], expected, rel_tol=1e-9))
        self.assertTrue(math.isclose(m["change_pct"], expected, rel_tol=1e-9))
        self.assertEqual((m["prev"], m["change_base"]), (6035.35, "meta"))


if __name__ == "__main__":
    unittest.main()
