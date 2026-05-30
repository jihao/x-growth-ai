from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.analysis.market_regime import MarketRegime, assess_daily_regime, assess_weekly_regime


@dataclass(frozen=True)
class WeeklyReviewConfig:
    start_date: str
    end_date: str
    output_path: Path | None = None


@dataclass(frozen=True)
class DailySnapshot:
    day: date
    index_rows: list[dict[str, Any]]
    breadth_rows: list[dict[str, Any]]
    concentration: dict[str, Any] | None
    industries: list[dict[str, Any]]
    sectors: list[dict[str, Any]]
    market_regime: MarketRegime


def generate_weekly_review(config: WeeklyReviewConfig) -> Path:
    repo_root = _find_repo_root()
    start = date.fromisoformat(config.start_date)
    end = date.fromisoformat(config.end_date)
    if end < start:
        raise ValueError("end_date must be greater than or equal to start_date")

    snapshots = _load_snapshots(repo_root, start, end)
    output_path = config.output_path or repo_root / "reports" / f"x_growth_weekly_review_{start.isoformat()}_{end.isoformat()}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_weekly_markdown(start, end, snapshots), encoding="utf-8")
    return output_path


def _render_weekly_markdown(start: date, end: date, snapshots: list[DailySnapshot]) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# X-Growth A 股周度复盘｜{start.isoformat()} 至 {end.isoformat()}",
        "",
        f"> 生成时间：{generated_at}｜数据来源：本地 `data/daily` 快照，不重新调用 skills。",
        "",
        "## 1. 本周一句话",
        "",
        _weekly_sentence(snapshots),
        "",
        "## 2. 数据覆盖",
        "",
        _coverage_table(start, end, snapshots),
        "",
        "## 3. 周度状态",
        "",
        _weekly_regime_block(snapshots),
        "",
        "## 4. 指数周表现",
        "",
        _index_weekly_table(snapshots),
        "",
        "## 5. 市场宽度趋势",
        "",
        _breadth_weekly_table(snapshots),
        "",
        "## 6. 成交额集中度趋势",
        "",
        _concentration_weekly_table(snapshots),
        "",
        "## 7. Top50 行业成交主线",
        "",
        _industry_weekly_table(snapshots),
        "",
        "## 8. 板块连续性",
        "",
        _sector_weekly_table(snapshots),
        "",
        "## 9. 下周观察",
        "",
        _next_week_watchlist(snapshots),
        "",
    ]
    return "\n".join(lines)


def _load_snapshots(repo_root: Path, start: date, end: date) -> list[DailySnapshot]:
    snapshots: list[DailySnapshot] = []
    current = start
    while current <= end:
        base = repo_root / "data" / "daily" / current.isoformat() / "normalized"
        if base.exists():
            index_rows = _load_json_list(base / "index_snapshot.json")
            breadth_rows = _load_json_list(base / "market_breadth.json")
            concentration = _load_json_dict(base / "concentration_metrics.json")
            market_regime = _load_market_regime(base / "market_regime.json")
            snapshots.append(
                DailySnapshot(
                    day=current,
                    index_rows=index_rows,
                    breadth_rows=breadth_rows,
                    concentration=concentration,
                    industries=_load_json_list(base / "industry_top50_turnover.json"),
                    sectors=_load_json_list(base / "sector_top_gainers.json"),
                    market_regime=market_regime or assess_daily_regime(index_rows, breadth_rows, concentration),
                )
            )
        current += timedelta(days=1)
    return snapshots


def _coverage_table(start: date, end: date, snapshots: list[DailySnapshot]) -> str:
    loaded = {snapshot.day for snapshot in snapshots}
    rows = ["| 日期 | 状态 |", "|---|---|"]
    current = start
    while current <= end:
        if current.weekday() >= 5:
            status = "周末跳过"
        elif current in loaded:
            status = "已落库"
        else:
            status = "无本地快照"
        rows.append(f"| {current.isoformat()} | {status} |")
        current += timedelta(days=1)
    return "\n".join(rows)


def _weekly_regime_block(snapshots: list[DailySnapshot]) -> str:
    weekly = assess_weekly_regime([snapshot.market_regime for snapshot in snapshots])
    daily_rows = ["| 日期 | 状态标签 | 操作语气 | 置信度 |", "|---|---|---|---|"]
    for snapshot in snapshots:
        regime = snapshot.market_regime
        daily_rows.append(f"| {snapshot.day.isoformat()} | {regime.label} | {regime.tone} | {regime.confidence} |")
    if not snapshots:
        daily_rows.append("| 暂无 | - | - | - |")

    drivers = "；".join(weekly.drivers) if weekly.drivers else "数据不足"
    watch_items = "\n".join(f"- {item}" for item in weekly.watch_items)
    return "\n".join(
        [
            f"- **周度标签**：{weekly.label}",
            f"- **下周语气**：{weekly.tone}",
            f"- **判断置信度**：{weekly.confidence}",
            f"- **触发依据**：{drivers}",
            "",
            "\n".join(daily_rows),
            "",
            watch_items,
        ]
    )


