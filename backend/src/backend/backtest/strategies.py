from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    label: str
    description: str


STRATEGIES: dict[str, StrategyDefinition] = {
    "macd": StrategyDefinition("macd", "MACD 金叉/死叉", "DIF 上穿 DEA 买入，下穿卖出。"),
    "kdj": StrategyDefinition("kdj", "KDJ 低位金叉/高位死叉", "低位金叉买入，高位死叉卖出。"),
    "rsi": StrategyDefinition("rsi", "RSI 超卖回升/超买回落", "RSI14 上穿 30 买入，下穿 70 卖出。"),
    "td9": StrategyDefinition("td9", "TD9 低9转强/高9风控", "低9后出现初步转强买入，高9或跌破短期均线卖出。"),
}


def build_strategy_signals(frame: pd.DataFrame, strategy_key: str) -> pd.DataFrame:
    if strategy_key == "macd":
        return _macd_signals(frame)
    if strategy_key == "kdj":
        return _kdj_signals(frame)
    if strategy_key == "rsi":
        return _rsi_signals(frame)
    if strategy_key == "td9":
        return _td9_signals(frame)
    raise ValueError(f"unknown strategy: {strategy_key}")


def _empty_signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"date": frame["date"], "signal": [None] * len(frame), "reason": [None] * len(frame)})


def _macd_signals(frame: pd.DataFrame) -> pd.DataFrame:
    signals = _empty_signal_frame(frame)
    previous_dif = frame["macd_dif"].shift(1)
    previous_dea = frame["macd_dea"].shift(1)
    buy = (previous_dif <= previous_dea) & (frame["macd_dif"] > frame["macd_dea"])
    sell = (previous_dif >= previous_dea) & (frame["macd_dif"] < frame["macd_dea"])
    signals.loc[buy, ["signal", "reason"]] = ["buy", "DIF 上穿 DEA"]
    signals.loc[sell, ["signal", "reason"]] = ["sell", "DIF 下穿 DEA"]
    return signals


def _kdj_signals(frame: pd.DataFrame) -> pd.DataFrame:
    signals = _empty_signal_frame(frame)
    previous_k = frame["kdj_k"].shift(1)
    previous_d = frame["kdj_d"].shift(1)
    buy = (previous_k <= previous_d) & (frame["kdj_k"] > frame["kdj_d"]) & (frame[["kdj_k", "kdj_d"]].min(axis=1) < 30)
    sell = (previous_k >= previous_d) & (frame["kdj_k"] < frame["kdj_d"]) & (frame[["kdj_k", "kdj_d"]].max(axis=1) > 70)
    signals.loc[buy, ["signal", "reason"]] = ["buy", "K 上穿 D 且处于低位"]
    signals.loc[sell, ["signal", "reason"]] = ["sell", "K 下穿 D 且处于高位"]
    return signals


def _rsi_signals(frame: pd.DataFrame) -> pd.DataFrame:
    signals = _empty_signal_frame(frame)
    previous = frame["rsi14"].shift(1)
    buy = (previous <= 30) & (frame["rsi14"] > 30)
    sell = (previous >= 70) & (frame["rsi14"] < 70)
    signals.loc[buy, ["signal", "reason"]] = ["buy", "RSI14 从超卖区上穿 30"]
    signals.loc[sell, ["signal", "reason"]] = ["sell", "RSI14 从超买区下穿 70"]
    return signals


def _td9_signals(frame: pd.DataFrame) -> pd.DataFrame:
    signals = _empty_signal_frame(frame)
    low9_recent = (frame["td_buy_setup"] == 9).rolling(window=5, min_periods=1).max().astype(bool)
    close_up = frame["close"] > frame["close"].shift(1)
    ma5 = frame["close"].rolling(window=5, min_periods=1).mean()
    ma10 = frame["close"].rolling(window=10, min_periods=1).mean()
    buy = low9_recent & close_up & (frame["close"] >= ma5)
    sell = (frame["td_sell_setup"] == 9) | (frame["close"] < ma10)
    signals.loc[buy, ["signal", "reason"]] = ["buy", "TD低9后收盘转强"]
    signals.loc[sell, ["signal", "reason"]] = ["sell", "TD高9或跌破10日均线"]
    return signals
