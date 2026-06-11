from __future__ import annotations

import numpy as np
import pandas as pd


def add_technical_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result = result.sort_values("date").reset_index(drop=True)
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result["high"] = pd.to_numeric(result["high"], errors="coerce")
    result["low"] = pd.to_numeric(result["low"], errors="coerce")

    _add_moving_averages(result)
    _add_macd(result)
    _add_kdj(result)
    _add_rsi(result)
    _add_td9(result)
    _add_macd_structure(result)
    return result


def _add_moving_averages(frame: pd.DataFrame) -> None:
    frame["ma20"] = frame["close"].rolling(window=20, min_periods=1).mean()
    frame["ma60"] = frame["close"].rolling(window=60, min_periods=1).mean()


def _add_macd(frame: pd.DataFrame) -> None:
    ema12 = frame["close"].ewm(span=12, adjust=False, min_periods=1).mean()
    ema26 = frame["close"].ewm(span=26, adjust=False, min_periods=1).mean()
    frame["macd_dif"] = ema12 - ema26
    frame["macd_dea"] = frame["macd_dif"].ewm(span=9, adjust=False, min_periods=1).mean()
    frame["macd_hist"] = 2 * (frame["macd_dif"] - frame["macd_dea"])


def _add_kdj(frame: pd.DataFrame, period: int = 9) -> None:
    low_min = frame["low"].rolling(window=period, min_periods=1).min()
    high_max = frame["high"].rolling(window=period, min_periods=1).max()
    denominator = (high_max - low_min).replace(0, np.nan)
    rsv = ((frame["close"] - low_min) / denominator * 100).fillna(50)

    k_values: list[float] = []
    d_values: list[float] = []
    j_values: list[float] = []
    previous_k = 50.0
    previous_d = 50.0
    for value in rsv:
        current_k = previous_k * 2 / 3 + float(value) / 3
        current_d = previous_d * 2 / 3 + current_k / 3
        current_j = 3 * current_k - 2 * current_d
        k_values.append(current_k)
        d_values.append(current_d)
        j_values.append(current_j)
        previous_k = current_k
        previous_d = current_d

    frame["kdj_k"] = k_values
    frame["kdj_d"] = d_values
    frame["kdj_j"] = j_values


def _add_rsi(frame: pd.DataFrame, period: int = 14) -> None:
    delta = frame["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100)
    rsi = rsi.mask((average_loss == 0) & (average_gain == 0), 50)
    frame["rsi14"] = rsi


def _add_td9(frame: pd.DataFrame) -> None:
    compare = frame["close"].shift(4)
    buy_condition = frame["close"] < compare
    sell_condition = frame["close"] > compare
    buy_counts: list[int] = []
    sell_counts: list[int] = []
    current_buy = 0
    current_sell = 0
    for buy_active, sell_active in zip(buy_condition.fillna(False), sell_condition.fillna(False)):
        current_buy = current_buy + 1 if bool(buy_active) else 0
        current_sell = current_sell + 1 if bool(sell_active) else 0
        buy_counts.append(min(current_buy, 9))
        sell_counts.append(min(current_sell, 9))

    frame["td_buy_setup"] = buy_counts
    frame["td_sell_setup"] = sell_counts
    frame["td_signal"] = np.select(
        [frame["td_buy_setup"] == 9, frame["td_sell_setup"] == 9],
        ["low9", "high9"],
        default=None,
    )


def _add_macd_structure(frame: pd.DataFrame, lookback: int = 40) -> None:
    previous_high = frame["close"].shift(1).rolling(window=lookback, min_periods=20).max()
    previous_low = frame["close"].shift(1).rolling(window=lookback, min_periods=20).min()
    previous_dif_high = frame["macd_dif"].shift(1).rolling(window=lookback, min_periods=20).max()
    previous_dif_low = frame["macd_dif"].shift(1).rolling(window=lookback, min_periods=20).min()
    top_divergence = (frame["close"] > previous_high) & (frame["macd_dif"] < previous_dif_high)
    bottom_divergence = (frame["close"] < previous_low) & (frame["macd_dif"] > previous_dif_low)

    hist_down_3 = frame["macd_hist"].diff().rolling(window=3, min_periods=3).sum() < 0
    hist_up_3 = frame["macd_hist"].diff().rolling(window=3, min_periods=3).sum() > 0
    top_passivation = (frame["macd_dif"] > frame["macd_dea"]) & hist_down_3 & (frame["close"] > frame["ma20"])
    bottom_passivation = (frame["macd_dif"] < frame["macd_dea"]) & hist_up_3 & (frame["close"] < frame["ma20"])

    frame["macd_top_divergence"] = top_divergence.fillna(False)
    frame["macd_bottom_divergence"] = bottom_divergence.fillna(False)
    frame["macd_top_passivation"] = top_passivation.fillna(False)
    frame["macd_bottom_passivation"] = bottom_passivation.fillna(False)