def _index_weekly_table(snapshots: list[DailySnapshot]) -> str:
    if not snapshots:
        return "| 指数 | 期初 | 期末 | 周涨跌 | 周内方向 |\n|---|---:|---:|---:|---|\n| 暂无 | - | - | - | - |"

    by_name: dict[str, list[tuple[date, dict[str, Any]]]] = defaultdict(list)
    for snapshot in snapshots:
        for row in snapshot.index_rows:
            by_name[str(row.get("name", "-"))].append((snapshot.day, row))

    rows = ["| 指数 | 期初 | 期末 | 周涨跌 | 周内方向 |", "|---|---:|---:|---:|---|"]
    for name in ["上证指数", "深证成指", "创业板指", "沪深300", "中证500"]:
        values = by_name.get(name) or []
        if not values:
            continue
        values.sort(key=lambda item: item[0])
        first = _to_float(values[0][1].get("close"))
        last = _to_float(values[-1][1].get("close"))
        weekly = (last / first - 1) if first and last else None
        direction = "走强" if weekly and weekly > 0 else "走弱" if weekly and weekly < 0 else "持平"
        rows.append(f"| {name} | {_fmt_number(first)} | {_fmt_number(last)} | {_fmt_ratio(weekly)} | {direction} |")
    return "\n".join(rows)


def _breadth_weekly_table(snapshots: list[DailySnapshot]) -> str:
    if not snapshots:
        return "| 日期 | 上涨家数 | 下跌家数 | 涨停 | 跌停 | 宽度判断 |\n|---|---:|---:|---:|---:|---|\n| 暂无 | - | - | - | - | - |"

    rows = ["| 日期 | 上涨家数 | 下跌家数 | 涨停 | 跌停 | 宽度判断 |", "|---|---:|---:|---:|---:|---|"]
    for snapshot in snapshots:
        metrics = _metric_map(snapshot.breadth_rows)
        up = _to_float(metrics.get("上涨家数"))
        down = _to_float(metrics.get("下跌家数"))
        judgment = "普跌" if down and up and down > up * 2 else "扩散" if up and down and up > down else "分化"
        rows.append(
            "| {day} | {up} | {down} | {limit_up} | {limit_down} | {judgment} |".format(
                day=snapshot.day.isoformat(),
                up=_fmt_plain(metrics.get("上涨家数")),
                down=_fmt_plain(metrics.get("下跌家数")),
                limit_up=_fmt_plain(metrics.get("涨停家数")),
                limit_down=_fmt_plain(metrics.get("跌停家数")),
                judgment=judgment,
            )
        )
    return "\n".join(rows)


def _concentration_weekly_table(snapshots: list[DailySnapshot]) -> str:
    rows = ["| 日期 | 两市成交额 | CR50 | CR100 | Top3 成交个股 |", "|---|---:|---:|---:|---|"]
    count = 0
    for snapshot in snapshots:
        if not snapshot.concentration:
            continue
        count += 1
        rows.append(
            "| {day} | {turnover} | {cr50} | {cr100} | {top3} |".format(
                day=snapshot.day.isoformat(),
                turnover=snapshot.concentration.get("market_turnover", "-"),
                cr50=snapshot.concentration.get("cr50_text", "-"),
                cr100=snapshot.concentration.get("cr100_text", "-"),
                top3="、".join(snapshot.concentration.get("top3") or []),
            )
        )
    if count == 0:
        rows.append("| 暂无 | - | - | - | - |")
    return "\n".join(rows)


def _industry_weekly_table(snapshots: list[DailySnapshot]) -> str:
    aggregate: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        for row in snapshot.industries:
            industry = str(row.get("industry") or "").strip()
            if not industry:
                continue
            item = aggregate.setdefault(industry, {"days": 0, "ratio_sum": 0.0, "max_ratio": 0.0})
            ratio = _to_float(row.get("ratio_value")) or 0.0
            item["days"] += 1
            item["ratio_sum"] += ratio
            item["max_ratio"] = max(item["max_ratio"], ratio)

    if not aggregate:
        return "| 行业 | 上榜天数 | 平均占比 | 最高占比 | 判断 |\n|---|---:|---:|---:|---|\n| 暂无 | - | - | - | - |"

    rows = ["| 行业 | 上榜天数 | 平均占比 | 最高占比 | 判断 |", "|---|---:|---:|---:|---|"]
    for industry, item in sorted(aggregate.items(), key=lambda pair: pair[1]["ratio_sum"], reverse=True)[:10]:
        avg = item["ratio_sum"] / item["days"] if item["days"] else 0.0
        judgment = "本周主线" if item["days"] >= max(2, len(snapshots) - 1) and avg >= 0.15 else "阶段活跃"
        rows.append(f"| {industry} | {item['days']} | {_fmt_ratio(avg)} | {_fmt_ratio(item['max_ratio'])} | {judgment} |")
    return "\n".join(rows)


