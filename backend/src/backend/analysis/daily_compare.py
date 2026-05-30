from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DailyComparison:
    ok: bool
    previous_date: str | None
    metrics: dict[str, Any]
    error: str | None = None


def compare_with_previous(repo_root: Path, review_date: str, current_dir: Path) -> DailyComparison:
    previous_dir = _find_previous_daily_dir(repo_root / "data" / "daily", review_date)
    if previous_dir is None:
        return DailyComparison(False, None, {}, "暂无前一日落库数据")

    current_normalized = current_dir / "normalized"
    previous_normalized = previous_dir / "normalized"
    try:
        current_concentration = _load_json(current_normalized / "concentration_metrics.json")
        previous_concentration = _load_json(previous_normalized / "concentration_metrics.json")
        current_breadth = _metric_map(_load_json(current_normalized / "market_breadth.json"))
        previous_breadth = _metric_map(_load_json(previous_normalized / "market_breadth.json"))
        current_industries = _industry_map(_load_json(current_normalized / "industry_top50_turnover.json"))
        previous_industries = _industry_map(_load_json(previous_normalized / "industry_top50_turnover.json"))
    except FileNotFoundError as exc:
        return DailyComparison(False, previous_dir.name, {}, f"缺少可比数据文件：{exc}")
    except json.JSONDecodeError as exc:
        return DailyComparison(False, previous_dir.name, {}, f"可比数据 JSON 解析失败：{exc}")

    metrics = {
        "cr50_delta_pp": _delta_pp(current_concentration.get("cr50"), previous_concentration.get("cr50")),
        "cr100_delta_pp": _delta_pp(current_concentration.get("cr100"), previous_concentration.get("cr100")),
        "up_count_delta": _delta_number(current_breadth.get("上涨家数"), previous_breadth.get("上涨家数")),
        "down_count_delta": _delta_number(current_breadth.get("下跌家数"), previous_breadth.get("下跌家数")),
        "limit_up_delta": _delta_number(current_breadth.get("涨停家数"), previous_breadth.get("涨停家数")),
        "limit_down_delta": _delta_number(current_breadth.get("跌停家数"), previous_breadth.get("跌停家数")),
        "industry_ratio_deltas": _industry_ratio_deltas(current_industries, previous_industries),
    }
    return DailyComparison(True, previous_dir.name, metrics)


def _find_previous_daily_dir(base_dir: Path, review_date: str) -> Path | None:
    if not base_dir.exists():
        return None
    candidates = [
        path
        for path in base_dir.iterdir()
        if path.is_dir() and path.name < review_date and (path / "normalized").exists()
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name)[-1]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _metric_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(row.get("metric")): row.get("value") for row in rows}


def _industry_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        industry = str(row.get("industry") or "").strip()
        ratio = row.get("ratio_value")
        if not industry:
            continue
        try:
            result[industry] = float(ratio)
        except (TypeError, ValueError):
            continue
    return result


def _delta_pp(current: Any, previous: Any) -> float | None:
    try:
        return (float(current) - float(previous)) * 100
    except (TypeError, ValueError):
        return None


def _delta_number(current: Any, previous: Any) -> float | None:
    try:
        return float(current) - float(previous)
    except (TypeError, ValueError):
        return None


def _industry_ratio_deltas(current: dict[str, float], previous: dict[str, float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for industry in sorted(set(current) | set(previous)):
        rows.append(
            {
                "industry": industry,
                "current_ratio": current.get(industry),
                "previous_ratio": previous.get(industry),
                "delta_pp": _delta_pp(current.get(industry, 0), previous.get(industry, 0)),
            }
        )
    return sorted(rows, key=lambda row: abs(row["delta_pp"] or 0), reverse=True)
