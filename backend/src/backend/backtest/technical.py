from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.backtest.engine import BacktestCostConfig, run_single_backtest
from backend.backtest.indicators import add_technical_indicators
from backend.backtest.strategies import STRATEGIES, build_strategy_signals
from backend.data_sources.a_stock_data import normalize_code
from backend.data_sources.baostock_data import BaoStockDataClient


@dataclass(frozen=True)
class TechnicalBacktestConfig:
    start_date: str | None = None
    end_date: str | None = None
    codes: list[str] | None = None
    strategies: list[str] | None = None
    output_path: Path | None = None
    initial_cash: float = 100000.0
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005


def generate_technical_backtest(config: TechnicalBacktestConfig) -> Path:
    repo_root = _find_repo_root()
    end_day = date.fromisoformat(config.end_date) if config.end_date else date.today()
    start_day = date.fromisoformat(config.start_date) if config.start_date else _one_year_before(end_day)
    if end_day < start_day:
        raise ValueError("--end must be greater than or equal to --start")

    stocks = _load_stocks(repo_root, config.codes)
    strategy_keys = _normalize_strategy_keys(config.strategies)
    run_dir = repo_root / "data" / "backtests" / f"technical_{start_day.isoformat()}_{end_day.isoformat()}"
    normalized_dir = run_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    costs = BacktestCostConfig(
        initial_cash=config.initial_cash,
        commission_rate=config.commission_rate,
        min_commission=config.min_commission,
        stamp_tax_rate=config.stamp_tax_rate,
    )
    summaries: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    data_errors: list[dict[str, str]] = []

    try:
        with BaoStockDataClient() as client:
            for stock in stocks:
                result = client.fetch_daily_kline(stock["code"], start_day.isoformat(), end_day.isoformat(), adjustflag="2")
                if not result.ok:
                    data_errors.append({"code": stock["code"], "name": stock["name"], "error": result.error or "unknown error"})
                    continue
                if result.frame.empty:
                    data_errors.append({"code": stock["code"], "name": stock["name"], "error": "empty k-line result"})
                    continue

                kline = result.frame
                _write_frame(normalized_dir / f"kline_{stock['code']}.csv", kline)
                indicators = add_technical_indicators(kline)
                _write_frame(normalized_dir / f"indicators_{stock['code']}.csv", indicators)

                for strategy_key in strategy_keys:
                    definition = STRATEGIES[strategy_key]
                    signals = build_strategy_signals(indicators, strategy_key)
                    _write_frame(normalized_dir / f"signals_{stock['code']}_{strategy_key}.csv", signals)
                    result = run_single_backtest(
                        indicators,
                        signals,
                        code=stock["code"],
                        name=stock["name"],
                        strategy=strategy_key,
                        strategy_label=definition.label,
                        costs=costs,
                    )
                    summaries.append(result.summary)
                    trades.extend(result.trades)
                    equity_rows.extend(result.equity_curve)
    except RuntimeError as exc:
        for stock in stocks:
            data_errors.append({"code": stock["code"], "name": stock["name"], "error": str(exc)})

    _write_rows(normalized_dir / "summary.csv", summaries)
    _write_json(normalized_dir / "summary.json", summaries)
    _write_rows(normalized_dir / "trades.csv", trades)
    _write_json(normalized_dir / "trades.json", trades)
    _write_rows(normalized_dir / "equity_curves.csv", equity_rows)
    _write_json(normalized_dir / "equity_curves.json", equity_rows)
    if data_errors:
        _write_json(normalized_dir / "data_errors.json", data_errors)

    manifest_path = _write_manifest(run_dir, start_day, end_day, stocks, strategy_keys, costs, summaries, trades, equity_rows, data_errors)
    output_path = config.output_path or repo_root / "reports" / f"x_growth_tech_backtest_{start_day.isoformat()}_{end_day.isoformat()}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _render_markdown(start_day, end_day, stocks, strategy_keys, costs, summaries, trades, data_errors, manifest_path),
        encoding="utf-8",
    )
    return output_path


def _load_stocks(repo_root: Path, codes: list[str] | None) -> list[dict[str, str]]:
    if codes:
        names = _stock_name_lookup(repo_root)
        return [
            {"code": normalized, "name": names.get(normalized, normalized)}
            for code in codes
            for normalized in [normalize_code(code)]
            if normalized
        ]

    path = repo_root / "backend" / "config" / "watchlist.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    stocks = []
    for item in payload.get("stocks", []):
        code = normalize_code(str(item.get("code", "")))
        if code:
            stocks.append({"code": code, "name": str(item.get("name") or code)})
    if not stocks:
        raise ValueError(f"watchlist is empty: {path}")
    return stocks


