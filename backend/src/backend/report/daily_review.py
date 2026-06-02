from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.analysis.daily_compare import DailyComparison, compare_with_previous
from backend.analysis.data_status import DATASET_LABELS
from backend.analysis.market_regime import MarketRegime, assess_daily_regime
from backend.data_sources.mx_finance_data import MxFinanceDataClient
from backend.data_sources.mx_stocks_screener import MxStocksScreenerClient
from backend.storage.daily_store import DailyDataStore


@dataclass(frozen=True)
class DailyReviewConfig:
    review_date: str | None = None
    output_path: Path | None = None
    use_live_data: bool = True
    force_refresh: bool = False


@dataclass(frozen=True)
class CachedDailyInputs:
    index_rows: list[dict[str, Any]]
    breadth_rows: list[dict[str, Any]]
    sector_rows: list[dict[str, Any]]
    top_gainer_rows: list[dict[str, Any]]
    top_turnover_rows: list[dict[str, Any]]


REQUIRED_LIVE_DATASETS = (
    "index_snapshot",
    "market_breadth",
    "sector_top_gainers",
    "stock_top_gainers",
    "stock_top_turnover",
)


def generate_daily_review(config: DailyReviewConfig) -> Path:
    repo_root = _find_repo_root()
    review_day = _parse_review_date(config.review_date)
    output_path = config.output_path or repo_root / "reports" / f"x_growth_daily_review_{review_day.isoformat()}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    store = DailyDataStore(repo_root, review_day.isoformat())

    data_notes: list[str] = []
    index_rows: list[dict[str, Any]] = []
    breadth_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    top_gainer_rows: list[dict[str, Any]] = []
    top_turnover_rows: list[dict[str, Any]] = []
    review_date_str = review_day.isoformat()
    concentration_summary: dict[str, Any] | None = None
    cache_inputs = _load_valid_cached_inputs(store)

    if cache_inputs and not config.force_refresh:
        index_rows = store.save_cached_dataset("index_snapshot", cache_inputs.index_rows)
        breadth_rows = store.save_cached_dataset("market_breadth", cache_inputs.breadth_rows)
        sector_rows = store.save_cached_dataset("sector_top_gainers", cache_inputs.sector_rows)
        top_gainer_rows = store.save_cached_dataset("stock_top_gainers", cache_inputs.top_gainer_rows)
        top_turnover_rows = store.save_cached_dataset("stock_top_turnover", cache_inputs.top_turnover_rows)
        data_notes.append("本地 manifest 校验通过，本次优先使用本地落库数据，未重新请求 mx skills。")
    elif config.use_live_data:
        if config.force_refresh:
            data_notes.append("已按参数强制刷新数据，本次会重新请求 mx skills。")
        finance_client = MxFinanceDataClient(repo_root)
        index_result = finance_client.query_index_snapshot(review_date_str)
        if index_result.ok:
            index_rows = index_result.rows
            store.save_dataset(
                "index_snapshot",
                index_rows,
                source=".skills/mx-skills/mx-finance-data",
                raw_paths=[index_result.xlsx_path, index_result.description_path],
            )
        else:
            data_notes.append(f"mx-finance-data 指数数据获取失败：{_compact_error(index_result.error)}")
            store.save_failure("index_snapshot", source=".skills/mx-skills/mx-finance-data", error=index_result.error)

        breadth_result = finance_client.query_market_breadth(review_date_str)
        if breadth_result.ok:
            breadth_rows = breadth_result.rows
            store.save_dataset(
                "market_breadth",
                breadth_rows,
                source=".skills/mx-skills/mx-finance-data",
                raw_paths=[breadth_result.xlsx_path, breadth_result.description_path],
            )
        else:
            data_notes.append(f"mx-finance-data 市场宽度获取失败：{_compact_error(breadth_result.error)}")
            store.save_failure("market_breadth", source=".skills/mx-skills/mx-finance-data", error=breadth_result.error)

        screener_client = MxStocksScreenerClient(repo_root)
        sector_result = screener_client.top_sectors(review_date_str)
        if sector_result.ok:
            sector_rows = sector_result.rows
            store.save_dataset(
                "sector_top_gainers",
                sector_rows,
                source=".skills/mx-skills/mx-stocks-screener",
                raw_paths=[sector_result.csv_path, sector_result.description_path],
            )
        else:
            data_notes.append(f"mx-stocks-screener 板块轮动获取失败：{_compact_error(sector_result.error)}")
            store.save_failure("sector_top_gainers", source=".skills/mx-skills/mx-stocks-screener", error=sector_result.error)

        gainer_result = screener_client.top_gainers(review_date_str)
        if gainer_result.ok:
            top_gainer_rows = gainer_result.rows
            store.save_dataset(
                "stock_top_gainers",
                top_gainer_rows,
                source=".skills/mx-skills/mx-stocks-screener",
                raw_paths=[gainer_result.csv_path, gainer_result.description_path],
            )
        else:
            data_notes.append(f"mx-stocks-screener 涨幅榜获取失败：{_compact_error(gainer_result.error)}")
            store.save_failure("stock_top_gainers", source=".skills/mx-skills/mx-stocks-screener", error=gainer_result.error)

        turnover_result = screener_client.top_turnover(review_date_str)
        if turnover_result.ok:
            top_turnover_rows = turnover_result.rows
            store.save_dataset(
                "stock_top_turnover",
                top_turnover_rows,
                source=".skills/mx-skills/mx-stocks-screener",
                raw_paths=[turnover_result.csv_path, turnover_result.description_path],
            )
        else:
            data_notes.append(f"mx-stocks-screener 成交额榜获取失败：{_compact_error(turnover_result.error)}")
            store.save_failure("stock_top_turnover", source=".skills/mx-skills/mx-stocks-screener", error=turnover_result.error)
    else:
        data_notes.append("已按参数跳过实时数据获取。")
        if cache_inputs:
            index_rows = store.save_cached_dataset("index_snapshot", cache_inputs.index_rows)
            breadth_rows = store.save_cached_dataset("market_breadth", cache_inputs.breadth_rows)
            sector_rows = store.save_cached_dataset("sector_top_gainers", cache_inputs.sector_rows)
            top_gainer_rows = store.save_cached_dataset("stock_top_gainers", cache_inputs.top_gainer_rows)
            top_turnover_rows = store.save_cached_dataset("stock_top_turnover", cache_inputs.top_turnover_rows)
            data_notes.append("已使用本地落库数据生成报告。")

    if config.use_live_data and (config.force_refresh or not cache_inputs):
        index_rows = _fallback_cached_dataset(store, "index_snapshot", index_rows, data_notes)
        breadth_rows = _fallback_cached_dataset(store, "market_breadth", breadth_rows, data_notes)
        sector_rows = _fallback_cached_dataset(store, "sector_top_gainers", sector_rows, data_notes)
        top_gainer_rows = _fallback_cached_dataset(store, "stock_top_gainers", top_gainer_rows, data_notes)
        top_turnover_rows = _fallback_cached_dataset(store, "stock_top_turnover", top_turnover_rows, data_notes)

    if top_turnover_rows and breadth_rows:
        concentration_summary = _concentration_summary(top_turnover_rows, breadth_rows, review_date_str)
        store.save_summary("concentration_metrics", concentration_summary)
        store.save_dataset(
            "industry_top50_turnover",
            _industry_concentration_rows(top_turnover_rows, review_date_str),
            source="backend-derived",
        )
    comparison = compare_with_previous(repo_root, review_day.isoformat(), store.base_dir)
    if comparison.ok:
        store.save_summary(
            "daily_comparison",
            {
                "previous_date": comparison.previous_date,
                **comparison.metrics,
            },
        )
    else:
        store.save_failure("daily_comparison", source="backend-derived", error=comparison.error)
    market_regime = assess_daily_regime(
        index_rows,
        breadth_rows,
        concentration_summary,
        comparison.metrics if comparison.ok else None,
    )
    store.save_summary("market_regime", _market_regime_summary(market_regime))
    manifest_path = store.write_manifest()

    markdown = _render_markdown(
        review_day,
        index_rows,
        breadth_rows,
        sector_rows,
        top_gainer_rows,
        top_turnover_rows,
        review_date_str,
        comparison,
        market_regime,
        data_notes,
        manifest_path,
    )
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def _render_markdown(
    review_day: date,
    index_rows: list[dict[str, Any]],
    breadth_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    top_gainer_rows: list[dict[str, Any]],
    top_turnover_rows: list[dict[str, Any]],
    review_date: str,
    comparison: DailyComparison,
    market_regime: MarketRegime,
    data_notes: list[str],
    manifest_path: Path,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# A 股复盘日报｜{review_day.isoformat()}",
        "",
        f"> 生成时间：{generated_at}｜定位：学习型市场复盘，不构成投资建议。",
        "",
        "## 1. 今日一句话",
        "",
        _one_sentence(index_rows),
        "",
        "## 2. 数据可信度",
        "",
        _data_credibility_block(manifest_path),
        "",
        "## 3. 市场状态",
        "",
        _market_regime_block(market_regime),
        "",
        "## 4. 复盘仪表盘",
        "",
        _review_dashboard(
            index_rows,
            breadth_rows,
            sector_rows,
            top_turnover_rows,
            review_date,
            comparison,
            market_regime,
        ),
        "",
        "## 5. 今日市场信号卡",
        "",
        _beginner_signal_card(breadth_rows, sector_rows, top_turnover_rows, review_date, comparison),
        "",
        "## 6. 大盘表现",
        "",
        _index_table(index_rows),
        "",
        "### 怎么看",
        "",
        "- 先看主要指数是否同涨同跌：同涨代表市场共振，分化代表结构行情。",
        "- 再看成交额是否放大：上涨放量通常更健康，下跌放量要警惕恐慌或出货。",
        "- 最后看长短周期位置：指数在 5 日/20 日均线附近的得失，可作为短线强弱参考。",
        "",
        "## 7. 市场宽度",
        "",
        _breadth_table(breadth_rows),
        "",
        _breadth_commentary(breadth_rows),
        "",
        "## 8. 成交额与量能",
        "",
        _turnover_block(breadth_rows, index_rows),
        "",
        "## 9. 资金与情绪",
        "",
        "- **北向资金**：2024 年下半年后实时披露口径变化，能拿到时只作为辅助观察，不单独作为买卖依据。",
        "- **主力资金流**：看连续性，不看单日噪音；连续流入且价格同步走强更有参考价值。",
        "- **情绪温度**：涨停数、连板高度、跌停数、炸板率比单一新闻更接近盘面真实状态。",
        "",
        _sentiment_temperature_block(breadth_rows),
        "",
        "## 10. 成交额集中度",
        "",
        _concentration_table(top_turnover_rows, breadth_rows, review_date),
        "",
        _concentration_commentary(top_turnover_rows, breadth_rows, review_date),
        "",
        "### 日环比",
        "",
        _comparison_table(comparison),
        "",
        "### Top50 行业成交分布",
        "",
        _industry_concentration_table(top_turnover_rows, review_date),
        "",
        "## 11. 板块轮动",
        "",
        _sector_table(sector_rows, review_date),
        "",
        _sector_commentary(sector_rows),
        "",
        "## 12. 个股强势榜",
        "",
        _stock_table(top_gainer_rows, review_date),
        "",
        "## 13. 成交额前十",
        "",
        _turnover_stock_table(top_turnover_rows, review_date),
        "",
        "## 14. 风险提示",
        "",
        _risk_block(index_rows, breadth_rows),
        "",
        _historical_context_note(breadth_rows),
        "",
        "## 15. 明日观察清单",
        "",
        _tomorrow_watch_list(breadth_rows, sector_rows, top_turnover_rows, review_date, market_regime),
        "",
        "## 16. 初学者行动边界",
        "",
        _beginner_action_guide(breadth_rows, sector_rows, top_turnover_rows, review_date),
        "",
        "## 17. 初学者术语表",
        "",
        _beginner_glossary(),
        "",
        "## 18. 学习路线",
        "",
        _beginner_learning_path(),
        "",
        "## 19. 数据缺口",
        "",
        _data_notes(data_notes),
        "",
        "## 20. 本地数据",
        "",
        f"- Manifest: `{manifest_path}`",
        f"- 标准化数据目录: `{manifest_path.parent / 'normalized'}`",
        f"- Skill 原始产物目录: `{manifest_path.parent / 'raw'}`",
        "",
        "## 21. 下一步迭代",
        "",
        "- 对自选股增加四层过滤：趋势、动量、量能、波动率。",
        "- 增加 1 日/5 日/20 日板块强度对比，区分一日游和趋势主线。",
        "- 基于每日落库数据计算 CR50、行业占比、板块热度的日环比。",
        "",
    ]
    return "\n".join(lines)


