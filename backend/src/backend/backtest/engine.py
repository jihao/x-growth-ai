from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BacktestCostConfig:
    initial_cash: float = 100000.0
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005


@dataclass(frozen=True)
class BacktestResult:
    summary: dict[str, Any]
    trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]


def run_single_backtest(
    frame: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    code: str,
    name: str,
    strategy: str,
    strategy_label: str,
    costs: BacktestCostConfig,
) -> BacktestResult:
    data = frame.sort_values("date").reset_index(drop=True)
    signal_by_index = signals.reset_index(drop=True)
    cash = float(costs.initial_cash)
    shares = 0
    open_trade: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []

    for index, row in data.iterrows():
        if index > 0:
            previous_signal = signal_by_index.iloc[index - 1].get("signal")
            previous_reason = signal_by_index.iloc[index - 1].get("reason")
            previous_date = str(data.iloc[index - 1]["date"])
            if previous_signal == "buy" and shares == 0:
                buy = _buy(cash, float(row["open"]), costs)
                if buy["shares"] > 0:
                    cash = buy["cash_after"]
                    shares = buy["shares"]
                    open_trade = {
                        "code": code,
                        "name": name,
                        "strategy": strategy,
                        "strategy_label": strategy_label,
                        "entry_signal_date": previous_date,
                        "entry_date": str(row["date"]),
                        "entry_price": float(row["open"]),
                        "shares": shares,
                        "entry_value": buy["value"],
                        "entry_fee": buy["fee"],
                        "entry_reason": previous_reason,
                    }
            elif previous_signal == "sell" and shares > 0 and open_trade is not None:
                sell = _sell(shares, float(row["open"]), costs)
                cash += sell["cash_delta"]
                trade = _close_trade(open_trade, row, sell, previous_date, previous_reason, costs.initial_cash)
                trades.append(trade)
                shares = 0
                open_trade = None

        close_value = float(row["close"])
        equity = cash + shares * close_value
        equity_curve.append(
            {
                "date": str(row["date"]),
                "code": code,
                "name": name,
                "strategy": strategy,
                "strategy_label": strategy_label,
                "cash": cash,
                "shares": shares,
                "close": close_value,
                "equity": equity,
            }
        )

    if not data.empty and open_trade is not None:
        last = data.iloc[-1]
        trades.append(_open_trade_snapshot(open_trade, last, costs.initial_cash))

    summary = _build_summary(
        data=data,
        equity_curve=equity_curve,
        trades=trades,
        code=code,
        name=name,
        strategy=strategy,
        strategy_label=strategy_label,
        initial_cash=costs.initial_cash,
    )
    return BacktestResult(summary=summary, trades=trades, equity_curve=equity_curve)


