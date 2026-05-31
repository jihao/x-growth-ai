from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.data_sources.a_stock_data import AStockDataClient, normalize_code
from backend.data_sources.mx_stocks_screener import MxStocksScreenerClient, normalize_watchlist_rows


@dataclass(frozen=True)
class WatchlistConfig:
    snapshot_date: str | None = None
    config_path: Path | None = None
    output_path: Path | None = None
    use_live_data: bool = True
    force_refresh: bool = False


def generate_watchlist_snapshot(config: WatchlistConfig) -> Path:
    repo_root = _find_repo_root()
    snapshot_day = _parse_snapshot_date(config.snapshot_date)
    watchlist_path = config.config_path or repo_root / "backend" / "config" / "watchlist.json"
    stocks = _load_watchlist(watchlist_path)
    output_path = config.output_path or repo_root / "reports" / f"x_growth_watchlist_{snapshot_day.isoformat()}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir = repo_root / "data" / "watchlist" / snapshot_day.isoformat()

    cached_rows = _load_valid_cached_snapshot(data_dir)
    if cached_rows and not config.force_refresh:
        manifest_path = data_dir / "manifest.json"
        comparison = _compare_with_previous(repo_root, snapshot_day, cached_rows)
        trend = _build_five_day_trend(repo_root, snapshot_day, cached_rows)
        normalized_dir = data_dir / "normalized"
        normalized_dir.mkdir(parents=True, exist_ok=True)
        if comparison["ok"]:
            _write_json(normalized_dir / "watchlist_comparison.json", comparison)
        if trend["ok"]:
            _write_json(normalized_dir / "watchlist_trend_5d.json", trend)
        chart_paths = _render_trend_charts(repo_root, snapshot_day, trend)
        markdown = _render_markdown(
            snapshot_day,
            cached_rows,
            quote_status="缓存",
            info_status="缓存",
            manifest_path=manifest_path,
            comparison=comparison,
            trend=trend,
            chart_paths=chart_paths,
            notes=["本地 manifest 校验通过，本次优先使用本地落库数据，未重新请求外部接口。"],
        )
        output_path.write_text(markdown, encoding="utf-8")
        return output_path

    if not config.use_live_data:
        raise FileNotFoundError(f"no valid local watchlist snapshot: {data_dir}")

    mx_client = MxStocksScreenerClient(repo_root)
    mx_result = mx_client.watchlist_snapshot(snapshot_day.isoformat(), stocks)
    if mx_result.ok:
        source_rows = normalize_watchlist_rows(mx_result.rows, snapshot_day.isoformat())
        source_by_code = {row["code"]: row for row in source_rows}
        rows = [_merge_stock_snapshot(stock, source_by_code, {}, snapshot_day.isoformat()) for stock in stocks]
        quote_status = "OK(mx-stocks-screener)"
        info_status = "配置/筛选器补充"
        artifacts = {
            "mx_csv": str(mx_result.csv_path) if mx_result.csv_path else None,
            "mx_description": str(mx_result.description_path) if mx_result.description_path else None,
            "mx_error": mx_result.error,
        }
    else:
        client = AStockDataClient()
        codes = [stock["code"] for stock in stocks]
        quote_result = client.fetch_quotes(codes)
        info_result = client.fetch_stock_info(codes)

        quote_by_code = {row["code"]: row for row in quote_result.rows}
        info_by_code = {row["code"]: row for row in info_result.rows}
        rows = [_merge_stock_snapshot(stock, quote_by_code, info_by_code, snapshot_day.isoformat()) for stock in stocks]
        quote_status = _source_status(quote_result.error)
        info_status = _source_status(info_result.error)
        artifacts = {
            "mx_error": mx_result.error,
            "tencent_error": quote_result.error,
            "eastmoney_error": info_result.error,
        }

    normalized_dir = data_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    _write_json(normalized_dir / "watchlist_snapshot.json", rows)
    comparison = _compare_with_previous(repo_root, snapshot_day, rows)
    if comparison["ok"]:
        _write_json(normalized_dir / "watchlist_comparison.json", comparison)
    trend = _build_five_day_trend(repo_root, snapshot_day, rows)
    if trend["ok"]:
        _write_json(normalized_dir / "watchlist_trend_5d.json", trend)
    chart_paths = _render_trend_charts(repo_root, snapshot_day, trend)
    manifest_path = _write_manifest(data_dir, rows, watchlist_path, source="mx-stocks-screener" if mx_result.ok else "tencent/eastmoney-fallback", artifacts=artifacts)

    notes = ["已按参数强制刷新数据，本次重新请求外部接口。"] if config.force_refresh else []
    markdown = _render_markdown(
        snapshot_day,
        rows,
        quote_status=quote_status,
        info_status=info_status,
        manifest_path=manifest_path,
        comparison=comparison,
        trend=trend,
        chart_paths=chart_paths,
        notes=notes,
    )
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def _merge_stock_snapshot(
    stock: dict[str, Any],
    quote_by_code: dict[str, dict[str, Any]],
    info_by_code: dict[str, dict[str, Any]],
    snapshot_date: str,
) -> dict[str, Any]:
    code = normalize_code(str(stock["code"]))
    quote = quote_by_code.get(code, {})
    info = info_by_code.get(code, {})
    return {
        "date": snapshot_date,
        "code": code,
        "name": stock.get("name") or quote.get("name") or info.get("name") or "",
        "theme": stock.get("theme", ""),
        "reason": stock.get("reason", ""),
        "risk": stock.get("risk", ""),
        "industry": quote.get("industry") or info.get("industry") or stock.get("industry", ""),
        "price": quote.get("price"),
        "change_pct": quote.get("change_pct"),
        "turnover_pct": quote.get("turnover_pct"),
        "amount_wan": quote.get("amount_wan"),
        "pe_ttm": quote.get("pe_ttm"),
        "pb": quote.get("pb"),
        "market_cap_yi": quote.get("market_cap_yi"),
        "float_market_cap_yi": quote.get("float_market_cap_yi"),
        "limit_up": quote.get("limit_up"),
        "limit_down": quote.get("limit_down"),
        "volume_ratio": quote.get("volume_ratio"),
        "list_date": info.get("list_date", ""),
        "data_status": _stock_data_status(quote, info, stock),
    }


