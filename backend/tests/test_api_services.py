from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backend.api.db import normalize_ts_code
from backend.api.services import ApiContext, health_status, market_overview, screen_candidates, stock_indicators


class ApiServiceTests(unittest.TestCase):
    def test_normalize_ts_code(self) -> None:
        self.assertEqual(normalize_ts_code("300308"), "300308.SZ")
        self.assertEqual(normalize_ts_code("603986"), "603986.SH")
        self.assertEqual(normalize_ts_code("688981"), "688981.SH")
        self.assertEqual(normalize_ts_code("000001.SZ"), "000001.SZ")

    def test_health_and_market_overview_from_fixture_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _fixture_context(Path(tmp))

            health = health_status(ctx)
            overview = market_overview("2026-06-10", ctx)

            self.assertTrue(health["ok"])
            self.assertEqual(health["stocks"], 3)
            self.assertEqual(overview["date"], "2026-06-09")
            self.assertEqual(overview["stock_count"], 3)
            self.assertEqual(overview["up"], 3)

    def test_indicators_and_candidates_from_fixture_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _fixture_context(Path(tmp))

            indicators = stock_indicators("300001", ctx=ctx)
            candidates = screen_candidates("2026-06-10", limit=2, ctx=ctx)

            self.assertGreater(len(indicators["rows"]), 30)
            self.assertIn("macd_dif", indicators["rows"][-1])
            self.assertIn("td_buy_setup", indicators["rows"][-1])
            self.assertLessEqual(len(candidates["rows"]), 2)
            self.assertIn("score", candidates["rows"][0])
            self.assertIn("td_sell_setup", candidates["rows"][0])


def _fixture_context(root: Path) -> ApiContext:
    db_path = root / "database" / "astocks_qfq.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE stocks (ts_code TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE daily_qfq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close_qfq REAL,
                volume INTEGER,
                amount REAL,
                UNIQUE (ts_code, trade_date)
            )
            """
        )
        stocks = [("300001.SZ", "样本成长"), ("600001.SH", "样本价值"), ("000001.SZ", "样本银行")]
        conn.executemany("INSERT INTO stocks(ts_code, name) VALUES (?, ?)", stocks)
        rows = []
        start = date(2026, 4, 1)
        for day in range(1, 71):
            trade_date = (start + timedelta(days=day - 1)).strftime("%Y%m%d")
            for idx, (code, _) in enumerate(stocks):
                base = 10 + idx * 5 + day * (0.18 if idx == 0 else 0.04)
                close = base + (day % 3) * 0.01
                rows.append((code, trade_date, close - 0.1, close + 0.3, close - 0.4, close, 100000 + day, 100000000 + idx * 50000000 + day * 1000000))
        conn.executemany(
            "INSERT INTO daily_qfq(ts_code, trade_date, open, high, low, close_qfq, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return ApiContext(repo_root=root, db_path=db_path)


if __name__ == "__main__":
    unittest.main()