def _buy(cash: float, price: float, costs: BacktestCostConfig) -> dict[str, Any]:
    shares = int(cash / price // 100 * 100) if price > 0 else 0
    while shares > 0:
        value = shares * price
        fee = _commission(value, costs)
        if value + fee <= cash:
            return {"shares": shares, "value": value, "fee": fee, "cash_after": cash - value - fee}
        shares -= 100
    return {"shares": 0, "value": 0.0, "fee": 0.0, "cash_after": cash}


def _sell(shares: int, price: float, costs: BacktestCostConfig) -> dict[str, Any]:
    value = shares * price
    fee = _commission(value, costs)
    tax = value * costs.stamp_tax_rate
    return {"value": value, "fee": fee, "tax": tax, "cash_delta": value - fee - tax, "price": price}


def _commission(value: float, costs: BacktestCostConfig) -> float:
    if value <= 0:
        return 0.0
    return max(value * costs.commission_rate, costs.min_commission)


def _close_trade(
    open_trade: dict[str, Any],
    row: pd.Series,
    sell: dict[str, Any],
    exit_signal_date: str,
    exit_reason: Any,
    initial_cash: float,
) -> dict[str, Any]:
    pnl = sell["cash_delta"] - open_trade["entry_value"] - open_trade["entry_fee"]
    holding_days = _date_diff(open_trade["entry_date"], str(row["date"]))
    return {
        **open_trade,
        "exit_signal_date": exit_signal_date,
        "exit_date": str(row["date"]),
        "exit_price": sell["price"],
        "exit_value": sell["value"],
        "exit_fee": sell["fee"],
        "stamp_tax": sell["tax"],
        "exit_reason": exit_reason,
        "status": "closed",
        "holding_days": holding_days,
        "pnl": pnl,
        "return_pct": pnl / initial_cash * 100,
    }


def _open_trade_snapshot(open_trade: dict[str, Any], row: pd.Series, initial_cash: float) -> dict[str, Any]:
    market_value = open_trade["shares"] * float(row["close"])
    pnl = market_value - open_trade["entry_value"] - open_trade["entry_fee"]
    holding_days = _date_diff(open_trade["entry_date"], str(row["date"]))
    return {
        **open_trade,
        "exit_signal_date": None,
        "exit_date": None,
        "exit_price": float(row["close"]),
        "exit_value": market_value,
        "exit_fee": None,
        "stamp_tax": None,
        "exit_reason": "期末持仓按收盘价估值",
        "status": "open",
        "holding_days": holding_days,
        "pnl": pnl,
        "return_pct": pnl / initial_cash * 100,
    }


def _build_summary(
    *,
    data: pd.DataFrame,
    equity_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    code: str,
    name: str,
    strategy: str,
    strategy_label: str,
    initial_cash: float,
) -> dict[str, Any]:
    if not equity_curve:
        return {
            "code": code,
            "name": name,
            "strategy": strategy,
            "strategy_label": strategy_label,
            "total_return_pct": None,
            "annual_return_pct": None,
            "max_drawdown_pct": None,
            "trade_count": 0,
            "closed_trade_count": 0,
            "win_rate_pct": None,
            "average_holding_days": None,
            "profit_loss_ratio": None,
            "buy_hold_return_pct": None,
            "excess_return_pct": None,
            "open_position": False,
            "final_equity": initial_cash,
        }

    final_equity = float(equity_curve[-1]["equity"])
    total_return_pct = (final_equity / initial_cash - 1) * 100
    max_drawdown_pct = _max_drawdown_pct([float(row["equity"]) for row in equity_curve])
    buy_hold_return_pct = _buy_hold_return_pct(data)
    closed = [trade for trade in trades if trade.get("status") == "closed"]
    wins = [trade for trade in closed if (trade.get("pnl") or 0) > 0]
    losses = [trade for trade in closed if (trade.get("pnl") or 0) < 0]
    days = _date_diff(str(data.iloc[0]["date"]), str(data.iloc[-1]["date"])) if len(data) >= 2 else 0
    annual_return_pct = ((final_equity / initial_cash) ** (365 / days) - 1) * 100 if days > 0 else total_return_pct
    average_gain = sum(float(trade["pnl"]) for trade in wins) / len(wins) if wins else None
    average_loss = abs(sum(float(trade["pnl"]) for trade in losses) / len(losses)) if losses else None
    return {
        "code": code,
        "name": name,
        "strategy": strategy,
        "strategy_label": strategy_label,
        "total_return_pct": total_return_pct,
        "annual_return_pct": annual_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "trade_count": len(trades),
        "closed_trade_count": len(closed),
        "win_rate_pct": len(wins) / len(closed) * 100 if closed else None,
        "average_holding_days": sum(int(trade.get("holding_days") or 0) for trade in trades) / len(trades) if trades else None,
        "profit_loss_ratio": average_gain / average_loss if average_gain is not None and average_loss else None,
        "buy_hold_return_pct": buy_hold_return_pct,
        "excess_return_pct": total_return_pct - buy_hold_return_pct if buy_hold_return_pct is not None else None,
        "open_position": any(trade.get("status") == "open" for trade in trades),
        "final_equity": final_equity,
    }


def _max_drawdown_pct(equity_values: list[float]) -> float | None:
    if not equity_values:
        return None
    frame = pd.Series(equity_values)
    drawdown = frame / frame.cummax() - 1
    return float(drawdown.min() * 100)


def _buy_hold_return_pct(data: pd.DataFrame) -> float | None:
    if data.empty:
        return None
    first = float(data.iloc[0]["close"])
    last = float(data.iloc[-1]["close"])
    if first <= 0:
        return None
    return (last / first - 1) * 100


def _date_diff(start: str, end: str) -> int:
    try:
        return (pd.Timestamp(end) - pd.Timestamp(start)).days
    except Exception:
        return 0