def _render_markdown(
    snapshot_day: date,
    rows: list[dict[str, Any]],
    quote_status: str,
    info_status: str,
    manifest_path: Path,
    comparison: dict[str, Any] | None = None,
    trend: dict[str, Any] | None = None,
    chart_paths: dict[str, Path] | None = None,
    notes: list[str] | None = None,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 自选股观察池｜{snapshot_day.isoformat()}",
        "",
        f"> 生成时间：{generated_at}｜定位：观察池快照，不构成投资建议。",
        "",
        "## 1. 数据状态",
        "",
        f"- 腾讯行情：{quote_status}",
        f"- 东财基础信息：{info_status}",
        f"- 本地落库：`{manifest_path}`",
    ]
    for note in notes or []:
        lines.append(f"- 备注：{note}")

    lines.extend(
        [
            "",
            "## 2. 快照总览",
            "",
            "| 股票 | 主题 | 行业 | 涨跌幅 | 现价 | PE(TTM) | PB | 换手率 | 成交额 | 数据 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| {name}({code}) | {theme} | {industry} | {change_pct} | {price} | {pe_ttm} | {pb} | {turnover_pct} | {amount} | {status} |".format(
                name=row["name"],
                code=row["code"],
                theme=row["theme"] or "-",
                industry=row["industry"] or "-",
                change_pct=_fmt_pct(row.get("change_pct")),
                price=_fmt_num(row.get("price")),
                pe_ttm=_fmt_num(row.get("pe_ttm")),
                pb=_fmt_num(row.get("pb")),
                turnover_pct=_fmt_pct(row.get("turnover_pct")),
                amount=_fmt_amount(row.get("amount_wan")),
                status=row["data_status"],
            )
        )

    lines.extend(["", "## 3. 环比变化", ""])
    lines.extend(_comparison_block(comparison))

    lines.extend(["", "## 4. 五日趋势", ""])
    lines.extend(_trend_block(trend, chart_paths))

    lines.extend(["", "## 5. 个股观察卡", ""])
    for row in rows:
        compare_row = _comparison_row_for_code(comparison, row["code"])
        lines.extend(_stock_card(row, compare_row))
        lines.append("")

    lines.extend(
        [
            "## 6. 下一步观察",
            "",
            "- 对涨跌幅明显偏离观察池均值的股票，回看行业/主题是否有同步变化。",
            "- 对 PE/PB 与成交活跃度同时变化的股票，优先补充技术指标和资金流数据。",
            "- 对数据不完整的股票，先标记观察，不做结论。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _stock_card(row: dict[str, Any], compare_row: dict[str, Any] | None = None) -> list[str]:
    valuation = _valuation_label(row)
    activity = _activity_label(row)
    lines = [
        f"### {row['name']}({row['code']})",
        "",
        f"- 观察主题：{row['theme'] or '-'}",
        f"- 所属行业：{row['industry'] or '-'}",
        f"- 价格表现：涨跌幅 {_fmt_pct(row.get('change_pct'))}，现价 {_fmt_num(row.get('price'))}，换手率 {_fmt_pct(row.get('turnover_pct'))}",
        f"- 估值观察：PE(TTM) {_fmt_num(row.get('pe_ttm'))}，PB {_fmt_num(row.get('pb'))}，{valuation}",
        f"- 活跃度观察：成交额 {_fmt_amount(row.get('amount_wan'))}，量比 {_fmt_num(row.get('volume_ratio'))}，{activity}",
        f"- 观察理由：{row['reason'] or '-'}",
        f"- 主要风险：{row['risk'] or '-'}",
    ]
    if compare_row:
        lines.insert(
            7,
            f"- 环比信号：{compare_row['signal']}；观察动作：{compare_row['action']}",
        )
    return lines


def _comparison_block(comparison: dict[str, Any] | None) -> list[str]:
    if not comparison or not comparison.get("ok"):
        reason = comparison.get("error") if comparison else "暂无上一份本地快照"
        return [f"> 暂无可用环比数据：{reason}。"]

    lines = [
        f"> 对比基准：{comparison['previous_date']}。",
        "",
        "| 股票 | 涨跌幅变化 | 成交额变化 | PE变化 | PB变化 | 换手率变化 | 信号 | 动作 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in comparison["rows"]:
        lines.append(
            "| {name}({code}) | {change_delta} | {amount_delta} | {pe_delta} | {pb_delta} | {turnover_delta} | {signal} | {action} |".format(
                name=row["name"],
                code=row["code"],
                change_delta=_fmt_pp_delta(row.get("change_pct_delta")),
                amount_delta=_fmt_ratio_delta(row.get("amount_delta_ratio")),
                pe_delta=_fmt_signed_num(row.get("pe_delta")),
                pb_delta=_fmt_signed_num(row.get("pb_delta")),
                turnover_delta=_fmt_pp_delta(row.get("turnover_delta")),
                signal=row["signal"],
                action=row["action"],
            )
        )
    return lines


def _comparison_row_for_code(comparison: dict[str, Any] | None, code: str) -> dict[str, Any] | None:
    if not comparison or not comparison.get("ok"):
        return None
    for row in comparison.get("rows", []):
        if row.get("code") == code:
            return row
    return None


def _trend_block(trend: dict[str, Any] | None, chart_paths: dict[str, Path] | None) -> list[str]:
    if not trend or not trend.get("ok"):
        reason = trend.get("error") if trend else "暂无足够本地快照"
        return [f"> 暂无可用五日趋势：{reason}。"]

    lines = [f"> 覆盖区间：{trend['start_date']} 至 {trend['end_date']}，共 {len(trend['dates'])} 个交易日。"]
    if chart_paths:
        lines.extend(
            [
                "",
                f"![5日价格走势]({chart_paths['price']})",
                "",
                f"![5日成交额走势]({chart_paths['amount']})",
                "",
                f"![5日估值走势]({chart_paths['valuation']})",
            ]
        )

    lines.extend(
        [
            "",
            "| 股票 | 5日累计涨幅 | 成交额变化 | PE变化 | PB变化 | 趋势判断 |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in trend["summary"]:
        lines.append(
            "| {name}({code}) | {return_5d} | {amount_delta} | {pe_delta} | {pb_delta} | {judgment} |".format(
                name=row["name"],
                code=row["code"],
                return_5d=_fmt_ratio_delta(row.get("return_5d")),
                amount_delta=_fmt_ratio_delta(row.get("amount_delta_ratio")),
                pe_delta=_fmt_signed_num(row.get("pe_delta")),
                pb_delta=_fmt_signed_num(row.get("pb_delta")),
                judgment=row["judgment"],
            )
        )
    return lines


def _build_five_day_trend(repo_root: Path, snapshot_day: date, rows: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = _load_recent_snapshots(repo_root, snapshot_day, limit=5)
    if not snapshots:
        return {"ok": False, "error": "没有找到有效观察池快照"}

    current_key = snapshot_day.isoformat()
    if snapshots[-1][0] != current_key:
        snapshots.append((current_key, rows))
    snapshots = snapshots[-5:]
    if len(snapshots) < 2:
        return {"ok": False, "error": "有效快照少于 2 天"}

    codes = [row.get("code") for row in rows]
    series: dict[str, dict[str, Any]] = {}
    for code in codes:
        points: list[dict[str, Any]] = []
        for day, day_rows in snapshots:
            row = next((item for item in day_rows if item.get("code") == code), None)
            if row:
                points.append(
                    {
                        "date": day,
                        "name": row.get("name", ""),
                        "price": row.get("price"),
                        "change_pct": row.get("change_pct"),
                        "amount_wan": row.get("amount_wan"),
                        "turnover_pct": row.get("turnover_pct"),
                        "pe_ttm": row.get("pe_ttm"),
                        "pb": row.get("pb"),
                    }
                )
        if points:
            series[str(code)] = {"name": points[-1]["name"], "points": points}

    return {
        "ok": True,
        "start_date": snapshots[0][0],
        "end_date": snapshots[-1][0],
        "dates": [day for day, _ in snapshots],
        "series": series,
        "summary": [_trend_summary_row(code, item) for code, item in series.items()],
    }


def _load_recent_snapshots(repo_root: Path, snapshot_day: date, limit: int) -> list[tuple[str, list[dict[str, Any]]]]:
    snapshots: list[tuple[str, list[dict[str, Any]]]] = []
    current = snapshot_day - timedelta(days=30)
    while current <= snapshot_day:
        if current.weekday() < 5:
            rows = _load_valid_cached_snapshot(repo_root / "data" / "watchlist" / current.isoformat())
            if rows:
                snapshots.append((current.isoformat(), rows))
        current += timedelta(days=1)
    return snapshots[-limit:]


def _trend_summary_row(code: str, item: dict[str, Any]) -> dict[str, Any]:
    points = item["points"]
    first = points[0]
    last = points[-1]
    return_5d = _ratio_delta(last.get("price"), first.get("price"))
    amount_delta_ratio = _ratio_delta(last.get("amount_wan"), first.get("amount_wan"))
    pe_delta = _delta(last.get("pe_ttm"), first.get("pe_ttm"))
    pb_delta = _delta(last.get("pb"), first.get("pb"))
    return {
        "code": code,
        "name": item.get("name", ""),
        "return_5d": return_5d,
        "amount_delta_ratio": amount_delta_ratio,
        "pe_delta": pe_delta,
        "pb_delta": pb_delta,
        "judgment": _trend_judgment(return_5d, amount_delta_ratio, pe_delta, pb_delta),
    }


def _trend_judgment(
    return_5d: float | None,
    amount_delta_ratio: float | None,
    pe_delta: float | None,
    pb_delta: float | None,
) -> str:
    if return_5d is None:
        return "数据不足"
    if return_5d >= 0.04 and amount_delta_ratio is not None and amount_delta_ratio >= 0.3:
        return "量价同升，趋势较强"
    if return_5d >= 0.02:
        return "温和走强"
    if return_5d <= -0.04 and amount_delta_ratio is not None and amount_delta_ratio >= 0.3:
        return "放量走弱，注意风险"
    if return_5d <= -0.02:
        return "偏弱调整"
    if pe_delta is not None and pb_delta is not None and pe_delta > 0 and pb_delta > 0:
        return "价格平稳但估值抬升"
    return "区间震荡"


def _render_trend_charts(repo_root: Path, snapshot_day: date, trend: dict[str, Any]) -> dict[str, Path]:
    if not trend.get("ok"):
        return {}
    try:
        return _render_trend_charts_with_matplotlib(repo_root, snapshot_day, trend)
    except Exception:
        return {}


def _render_trend_charts_with_matplotlib(repo_root: Path, snapshot_day: date, trend: dict[str, Any]) -> dict[str, Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

    font = _chart_font(FontProperties)
    asset_dir = repo_root / "reports" / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    base = f"x_growth_watchlist_{snapshot_day.isoformat()}"
    paths = {
        "price": asset_dir / f"{base}_price_5d.png",
        "amount": asset_dir / f"{base}_amount_5d.png",
        "valuation": asset_dir / f"{base}_valuation_5d.png",
    }

    dates = trend["dates"]
    x_labels = [day[5:] for day in dates]

    _plot_line_chart(
        plt,
        font,
        paths["price"],
        title="观察池5日价格走势",
        x_labels=x_labels,
        series=trend["series"],
        metric="price",
        ylabel="收盘价(元)",
    )
    _plot_line_chart(
        plt,
        font,
        paths["amount"],
        title="观察池5日成交额走势",
        x_labels=x_labels,
        series=trend["series"],
        metric="amount_wan",
        ylabel="成交额(万元)",
        scale=10000,
    )
    _plot_valuation_chart(plt, font, paths["valuation"], x_labels, trend["series"])
    return paths


def _plot_line_chart(
    plt: Any,
    font: Any,
    path: Path,
    *,
    title: str,
    x_labels: list[str],
    series: dict[str, Any],
    metric: str,
    ylabel: str,
    scale: float = 1.0,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=160)
    for item in series.values():
        values = [_chart_value(point.get(metric), scale=scale) for point in item["points"]]
        ax.plot(x_labels[-len(values):], values, marker="o", linewidth=2, label=item["name"])
    ax.axhline(0, color="#d0d5dd", linewidth=0.8)
    ax.set_title(title, fontproperties=font, fontsize=13)
    ax.set_ylabel(ylabel, fontproperties=font)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.35)
    ax.legend(prop=font, loc="best")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def _plot_valuation_chart(plt: Any, font: Any, path: Path, x_labels: list[str], series: dict[str, Any]) -> None:
    fig, (ax_pe, ax_pb) = plt.subplots(2, 1, figsize=(9, 6.2), dpi=160, sharex=True)
    for item in series.values():
        pe_values = [_chart_value(point.get("pe_ttm")) for point in item["points"]]
        pb_values = [_chart_value(point.get("pb")) for point in item["points"]]
        labels = x_labels[-len(pe_values):]
        ax_pe.plot(labels, pe_values, marker="o", linewidth=2, label=item["name"])
        ax_pb.plot(labels, pb_values, marker="o", linewidth=2, label=item["name"])
    ax_pe.set_title("观察池5日估值走势", fontproperties=font, fontsize=13)
    ax_pe.set_ylabel("PE(TTM)", fontproperties=font)
    ax_pb.set_ylabel("PB", fontproperties=font)
    for ax in (ax_pe, ax_pb):
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.35)
    ax_pe.legend(prop=font, loc="best")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def _chart_font(font_properties_cls: Any) -> Any:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return font_properties_cls(fname=str(path))
    return font_properties_cls()


def _chart_value(value: Any, *, scale: float = 1.0) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return value / scale


def _compare_with_previous(repo_root: Path, snapshot_day: date, rows: list[dict[str, Any]]) -> dict[str, Any]:
    previous_date, previous_rows = _load_previous_snapshot(repo_root, snapshot_day)
    if previous_date is None or previous_rows is None:
        return {"ok": False, "error": "没有找到上一份有效观察池快照"}

    previous_by_code = {row.get("code"): row for row in previous_rows}
    comparison_rows: list[dict[str, Any]] = []
    for row in rows:
        previous = previous_by_code.get(row.get("code"))
        if not previous:
            comparison_rows.append(_missing_comparison_row(row))
            continue
        comparison_rows.append(_compare_stock_row(row, previous))

    return {
        "ok": True,
        "previous_date": previous_date.isoformat(),
        "rows": comparison_rows,
    }


def _load_previous_snapshot(repo_root: Path, snapshot_day: date) -> tuple[date | None, list[dict[str, Any]] | None]:
    current = snapshot_day - timedelta(days=1)
    lower_bound = snapshot_day - timedelta(days=14)
    while current >= lower_bound:
        if current.weekday() < 5:
            rows = _load_valid_cached_snapshot(repo_root / "data" / "watchlist" / current.isoformat())
            if rows:
                return current, rows
        current -= timedelta(days=1)
    return None, None


def _compare_stock_row(row: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    change_delta = _delta(row.get("change_pct"), previous.get("change_pct"))
    amount_delta_ratio = _ratio_delta(row.get("amount_wan"), previous.get("amount_wan"))
    pe_delta = _delta(row.get("pe_ttm"), previous.get("pe_ttm"))
    pb_delta = _delta(row.get("pb"), previous.get("pb"))
    turnover_delta = _delta(row.get("turnover_pct"), previous.get("turnover_pct"))
    signal = _comparison_signal(change_delta, amount_delta_ratio, pe_delta, pb_delta, turnover_delta)
    return {
        "code": row.get("code", ""),
        "name": row.get("name", ""),
        "change_pct_delta": change_delta,
        "amount_delta_ratio": amount_delta_ratio,
        "pe_delta": pe_delta,
        "pb_delta": pb_delta,
        "turnover_delta": turnover_delta,
        "signal": signal,
        "action": _comparison_action(row, change_delta, amount_delta_ratio, pe_delta, pb_delta, signal),
    }


def _missing_comparison_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row.get("code", ""),
        "name": row.get("name", ""),
        "change_pct_delta": None,
        "amount_delta_ratio": None,
        "pe_delta": None,
        "pb_delta": None,
        "turnover_delta": None,
        "signal": "上一期缺少该股票",
        "action": "数据不足",
    }


def _valuation_label(row: dict[str, Any]) -> str:
    pe = row.get("pe_ttm")
    pb = row.get("pb")
    if pe is None and pb is None:
        return "估值数据不足"
    notes: list[str] = []
    if isinstance(pe, (int, float)):
        if pe <= 8:
            notes.append("PE 偏低")
        elif pe >= 35:
            notes.append("PE 偏高")
        else:
            notes.append("PE 中性")
    if isinstance(pb, (int, float)):
        if pb <= 1:
            notes.append("PB 偏低")
        elif pb >= 5:
            notes.append("PB 偏高")
    return "，".join(notes)


def _activity_label(row: dict[str, Any]) -> str:
    turnover = row.get("turnover_pct")
    amount = row.get("amount_wan")
    if turnover is None and amount is None:
        return "活跃度数据不足"
    if isinstance(turnover, (int, float)) and turnover >= 5:
        return "换手较活跃"
    if isinstance(amount, (int, float)) and amount >= 500000:
        return "成交额较高"
    return "活跃度正常"


def _comparison_signal(
    change_delta: float | None,
    amount_delta_ratio: float | None,
    pe_delta: float | None,
    pb_delta: float | None,
    turnover_delta: float | None,
) -> str:
    signals: list[str] = []
    if amount_delta_ratio is not None:
        if amount_delta_ratio >= 0.5:
            signals.append("成交明显放大")
        elif amount_delta_ratio <= -0.3:
            signals.append("成交明显收缩")
    if turnover_delta is not None and turnover_delta >= 0.5:
        signals.append("换手抬升")
    if pe_delta is not None:
        if pe_delta >= 1:
            signals.append("估值抬升")
        elif pe_delta <= -1:
            signals.append("估值压缩")
    if pb_delta is not None:
        if pb_delta >= 0.2:
            signals.append("PB抬升")
        elif pb_delta <= -0.2:
            signals.append("PB压缩")
    if change_delta is not None:
        if change_delta >= 3:
            signals.append("股价动能增强")
        elif change_delta <= -3:
            signals.append("股价动能转弱")
    return "，".join(signals) if signals else "变化温和"


def _comparison_action(
    row: dict[str, Any],
    change_delta: float | None,
    amount_delta_ratio: float | None,
    pe_delta: float | None,
    pb_delta: float | None,
    signal: str,
) -> str:
    if any(value is None for value in (change_delta, amount_delta_ratio)):
        return "数据不足"

    current_change = row.get("change_pct")
    if isinstance(current_change, (int, float)) and current_change >= 5 and amount_delta_ratio is not None and amount_delta_ratio >= 0.5:
        return "暂不追高"
    if "成交明显放大" in signal and ("估值抬升" in signal or "股价动能增强" in signal):
        return "重点关注"
    if pe_delta is not None and pb_delta is not None and pe_delta <= -1 and pb_delta <= -0.1:
        return "继续观察"
    return "继续观察"


def _delta(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return None
    return current - previous


def _ratio_delta(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)) or previous == 0:
        return None
    return current / previous - 1


def _stock_data_status(quote: dict[str, Any], info: dict[str, Any], stock: dict[str, Any]) -> str:
    if quote and info:
        return "OK"
    if quote and stock.get("industry"):
        return "行情OK/配置补充"
    if quote:
        return "缺基础信息"
    if info:
        return "缺行情"
    return "缺失"


def _load_watchlist(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"watchlist config not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    stocks = payload.get("stocks", [])
    if not isinstance(stocks, list) or not stocks:
        raise ValueError(f"watchlist config has no stocks: {path}")
    return [_validate_stock(row) for row in stocks]


def _validate_stock(row: dict[str, Any]) -> dict[str, Any]:
    if "code" not in row:
        raise ValueError("watchlist stock missing code")
    return {**row, "code": normalize_code(str(row["code"]))}


def _load_valid_cached_snapshot(data_dir: Path) -> list[dict[str, Any]] | None:
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    datasets = manifest.get("datasets", [])
    snapshot_record = next((item for item in datasets if item.get("name") == "watchlist_snapshot"), None)
    if not snapshot_record or not snapshot_record.get("ok"):
        return None

    json_path = Path(snapshot_record.get("normalized_json") or data_dir / "normalized" / "watchlist_snapshot.json")
    if not json_path.exists():
        return None
    try:
        rows = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_manifest(
    data_dir: Path,
    rows: list[dict[str, Any]],
    config_path: Path,
    *,
    source: str,
    artifacts: dict[str, Any],
) -> Path:
    path = data_dir / "manifest.json"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_path": str(config_path),
        "datasets": [
            {
                "name": "watchlist_snapshot",
                "ok": all(row["data_status"] in {"OK", "行情OK/配置补充"} for row in rows),
                "row_count": len(rows),
                "normalized_json": str(data_dir / "normalized" / "watchlist_snapshot.json"),
            },
            {
                "name": "watchlist_source",
                "ok": all(row["data_status"] in {"OK", "行情OK/配置补充"} for row in rows),
                "row_count": len(rows),
                "source": source,
                **artifacts,
            },
        ],
    }
    _write_json(path, payload)
    return path


def _parse_snapshot_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    today = date.today()
    current = today - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _find_repo_root() -> Path:
    current = Path.cwd()
    if current.name == "backend":
        return current.parent
    return current


def _fmt_num(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:.2f}"


def _fmt_pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:.2f}%"


def _fmt_amount(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    if value >= 10000:
        return f"{value / 10000:.2f}亿"
    return f"{value:.0f}万"


def _fmt_signed_num(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:+.2f}"


def _fmt_pp_delta(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:+.2f}pct"


def _fmt_ratio_delta(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value * 100:+.1f}%"


def _source_status(error: str | None) -> str:
    if not error:
        return "OK"
    parts = [part.strip() for part in error.split(";") if part.strip()]
    if not parts:
        return "部分异常"
    compact = "；".join(_compact_error(part) for part in parts[:3])
    if len(parts) > 3:
        compact += f"；另有 {len(parts) - 3} 条异常"
    return f"部分异常：{compact}"


def _compact_error(error: str) -> str:
    text = error.replace("\n", " ")
    if "ProxyError" in text:
        code = text.split(":", 1)[0]
        return f"{code}: ProxyError"
    if len(text) > 120:
        return text[:117] + "..."
    return text
