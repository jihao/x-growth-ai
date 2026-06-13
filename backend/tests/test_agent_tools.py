from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.agent_tools import TOOL_NAMES, run_tool, tool_definitions
from test_api_services import _fixture_context


class AgentToolTests(unittest.TestCase):
    def test_tool_definitions_are_openai_function_shapes(self) -> None:
        definitions = tool_definitions()

        self.assertEqual(len(definitions), len(TOOL_NAMES))
        self.assertIn("market_overview", TOOL_NAMES)
        self.assertIn("stock_indicators", TOOL_NAMES)
        self.assertIn("kline_patterns", TOOL_NAMES)
        self.assertIn("search_strategy", TOOL_NAMES)
        self.assertIn("stock_agent_brief", TOOL_NAMES)
        self.assertTrue(all(item["type"] == "function" for item in definitions))
        self.assertTrue(all("parameters" in item["function"] for item in definitions))

    def test_run_tool_uses_existing_service_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _fixture_context(Path(tmp))

            health = run_tool("health_status", ctx=ctx)
            overview = run_tool("market_overview", {"date": "2026-06-10"}, ctx=ctx)
            indicators = run_tool("stock_indicators", {"code": "300001"}, ctx=ctx)
            patterns = run_tool("kline_patterns", {"code": "300001"}, ctx=ctx)
            strategy = run_tool("search_strategy", {"query": "放量突破 MA20", "top_k": 1}, ctx=ctx)
            brief = run_tool("stock_agent_brief", {"code": "300001"}, ctx=ctx)

            self.assertTrue(health["ok"])
            self.assertEqual(health["result"]["stocks"], 3)
            self.assertTrue(overview["ok"])
            self.assertEqual(overview["result"]["date"], "2026-06-09")
            self.assertTrue(indicators["ok"])
            self.assertIn("analysis", indicators["result"])
            self.assertTrue(patterns["ok"])
            self.assertIn("summary", patterns["result"])
            self.assertTrue(strategy["ok"])
            self.assertEqual(strategy["result"]["results"][0]["filename"], "01-放量突破战法.md")
            self.assertTrue(brief["ok"])
            self.assertIn("status", brief["result"])
            self.assertIn("next_steps", brief["result"])
            self.assertIn("invalidation", brief["result"])
            self.assertIn("matched_strategies", brief["result"])
            self.assertIn("engine", brief["result"])

    def test_run_tool_validates_required_and_unknown_arguments(self) -> None:
        missing = run_tool("stock_indicators", {})
        unknown = run_tool("market_overview", {"date": "2026-06-10", "extra": True})
        missing_tool = run_tool("not_a_tool", {})

        self.assertFalse(missing["ok"])
        self.assertIn("missing required", missing["error"])
        self.assertFalse(unknown["ok"])
        self.assertIn("unknown argument", unknown["error"])
        self.assertFalse(missing_tool["ok"])
        self.assertIn("available_tools", missing_tool)


if __name__ == "__main__":
    unittest.main()