def _sector_weekly_table(snapshots: list[DailySnapshot]) -> str:
    counter: Counter[str] = Counter()
    latest_pct: dict[str, Any] = {}
    for snapshot in snapshots:
        for row in snapshot.sectors[:10]:
            name = str(row.get("名称") or "").strip()
            if not name:
                continue
            counter[name] += 1
            latest_pct[name] = _fmt_pct_text(_find_value(row, "涨跌幅", snapshot.day.isoformat()))

    if not counter:
        return "| 板块 | 上榜天数 | 最近涨跌幅 | 连续性 |\n|---|---:|---:|---|\n| 暂无 | - | - | - |"

    rows = ["| 板块 | 上榜天数 | 最近涨跌幅 | 连续性 |", "|---|---:|---:|---|"]
    for name, days in counter.most_common(10):
        continuity = "高" if days >= 3 else "中" if days == 2 else "低"
        rows.append(f"| {name} | {days} | {latest_pct.get(name, '-')} | {continuity} |")
    return "\n".join(rows)


def _weekly_sentence(snapshots: list[DailySnapshot]) -> str:
    if not snapshots:
        return "本周暂无可用本地快照，先运行 `backfill` 生成每日数据。"
    concentration = [snapshot.concentration for snapshot in snapshots if snapshot.concentration]
    breadth = [_metric_map(snapshot.breadth_rows) for snapshot in snapshots if snapshot.breadth_rows]
    weak_days = sum(1 for metrics in breadth if (_to_float(metrics.get("下跌家数")) or 0) > (_to_float(metrics.get("上涨家数")) or 0))
    if concentration:
        first = _to_float(concentration[0].get("cr50"))
        last = _to_float(concentration[-1].get("cr50"))
        if first is not None and last is not None and last > first and weak_days >= len(snapshots) / 2:
            return "本周市场宽度偏弱，同时头部成交集中度抬升，资金更偏向少数主线。"
    if weak_days >= len(snapshots) / 2:
        return "本周多数交易日下跌家数多于上涨家数，市场赚钱效应偏弱。"
    return "本周市场宽度相对均衡，重点观察成交主线是否延续。"


def _next_week_watchlist(snapshots: list[DailySnapshot]) -> str:
    if not snapshots:
        return "- 先补齐本周每日快照，再生成周度观察。"
    return "\n".join(
        [
            "- 观察 CR50 是否继续上行；若上行且宽度走弱，说明资金进一步抱团。",
            "- 观察 Top50 行业中电子、通信等高占比行业是否连续维持优势。",
            "- 观察上涨家数能否重新超过下跌家数，这是赚钱效应修复的第一信号。",
            "- 观察成交额前十个股是否频繁更换；频繁更换代表主线不稳，持续集中代表主线强化。",
        ]
    )


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _load_market_regime(path: Path) -> MarketRegime | None:
    data = _load_json_dict(path)
    if not data:
        return None
    return MarketRegime(
        label=str(data.get("label") or "数据不足"),
        tone=str(data.get("tone") or "观察"),
        confidence=str(data.get("confidence") or "低"),
        drivers=[str(item) for item in data.get("drivers") or []],
        watch_items=[str(item) for item in data.get("watch_items") or []],
    )


def _metric_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(row.get("metric")): row.get("value") for row in rows}


def _find_value(row: dict[str, Any], contains: str, review_date: str | None = None) -> Any:
    if review_date:
        date_token = review_date.replace("-", ".")
        for key, value in row.items():
            key_text = str(key)
            if contains in key_text and date_token in key_text:
                return value
    for key, value in row.items():
        if contains in str(key):
            return value
    return "-"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "").replace("点", "")
    text = text.replace("万亿", "").replace("亿", "").replace("万", "")
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def _fmt_plain(value: Any) -> str:
    return "-" if value is None else str(value)


def _fmt_pct_text(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return _fmt_plain(value)
    return f"{number:.2f}%"


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "skills").exists() and (parent / "参考资料").exists():
            return parent
    return current.parents[4]
