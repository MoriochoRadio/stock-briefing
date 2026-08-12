"""stock-briefing 핵심 파이프라인 단위 테스트.

외부 API나 LLM 키 없이 데이터 품질 메타데이터와 근거 인용 안전장치를 검증한다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_data  # noqa: E402
import generate  # noqa: E402
import intraday_kr  # noqa: E402


class PipelineQualityTests(unittest.TestCase):
    def test_quality_tracks_coverage_and_asof_dates(self):
        cfg = {
            "indices": [{"ticker": "^KS11"}, {"ticker": "KRW=X"}],
            "watchlist_us": [{"ticker": "NVDA"}],
            "watchlist_kr": [{"ticker": "005930.KS"}, {"ticker": "000660.KS"}],
            "news_queries": [{"q": "반도체"}],
        }
        data = {
            "generated_at": "2026-08-12T07:10:00+09:00",
            "date_kst": "2026-08-12",
            "indices": [{"ticker": "^KS11", "date": "2026-08-11"}],
            "watchlist_us": [{"ticker": "NVDA", "date": "2026-08-11"}],
            "watchlist_kr": [{"ticker": "005930.KS", "date": "2026-08-12"}],
            "news": [{"title": "테스트 기사"}],
        }

        quality = fetch_data.build_quality(cfg, data)
        self.assertEqual(quality["groups"]["indices"]["coveragePct"], 50.0)
        self.assertEqual(quality["groups"]["watchlist_us"]["status"], "complete")
        self.assertEqual(quality["groups"]["watchlist_kr"]["asOfDates"], ["2026-08-12"])
        self.assertEqual(quality["newsCollected"], 1)

    def test_evidence_keeps_known_ids_and_removes_unknown_ids(self):
        data = {
            "news": [
                {
                    "title": "반도체 수요 회복 기대 - 테스트경제",
                    "link": "https://example.com/a",
                    "query": "반도체",
                },
                {
                    "title": "반도체 수요 회복 기대 - 다른매체",
                    "link": "https://example.com/b",
                    "query": "반도체",
                },
            ]
        }
        evidence = generate.build_news_evidence(data)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["source"], "테스트경제")

        rendered = generate.append_evidence_references("기사 근거 [N01], 가짜 근거 [N99]", evidence)
        self.assertIn("[N01]", rendered)
        self.assertNotIn("[N99]", rendered)
        self.assertIn("## 🔗 기사 근거", rendered)
        self.assertIn("https://example.com/a", rendered)

    def test_intraday_quality_marks_delayed_partial_data(self):
        stocks = [{"asof": "2026-08-11"}]
        market = {"kospi": {"close": 1}, "krw": None}
        now = intraday_kr.datetime(2026, 8, 12, 10, 0, tzinfo=intraday_kr.KST)

        quality = intraday_kr.snapshot_quality(now, stocks, market, delayed=True)
        self.assertEqual(quality["primaryCoveragePct"], 50.0)
        self.assertEqual(quality["marketCoveragePct"], 50.0)
        self.assertTrue(quality["delayed"])
        self.assertEqual(quality["primaryAsOfDates"], ["2026-08-11"])


if __name__ == "__main__":
    unittest.main()
