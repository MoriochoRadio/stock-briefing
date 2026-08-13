"""개인 시장 인텔리전스 확장의 결정론적 데이터 로직을 검증한다."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_data  # noqa: E402
import generate_reviews  # noqa: E402


class ProductExtensionTests(unittest.TestCase):
    def test_event_ledger_preserves_explicit_category_and_replaces_same_day(self):
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            old_root = fetch_data.ROOT
            try:
                fetch_data.ROOT = temp_root
                first = {
                    "date_kst": "2026-08-13",
                    "generated_at": "2026-08-13T07:10:00+09:00",
                    "news": [{"title": "첫 기사", "source": "테스트", "category": "메모리·HBM", "link": "https://example.com/1"}],
                }
                second = {
                    "date_kst": "2026-08-13",
                    "generated_at": "2026-08-13T09:10:00+09:00",
                    "news": [{"title": "교체 기사", "source": "테스트", "category": "AI·수요", "link": "https://example.com/2"}],
                }
                fetch_data.build_event_ledger(first)
                fetch_data.build_event_ledger(second)
                output = json.loads((temp_root / "site/src/data/event_ledger.json").read_text(encoding="utf-8"))
                self.assertEqual(len(output["entries"]), 1)
                self.assertEqual(output["entries"][0]["items"][0]["title"], "교체 기사")
                self.assertEqual(output["entries"][0]["items"][0]["category"], "AI·수요")
            finally:
                fetch_data.ROOT = old_root

    def test_review_return_uses_first_and_last_collected_close(self):
        snapshots = [
            {"date": date(2026, 8, 10), "quotes": [{"ticker": "NVDA", "name": "엔비디아", "close": 100.0}]},
            {"date": date(2026, 8, 12), "quotes": [{"ticker": "NVDA", "name": "엔비디아", "close": 125.0}]},
        ]
        rows = generate_reviews.returns_for(snapshots)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "엔비디아")
        self.assertEqual(rows[0]["return"], 25.0)

    def test_week_group_uses_iso_week_key(self):
        snapshots = [{"date": date(2026, 8, 10), "quotes": []}]
        groups = generate_reviews.group_snapshots(snapshots, "weekly")
        self.assertIn("2026-W33", groups)


if __name__ == "__main__":
    unittest.main()
