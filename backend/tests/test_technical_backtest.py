from __future__ import annotations

import unittest

import pandas as pd

from backend.backtest.engine import BacktestCostConfig, run_single_backtest
from backend.backtest.indicators import add_technical_indicators
from backend.backtest.strategies import build_strategy_signals


class TechnicalIndicatorTests(unittest.TestCase):
    def test_indicators_add_expected_columns(self) -> None:
        frame = _price_frame(40)

        result = add_technical_indicators(frame)

        for column in ["macd_dif", "macd_dea", "macd_hist", "kdj_k", "kdj_d", "kdj_j", "rsi14"]:
            self.assertIn(column, result.columns)
        self.assertEqual(len(result), 40)
        self.assertTrue(result["macd_dif"].notna().all())
        self.assertTrue(result["kdj_k"].notna().all())

    def test_strategy_signal_does_not_execute_same_day(self) -> None:
        frame = _manual_frame()
        signals = pd.DataFrame(
            {
                "date": frame["date"],
                "signal": ["buy", None, "sell", None],
                "reason": ["test buy", None, "test sell", None],
            }
        )

        result = run_single_backtest(
            frame,
            signals,
            code="600519",
            name="贵州茅台",
            strategy="fixture",
            strategy_label="Fixture",
            costs=BacktestCostConfig(initial_cash=100000, commission_rate=0, min_commission=0, stamp_tax_rate=0),
        )

        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0]["entry_signal_date"], "2026-01-01")
        self.assertEqual(result.trades[0]["entry_date"], "2026-01-02")
        self.assertEqual(result.trades[0]["exit_signal_date"], "2026-01-03")
        self.assertEqual(result.trades[0]["exit_date"], "2026-01-04")
        self.assertEqual(result.trades[0]["entry_price"], 10)
        self.assertEqual(result.trades[0]["exit_price"], 12)


class BacktestEngineTests(unittest.TestCase):
    def test_no_signal_has_no_trades_and_keeps_cash(self) -> None:
        frame = _manual_frame()
        signals = pd.DataFrame({"date": frame["date"], "signal": [None] * len(frame), "reason": [None] * len(frame)})

        result = run_single_backtest(
            frame,
            signals,
            code="000001",
            name="平安银行",
            strategy="fixture",
            strategy_label="Fixture",
            costs=BacktestCostConfig(initial_cash=100000, commission_rate=0, min_commission=0, stamp_tax_rate=0),
        )

        self.assertEqual(result.summary["trade_count"], 0)
        self.assertEqual(result.summary["final_equity"], 100000)
        self.assertEqual(result.trades, [])

    def test_built_in_signals_return_signal_frame(self) -> None:
        frame = add_technical_indicators(_price_frame(60))

        signals = build_strategy_signals(frame, "macd")

        self.assertEqual(list(signals.columns), ["date", "signal", "reason"])
        self.assertEqual(len(signals), len(frame))


def _price_frame(days: int) -> pd.DataFrame:
    rows = []
    for index in range(days):
        close = 10 + index * 0.1 + (index % 5) * 0.03
        rows.append(
            {
                "date": str(pd.Timestamp("2026-01-01") + pd.Timedelta(days=index))[:10],
                "code": "sh.600519",
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 100000,
                "amount": 1000000,
                "tradestatus": "1",
            }
        )
    return pd.DataFrame(rows)


def _manual_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10},
            {"date": "2026-01-02", "open": 10, "high": 11, "low": 9, "close": 11},
            {"date": "2026-01-03", "open": 11, "high": 12, "low": 10, "close": 12},
            {"date": "2026-01-04", "open": 12, "high": 13, "low": 11, "close": 12},
        ]
    )


if __name__ == "__main__":
    unittest.main()