def _index_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "| 指数 | 代码 | 收盘 | 涨跌幅 | 成交额 | 数据状态 |\n|---|---:|---:|---:|---:|---|\n| 暂无 | - | - | - | - | 等待数据源依赖或网络可用 |"

    table = ["| 指数 | 代码 | 收盘 | 涨跌幅 | 成交额 |", "|---|---:|---:|---:|---:|"]
    for row in rows:
        table.append(
            "| {name} | {code} | {close} | {pct_change} | {amount} |".format(
                name=row.get("name", "-"),
                code=row.get("code", "-"),
                close=_fmt_number(row.get("close")),
                pct_change=_fmt_pct(row.get("pct_change")),
                amount=_fmt_amount(row.get("amount")),
            )
        )
    return "\n".join(table)


def _market_regime_block(regime: MarketRegime) -> str:
    drivers = "；".join(regime.drivers) if regime.drivers else "数据不足"
    watch_items = "\n".join(f"- {item}" for item in regime.watch_items)
    return "\n".join(
        [
            f"- **状态标签**：{regime.label}",
            f"- **操作语气**：{regime.tone}",
            f"- **判断置信度**：{regime.confidence}",
            f"- **触发依据**：{drivers}",
            "",
            watch_items,
        ]
    )


def _data_credibility_block(manifest_path: Path) -> str:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "> manifest 暂不可读，无法判断数据可信度。"

    records = manifest.get("datasets", [])
    if not isinstance(records, list):
        return "> manifest 格式异常，无法判断数据可信度。"

    rows = []
    for name in REQUIRED_LIVE_DATASETS:
        rows.append(_dataset_credibility_row(name, records))

    table = ["| 数据集 | 状态 | 来源 | 行数 | 备注 |", "|---|---|---|---:|---|"]
    for row in rows:
        table.append(
            "| {label} | {status} | {source} | {row_count} | {note} |".format(
                label=row["label"],
                status=row["status"],
                source=row["source"],
                row_count=row["row_count"],
                note=row["note"],
            )
        )

    table.extend(["", f"> 结论：{_credibility_summary(rows)}"])
    return "\n".join(table)


