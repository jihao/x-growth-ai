from __future__ import annotations

from typing import Any


Pattern = dict[str, Any]


def recognize_kline_patterns(rows: list[dict[str, Any]]) -> list[Pattern]:
    candles = [_clean_candle(row) for row in rows]
    candles = [row for row in candles if row is not None]
    if len(candles) < 3:
        return []

    patterns: list[Pattern] = []
    patterns.extend(_single_candle_patterns(candles))
    patterns.extend(_double_candle_patterns(candles))
    patterns.extend(_triple_candle_patterns(candles))
    patterns.extend(_range_patterns(candles))
    return patterns


def summarize_patterns(patterns: list[Pattern]) -> dict[str, Any]:
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for pattern in patterns:
        pattern_type = str(pattern.get("type") or "neutral")
        counts[pattern_type if pattern_type in counts else "neutral"] += 1
    if counts["bullish"] > counts["bearish"]:
        bias = "bullish"
        message = "偏多形态更多，但仍需要成交量和趋势确认。"
    elif counts["bearish"] > counts["bullish"]:
        bias = "bearish"
        message = "偏空形态更多，短线需要优先控制回撤。"
    elif counts["neutral"]:
        bias = "neutral"
        message = "以中性/整理形态为主，等待突破或确认信号。"
    else:
        bias = "none"
        message = "未识别到典型K线形态。"
    return {"bias": bias, "counts": counts, "message": message}


