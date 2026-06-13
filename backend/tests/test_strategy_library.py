from __future__ import annotations

import unittest

from backend.knowledge.strategy_library import get_strategy, list_strategies, search_strategies


class StrategyLibraryTests(unittest.TestCase):
    def test_list_strategies_loads_imported_library(self) -> None:
        strategies = list_strategies()

        self.assertEqual(len(strategies), 40)
        self.assertEqual(strategies[0]["filename"], "01-放量突破战法.md")
        self.assertIn("放量突破", strategies[0]["title"])

    def test_search_strategy_matches_scenario_terms(self) -> None:
        result = search_strategies("放量突破 MA20 MACD 金叉", top_k=3)

        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["filename"], "01-放量突破战法.md")
        self.assertIn("key_conditions", result["results"][0])

    def test_get_strategy_by_title_or_filename(self) -> None:
        by_title = get_strategy("放量突破战法")
        by_file = get_strategy("01-放量突破战法.md")

        self.assertIsNotNone(by_title)
        self.assertIsNotNone(by_file)
        self.assertEqual(by_title["filename"], by_file["filename"])
        self.assertIn("content", by_title)


if __name__ == "__main__":
    unittest.main()