def _dataset_credibility_row(name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    label = DATASET_LABELS.get(name, name)
    dataset_records = [record for record in records if record.get("name") == name]
    ok_records = [record for record in dataset_records if record.get("ok") is True]
    failure_records = [record for record in dataset_records if record.get("ok") is False]
    latest_ok = ok_records[-1] if ok_records else None
    latest_failure = failure_records[-1] if failure_records else None

    if latest_ok:
        source = str(latest_ok.get("source") or "-")
        status = "缓存" if source == "local-cache" else "OK"
        note = "本地落库" if source == "local-cache" else "本次或最近一次 skill 获取成功"
        if latest_failure:
            note = f"已兜底；此前失败：{_compact_error(str(latest_failure.get('error') or ''))}"
        return {
            "label": label,
            "status": status,
            "source": source,
            "row_count": _safe_int(latest_ok.get("row_count")),
            "note": note,
        }

    if latest_failure:
        return {
            "label": label,
            "status": "失败",
            "source": str(latest_failure.get("source") or "-"),
            "row_count": 0,
            "note": _compact_error(str(latest_failure.get("error") or "")),
        }

    return {"label": label, "status": "缺失", "source": "-", "row_count": 0, "note": "manifest 未记录该数据集"}


def _credibility_summary(rows: list[dict[str, Any]]) -> str:
    failed = [row["label"] for row in rows if row["status"] in {"失败", "缺失"}]
    cached = [row["label"] for row in rows if row["status"] == "缓存"]
    if failed:
        return f"核心数据不完整，缺口包括 {', '.join(failed)}，本报告只能做部分参考。"
    if cached and len(cached) == len(rows):
        return "核心数据完整；本次使用本地落库数据，未重新请求 mx skills，适合做横向比较。"
    if cached:
        return f"核心数据完整；其中 {', '.join(cached)} 使用本地缓存，其余来自 skill 成功结果。"
    return "核心数据完整；基础数据来自 skill 成功结果。"


def _review_dashboard(
    index_rows: list[dict[str, Any]],
    breadth_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    turnover_rows: list[dict[str, Any]],
    review_date: str,
    comparison: DailyComparison,
    regime: MarketRegime,
) -> str:
    values = _metrics(breadth_rows)
    up = _to_float(values.get("上涨家数"))
    down = _to_float(values.get("下跌家数"))
    limit_up = _to_float(values.get("涨停家数"))
    limit_down = _to_float(values.get("跌停家数"))
    cr50 = _dashboard_cr50(turnover_rows, breadth_rows, review_date)
    index_positive = sum(1 for row in index_rows if (_to_float(row.get("pct_change")) or 0) > 0)
    index_total = len(index_rows)

    rows = [
        ("市场状态", regime.label, regime.tone, "先按状态决定观察顺序，而不是先猜涨跌。"),
        ("指数共振", _index_sync_label(index_positive, index_total), _index_sync_score(index_positive, index_total), "指数同涨同跌代表共振，分化时更重视结构。"),
        ("赚钱效应", _breadth_label(up, down), _breadth_score(up, down), "上涨家数越多，机会越容易扩散到普通个股。"),
        ("亏钱效应", _tail_risk_label(limit_up, limit_down), _tail_risk_score(limit_up, limit_down), "跌停数和高位补跌决定短线风险温度。"),
        ("主线持续性", _sector_strength_label(sector_rows, review_date), _sector_strength_score(sector_rows, review_date), "领涨板块需要连续性，单日强只能算线索。"),
        ("资金集中", _concentration_label(cr50), _concentration_score(cr50), "集中度高说明资金抱团，集中度低更利于扩散。"),
        ("日环比", _comparison_label(comparison), _comparison_score(comparison), "环比用来判断今天是改善、恶化，还是单日噪音。"),
    ]

    table = ["| 维度 | 观察结果 | 复盘语气 | 怎么用 |", "|---|---|---|---|"]
    for dimension, result, tone, note in rows:
        table.append(f"| {dimension} | {result} | {tone} | {note} |")
    return "\n".join(table)


def _beginner_signal_card(
    breadth_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    turnover_rows: list[dict[str, Any]],
    review_date: str,
    comparison: DailyComparison,
) -> str:
    values = _metrics(breadth_rows)
    up = _to_float(values.get("上涨家数"))
    down = _to_float(values.get("下跌家数"))
    limit_up = _to_float(values.get("涨停家数"))
    limit_down = _to_float(values.get("跌停家数"))
    cr50 = _dashboard_cr50(turnover_rows, breadth_rows, review_date)

    rows = [
        ("涨跌家数", _up_down_signal(up, down), _breadth_points(up, down), "看多数股票是在涨还是跌。"),
        ("跌停风险", _limit_down_signal(limit_up, limit_down), _limit_down_points(limit_up, limit_down), "跌停多说明情绪仍在释放风险。"),
        ("成交集中度", _cr50_signal(cr50), _cr50_points(cr50), "CR50 越高，越像少数股票吸走成交。"),
        ("主线持续性", _sector_signal(sector_rows, review_date), _sector_points(sector_rows, review_date), "单日领涨只算线索，连续确认才算主线。"),
    ]
    if comparison.ok:
        rows.append(("日环比", _comparison_label(comparison), _comparison_points(comparison), "看今天比昨天是改善还是恶化。"))

    total = sum(points for _, _, points, _ in rows)
    max_score = len(rows) * 3
    level = _signal_level(total, max_score)

    table = ["| 维度 | 信号 | 得分 | 新手解释 |", "|---|---|---:|---|"]
    for dimension, signal, points, note in rows:
        table.append(f"| {dimension} | {signal} | {points}/3 | {note} |")
    table.extend(
        [
            f"| **综合评分** | **{level}** | **{total}/{max_score}** | 分数越低越应该先观察，分数回升再考虑学习性试错。 |",
            "",
            f"> 新手读法：{_signal_reading(total, max_score)}",
        ]
    )
    return "\n".join(table)


def _breadth_table(rows: list[dict[str, Any]]) -> str:
    values = _metrics(rows)
    if not values:
        return "| 指标 | 数值 | 解读 |\n|---|---:|---|\n| 暂无 | - | 等待 skill 数据 |"

    items = [
        ("上涨家数", "越多说明赚钱效应越扩散"),
        ("下跌家数", "越多说明亏钱效应越扩散"),
        ("涨停家数", "短线情绪强弱"),
        ("跌停家数", "极端风险释放"),
    ]
    table = ["| 指标 | 数值 | 解读 |", "|---|---:|---|"]
    for metric, note in items:
        table.append(f"| {metric} | {values.get(metric, '-')} | {note} |")
    return "\n".join(table)


def _turnover_block(breadth_rows: list[dict[str, Any]], index_rows: list[dict[str, Any]]) -> str:
    values = _metrics(breadth_rows)
    lines = [
        "| 指标 | 数值 | 初学者判断 |",
        "|---|---:|---|",
        f"| 两市成交额 | {values.get('成交额(合计)', '-')} | 放量上涨偏积极，放量下跌说明分歧或抛压较大 |",
    ]
    for row in index_rows[:3]:
        lines.append(
            "| {name}成交额 | {amount} | 观察资金主要集中在哪类指数 |".format(
                name=row.get("name", "-"),
                amount=_fmt_amount(row.get("amount")),
            )
        )
    return "\n".join(lines)


def _sector_table(rows: list[dict[str, Any]], review_date: str) -> str:
    if not rows:
        return "| 排名 | 板块 | 涨跌幅 | 成交额 | 上涨/下跌家数 |\n|---:|---|---:|---:|---:|\n| - | 暂无 | - | - | - |"

    table = ["| 排名 | 板块 | 涨跌幅 | 成交额 | 上涨/下跌家数 |", "|---:|---|---:|---:|---:|"]
    for idx, row in enumerate(rows[:10], start=1):
        table.append(
            "| {idx} | {name} | {pct} | {amount} | {up}/{down} |".format(
                idx=idx,
                name=row.get("名称", "-"),
                pct=_find_value(row, "涨跌幅", review_date),
                amount=_find_value(row, "成交额", review_date),
                up=_find_value(row, "上涨家数", review_date),
                down=_find_value(row, "下跌家数", review_date),
            )
        )
    return "\n".join(table)


def _stock_table(rows: list[dict[str, Any]], review_date: str) -> str:
    if not rows:
        return "| 排名 | 代码 | 名称 | 涨跌幅 | 成交额 | 行业 |\n|---:|---:|---|---:|---:|---|\n| - | - | 暂无 | - | - | - |"

    table = ["| 排名 | 代码 | 名称 | 涨跌幅 | 成交额 | 行业 |", "|---:|---:|---|---:|---:|---|"]
    for idx, row in enumerate(rows[:10], start=1):
        table.append(
            "| {idx} | {code} | {name} | {pct} | {amount} | {industry} |".format(
                idx=idx,
                code=row.get("代码", "-"),
                name=row.get("名称", "-"),
                pct=_find_value(row, "涨跌幅", review_date),
                amount=_find_value(row, "成交额", review_date),
                industry=row.get("申万行业分类") or row.get("东财行业总分类") or "-",
            )
        )
    return "\n".join(table)


def _turnover_stock_table(rows: list[dict[str, Any]], review_date: str) -> str:
    if not rows:
        return "| 排名 | 代码 | 名称 | 涨跌幅 | 成交额 | 行业 |\n|---:|---:|---|---:|---:|---|\n| - | - | 暂无 | - | - | - |"

    table = ["| 排名 | 代码 | 名称 | 涨跌幅 | 成交额 | 行业 |", "|---:|---:|---|---:|---:|---|"]
    for idx, row in enumerate(rows[:10], start=1):
        table.append(
            "| {idx} | {code} | {name} | {pct} | {amount} | {industry} |".format(
                idx=idx,
                code=row.get("代码", "-"),
                name=row.get("名称", "-"),
                pct=_find_value(row, "涨跌幅", review_date),
                amount=_find_value(row, "成交额", review_date),
                industry=row.get("申万行业分类") or row.get("东财行业总分类") or "-",
            )
        )
    return "\n".join(table)


def _concentration_table(turnover_rows: list[dict[str, Any]], breadth_rows: list[dict[str, Any]], review_date: str) -> str:
    total = _market_turnover_yuan(breadth_rows)
    if not turnover_rows or total is None:
        return "| 指标 | 数值 | 解读 |\n|---|---:|---|\n| 暂无 | - | 等待成交额榜和两市成交额数据 |"

    metrics = [
        ("CR5", _turnover_ratio(turnover_rows, total, 5, review_date), "成交额前 5 只占全市场比例"),
        ("CR10", _turnover_ratio(turnover_rows, total, 10, review_date), "成交额前 10 只占全市场比例"),
        ("CR50", _turnover_ratio(turnover_rows, total, 50, review_date), "成交额前 50 只占全市场比例"),
        ("CR100", _turnover_ratio(turnover_rows, total, 100, review_date), "成交额前 100 只占全市场比例"),
    ]
    table = ["| 指标 | 数值 | 解读 |", "|---|---:|---|"]
    for name, value, note in metrics:
        table.append(f"| {name} | {_fmt_ratio(value)} | {note} |")
    return "\n".join(table)


def _industry_concentration_table(turnover_rows: list[dict[str, Any]], review_date: str) -> str:
    if not turnover_rows:
        return "| 行业 | 上榜数 | Top50 成交额 | 占 Top50 | 代表股票 |\n|---|---:|---:|---:|---|\n| 暂无 | - | - | - | - |"

    table = ["| 行业 | 上榜数 | Top50 成交额 | 占 Top50 | 代表股票 |", "|---|---:|---:|---:|---|"]
    for item in _industry_concentration_rows(turnover_rows, review_date)[:8]:
        table.append(
            "| {industry} | {count} | {amount} | {ratio} | {stocks} |".format(
                industry=item["industry"],
                count=item["count"],
                amount=item["amount"],
                ratio=item["ratio"],
                stocks=item["stocks"],
            )
        )
    return "\n".join(table)


def _concentration_commentary(turnover_rows: list[dict[str, Any]], breadth_rows: list[dict[str, Any]], review_date: str) -> str:
    total = _market_turnover_yuan(breadth_rows)
    if not turnover_rows or total is None:
        return "> 集中度数据不足，暂不判断资金是否抱团。"
    cr50 = _turnover_ratio(turnover_rows, total, 50, review_date)
    cr10 = _turnover_ratio(turnover_rows, total, 10, review_date)
    leaders = "、".join(str(row.get("名称", "-")) for row in turnover_rows[:3])
    if cr50 is not None and cr50 >= 0.22:
        tone = "头部成交占比较高，资金偏抱团，指数容易被少数高成交标的影响。"
    elif cr50 is not None and cr50 < 0.16:
        tone = "头部成交占比不高，资金相对分散，市场更容易走出扩散行情。"
    else:
        tone = "头部成交占比处于中性区间，需结合市场宽度判断扩散还是收缩。"
    return f"> CR10 为 {_fmt_ratio(cr10)}，CR50 为 {_fmt_ratio(cr50)}。成交额前三为 {leaders}。{tone}"


def _sentiment_temperature_block(breadth_rows: list[dict[str, Any]]) -> str:
    values = _metrics(breadth_rows)
    up = _to_float(values.get("上涨家数"))
    down = _to_float(values.get("下跌家数"))
    limit_up = _to_float(values.get("涨停家数"))
    limit_down = _to_float(values.get("跌停家数"))
    if up is None or down is None or limit_up is None or limit_down is None:
        return "> 情绪温度：数据不足，暂不计算。"

    total = up + down
    raw = (limit_up - limit_down) / total * 100 if total else 0
    label = _sentiment_label(raw)
    return (
        f"> **情绪温度**：({int(limit_up)} - {int(limit_down)}) / {int(total)} × 100 = "
        f"**{raw:.2f}**，当前为 **{label}**。这个数值越低，说明涨停带来的进攻情绪越难覆盖跌停带来的亏钱效应。"
    )


def _tomorrow_watch_list(
    breadth_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    turnover_rows: list[dict[str, Any]],
    review_date: str,
    regime: MarketRegime,
) -> str:
    values = _metrics(breadth_rows)
    up = _to_float(values.get("上涨家数"))
    down = _to_float(values.get("下跌家数"))
    limit_up = _to_float(values.get("涨停家数"))
    limit_down = _to_float(values.get("跌停家数"))
    cr50 = _dashboard_cr50(turnover_rows, breadth_rows, review_date)
    leaders = "、".join(str(row.get("名称", "-")) for row in sector_rows[:3]) if sector_rows else "今日领涨板块"

    items = [f"市场状态是否从“{regime.label}”切换：优先看上涨家数、跌停家数和成交额是否同步改善。"]
    if up is not None and down is not None and down > up:
        items.append("上涨家数能否重新接近或超过下跌家数；如果不能，指数反抽也先按弱修复看。")
    else:
        items.append("上涨家数能否继续扩大；若指数上涨但上涨家数减少，要警惕宽度背离。")
    if limit_down is not None and limit_up is not None and limit_down >= max(20, limit_up * 0.6):
        items.append("跌停家数能否快速回落；跌停维持高位时，短线情绪仍未稳定。")
    else:
        items.append("涨停家数能否保持，同时跌停数不抬升；这是进攻情绪延续的底线。")
    items.append(f"{leaders} 能否出现第二天确认；没有持续性的热点，先按短线轮动处理。")
    if cr50 is not None and cr50 >= 0.22:
        items.append("CR50 是否继续上行；若继续上行，说明资金仍在向少数高成交标的收缩。")
    else:
        items.append("成交额前 50 集中度是否下降；下降且宽度改善，才更像主线扩散。")
    return "\n".join(f"- {item}" for item in items)


def _beginner_action_guide(
    breadth_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    turnover_rows: list[dict[str, Any]],
    review_date: str,
) -> str:
    values = _metrics(breadth_rows)
    up = _to_float(values.get("上涨家数"))
    down = _to_float(values.get("下跌家数"))
    limit_up = _to_float(values.get("涨停家数"))
    limit_down = _to_float(values.get("跌停家数"))
    cr50 = _dashboard_cr50(turnover_rows, breadth_rows, review_date)
    leaders = "、".join(str(row.get("名称", "-")) for row in sector_rows[:3]) if sector_rows else "领涨板块"

    rows = [
        ("跌停家数继续增加", "不开新仓，先观察风险是否扩散。"),
        ("上涨家数重新超过下跌家数", "只把它当作市场修复信号，先小样本观察最强板块，不急着扩大仓位。"),
        (f"{leaders} 次日继续走强", "等尾盘确认持续性，避免早盘冲高时追入。"),
        ("成交额前十里多只高成交股大跌", "不急着抄底，高成交核心股补跌通常说明资金仍有分歧。"),
    ]
    if limit_down is not None and limit_up is not None and limit_down >= max(20, limit_up * 0.8):
        rows.insert(0, ("跌停数接近或超过涨停数", "防守优先，先学习复盘，不做冲动试错。"))
    if up is not None and down is not None and down > up * 1.6:
        rows.insert(0, ("下跌家数显著多于上涨家数", "把指数反弹当作弱修复观察，不把单日反抽当成新行情。"))
    if cr50 is not None and cr50 >= 0.22:
        rows.append(("CR50 继续上升", "说明资金更抱团，新手尽量避开高位拥挤方向。"))

    table = ["| 盘中出现的情况 | 初学者行动边界 |", "|---|---|"]
    for condition, action in rows[:7]:
        table.append(f"| {condition} | {action} |")
    table.append("")
    table.append("> 这不是买卖建议，而是帮助新手把观察信号转换成风险边界。")
    return "\n".join(table)


def _historical_context_note(breadth_rows: list[dict[str, Any]]) -> str:
    values = _metrics(breadth_rows)
    up = _to_float(values.get("上涨家数"))
    limit_down = _to_float(values.get("跌停家数"))
    if up is None or limit_down is None:
        return "> 历史经验：数据不足时不做类比，先补齐宽度和涨跌停数据。"
    if limit_down >= 60 and up < 1600:
        return "> 历史经验：当跌停数处在高位且上涨家数偏少时，市场常先经历反抽和再确认；在跌停数明显回落前，不宜把第一次反弹直接理解为风险结束。"
    if limit_down >= 30:
        return "> 历史经验：跌停数仍不低时，修复通常需要先看到亏钱效应收敛，再看领涨方向能否持续。"
    return "> 历史经验：当跌停数保持低位时，复盘重点可以从防守转向观察主线持续性和成交额配合。"


def _comparison_table(comparison: DailyComparison) -> str:
    if not comparison.ok:
        return f"> {comparison.error or '暂无可比数据'}。后续多跑几个日期后，这里会自动显示 CR、宽度和行业占比变化。"

    metrics = comparison.metrics
    rows = [
        ("对比日期", comparison.previous_date or "-", "最近一个更早的本地快照"),
        ("CR50 变化", _fmt_pp_delta(metrics.get("cr50_delta_pp")), "头部成交集中度变化"),
        ("CR100 变化", _fmt_pp_delta(metrics.get("cr100_delta_pp")), "成交额前 100 只集中度变化"),
        ("上涨家数变化", _fmt_number_delta(metrics.get("up_count_delta")), "赚钱效应扩散/收缩"),
        ("下跌家数变化", _fmt_number_delta(metrics.get("down_count_delta")), "亏钱效应扩散/收缩"),
        ("涨停家数变化", _fmt_number_delta(metrics.get("limit_up_delta")), "短线进攻情绪"),
        ("跌停家数变化", _fmt_number_delta(metrics.get("limit_down_delta")), "极端风险变化"),
    ]
    table = ["| 指标 | 变化 | 含义 |", "|---|---:|---|"]
    for metric, value, note in rows:
        table.append(f"| {metric} | {value} | {note} |")

    industry_rows = (metrics.get("industry_ratio_deltas") or [])[:5]
    if industry_rows:
        table.extend(["", "| 行业 | 占比变化 |", "|---|---:|"])
        for row in industry_rows:
            table.append(f"| {row.get('industry', '-')} | {_fmt_pp_delta(row.get('delta_pp'))} |")
    return "\n".join(table)


def _concentration_summary(turnover_rows: list[dict[str, Any]], breadth_rows: list[dict[str, Any]], review_date: str) -> dict[str, Any]:
    total = _market_turnover_yuan(breadth_rows)
    metrics = {
        "market_turnover": _fmt_yuan_amount(total),
        "market_turnover_yuan": total,
        "cr5": _turnover_ratio(turnover_rows, total, 5, review_date) if total else None,
        "cr10": _turnover_ratio(turnover_rows, total, 10, review_date) if total else None,
        "cr50": _turnover_ratio(turnover_rows, total, 50, review_date) if total else None,
        "cr100": _turnover_ratio(turnover_rows, total, 100, review_date) if total else None,
        "top3": [row.get("名称", "-") for row in turnover_rows[:3]],
    }
    return {
        **metrics,
        "cr5_text": _fmt_ratio(metrics["cr5"]),
        "cr10_text": _fmt_ratio(metrics["cr10"]),
        "cr50_text": _fmt_ratio(metrics["cr50"]),
        "cr100_text": _fmt_ratio(metrics["cr100"]),
    }


def _industry_concentration_rows(turnover_rows: list[dict[str, Any]], review_date: str) -> list[dict[str, Any]]:
    top50 = turnover_rows[:50]
    total = sum(_amount_yuan(_find_value(row, "成交额", review_date)) or 0 for row in top50)
    groups: dict[str, dict[str, Any]] = {}
    for row in top50:
        industry = _primary_industry(row.get("申万行业分类") or row.get("东财行业总分类") or "未分类")
        amount = _amount_yuan(_find_value(row, "成交额", review_date)) or 0
        item = groups.setdefault(industry, {"industry": industry, "count": 0, "amount_yuan": 0.0, "stocks": []})
        item["count"] += 1
        item["amount_yuan"] += amount
        if len(item["stocks"]) < 3:
            item["stocks"].append(str(row.get("名称", "-")))

    rows: list[dict[str, Any]] = []
    for item in sorted(groups.values(), key=lambda row: row["amount_yuan"], reverse=True):
        ratio = item["amount_yuan"] / total if total else None
        rows.append(
            {
                "industry": item["industry"],
                "count": item["count"],
                "amount_yuan": item["amount_yuan"],
                "amount": _fmt_yuan_amount(item["amount_yuan"]),
                "ratio_value": ratio,
                "ratio": _fmt_ratio(ratio),
                "stocks": "、".join(item["stocks"]),
            }
        )
    return rows


def _breadth_commentary(rows: list[dict[str, Any]]) -> str:
    values = _metrics(rows)
    up = _to_float(values.get("上涨家数"))
    down = _to_float(values.get("下跌家数"))
    limit_up = _to_float(values.get("涨停家数"))
    limit_down = _to_float(values.get("跌停家数"))
    if up is None or down is None:
        return "> 市场宽度数据不足，先不做扩散判断。"
    if down > up * 2:
        base = "> 下跌家数显著多于上涨家数，盘面偏普跌，赚钱效应较弱。"
    elif up > down:
        base = "> 上涨家数多于下跌家数，盘面有扩散迹象。"
    else:
        base = "> 上涨与下跌家数接近，盘面偏分化。"
    if limit_down and limit_up and limit_down >= limit_up * 0.8:
        base += " 跌停数量接近涨停数量，短线风险偏高。"
    return base


def _sector_commentary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "> 板块数据不足，暂不判断主线。"
    leaders = "、".join(str(row.get("名称", "-")) for row in rows[:3])
    return f"> 今日领涨集中在 {leaders}。下一步要看这些板块能否连续两天保持强势，否则先按短线轮动处理。"


def _one_sentence(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "今日数据尚未接入成功，先按复盘框架检查指数方向、成交额、市场宽度、资金情绪和板块轮动。"
    positive = sum(1 for row in rows if _to_float(row.get("pct_change")) > 0)
    total = len(rows)
    if positive == total:
        return "主要指数同步收涨，先观察成交额能否配合放大，以确认反弹质量。"
    if positive == 0:
        return "主要指数同步走弱，优先关注成交额是否放大和跌停数是否扩散。"
    return "主要指数表现分化，今日更像结构行情，复盘重点放在领涨板块持续性和资金集中度。"


def _risk_block(rows: list[dict[str, Any]], breadth_rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 数据不足时不做方向判断，先避免基于单一新闻或单只个股走势推断全市场。"

    negatives = [row for row in rows if _to_float(row.get("pct_change")) < 0]
    values = _metrics(breadth_rows)
    up = _to_float(values.get("上涨家数")) or 0
    down = _to_float(values.get("下跌家数")) or 0
    if len(negatives) >= len(rows) / 2 and down > up:
        return "- 半数以上核心指数收跌，短线仓位应更重视防守；若同时放量下跌，说明分歧或抛压加大。"
    if len(negatives) >= len(rows) / 2:
        return "- 核心指数偏弱，短线先看反弹质量；若市场宽度不能改善，谨慎追涨。"
    return "- 指数层面暂无一致性风险信号，但仍需防范缩量上涨、热点一日游和高位股补跌。"


def _dashboard_cr50(turnover_rows: list[dict[str, Any]], breadth_rows: list[dict[str, Any]], review_date: str) -> float | None:
    total = _market_turnover_yuan(breadth_rows)
    if not turnover_rows or total is None:
        return None
    return _turnover_ratio(turnover_rows, total, 50, review_date)


def _index_sync_label(positive: int, total: int) -> str:
    if total == 0:
        return "指数数据不足"
    if positive == total:
        return "主要指数同步收涨"
    if positive == 0:
        return "主要指数同步收跌"
    return f"{positive}/{total} 个指数收涨，结构分化"


def _index_sync_score(positive: int, total: int) -> str:
    if total == 0:
        return "观察"
    if positive == total:
        return "偏进攻"
    if positive == 0:
        return "偏防守"
    return "看结构"


def _breadth_label(up: float | None, down: float | None) -> str:
    if up is None or down is None:
        return "宽度数据不足"
    total = up + down
    up_ratio = up / total if total else 0
    if up_ratio >= 0.65:
        return f"扩散较强，上涨占比 {_fmt_ratio(up_ratio)}"
    if up_ratio >= 0.5:
        return f"温和扩散，上涨占比 {_fmt_ratio(up_ratio)}"
    if up_ratio <= 0.3:
        return f"赚钱效应弱，上涨占比 {_fmt_ratio(up_ratio)}"
    return f"分化偏弱，上涨占比 {_fmt_ratio(up_ratio)}"


def _breadth_score(up: float | None, down: float | None) -> str:
    if up is None or down is None:
        return "观察"
    if up > down * 1.2:
        return "偏进攻"
    if down > up * 1.6:
        return "偏防守"
    return "结构分化"


def _tail_risk_label(limit_up: float | None, limit_down: float | None) -> str:
    if limit_up is None or limit_down is None:
        return "涨跌停数据不足"
    if limit_down >= max(20, limit_up * 0.8):
        return f"尾部风险高，涨停 {int(limit_up)} / 跌停 {int(limit_down)}"
    if limit_up >= max(30, limit_down * 2):
        return f"短线情绪较强，涨停 {int(limit_up)} / 跌停 {int(limit_down)}"
    return f"情绪中性，涨停 {int(limit_up)} / 跌停 {int(limit_down)}"


def _tail_risk_score(limit_up: float | None, limit_down: float | None) -> str:
    if limit_up is None or limit_down is None:
        return "观察"
    if limit_down >= max(20, limit_up * 0.8):
        return "防守优先"
    if limit_up >= max(30, limit_down * 2):
        return "可看进攻"
    return "谨慎观察"


def _sector_strength_label(rows: list[dict[str, Any]], review_date: str) -> str:
    if not rows:
        return "板块数据不足"
    top = rows[0]
    pct = _to_float(_find_value(top, "涨跌幅", review_date))
    name = str(top.get("名称", "-"))
    if pct is None:
        return f"领涨 {name}"
    if pct >= 5:
        return f"领涨 {name}，强度较高"
    if pct >= 3:
        return f"领涨 {name}，强度中等"
    return f"领涨 {name}，强度一般"


def _sector_strength_score(rows: list[dict[str, Any]], review_date: str) -> str:
    if not rows:
        return "观察"
    top_pct = _to_float(_find_value(rows[0], "涨跌幅", review_date))
    if top_pct is None:
        return "看持续"
    if top_pct >= 5:
        return "看确认"
    if top_pct >= 3:
        return "短线轮动"
    return "主线不强"


def _concentration_label(cr50: float | None) -> str:
    if cr50 is None:
        return "集中度数据不足"
    if cr50 >= 0.22:
        return f"资金偏抱团，CR50 {_fmt_ratio(cr50)}"
    if cr50 < 0.16:
        return f"资金较分散，CR50 {_fmt_ratio(cr50)}"
    return f"集中度中性，CR50 {_fmt_ratio(cr50)}"


def _concentration_score(cr50: float | None) -> str:
    if cr50 is None:
        return "观察"
    if cr50 >= 0.22:
        return "防抱团回撤"
    if cr50 < 0.16:
        return "利于扩散"
    return "中性"


def _comparison_label(comparison: DailyComparison) -> str:
    if not comparison.ok:
        return comparison.error or "暂无可比数据"
    metrics = comparison.metrics
    up_delta = _to_float(metrics.get("up_count_delta"))
    down_delta = _to_float(metrics.get("down_count_delta"))
    limit_down_delta = _to_float(metrics.get("limit_down_delta"))
    parts = [f"对比 {comparison.previous_date}"]
    if up_delta is not None:
        parts.append(f"上涨家数 {_fmt_number_delta(up_delta)}")
    if down_delta is not None:
        parts.append(f"下跌家数 {_fmt_number_delta(down_delta)}")
    if limit_down_delta is not None:
        parts.append(f"跌停 {_fmt_number_delta(limit_down_delta)}")
    return "，".join(parts)


def _comparison_score(comparison: DailyComparison) -> str:
    if not comparison.ok:
        return "待补数据"
    metrics = comparison.metrics
    up_delta = _to_float(metrics.get("up_count_delta"))
    down_delta = _to_float(metrics.get("down_count_delta"))
    limit_down_delta = _to_float(metrics.get("limit_down_delta"))
    if up_delta is not None and down_delta is not None:
        if up_delta > 0 and down_delta < 0:
            return "改善"
        if up_delta < 0 and down_delta > 0:
            return "恶化"
    if limit_down_delta is not None and limit_down_delta > 20:
        return "风险升温"
    return "变化中性"


def _up_down_signal(up: float | None, down: float | None) -> str:
    if up is None or down is None:
        return "数据不足"
    return f"{int(up)} 上涨 / {int(down)} 下跌"


def _breadth_points(up: float | None, down: float | None) -> int:
    if up is None or down is None:
        return 0
    if up > down * 1.2:
        return 3
    if up > down:
        return 2
    if down > up * 1.6:
        return 0
    return 1


def _limit_down_signal(limit_up: float | None, limit_down: float | None) -> str:
    if limit_up is None or limit_down is None:
        return "数据不足"
    return f"{int(limit_up)} 涨停 / {int(limit_down)} 跌停"


def _limit_down_points(limit_up: float | None, limit_down: float | None) -> int:
    if limit_up is None or limit_down is None:
        return 0
    if limit_down >= max(20, limit_up * 0.8):
        return 0
    if limit_up >= max(30, limit_down * 2):
        return 3
    if limit_down <= 20:
        return 2
    return 1


def _cr50_signal(cr50: float | None) -> str:
    if cr50 is None:
        return "数据不足"
    if cr50 >= 0.22:
        return f"偏集中，CR50 {_fmt_ratio(cr50)}"
    if cr50 < 0.16:
        return f"较分散，CR50 {_fmt_ratio(cr50)}"
    return f"中性，CR50 {_fmt_ratio(cr50)}"


def _cr50_points(cr50: float | None) -> int:
    if cr50 is None:
        return 0
    if cr50 < 0.16:
        return 3
    if cr50 < 0.22:
        return 2
    return 1


def _sector_signal(rows: list[dict[str, Any]], review_date: str) -> str:
    if not rows:
        return "数据不足"
    top_name = str(rows[0].get("名称", "-"))
    top_pct = _to_float(_find_value(rows[0], "涨跌幅", review_date))
    if top_pct is None:
        return f"领涨 {top_name}"
    return f"领涨 {top_name}，涨跌幅 {top_pct:.2f}%"


def _sector_points(rows: list[dict[str, Any]], review_date: str) -> int:
    if not rows:
        return 0
    top_pct = _to_float(_find_value(rows[0], "涨跌幅", review_date))
    if top_pct is None:
        return 1
    if top_pct >= 5:
        return 2
    if top_pct >= 3:
        return 1
    return 0


def _comparison_points(comparison: DailyComparison) -> int:
    score = _comparison_score(comparison)
    if score == "改善":
        return 3
    if score in {"变化中性", "待补数据"}:
        return 1
    return 0


def _signal_level(total: int, max_score: int) -> str:
    if max_score <= 0:
        return "数据不足"
    ratio = total / max_score
    if ratio >= 0.75:
        return "偏暖"
    if ratio >= 0.5:
        return "中性"
    if ratio >= 0.3:
        return "偏冷"
    return "极弱"


def _signal_reading(total: int, max_score: int) -> str:
    level = _signal_level(total, max_score)
    if level == "偏暖":
        return "市场信号相对友好，但仍要看领涨方向能否连续确认。"
    if level == "中性":
        return "市场不算极端，但仍偏结构行情，适合多观察、少冲动。"
    if level == "偏冷":
        return "市场偏冷，新手应先看风险是否收敛，再考虑学习性参与。"
    if level == "极弱":
        return "市场很弱，新手最重要的是避免因为下跌而冲动抄底。"
    return "数据不足，先不做市场冷暖判断。"


def _sentiment_label(value: float) -> str:
    if value <= -0.5:
        return "冰点"
    if value <= 0.5:
        return "极冷"
    if value <= 2:
        return "偏冷"
    if value <= 5:
        return "中性"
    return "偏热"


def _beginner_glossary() -> str:
    rows = [
        ("CR50", "成交额前 50 只股票占全市场总成交额的比例，越高说明资金越集中。"),
        ("炸板率", "股票曾经涨停但后来打开涨停的比例，越高说明短线情绪越不稳定。"),
        ("连板高度", "连续涨停的最高板数，反映短线资金愿意追高到什么程度。"),
        ("打二板以上表现", "观察昨天已经 2 连板及以上的股票，今天还能不能赚钱，用来判断追高资金是否亏钱。"),
        ("市场宽度", "上涨家数、下跌家数、涨停跌停等指标，比指数更能反映普通股票的真实体验。"),
        ("主线", "连续被资金关注、板块内多只股票一起走强的方向，不是单只股票一天大涨。"),
    ]
    table = ["| 术语 | 简单解释 |", "|---|---|"]
    for term, explanation in rows:
        table.append(f"| {term} | {explanation} |")
    return "\n".join(table)


def _beginner_learning_path() -> str:
    return "\n".join(
        [
            "- 第一周：只观察上涨家数、下跌家数、涨停数、跌停数，不急着解释所有板块。",
            "- 第二周：开始看 CR50 和 Top50 行业占比，理解资金是在扩散还是抱团。",
            "- 第三周：记录每天前三强板块，练习判断它们是连续主线还是一日轮动。",
            "- 第四周：再结合自选股，按趋势、动量、量能、波动率做四层过滤。",
        ]
    )


def _data_notes(notes: list[str]) -> str:
    if not notes:
        return "- 本次报告已成功获取基础指数数据。"
    return "\n".join(f"- {note}" for note in notes[:12])


def _fallback_cached_dataset(
    store: DailyDataStore,
    name: str,
    rows: list[dict[str, Any]],
    data_notes: list[str],
) -> list[dict[str, Any]]:
    if rows:
        return rows
    cached = _load_cached_json_list(store.normalized_dir / f"{name}.json")
    if not cached:
        return rows
    store.save_dataset(name, cached, source="local-cache")
    data_notes.append(f"{name} 本次 skill 未返回有效数据，已回退使用本地落库快照。")
    return cached


def _load_valid_cached_inputs(store: DailyDataStore) -> CachedDailyInputs | None:
    manifest_path = store.base_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    records = manifest.get("datasets")
    if not isinstance(records, list):
        return None

    required_records = [record for record in records if record.get("name") in REQUIRED_LIVE_DATASETS]
    if any(record.get("ok") is False for record in required_records):
        return None

    cached: dict[str, list[dict[str, Any]]] = {}
    for name in REQUIRED_LIVE_DATASETS:
        if not any(record.get("name") == name and record.get("ok") is True for record in required_records):
            return None
        rows = _load_cached_json_list(store.normalized_dir / f"{name}.json")
        if not rows:
            return None
        cached[name] = rows

    return CachedDailyInputs(
        index_rows=cached["index_snapshot"],
        breadth_rows=cached["market_breadth"],
        sector_rows=cached["sector_top_gainers"],
        top_gainer_rows=cached["stock_top_gainers"],
        top_turnover_rows=cached["stock_top_turnover"],
    )


def _load_cached_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _market_regime_summary(regime: MarketRegime) -> dict[str, Any]:
    return {
        "label": regime.label,
        "tone": regime.tone,
        "confidence": regime.confidence,
        "drivers": regime.drivers,
        "watch_items": regime.watch_items,
    }


def _parse_review_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    today = date.today()
    day = today - timedelta(days=1 if today.weekday() < 5 else today.weekday() - 4)
    return day


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".skills").exists() and (parent / "参考资料").exists():
            return parent
    return current.parents[4]


def _compact_error(error: str | None) -> str:
    if not error:
        return "未知错误"
    if "ProxyError" in error:
        return "本机代理连接失败，当前环境无法访问 skill 背后的数据服务。"
    if "NameResolutionError" in error or "Failed to resolve" in error:
        return "DNS 解析失败，当前环境无法直连东方财富接口。"
    if "timed out" in error.lower() or "timeout" in error.lower():
        return "数据源请求超时。"
    first_line = error.splitlines()[0]
    return first_line[:180]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fmt_number(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-" if value is None else str(value)
    return f"{number:,.2f}"


def _fmt_pct(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-" if value is None else str(value)
    return f"{number:.2f}%"


def _fmt_amount(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-" if value is None else str(value)
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.2f} 亿"
    if abs(number) >= 10_000:
        return f"{number / 10_000:.2f} 万"
    return f"{number:.2f}"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("%", "").replace("点", "")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _amount_yuan(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    multiplier = 1.0
    if "万亿" in text:
        multiplier = 1_000_000_000_000
    elif "亿" in text:
        multiplier = 100_000_000
    elif "万" in text:
        multiplier = 10_000
    text = text.replace("万亿", "").replace("亿", "").replace("万", "").replace("元", "")
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _market_turnover_yuan(breadth_rows: list[dict[str, Any]]) -> float | None:
    return _amount_yuan(_metrics(breadth_rows).get("成交额(合计)"))


def _turnover_ratio(rows: list[dict[str, Any]], total: float, n: int, review_date: str) -> float | None:
    if total <= 0:
        return None
    amount = sum(_amount_yuan(_find_value(row, "成交额", review_date)) or 0 for row in rows[:n])
    return amount / total


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def _fmt_pp_delta(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}pp"


def _fmt_number_delta(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    sign = "+" if number > 0 else ""
    if number.is_integer():
        return f"{sign}{int(number)}"
    return f"{sign}{number:.2f}"


def _fmt_yuan_amount(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.3f}万亿"
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.2f}"


def _primary_industry(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "未分类"
    return text.split("-")[0]


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(row.get("metric")).strip(): row.get("value")
        for row in rows
        if row.get("metric") is not None
    }


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