def _clean_candle(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if high < low or min(open_price, close) < low or max(open_price, close) > high:
        return None
    return {
        "date": row.get("date"),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": row.get("volume"),
    }


def _single_candle_patterns(rows: list[dict[str, Any]]) -> list[Pattern]:
    last = rows[-1]
    span = _span(last)
    if span <= 0:
        return []

    patterns: list[Pattern] = []
    body = _body(last)
    upper = _upper_shadow(last)
    lower = _lower_shadow(last)
    body_ratio = body / span
    trend = _recent_trend(rows[:-1])

    if body_ratio < 0.1 and abs(upper - lower) / span < 0.3:
        patterns.append(_pattern("十字星", "neutral", 0.7, "实体很小，多空暂时平衡，常作为变盘观察信号。", last))

    if body > 0 and lower > body * 2 and upper < body * 0.6 and trend == "down":
        patterns.append(_pattern("锤子线", "bullish", 0.65, "下跌后出现长下影，低位承接增强，关注后续阳线确认。", last))

    if body > 0 and upper > body * 2 and lower < body * 0.6:
        if trend == "down":
            patterns.append(_pattern("倒锤子线", "bullish", 0.52, "下跌后试探上方压力，需后续放量站稳确认。", last))
        elif trend == "up":
            patterns.append(_pattern("射击之星", "bearish", 0.6, "上涨后出现长上影，上方抛压增强，追高需要谨慎。", last))

    previous_close = rows[-2]["close"]
    change_pct = (last["close"] / previous_close - 1) * 100 if previous_close > 0 else 0
    if _bullish(last) and body_ratio > 0.7 and change_pct > 3:
        patterns.append(_pattern("大阳线", "bullish", min(0.9, 0.5 + change_pct / 20), f"涨幅约 {change_pct:.1f}%，多方主动性较强。", last))
    if _bearish(last) and body_ratio > 0.7 and change_pct < -3:
        patterns.append(_pattern("大阴线", "bearish", min(0.9, 0.5 + abs(change_pct) / 20), f"跌幅约 {change_pct:.1f}%，空方主动性较强。", last))

    return patterns


def _double_candle_patterns(rows: list[dict[str, Any]]) -> list[Pattern]:
    prev, last = rows[-2], rows[-1]
    patterns: list[Pattern] = []

    if _bearish(prev) and _bullish(last) and last["open"] <= prev["close"] and last["close"] >= prev["open"]:
        patterns.append(_pattern("看涨吞没", "bullish", 0.7, "阳线实体覆盖前一根阴线实体，多方反攻信号。", last))
    if _bullish(prev) and _bearish(last) and last["open"] >= prev["close"] and last["close"] <= prev["open"]:
        patterns.append(_pattern("看跌吞没", "bearish", 0.7, "阴线实体覆盖前一根阳线实体，空方反攻信号。", last))

    prev_mid = (prev["open"] + prev["close"]) / 2
    if _bullish(prev) and _bearish(last) and last["open"] > prev["high"] and last["close"] < prev_mid:
        patterns.append(_pattern("乌云盖顶", "bearish", 0.65, "高开低走并跌入前一根阳线实体中部以下，偏空。", last))
    if _bearish(prev) and _bullish(last) and last["open"] < prev["low"] and last["close"] > prev_mid:
        patterns.append(_pattern("曙光初现", "bullish", 0.65, "低开高走并收复前一根阴线实体中部以上，偏多。", last))

    return patterns


def _triple_candle_patterns(rows: list[dict[str, Any]]) -> list[Pattern]:
    first, middle, last = rows[-3], rows[-2], rows[-1]
    patterns: list[Pattern] = []

    first_mid = (first["open"] + first["close"]) / 2
    if _bearish(first) and _body(middle) < _body(first) * 0.35 and _bullish(last) and last["close"] > first_mid:
        patterns.append(_pattern("早晨之星", "bullish", 0.75, "下跌后出现小实体停顿，再由阳线收复，底部反转意味增强。", last))
    if _bullish(first) and _body(middle) < _body(first) * 0.35 and _bearish(last) and last["close"] < first_mid:
        patterns.append(_pattern("黄昏之星", "bearish", 0.75, "上涨后出现小实体停顿，再由阴线压回，顶部反转意味增强。", last))

    if all(_bullish(row) for row in (first, middle, last)) and first["close"] < middle["close"] < last["close"]:
        patterns.append(_pattern("三连阳", "bullish", 0.6, "连续三根阳线逐步走高，多方延续进攻。", last))
        if _body(first) < _body(middle) < _body(last):
            patterns.append(_pattern("红三兵", "bullish", 0.7, "三根阳线实体递增，多方力量加速释放。", last))
    if all(_bearish(row) for row in (first, middle, last)) and first["close"] > middle["close"] > last["close"]:
        patterns.append(_pattern("三连阴", "bearish", 0.6, "连续三根阴线逐步走低，空方延续施压。", last))

    return patterns


def _range_patterns(rows: list[dict[str, Any]]) -> list[Pattern]:
    recent = rows[-min(20, len(rows)) :]
    if len(recent) < 10:
        return []

    closes = [row["close"] for row in recent]
    avg_close = sum(closes) / len(closes)
    if avg_close <= 0:
        return []

    patterns: list[Pattern] = []
    max_deviation = max(abs(close - avg_close) / avg_close for close in closes)
    if max_deviation < 0.05:
        patterns.append(
            _pattern(
                "横盘整理",
                "neutral",
                0.6,
                f"近 {len(closes)} 根K线围绕均价窄幅波动，最大偏离约 {max_deviation * 100:.1f}%。",
                recent[-1],
            )
        )

    peaks: list[tuple[int, float]] = []
    troughs: list[tuple[int, float]] = []
    for idx in range(1, len(closes) - 1):
        if closes[idx] > closes[idx - 1] and closes[idx] > closes[idx + 1]:
            peaks.append((idx, closes[idx]))
        if closes[idx] < closes[idx - 1] and closes[idx] < closes[idx + 1]:
            troughs.append((idx, closes[idx]))
    if len(peaks) >= 2 and troughs:
        first_peak, last_peak = peaks[-2], peaks[-1]
        trough = troughs[-1]
        if first_peak[0] < trough[0] < last_peak[0] and last_peak[1] > first_peak[1] and trough[1] > first_peak[1] * 0.95:
            patterns.append(_pattern("N字上攻", "bullish", 0.6, "上涨、回踩、再创新高，趋势延续特征较明显。", recent[-1]))

    return patterns


def _pattern(name: str, pattern_type: str, confidence: float, description: str, row: dict[str, Any]) -> Pattern:
    return {
        "name": name,
        "type": pattern_type,
        "confidence": round(float(confidence), 2),
        "date": row.get("date"),
        "description": description,
    }


def _recent_trend(rows: list[dict[str, Any]]) -> str:
    closes = [row["close"] for row in rows[-5:]]
    if len(closes) < 3:
        return "flat"
    if closes[-1] > closes[0] * 1.02:
        return "up"
    if closes[-1] < closes[0] * 0.98:
        return "down"
    return "flat"


def _body(row: dict[str, Any]) -> float:
    return abs(row["close"] - row["open"])


def _upper_shadow(row: dict[str, Any]) -> float:
    return row["high"] - max(row["open"], row["close"])


def _lower_shadow(row: dict[str, Any]) -> float:
    return min(row["open"], row["close"]) - row["low"]


def _span(row: dict[str, Any]) -> float:
    return row["high"] - row["low"]


def _bullish(row: dict[str, Any]) -> bool:
    return row["close"] > row["open"]


def _bearish(row: dict[str, Any]) -> bool:
    return row["close"] < row["open"]
