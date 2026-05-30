from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketRegime:
    label: str
    tone: str
    confidence: str
    drivers: list[str]
    watch_items: list[str]


def assess_daily_regime(
    index_rows: list[dict[str, Any]],
    breadth_rows: list[dict[str, Any]],
    concentration: dict[str, Any] | None,
    comparison_metrics: dict[str, Any] | None = None,
) -> MarketRegime:
    metrics = _metric_map(breadth_rows)
    up = _to_float(metrics.get("上涨家数"))
    down = _to_float(metrics.get("下跌家数"))
    limit_up = _to_float(metrics.get("涨停家数"))
    limit_down = _to_float(metrics.get("跌停家数"))
    cr50 = _to_float((concentration or {}).get("cr50"))
    cr50_delta = _to_float((comparison_metrics or {}).get("cr50_delta_pp"))
    up_delta = _to_float((comparison_metrics or {}).get("up_count_delta"))
    down_delta = _to_float((comparison_metrics or {}).get("down_count_delta"))
    index_positive = sum(1 for row in index_rows if (_to_float(row.get("pct_change")) or 0) > 0)
    index_negative = sum(1 for row in index_rows if (_to_float(row.get("pct_change")) or 0) < 0)

    drivers: list[str] = []
    if up is not None and down is not None:
        drivers.append(f"上涨 {int(up)} 家、下跌 {int(down)} 家")
    if cr50 is not None:
        drivers.append(f"CR50 {_fmt_ratio(cr50)}")
    if cr50_delta is not None:
        drivers.append(f"CR50 环比 {_fmt_pp(cr50_delta)}")
    if up_delta is not None and down_delta is not None:
        drivers.append(f"上涨家数环比 {_fmt_number_delta(up_delta)}，下跌家数环比 {_fmt_number_delta(down_delta)}")

    weak_breadth = bool(up and down and down > up * 1.6)
    strong_breadth = bool(up and down and up > down * 1.2)
    high_concentration = bool(cr50 is not None and cr50 >= 0.22)
    rising_concentration = bool(cr50_delta is not None and cr50_delta >= 0.2)
    falling_concentration = bool(cr50_delta is not None and cr50_delta <= -0.2)
    high_tail_risk = bool(limit_down and limit_up and limit_down >= max(20, limit_up * 0.8))

    if weak_breadth and (high_concentration or rising_concentration):
        return MarketRegime(
            label="弱势抱团",
            tone="谨慎",
            confidence=_confidence(drivers),
            drivers=drivers,
            watch_items=[
                "看 CR50 是否继续上行，若继续上行说明资金进一步收缩到少数标的。",
                "看上涨家数能否修复到下跌家数的一半以上，这是弱转稳的第一步。",
                "高成交主线若次日不能延续，容易出现补跌或快速轮动。",
            ],
        )
    if strong_breadth and (cr50 is None or cr50 < 0.22 or falling_concentration):
        return MarketRegime(
            label="主线扩散",
            tone="积极但不追高",
            confidence=_confidence(drivers),
            drivers=drivers,
            watch_items=[
                "看领涨行业是否从少数高成交个股扩散到更多中低位标的。",
                "看成交额能否维持，缩量扩散的持续性通常较弱。",
                "优先跟踪连续两天进入强势榜的板块。",
            ],
        )
    if high_tail_risk:
        return MarketRegime(
            label="风险释放",
            tone="防守",
            confidence=_confidence(drivers),
            drivers=drivers,
            watch_items=[
                "看跌停家数是否快速回落，回落前不急于判断情绪修复。",
                "看高位成交额个股是否继续补跌，避免把反抽误判成新主线。",
                "等待上涨家数和涨停家数同步恢复。",
            ],
        )
    if index_positive > 0 and index_negative > 0:
        return MarketRegime(
            label="结构轮动",
            tone="精选主线",
            confidence=_confidence(drivers),
            drivers=drivers,
            watch_items=[
                "看领涨板块是否有第二天确认，没有确认先按一日游处理。",
                "看成交额前十是否频繁换手，频繁更换代表主线仍不稳定。",
                "避免只看指数涨跌，重点看行业占比和市场宽度是否同步。",
            ],
        )
    if weak_breadth:
        return MarketRegime(
            label="普跌退潮",
            tone="防守",
            confidence=_confidence(drivers),
            drivers=drivers,
            watch_items=[
                "先看下跌家数是否收敛，再看指数是否企稳。",
                "跌停数若继续抬升，短线情绪仍在释放风险。",
                "缩小观察范围，只跟踪最强主线和低位补涨方向。",
            ],
        )
    return MarketRegime(
        label="均衡震荡",
        tone="观察",
        confidence=_confidence(drivers),
        drivers=drivers,
        watch_items=[
            "观察成交额能否选择方向，放量方向更值得重视。",
            "观察上涨/下跌家数能否拉开差距。",
            "等待行业主线连续性提高后再提高判断权重。",
        ],
    )


def assess_weekly_regime(daily_regimes: list[MarketRegime]) -> MarketRegime:
    if not daily_regimes:
        return MarketRegime(
            label="数据不足",
            tone="观察",
            confidence="低",
            drivers=["本周暂无可用本地快照"],
            watch_items=["先补齐本周每日快照，再判断周度状态。"],
        )

    counts: dict[str, int] = {}
    for regime in daily_regimes:
        counts[regime.label] = counts.get(regime.label, 0) + 1
    label, days = sorted(counts.items(), key=lambda item: item[1], reverse=True)[0]
    defensive_days = sum(1 for regime in daily_regimes if regime.tone in {"谨慎", "防守"})
    constructive_days = sum(1 for regime in daily_regimes if regime.tone in {"积极但不追高", "精选主线"})

    if defensive_days >= max(2, len(daily_regimes) // 2 + 1):
        tone = "防守优先"
    elif constructive_days >= max(2, len(daily_regimes) // 2 + 1):
        tone = "结构参与"
    else:
        tone = "观察轮动"

    return MarketRegime(
        label=f"{label}占优",
        tone=tone,
        confidence="高" if days >= max(2, len(daily_regimes) - 1) else "中",
        drivers=[f"{label}出现 {days} 天", f"防守/谨慎状态 {defensive_days} 天", f"积极/结构状态 {constructive_days} 天"],
        watch_items=_dedupe_watch_items(daily_regimes),
    )


def _metric_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(row.get("metric")).strip(): row.get("value") for row in rows if row.get("metric") is not None}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "").replace("点", "")
    text = text.replace("万亿", "").replace("亿", "").replace("万", "")
    try:
        return float(text)
    except ValueError:
        return None


def _confidence(drivers: list[str]) -> str:
    if len(drivers) >= 4:
        return "高"
    if len(drivers) >= 2:
        return "中"
    return "低"


def _dedupe_watch_items(regimes: list[MarketRegime]) -> list[str]:
    items: list[str] = []
    for regime in regimes:
        for item in regime.watch_items:
            if item not in items:
                items.append(item)
            if len(items) >= 4:
                return items
    return items


def _fmt_ratio(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fmt_pp(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}pp"


def _fmt_number_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{int(value)}" if value.is_integer() else f"{sign}{value:.2f}"