def _stock_name_lookup(repo_root: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in _read_stock_rows(repo_root / "backend" / "config" / "watchlist.json", "stocks"):
        _add_name(names, row)

    screen_root = repo_root / "data" / "screen"
    if screen_root.exists():
        for path in sorted(screen_root.glob("*/normalized/stock_screen_candidates.json")):
            for row in _read_stock_rows(path):
                _add_name(names, row)
        for path in sorted(screen_root.glob("*/normalized/system_watchlist.json")):
            for row in _read_stock_rows(path, "items"):
                _add_name(names, row)

    watchlist_root = repo_root / "data" / "watchlist" / "system"
    if watchlist_root.exists():
        for path in sorted(watchlist_root.glob("*.json")):
            for row in _read_stock_rows(path, "items"):
                _add_name(names, row)
    return names


def _read_stock_rows(path: Path, key: str | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if key is not None:
        rows = payload.get(key, []) if isinstance(payload, dict) else []
    else:
        rows = payload
    return rows if isinstance(rows, list) else []


def _add_name(names: dict[str, str], row: dict[str, Any]) -> None:
    code = normalize_code(str(row.get("code", "")))
    name = str(row.get("name") or "").strip()
    if code and name:
        names[code] = name


def _normalize_strategy_keys(strategies: list[str] | None) -> list[str]:
    keys = strategies or ["macd", "kdj", "rsi"]
    normalized = [key.strip().lower() for key in keys if key.strip()]
    unknown = sorted(set(normalized) - set(STRATEGIES))
    if unknown:
        raise ValueError(f"unknown strategies: {', '.join(unknown)}")
    return normalized


def _render_markdown(
    start_day: date,
    end_day: date,
    stocks: list[dict[str, str]],
    strategy_keys: list[str],
    costs: BacktestCostConfig,
    summaries: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    data_errors: list[dict[str, str]],
    manifest_path: Path,
) -> str:
    lines = [
        f"# 技术指标策略回测｜{start_day.isoformat()} 至 {end_day.isoformat()}",
        "",
        "> 本报告仅用于研究和学习，不构成任何投资建议。信号来自历史日 K 线，回测结果不代表未来收益。",
        "",
        "## 1. 回测设置",
        "",
        f"- 股票池：{_stock_names(stocks)}",
        f"- 策略：{', '.join(STRATEGIES[key].label for key in strategy_keys)}",
        "- 成交：收盘产生信号，下一交易日开盘成交。",
        f"- 单票初始资金：{_fmt_money(costs.initial_cash)}；佣金 {costs.commission_rate * 100:.3f}%、最低 {_fmt_money(costs.min_commission)}；卖出印花税 {costs.stamp_tax_rate * 100:.3f}%。",
        f"- 本地落库：`{manifest_path}`",
        "",
        "## 2. 策略总览",
        "",
    ]
    lines.extend(_strategy_overview(summaries))
    lines.extend(["", "## 3. 股票明细", ""])
    lines.extend(_summary_table(summaries))
    lines.extend(["", "## 4. 交易明细", ""])
    lines.extend(_trade_table(trades))
    lines.extend(["", "## 5. 新手读法", ""])
    lines.extend(_beginner_notes(summaries))
    if data_errors:
        lines.extend(["", "## 6. 数据缺口", ""])
        for item in data_errors:
            lines.append(f"- {item.get('name')}({item.get('code')})：{item.get('error')}")
    return "\n".join(lines) + "\n"


def _strategy_overview(summaries: list[dict[str, Any]]) -> list[str]:
    if not summaries:
        return ["> 暂无可用回测结果。"]
    frame = pd.DataFrame(summaries)
    rows = [
        "| 策略 | 股票数 | 平均收益 | 平均最大回撤 | 平均胜率 | 平均交易数 | 平均超额 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy, group in frame.groupby("strategy_label", sort=False):
        rows.append(
            "| {strategy} | {count} | {ret} | {dd} | {win} | {trades} | {excess} |".format(
                strategy=strategy,
                count=len(group),
                ret=_fmt_pct(group["total_return_pct"].mean()),
                dd=_fmt_pct(group["max_drawdown_pct"].mean()),
                win=_fmt_pct(group["win_rate_pct"].mean()),
                trades=_fmt_num(group["trade_count"].mean()),
                excess=_fmt_pct(group["excess_return_pct"].mean()),
            )
        )
    return rows


def _summary_table(summaries: list[dict[str, Any]]) -> list[str]:
    rows = [
        "| 股票 | 策略 | 收益 | 年化 | 最大回撤 | 交易 | 胜率 | 买入持有 | 超额 | 期末持仓 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    if not summaries:
        rows.append("| - | - | - | - | - | - | - | - | - | - |")
        return rows
    for item in sorted(summaries, key=lambda row: (row["code"], row["strategy"])):
        rows.append(
            "| {stock} | {strategy} | {ret} | {annual} | {dd} | {trades} | {win} | {hold} | {excess} | {open_position} |".format(
                stock=f"{item.get('name')}({item.get('code')})",
                strategy=item.get("strategy_label", "-"),
                ret=_fmt_pct(item.get("total_return_pct")),
                annual=_fmt_pct(item.get("annual_return_pct")),
                dd=_fmt_pct(item.get("max_drawdown_pct")),
                trades=item.get("trade_count", 0),
                win=_fmt_pct(item.get("win_rate_pct")),
                hold=_fmt_pct(item.get("buy_hold_return_pct")),
                excess=_fmt_pct(item.get("excess_return_pct")),
                open_position="是" if item.get("open_position") else "否",
            )
        )
    return rows


def _trade_table(trades: list[dict[str, Any]], limit: int = 80) -> list[str]:
    rows = [
        "| 股票 | 策略 | 买入日 | 卖出日/状态 | 买入价 | 卖出/估值价 | 收益 | 持仓天数 | 触发原因 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    if not trades:
        rows.append("| - | - | - | - | - | - | - | - | 无交易 |")
        return rows
    for item in trades[:limit]:
        exit_label = item.get("exit_date") or "期末持仓"
        reason = f"{item.get('entry_reason', '-')}; {item.get('exit_reason', '-')}"
        rows.append(
            "| {stock} | {strategy} | {entry_date} | {exit_label} | {entry_price} | {exit_price} | {ret} | {days} | {reason} |".format(
                stock=f"{item.get('name')}({item.get('code')})",
                strategy=item.get("strategy_label", "-"),
                entry_date=item.get("entry_date", "-"),
                exit_label=exit_label,
                entry_price=_fmt_num(item.get("entry_price")),
                exit_price=_fmt_num(item.get("exit_price")),
                ret=_fmt_pct(item.get("return_pct")),
                days=item.get("holding_days", "-"),
                reason=reason,
            )
        )
    if len(trades) > limit:
        rows.append(f"| ... | ... | ... | ... | ... | ... | ... | ... | 仅展示前 {limit} 条，共 {len(trades)} 条 |")
    return rows


def _beginner_notes(summaries: list[dict[str, Any]]) -> list[str]:
    if not summaries:
        return ["- 没有生成回测结果，先检查 BaoStock 数据是否可用。"]
    frame = pd.DataFrame(summaries)
    best = frame.sort_values("total_return_pct", ascending=False).iloc[0]
    frequent = frame.sort_values("trade_count", ascending=False).iloc[0]
    risky = frame.sort_values("max_drawdown_pct", ascending=True).iloc[0]
    return [
        f"- 本次收益最高的是 {best['name']}({best['code']}) 的 {best['strategy_label']}，收益 {_fmt_pct(best['total_return_pct'])}。",
        f"- 交易最频繁的是 {frequent['name']}({frequent['code']}) 的 {frequent['strategy_label']}，共 {int(frequent['trade_count'])} 笔。",
        f"- 回撤最大的是 {risky['name']}({risky['code']}) 的 {risky['strategy_label']}，最大回撤 {_fmt_pct(risky['max_drawdown_pct'])}。",
        "- 如果策略收益高但回撤也大，说明过程波动更难承受；如果交易很多但收益一般，手续费和假信号可能在吞噬优势。",
        "- `超额` 是相对同一股票买入持有的结果，正数表示这套指标规则在样本期内跑赢了简单持有。",
    ]


def _write_manifest(
    run_dir: Path,
    start_day: date,
    end_day: date,
    stocks: list[dict[str, str]],
    strategy_keys: list[str],
    costs: BacktestCostConfig,
    summaries: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    equity_rows: list[dict[str, Any]],
    data_errors: list[dict[str, str]],
) -> Path:
    path = run_dir / "manifest.json"
    payload = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "stocks": stocks,
        "strategies": strategy_keys,
        "costs": costs.__dict__,
        "datasets": [
            {"name": "summary", "ok": True, "row_count": len(summaries), "normalized_json": str(run_dir / "normalized" / "summary.json")},
            {"name": "trades", "ok": True, "row_count": len(trades), "normalized_json": str(run_dir / "normalized" / "trades.json")},
            {"name": "equity_curves", "ok": True, "row_count": len(equity_rows), "normalized_json": str(run_dir / "normalized" / "equity_curves.json")},
            {"name": "data_errors", "ok": not data_errors, "row_count": len(data_errors), "normalized_json": str(run_dir / "normalized" / "data_errors.json") if data_errors else None},
        ],
    }
    _write_json(path, payload)
    return path


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _fieldnames(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                ordered.append(key)
                seen.add(key)
    return ordered or ["empty"]


def _one_year_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _find_repo_root() -> Path:
    current = Path.cwd()
    if current.name == "backend":
        return current.parent
    return current


def _stock_names(stocks: list[dict[str, str]]) -> str:
    return "、".join(f"{item['name']}({item['code']})" for item in stocks) or "-"


def _fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}%"


def _fmt_num(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def _fmt_money(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.2f}"
