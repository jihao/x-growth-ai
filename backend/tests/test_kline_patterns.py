from __future__ import annotations

import unittest

from backend.analysis.kline_patterns import recognize_kline_patterns, summarize_patterns


class KlinePatternTests(unittest.TestCase):
    def test_bullish_engulfing_pattern(self) -> None:
        rows = [
            {"date": "2026-06-01", "open": 10.1, "high": 10.3, "low": 9.9, "close": 10.0},
            {"date": "2026-06-02", "open": 10.0, "high": 10.2, "low": 9.7, "close": 9.8},
            {"date": "2026-06-03", "open": 9.7, "high": 10.4, "low": 9.6, "close": 10.3},
        ]

        patterns = recognize_kline_patterns(rows)
        names = {item["name"] for item in patterns}

        self.assertIn("看涨吞没", names)
        self.assertEqual(summarize_patterns(patterns)["bias"], "bullish")

    def test_sideways_range_pattern(self) -> None:
        rows = []
        for idx in range(12):
            close = 10 + (0.08 if idx % 2 else -0.05)
            rows.append({"date": f"2026-06-{idx + 1:02d}", "open": 10.0, "high": 10.2, "low": 9.8, "close": close})

        patterns = recognize_kline_patterns(rows)
        names = {item["name"] for item in patterns}

        self.assertIn("横盘整理", names)


if __name__ == "__main__":
    unittest.main()
