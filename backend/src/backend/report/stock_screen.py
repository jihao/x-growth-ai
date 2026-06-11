from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.data_sources.mx_hotspot import MxHotspotClient, promote_text_artifact


@dataclass(frozen=True)
class StockScreenConfig:
    screen_date: str | None = None
    output_path: Path | None = None
    limit: int | None = None
    with_hotspot: bool = False
    precheck_days: int | None = None


def generate_stock_screen(config: StockScreenConfig) -> Path:
    repo_root = _find_repo_root()
    rules = _load_rules(repo_root)
    screen_day = _parse_screen_date(config.screen_date)
    daily_dir = repo_root / "data" / "daily" / screen_day.isoformat()
    normalized_dir = daily_dir / "normalized"
    if not normalized_dir.exists():
        raise FileNotFoundError(f"daily data not found: {daily_dir}")

    turnover_rows = _read_json(normalized_dir / "stock_top_turnover.json")
    sector_rows = _read_json(normalized_dir / "sector_top_gainers.json")
    industry_rows = _read_json(normalized_dir / "industry_top50_turnover.json")
    regime = _read_json(normalized_dir / "market_regime.json")
    comparison = _read_json(normalized_dir / "daily_comparison.json", default={})
    previous_review = _build_previous_action_review(repo_root, screen_day, turnover_rows, rules)

    candidates = _screen_candidates(
        turnover_rows=turnover_rows,
        sector_rows=sector_rows,
        industry_rows=industry_rows,
        regime=regime,
        limit=config.limit or _rule_int(rules, "candidate_limit", 15),
        screen_date=screen_day.isoformat(),
        rules=rules,
    )

    screen_dir = repo_root / "data" / "screen" / screen_day.isoformat()
    screen_normalized = screen_dir / "normalized"
    screen_normalized.mkdir(parents=True, exist_ok=True)
    _write_json(screen_normalized / "stock_screen_candidates.json", candidates)
    precheck = _build_precheck(repo_root, screen_day, candidates, config.precheck_days or _rule_int(rules, "precheck_days", 5), rules)
    _write_json(screen_normalized / "stock_screen_precheck.json", precheck)
    mainline = _build_mainline_continuity(repo_root, screen_day, sector_rows, industry_rows, candidates, rules)
    _write_json(screen_normalized / "mainline_continuity.json", mainline)
    hotspot = _build_hotspot_confirmation(repo_root, screen_day.isoformat(), candidates, sector_rows, config.with_hotspot)
    if hotspot["enabled"]:
        _write_json(screen_normalized / "hotspot_confirmation.json", hotspot)
    groups = _build_candidate_groups(candidates, hotspot, precheck, rules)
    _write_json(screen_normalized / "stock_screen_groups.json", groups)
    action_plan = _build_action_plan(candidates, groups, hotspot, precheck, regime, rules)
    _write_json(screen_normalized / "stock_screen_action_plan.json", action_plan)
    system_watchlist = _build_system_watchlist(repo_root, screen_day, candidates, groups, action_plan, previous_review, mainline)
    _write_json(repo_root / "data" / "watchlist" / "system" / f"{screen_day.isoformat()}.json", system_watchlist)
    _write_json(screen_normalized / "system_watchlist.json", system_watchlist)
    rule_stats = _build_rule_stats(repo_root, screen_day)
    _write_json(screen_normalized / "rule_backtest_stats.json", rule_stats)
    if previous_review["enabled"]:
        _write_json(screen_normalized / "previous_action_review.json", previous_review)
    manifest_path = _write_manifest(screen_dir, candidates, daily_dir, hotspot, precheck, groups, action_plan, previous_review, mainline, system_watchlist, rule_stats)

    output_path = config.output_path or repo_root / "reports" / f"x_growth_stock_screen_{screen_day.isoformat()}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = _render_markdown(screen_day, candidates, regime, comparison, manifest_path, hotspot, precheck, groups, action_plan, previous_review, mainline, system_watchlist, rule_stats)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def _screen_candidates(
    *,
    turnover_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    industry_rows: list[dict[str, Any]],
    regime: dict[str, Any],
    limit: int,
    screen_date: str,
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    strong_industries = _strong_industries(industry_rows)
    strong_themes = _strong_theme_tokens(sector_rows)
    market_penalty = _market_penalty(regime)

    candidates: list[dict[str, Any]] = []
    for rank, row in enumerate(turnover_rows[:_rule_int(rules, "screen.turnover_scan_limit", 80)], start=1):
        stock = _normalize_turnover_stock(row, rank, screen_date)
        score, reasons, risks = _score_stock(stock, strong_industries, strong_themes, market_penalty, regime, rules)
        if score < _rule_int(rules, "screen.min_score", 45):
            continue
        candidates.append(
            {
                **stock,
                "score": score,
                "reasons": reasons,
                "risks": risks,
                "action": _candidate_action(score, stock, risks, regime, rules),
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["turnover_rank"]))
    return candidates[:limit]


def _normalize_turnover_stock(row: dict[str, Any], rank: int, screen_date: str) -> dict[str, Any]:
    date_key = screen_date.replace("-", ".")
    industry_path = str(row.get("申万行业分类") or row.get("东财行业总分类") or "")
    return {
        "date": screen_date,
        "turnover_rank": rank,
        "code": _text(row.get("代码")),
        "name": _text(row.get("名称") or row.get("股票简称")),
        "price": _number(_find_by_prefix(row, f"最新价(元) {date_key}")),
        "change_pct": _number(_find_by_prefix(row, f"涨跌幅(%) {date_key}")),
        "amount_wan": _amount_to_wan(_find_by_prefix(row, f"成交额(元) {date_key}")),
        "turnover_pct": _number(_find_by_prefix(row, f"换手率(%) {date_key}")),
        "volume_ratio": _number(_find_by_prefix(row, f"量比 {date_key}")),
        "pe_dynamic": _number(_find_by_prefix(row, f"市盈率(动)(倍) {date_key}")),
        "pb": _number(_find_by_prefix(row, f"市净率(倍) {date_key}")),
        "industry_path": industry_path,
        "industry": _industry_level1(industry_path),
        "industry_detail": industry_path.split("-")[-1] if industry_path else "",
        "concepts": _text(row.get("概念")),
    }


def _score_stock(
    stock: dict[str, Any],
    strong_industries: dict[str, dict[str, Any]],
    strong_themes: set[str],
    market_penalty: int,
    regime: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[int, list[str], list[str]]:
    score = 50 - market_penalty
    reasons: list[str] = []
    risks: list[str] = []

    rank = stock["turnover_rank"]
    if rank <= _rule_int(rules, "screen.top_turnover_rank", 10):
        score += 18
        reasons.append(f"成交额排名前{_rule_int(rules, 'screen.top_turnover_rank', 10)}，资金关注度高")
    elif rank <= _rule_int(rules, "screen.mid_turnover_rank", 30):
        score += 12
        reasons.append(f"成交额排名前{_rule_int(rules, 'screen.mid_turnover_rank', 30)}，资金参与度较高")
    elif rank <= _rule_int(rules, "screen.low_turnover_rank", 50):
        score += 6
        reasons.append(f"成交额进入前{_rule_int(rules, 'screen.low_turnover_rank', 50)}")

    industry_info = strong_industries.get(stock["industry"])
    if industry_info:
        ratio = industry_info.get("ratio_value") or 0
        bonus = 16 if ratio >= 0.15 else 10 if ratio >= 0.05 else 6
        score += bonus
        reasons.append(f"所属行业在Top50成交分布中占比{industry_info.get('ratio', '-')}")

    theme_hits = _theme_hits(stock, strong_themes)
    if theme_hits:
        score += min(12, 4 * len(theme_hits))
        reasons.append("贴近当日强势主题：" + "、".join(theme_hits[:3]))

    change_pct = stock.get("change_pct")
    if isinstance(change_pct, (int, float)):
        if _rule_float(rules, "screen.warm_change_min_pct", 1) <= change_pct <= _rule_float(rules, "screen.warm_change_max_pct", 6):
            score += 10
            reasons.append("涨幅温和偏强，尚未明显过热")
        elif _rule_float(rules, "screen.warm_change_max_pct", 6) < change_pct <= _rule_float(rules, "screen.high_change_max_pct", 9):
            score += 3
            risks.append("涨幅偏高，追高风险上升")
        elif change_pct > _rule_float(rules, "screen.overheat_change_pct", 9):
            score -= 12
            risks.append("接近涨停或涨幅过热，不适合作为低风险观察点")
        elif change_pct < _rule_float(rules, "screen.negative_change_penalty_pct", 0):
            score -= 6
            risks.append("当日逆势走弱")

    turnover_pct = stock.get("turnover_pct")
    if isinstance(turnover_pct, (int, float)):
        if _rule_float(rules, "screen.healthy_turnover_min_pct", 2) <= turnover_pct <= _rule_float(rules, "screen.healthy_turnover_max_pct", 8):
            score += 6
            reasons.append("换手率适中，流动性较好")
        elif turnover_pct > _rule_float(rules, "screen.high_turnover_pct", 12):
            score -= 5
            risks.append("换手率过高，短线分歧较大")

    volume_ratio = stock.get("volume_ratio")
    if isinstance(volume_ratio, (int, float)) and volume_ratio >= _rule_float(rules, "screen.active_volume_ratio", 1.2):
        score += 4
        reasons.append("量比较高，成交活跃")

    if regime.get("label") in {"弱势抱团", "风险释放"}:
        risks.append(f"市场状态为{regime.get('label')}，候选股只适合观察确认")

    return max(0, min(100, score)), reasons[:5], risks[:4]


def _strong_industries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = _text(row.get("industry"))
        if name:
            result[name] = row
    return result


def _strong_theme_tokens(rows: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for row in rows[:8]:
        name = _text(row.get("名称") or row.get("板块"))
        for token in _split_theme_name(name):
            tokens.add(token)
    return tokens


def _split_theme_name(name: str) -> set[str]:
    cleaned = name.replace("(申万)", "").replace("概念", "")
    parts = {cleaned}
    for marker in ["通信", "CPO", "MLCC", "元件", "半导体", "算力", "电池", "机器人", "自动化", "消费电子"]:
        if marker in cleaned:
            parts.add(marker)
    return {part for part in parts if part}


def _theme_hits(stock: dict[str, Any], strong_themes: set[str]) -> list[str]:
    text = " ".join([stock.get("industry_path", ""), stock.get("industry_detail", ""), stock.get("concepts", "")])
    hits = [theme for theme in strong_themes if theme and theme in text]
    return sorted(hits, key=len, reverse=True)


def _market_penalty(regime: dict[str, Any]) -> int:
    label = regime.get("label")
    if label == "主线扩散":
        return 0
    if label == "弱势抱团":
        return 8
    if label == "风险释放":
        return 16
    return 4


def _candidate_action(score: int, stock: dict[str, Any], risks: list[str], regime: dict[str, Any], rules: dict[str, Any]) -> str:
    if stock.get("change_pct") is not None and stock["change_pct"] > _rule_float(rules, "screen.overheat_change_pct", 9):
        return "暂不追高"
    if regime.get("label") in {"弱势抱团", "风险释放"}:
        if score >= 75:
            return "重点观察"
        return "只观察不追"
    if score >= 78 and regime.get("label") != "风险释放":
        return "可加入观察池"
    if score >= 65:
        return "重点观察"
    if risks:
        return "只观察不追"
    return "继续观察"


def _render_markdown(
    screen_day: date,
    candidates: list[dict[str, Any]],
    regime: dict[str, Any],
    comparison: dict[str, Any],
    manifest_path: Path,
    hotspot: dict[str, Any],
    precheck: dict[str, Any],
    groups: dict[str, Any],
    action_plan: dict[str, Any],
    previous_review: dict[str, Any],
    mainline: dict[str, Any],
    system_watchlist: dict[str, Any],
    rule_stats: dict[str, Any],
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    section = 1
    lines = [
        f"# 系统选股报告｜{screen_day.isoformat()}",
        "",
        f"> 生成时间：{generated_at}｜定位：规则选股练习，不构成投资建议。",
        "",
        "## 今日只看这几件事",
        "",
    ]
    lines.extend(_daily_brief_block(candidates, regime, groups, action_plan, previous_review, mainline, system_watchlist, rule_stats))
    lines.append("")

    if previous_review.get("enabled"):
        lines.extend([f"## {section}. 上一观察计划复盘", ""])
        lines.extend(_previous_review_block(previous_review))
        lines.append("")
        section += 1

    lines.extend(
        [
        f"## {section}. 今日筛选结论",
        "",
        f"- 市场状态：{regime.get('label', '-')}｜{regime.get('tone', '-')}",
        f"- 候选数量：{len(candidates)}",
        f"- 本地落库：`{manifest_path}`",
        "",
        _screen_summary(candidates, regime, comparison),
        "",
        f"## {section + 1}. 主线板块连续性",
        "",
        ]
    )
    lines.extend(_mainline_block(mainline))
    lines.extend(
        [
        "",
        f"## {section + 2}. 系统观察池变化",
        "",
        ]
    )
    lines.extend(_system_watchlist_block(system_watchlist))
    lines.extend(
        [
        "",
        f"## {section + 3}. 规则历史统计",
        "",
        ]
    )
    lines.extend(_rule_stats_block(rule_stats))
    lines.extend(
        [
        "",
        f"## {section + 4}. 今日分组结论",
        "",
        ]
    )
    lines.extend(_groups_block(groups))
    lines.extend(
        [
            "",
            f"## {section + 5}. 下一交易日观察计划",
            "",
        ]
    )
    lines.extend(_action_plan_block(action_plan))
    lines.extend(
        [
            "",
            f"## {section + 6}. 规则说明",
            "",
            "- 只从当日成交额前100中筛选，避免流动性太弱。",
            "- 优先选择所在行业进入 Top50 成交分布的股票。",
            "- 优先贴近当日强势板块/概念，但过滤明显过热的涨幅。",
            "- 弱势抱团或风险释放时降低分数，候选只作为观察清单。",
            "",
            f"## {section + 7}. 候选股列表",
            "",
            "| 排名 | 股票 | 分数 | 分组 | 观察动作 | 涨跌幅 | 成交额 | 换手率 | 行业 |",
            "| ---: | --- | ---: | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    group_by_code = _group_by_code(groups)
    action_by_code = _action_by_code(action_plan)
    for index, item in enumerate(candidates, start=1):
        lines.append(
            "| {rank} | {name}({code}) | {score} | {group} | {action} | {change} | {amount} | {turnover} | {industry} |".format(
                rank=index,
                name=item["name"],
                code=item["code"],
                score=item["score"],
                group=group_by_code.get(item["code"], "-"),
                action=action_by_code.get(item["code"], {}).get("watch_action", item["action"]),
                change=_fmt_pct(item.get("change_pct")),
                amount=_fmt_amount(item.get("amount_wan")),
                turnover=_fmt_pct(item.get("turnover_pct")),
                industry=item.get("industry_detail") or item.get("industry") or "-",
            )
        )

    lines.extend(["", f"## {section + 8}. 入选前5日体检", ""])
    lines.extend(_precheck_block(precheck))

    if hotspot.get("enabled"):
        lines.extend(["", f"## {section + 9}. 热点确认", ""])
        lines.extend(_hotspot_block(hotspot))
        next_section = section + 10
    else:
        next_section = section + 9

    lines.extend(["", f"## {next_section}. 入选理由与风险", ""])
    for item in candidates:
        lines.extend(
            _candidate_card(
                item,
                _hotspot_row_for_code(hotspot, item["code"]),
                _precheck_row_for_code(precheck, item["code"]),
                group_by_code.get(item["code"]),
                action_by_code.get(item["code"]),
            )
        )
        lines.append("")

    lines.extend(
        [
            f"## {next_section + 1}. 使用边界",
            "",
            "- 这是规则筛选，不是收益验证；没有回测前不能当作策略有效。",
            "- 弱势抱团环境下，强势股容易快速轮动，次日必须看板块持续性。",
            "- 涨幅接近涨停、换手过高、估值极高的股票，只做观察，不做追高结论。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _groups_block(groups: dict[str, Any]) -> list[str]:
    lines = [
        "| 分组 | 股票 | 观察重点 |",
        "| --- | --- | --- |",
    ]
    group_rows = [row for row in groups.get("groups", []) if row.get("stocks")]
    if not group_rows:
        lines.append("| - | - | 今日没有形成可读分组 |")
        return lines
    for row in group_rows:
        stocks = "、".join(f"{item['name']}({item['code']})" for item in row.get("stocks", []))
        lines.append(f"| {row.get('label', '-')} | {stocks} | {row.get('watch_focus', '-')} |")
    return lines


def _mainline_block(mainline: dict[str, Any]) -> list[str]:
    lines = [
        f"> 主线状态：{mainline.get('status', '-')}｜{mainline.get('summary', '-')}",
        "",
        "| 今日强势主题 | 近几日延续 | 今日涨幅 | 成交额 | 候选股共振 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    rows = mainline.get("themes", [])
    if not rows:
        lines.append("| - | - | - | - | - |")
        return lines
    for row in rows:
        lines.append(
            "| {name} | {days}天 | {change} | {amount} | {stocks} |".format(
                name=row.get("name", "-"),
                days=row.get("continuation_days", 0),
                change=_fmt_pct(row.get("change_pct")),
                amount=_fmt_amount(row.get("amount_wan")),
                stocks="、".join(row.get("candidate_hits", [])) or "-",
            )
        )
    return lines


def _system_watchlist_block(system_watchlist: dict[str, Any]) -> list[str]:
    summary = system_watchlist.get("summary", {})
    lines = [
        f"> 新入池 {summary.get('new', 0)}，留存 {summary.get('retained', 0)}，降级 {summary.get('downgraded', 0)}，移除 {summary.get('removed', 0)}。",
        "",
        "| 状态 | 股票 | 分组 | 观察动作 | 原因 |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows = system_watchlist.get("items", [])
    if not rows:
        lines.append("| - | - | - | - | - |")
        return lines
    for row in rows:
        lines.append(
            "| {status} | {name}({code}) | {group} | {action} | {reason} |".format(
                status=row.get("pool_status", "-"),
                name=row.get("name", ""),
                code=row.get("code", ""),
                group=row.get("group", "-"),
                action=row.get("watch_action", "-"),
                reason=row.get("pool_reason", "-"),
            )
        )
    return lines


def _rule_stats_block(rule_stats: dict[str, Any]) -> list[str]:
    summary = rule_stats.get("summary", {})
    lines = [
        f"> 样本 {summary.get('total', 0)} 条，确认率 {_fmt_pct(summary.get('confirmed_rate'))}，失效率 {_fmt_pct(summary.get('invalidated_rate'))}。",
        "",
        "| 动作 | 样本 | 确认率 | 失效率 | 主要结论 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    rows = rule_stats.get("by_action", [])
    if not rows:
        lines.append("| - | 0 | - | - | 样本不足 |")
        return lines
    for row in rows:
        lines.append(
            "| {action} | {total} | {confirmed_rate} | {invalidated_rate} | {note} |".format(
                action=row.get("action", "-"),
                total=row.get("total", 0),
                confirmed_rate=_fmt_pct(row.get("confirmed_rate")),
                invalidated_rate=_fmt_pct(row.get("invalidated_rate")),
                note=row.get("note", "-"),
            )
        )
    return lines


def _daily_brief_block(
    candidates: list[dict[str, Any]],
    regime: dict[str, Any],
    groups: dict[str, Any],
    action_plan: dict[str, Any],
    previous_review: dict[str, Any],
    mainline: dict[str, Any],
    system_watchlist: dict[str, Any],
    rule_stats: dict[str, Any],
) -> list[str]:
    lines = [
        f"- 市场状态：{regime.get('label', '-')}｜{regime.get('tone', '-')}",
    ]
    if mainline:
        lines.append(f"- 主线状态：{mainline.get('status', '-')}｜{mainline.get('summary', '-')}")
    if system_watchlist:
        summary = system_watchlist.get("summary", {})
        lines.append(f"- 观察池：新入 {summary.get('new', 0)}，留存 {summary.get('retained', 0)}，降级 {summary.get('downgraded', 0)}，移除 {summary.get('removed', 0)}。")
    stats_summary = rule_stats.get("summary", {})
    if stats_summary.get("total"):
        lines.append(f"- 规则统计：样本 {stats_summary.get('total')}，确认率 {_fmt_pct(stats_summary.get('confirmed_rate'))}。")
    if previous_review.get("enabled"):
        summary = previous_review.get("summary", {})
        lines.append(
            "- 昨日计划：{confirmed}/{total} 确认有效，{invalidated} 个失效，{risk} 个风险提示有效/继续过热。".format(
                confirmed=summary.get("confirmed", 0),
                total=summary.get("total", 0),
                invalidated=summary.get("invalidated", 0),
                risk=summary.get("risk_warning_effective", 0),
            )
        )
    main_group = _group_by_label(groups, "主线核心")
    hot_group = _group_by_label(groups, "过热观察")
    if main_group:
        lines.append(f"- 今日主线核心：{_stock_names(main_group[:5])}。")
    priority = action_plan.get("items", [])[:3]
    if priority:
        lines.append(f"- 优先观察前三：{_action_names(priority)}。")
    if hot_group:
        lines.append(f"- 坚决不追：{_stock_names(hot_group[:5])}。")
    if candidates:
        top = candidates[0]
        lines.append(f"- 最高分：{top.get('name')}({top.get('code')})，{top.get('score')}分。")
    return lines


def _group_by_label(groups: dict[str, Any], label: str) -> list[dict[str, Any]]:
    for group in groups.get("groups", []):
        if group.get("label") == label:
            return group.get("stocks", [])
    return []


def _stock_names(rows: list[dict[str, Any]]) -> str:
    return "、".join(f"{row.get('name', '')}({row.get('code', '')})" for row in rows) or "-"


def _action_names(rows: list[dict[str, Any]]) -> str:
    return "、".join(f"{row.get('name', '')}({row.get('watch_action', '-')})" for row in rows) or "-"


def _previous_review_block(previous_review: dict[str, Any]) -> list[str]:
    rows = previous_review.get("items", [])
    source_date = previous_review.get("source_date", "-")
    lines = [
        f"> 自动读取上一份观察计划：{source_date}。",
        "",
        "| 股票 | 昨日动作 | 今日表现 | 是否确认 | 是否失效 | 复盘结论 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| - | - | - | - | - | 暂无可复盘标的 |")
        return lines
    for row in rows:
        lines.append(
            "| {name}({code}) | {action} | {performance} | {confirmed} | {invalidated} | {conclusion} |".format(
                name=row.get("name", ""),
                code=row.get("code", ""),
                action=row.get("previous_action", "-"),
                performance=row.get("performance", "-"),
                confirmed="是" if row.get("confirmed") else "否",
                invalidated="是" if row.get("invalidated") else "否",
                conclusion=row.get("conclusion", "-"),
            )
        )
    return lines


def _action_plan_block(action_plan: dict[str, Any]) -> list[str]:
    rows = action_plan.get("items", [])
    lines = [
        "| 优先级 | 股票 | 分组 | 观察动作 | 确认条件 | 失效条件 |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| - | - | - | - | - | - |")
        return lines
    for row in rows:
        lines.append(
            "| {priority} | {name}({code}) | {group} | {action} | {confirm} | {invalid} |".format(
                priority=row.get("priority", "-"),
                name=row.get("name", ""),
                code=row.get("code", ""),
                group=row.get("group", "-"),
                action=row.get("watch_action", "-"),
                confirm=row.get("confirm_condition", "-"),
                invalid=row.get("invalid_condition", "-"),
            )
        )
    return lines


def _group_by_code(groups: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for group in groups.get("groups", []):
        label = group.get("label", "")
        for stock in group.get("stocks", []):
            code = stock.get("code", "")
            if code:
                result[code] = label
    return result


def _action_by_code(action_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("code", ""): item for item in action_plan.get("items", []) if item.get("code")}


def _precheck_block(precheck: dict[str, Any]) -> list[str]:
    rows = precheck.get("rows", [])
    dates = "、".join(precheck.get("dates", [])) or "-"
    lines = [
        f"> 默认回看入选日前 {precheck.get('lookback_days', 5)} 个本地交易日：{dates}。",
        "",
        "| 股票 | 可用天数 | 入选前涨跌 | 连涨天数 | 成交额变化 | 换手变化 | 判断 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    if not rows:
        lines.append("| - | 0 | - | - | - | - | 本地前序数据不足 |")
        return lines
    for row in rows:
        lines.append(
            "| {name}({code}) | {days} | {change} | {streak} | {amount} | {turnover} | {status} |".format(
                name=row.get("name", ""),
                code=row.get("code", ""),
                days=row.get("available_days", 0),
                change=_fmt_pct(row.get("pre_change_pct")),
                streak=row.get("consecutive_up_days", 0),
                amount=_fmt_pct(row.get("amount_change_pct")),
                turnover=_fmt_pct(row.get("turnover_change_pct")),
                status=row.get("status", "-"),
            )
        )
    return lines


def _hotspot_block(hotspot: dict[str, Any]) -> list[str]:
    if not hotspot.get("ok"):
        return [f"> 热点确认获取失败：{hotspot.get('error', 'unknown error')}。"]

    lines = [
        f"> 热点来源：{hotspot.get('source', '-')}。市场热点摘要和资讯检索已落库。",
        "",
        "| 候选股 | 数据信号 | 热点/新闻证据 | 判断 |",
        "| --- | --- | --- | --- |",
    ]
    for row in hotspot.get("confirmations", []):
        lines.append(
            "| {name}({code}) | {data_signal} | {evidence} | {judgment} |".format(
                name=row.get("name", ""),
                code=row.get("code", ""),
                data_signal=row.get("data_signal", "-"),
                evidence=row.get("evidence", "-"),
                judgment=row.get("judgment", "-"),
            )
        )
    return lines


def _screen_summary(candidates: list[dict[str, Any]], regime: dict[str, Any], comparison: dict[str, Any]) -> str:
    if not candidates:
        return "> 今日没有满足规则的候选股，说明规则偏保守，适合先观察市场状态。"
    top = candidates[0]
    breadth_note = ""
    if isinstance(comparison, dict) and comparison:
        breadth_note = f"上涨家数环比 {_fmt_signed(comparison.get('up_count_delta'))}，下跌家数环比 {_fmt_signed(comparison.get('down_count_delta'))}。"
    return (
        f"> 今日最高分为 {top['name']}({top['code']})，分数 {top['score']}。"
        f"市场处于{regime.get('label', '-')}，{breadth_note}"
        "候选名单优先用于复盘观察。"
    )


def _candidate_card(
    item: dict[str, Any],
    hotspot_row: dict[str, Any] | None = None,
    precheck_row: dict[str, Any] | None = None,
    group_label: str | None = None,
    action_row: dict[str, Any] | None = None,
) -> list[str]:
    reasons = "；".join(item["reasons"]) if item["reasons"] else "规则命中较少"
    risks = "；".join(item["risks"]) if item["risks"] else "暂无显著规则风险"
    lines = [
        f"### {item['name']}({item['code']})｜{item['score']}分",
        "",
        f"- 动作：{item['action']}",
        f"- 分组：{group_label or '-'}",
        f"- 行业/主题：{item.get('industry_detail') or item.get('industry') or '-'}",
        f"- 量价：涨跌幅 {_fmt_pct(item.get('change_pct'))}，成交额 {_fmt_amount(item.get('amount_wan'))}，换手率 {_fmt_pct(item.get('turnover_pct'))}，量比 {_fmt_num(item.get('volume_ratio'))}",
        f"- 入选理由：{reasons}",
        f"- 风险标签：{risks}",
    ]
    if precheck_row:
        lines.append(
            "- 入选前体检：{status}｜入选前涨跌 {change}，连涨 {streak} 天，成交额变化 {amount}".format(
                status=precheck_row.get("status", "-"),
                change=_fmt_pct(precheck_row.get("pre_change_pct")),
                streak=precheck_row.get("consecutive_up_days", 0),
                amount=_fmt_pct(precheck_row.get("amount_change_pct")),
            )
        )
    if hotspot_row:
        lines.append(f"- 热点确认：{hotspot_row.get('judgment', '-')}｜{hotspot_row.get('evidence', '-')}")
    if action_row:
        lines.append(f"- 下一交易日：{action_row.get('watch_action', '-')}｜{action_row.get('confirm_condition', '-')}")
        lines.append(f"- 失效条件：{action_row.get('invalid_condition', '-')}")
    return lines


def _write_manifest(
    screen_dir: Path,
    candidates: list[dict[str, Any]],
    daily_dir: Path,
    hotspot: dict[str, Any],
    precheck: dict[str, Any],
    groups: dict[str, Any],
    action_plan: dict[str, Any],
    previous_review: dict[str, Any],
    mainline: dict[str, Any],
    system_watchlist: dict[str, Any],
    rule_stats: dict[str, Any],
) -> Path:
    path = screen_dir / "manifest.json"
    datasets = [
        {
            "name": "stock_screen_candidates",
            "ok": True,
            "row_count": len(candidates),
            "source": "backend-derived",
            "normalized_json": str(screen_dir / "normalized" / "stock_screen_candidates.json"),
        },
        {
            "name": "stock_screen_precheck",
            "ok": True,
            "row_count": len(precheck.get("rows", [])),
            "source": "backend-derived-local-daily",
            "normalized_json": str(screen_dir / "normalized" / "stock_screen_precheck.json"),
        },
        {
            "name": "stock_screen_groups",
            "ok": True,
            "row_count": len(groups.get("groups", [])),
            "source": "backend-derived",
            "normalized_json": str(screen_dir / "normalized" / "stock_screen_groups.json"),
        },
        {
            "name": "stock_screen_action_plan",
            "ok": True,
            "row_count": len(action_plan.get("items", [])),
            "source": "backend-derived",
            "normalized_json": str(screen_dir / "normalized" / "stock_screen_action_plan.json"),
        },
        {
            "name": "mainline_continuity",
            "ok": True,
            "row_count": len(mainline.get("themes", [])),
            "source": "backend-derived-local-daily",
            "normalized_json": str(screen_dir / "normalized" / "mainline_continuity.json"),
        },
        {
            "name": "system_watchlist",
            "ok": True,
            "row_count": len(system_watchlist.get("items", [])),
            "source": "backend-derived",
            "normalized_json": str(screen_dir / "normalized" / "system_watchlist.json"),
            "canonical_json": str(screen_dir.parents[1] / "watchlist" / "system" / f"{screen_dir.name}.json"),
        },
        {
            "name": "rule_backtest_stats",
            "ok": True,
            "row_count": len(rule_stats.get("items", [])),
            "source": "backend-derived-previous-action-reviews",
            "normalized_json": str(screen_dir / "normalized" / "rule_backtest_stats.json"),
        },
    ]
    if previous_review.get("enabled"):
        datasets.append(
            {
                "name": "previous_action_review",
                "ok": True,
                "row_count": len(previous_review.get("items", [])),
                "source": "backend-derived-previous-action-plan",
                "normalized_json": str(screen_dir / "normalized" / "previous_action_review.json"),
            }
        )
    if hotspot.get("enabled"):
        datasets.append(
            {
                "name": "hotspot_confirmation",
                "ok": hotspot.get("ok", False),
                "row_count": len(hotspot.get("confirmations", [])),
                "source": hotspot.get("source", "mx-hotspot"),
                "normalized_json": str(screen_dir / "normalized" / "hotspot_confirmation.json"),
                "error": hotspot.get("error"),
            }
        )
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "daily_dir": str(daily_dir),
        "datasets": datasets,
    }
    _write_json(path, payload)
    return path


def _build_previous_action_review(repo_root: Path, screen_day: date, turnover_rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    source_path = _previous_action_plan_path(repo_root / "data" / "screen", screen_day)
    if source_path is None:
        return {"enabled": False, "items": []}
    previous_plan = _read_json(source_path, default={})
    current_snapshot = {
        stock["code"]: stock
        for rank, row in enumerate(turnover_rows, start=1)
        for stock in [_normalize_turnover_stock(row, rank, screen_day.isoformat())]
        if stock["code"]
    }
    items = [_review_previous_action_item(item, current_snapshot.get(item.get("code", "")), rules) for item in previous_plan.get("items", [])]
    return {
        "enabled": True,
        "source_date": previous_plan.get("date") or source_path.parents[1].name,
        "source_path": str(source_path),
        "review_date": screen_day.isoformat(),
        "items": items,
        "summary": _previous_review_summary(items),
    }


def _previous_action_plan_path(screen_root: Path, screen_day: date) -> Path | None:
    candidates: list[tuple[date, Path]] = []
    if not screen_root.exists():
        return None
    for child in screen_root.iterdir():
        if not child.is_dir():
            continue
        try:
            day = date.fromisoformat(child.name)
        except ValueError:
            continue
        path = child / "normalized" / "stock_screen_action_plan.json"
        if day < screen_day and path.exists():
            candidates.append((day, path))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[-1][1]


def _review_previous_action_item(plan_item: dict[str, Any], current: dict[str, Any] | None, rules: dict[str, Any]) -> dict[str, Any]:
    previous_action = _text(plan_item.get("watch_action") or plan_item.get("base_action"))
    if current is None:
        return {
            "code": plan_item.get("code", ""),
            "name": plan_item.get("name", ""),
            "previous_action": previous_action,
            "performance": "未进入当日成交额榜单",
            "confirmed": False,
            "invalidated": True,
            "conclusion": "失效剔除",
            "current": None,
        }

    confirmed, invalidated = _review_flags(previous_action, current, rules)
    conclusion = _review_conclusion(previous_action, confirmed, invalidated, current)
    return {
        "code": plan_item.get("code", ""),
        "name": plan_item.get("name", ""),
        "previous_action": previous_action,
        "performance": _review_performance_text(current),
        "confirmed": confirmed,
        "invalidated": invalidated,
        "conclusion": conclusion,
        "current": {
            "turnover_rank": current.get("turnover_rank"),
            "change_pct": current.get("change_pct"),
            "amount_wan": current.get("amount_wan"),
            "turnover_pct": current.get("turnover_pct"),
            "volume_ratio": current.get("volume_ratio"),
        },
    }


def _review_flags(previous_action: str, current: dict[str, Any], rules: dict[str, Any]) -> tuple[bool, bool]:
    rank = current.get("turnover_rank", 999)
    change_pct = current.get("change_pct")
    volume_ratio = current.get("volume_ratio")
    rank_value = rank if isinstance(rank, int) else 999
    change_value = change_pct if isinstance(change_pct, (int, float)) else 0
    volume_value = volume_ratio if isinstance(volume_ratio, (int, float)) else 0

    if previous_action == "重点关注":
        return (
            rank_value <= _rule_int(rules, "action_review.focus_confirm_rank", 30) and change_value >= 0,
            rank_value > _rule_int(rules, "action_review.focus_invalid_rank", 50) or change_value <= _rule_float(rules, "action_review.focus_invalid_change_pct", -3),
        )
    if previous_action == "观察确认":
        confirm_rank = _rule_int(rules, "action_review.confirm_rank", 50)
        return (
            (rank_value <= confirm_rank and change_value >= _rule_float(rules, "action_review.confirm_change_pct", 1))
            or (rank_value <= confirm_rank and volume_value >= _rule_float(rules, "action_review.confirm_volume_ratio", 1.2)),
            rank_value > _rule_int(rules, "action_review.confirm_invalid_rank", 80) or change_value <= _rule_float(rules, "action_review.confirm_invalid_change_pct", -4),
        )
    if previous_action == "不追涨":
        return (
            _rule_float(rules, "action_review.no_chase_confirm_min_change_pct", -3) <= change_value <= _rule_float(rules, "action_review.no_chase_confirm_max_change_pct", 3)
            and rank_value <= _rule_int(rules, "action_review.no_chase_confirm_rank", 60),
            change_value >= _rule_float(rules, "action_review.no_chase_invalid_up_pct", 7) or change_value <= _rule_float(rules, "action_review.no_chase_invalid_down_pct", -5),
        )
    if previous_action == "暂不追高":
        return (
            change_value <= _rule_float(rules, "action_review.avoid_chase_confirm_change_pct", 0)
            or rank_value > _rule_int(rules, "action_review.avoid_chase_confirm_rank", 30),
            change_value >= _rule_float(rules, "action_review.avoid_chase_invalid_change_pct", 5)
            and rank_value <= _rule_int(rules, "action_review.avoid_chase_invalid_rank", 20),
        )
    if previous_action == "等待确认":
        return (
            rank_value <= _rule_int(rules, "action_review.confirm_rank", 50) and change_value >= _rule_float(rules, "action_review.confirm_change_pct", 1),
            rank_value > _rule_int(rules, "action_review.confirm_invalid_rank", 80) or change_value <= _rule_float(rules, "action_review.confirm_invalid_change_pct", -4),
        )
    return (
        rank_value <= _rule_int(rules, "action_review.fallback_confirm_rank", 60) and change_value >= 0,
        rank_value > _rule_int(rules, "action_review.fallback_invalid_rank", 80) or change_value <= _rule_float(rules, "action_review.fallback_invalid_change_pct", -4),
    )


def _review_conclusion(previous_action: str, confirmed: bool, invalidated: bool, current: dict[str, Any]) -> str:
    if previous_action == "暂不追高" and confirmed:
        return "风险提示有效"
    if previous_action == "暂不追高" and invalidated:
        return "继续过热，仍不追"
    if invalidated:
        return "失效剔除"
    if confirmed:
        return "确认有效"
    if current.get("turnover_rank", 999) <= 50:
        return "继续观察"
    return "观察降级"


def _review_performance_text(current: dict[str, Any]) -> str:
    return "成交额第{rank}，涨跌幅{change}，成交额{amount}".format(
        rank=current.get("turnover_rank", "-"),
        change=_fmt_pct(current.get("change_pct")),
        amount=_fmt_amount(current.get("amount_wan")),
    )


def _previous_review_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "confirmed": sum(1 for item in items if item.get("confirmed")),
        "invalidated": sum(1 for item in items if item.get("invalidated")),
        "risk_warning_effective": sum(1 for item in items if item.get("conclusion") in {"风险提示有效", "继续过热，仍不追"}),
        "total": len(items),
    }


def _build_system_watchlist(
    repo_root: Path,
    screen_day: date,
    candidates: list[dict[str, Any]],
    groups: dict[str, Any],
    action_plan: dict[str, Any],
    previous_review: dict[str, Any],
    mainline: dict[str, Any],
) -> dict[str, Any]:
    previous_pool = _previous_system_watchlist(repo_root / "data" / "watchlist" / "system", screen_day)
    previous_by_code = {item.get("code", ""): item for item in previous_pool.get("items", []) if item.get("code")}
    review_by_code = {item.get("code", ""): item for item in previous_review.get("items", []) if item.get("code")}
    group_by_code = _group_by_code(groups)
    action_by_code = _action_by_code(action_plan)
    current_codes = {item.get("code", "") for item in candidates}

    items = []
    for item in candidates:
        code = item.get("code", "")
        action = action_by_code.get(code, {})
        review = review_by_code.get(code)
        pool_status, reason = _system_pool_status(code, group_by_code.get(code, ""), action, previous_by_code, review)
        items.append(
            {
                "code": code,
                "name": item.get("name", ""),
                "score": item.get("score"),
                "group": group_by_code.get(code, ""),
                "watch_action": action.get("watch_action", item.get("action", "")),
                "pool_status": pool_status,
                "pool_reason": reason,
                "mainline_status": mainline.get("status"),
                "source": "stock-screen",
            }
        )

    for code, item in previous_by_code.items():
        if code in current_codes:
            continue
        review = review_by_code.get(code)
        if review and review.get("conclusion") in {"失效剔除", "观察降级"}:
            items.append(
                {
                    "code": code,
                    "name": item.get("name", ""),
                    "score": item.get("score"),
                    "group": item.get("group", ""),
                    "watch_action": item.get("watch_action", ""),
                    "pool_status": "移除",
                    "pool_reason": review.get("conclusion", "未入选今日候选"),
                    "mainline_status": mainline.get("status"),
                    "source": "previous-pool",
                }
            )

    return {
        "date": screen_day.isoformat(),
        "previous_date": previous_pool.get("date"),
        "items": items,
        "summary": _system_watchlist_summary(items),
    }


def _previous_system_watchlist(pool_root: Path, screen_day: date) -> dict[str, Any]:
    candidates: list[tuple[date, Path]] = []
    if not pool_root.exists():
        return {"items": []}
    for path in pool_root.glob("*.json"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day < screen_day:
            candidates.append((day, path))
    if not candidates:
        return {"items": []}
    return _read_json(sorted(candidates, key=lambda item: item[0])[-1][1], default={"items": []})


def _system_pool_status(
    code: str,
    group_label: str,
    action: dict[str, Any],
    previous_by_code: dict[str, dict[str, Any]],
    review: dict[str, Any] | None,
) -> tuple[str, str]:
    if code not in previous_by_code:
        return "新入池", "今日首次进入系统候选"
    if review and review.get("conclusion") in {"失效剔除", "观察降级"}:
        return "降级", review.get("conclusion", "上一计划未确认")
    if group_label == "过热观察" or action.get("watch_action") in {"暂不追高", "不追涨"}:
        return "降级", "进入过热/不追涨观察"
    return "留存", "继续在系统候选内"


def _system_watchlist_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "new": sum(1 for item in items if item.get("pool_status") == "新入池"),
        "retained": sum(1 for item in items if item.get("pool_status") == "留存"),
        "downgraded": sum(1 for item in items if item.get("pool_status") == "降级"),
        "removed": sum(1 for item in items if item.get("pool_status") == "移除"),
        "total": len(items),
    }


def _build_rule_stats(repo_root: Path, screen_day: date) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    screen_root = repo_root / "data" / "screen"
    if screen_root.exists():
        for path in sorted(screen_root.glob("*/normalized/previous_action_review.json")):
            try:
                day = date.fromisoformat(path.parents[1].name)
            except ValueError:
                continue
            if day > screen_day:
                continue
            review = _read_json(path, default={})
            for item in review.get("items", []):
                items.append(
                    {
                        "review_date": review.get("review_date") or day.isoformat(),
                        "source_date": review.get("source_date"),
                        "code": item.get("code"),
                        "name": item.get("name"),
                        "action": item.get("previous_action"),
                        "confirmed": bool(item.get("confirmed")),
                        "invalidated": bool(item.get("invalidated")),
                        "conclusion": item.get("conclusion"),
                    }
                )
    summary = _rule_stats_summary(items)
    return {
        "date": screen_day.isoformat(),
        "summary": summary,
        "by_action": _rule_stats_by_action(items),
        "items": items,
    }


def _rule_stats_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    confirmed = sum(1 for item in items if item.get("confirmed"))
    invalidated = sum(1 for item in items if item.get("invalidated"))
    return {
        "total": total,
        "confirmed": confirmed,
        "invalidated": invalidated,
        "confirmed_rate": confirmed / total * 100 if total else None,
        "invalidated_rate": invalidated / total * 100 if total else None,
    }


def _rule_stats_by_action(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = sorted({_text(item.get("action")) for item in items if item.get("action")})
    rows: list[dict[str, Any]] = []
    for action in actions:
        subset = [item for item in items if item.get("action") == action]
        summary = _rule_stats_summary(subset)
        rows.append(
            {
                "action": action,
                **summary,
                "note": _rule_stats_note(action, summary),
            }
        )
    rows.sort(key=lambda row: (-row.get("total", 0), row.get("action", "")))
    return rows


def _rule_stats_note(action: str, summary: dict[str, Any]) -> str:
    if summary.get("total", 0) < 5:
        return "样本少，仅供观察"
    confirmed_rate = summary.get("confirmed_rate") or 0
    invalidated_rate = summary.get("invalidated_rate") or 0
    if action == "暂不追高" and invalidated_rate >= 50:
        return "过热提示频繁触发，适合继续保守"
    if confirmed_rate >= 60:
        return "确认率较高，规则暂时有效"
    if invalidated_rate >= 40:
        return "失效率偏高，需要调阈值"
    return "表现中性，继续积累样本"


def _build_mainline_continuity(
    repo_root: Path,
    screen_day: date,
    sector_rows: list[dict[str, Any]],
    industry_rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    rules: dict[str, Any],
) -> dict[str, Any]:
    top_count = _rule_int(rules, "mainline.top_sector_count", 8)
    lookback_days = _rule_int(rules, "mainline.lookback_days", 3)
    daily_root = repo_root / "data" / "daily"
    lookback_dates = _available_sector_lookback_dates(daily_root, screen_day, lookback_days)
    previous_theme_sets = [_sector_theme_tokens(_read_json(daily_root / day / "normalized" / "sector_top_gainers.json", default=[]), top_count) for day in lookback_dates]
    current = [_normalize_sector(row, screen_day.isoformat()) for row in sector_rows[:top_count]]
    themes = [_mainline_theme(row, previous_theme_sets, candidates) for row in current]
    immediate_overlap = _immediate_theme_overlap(current, previous_theme_sets[-1] if previous_theme_sets else set())
    concentrated = _is_highly_concentrated(industry_rows, rules)
    status = _mainline_status(immediate_overlap, themes, concentrated, rules)
    summary = _mainline_summary(status, themes, industry_rows)
    return {
        "date": screen_day.isoformat(),
        "lookback_dates": lookback_dates,
        "status": status,
        "summary": summary,
        "immediate_overlap_count": immediate_overlap,
        "high_concentration": concentrated,
        "themes": themes,
    }


def _available_sector_lookback_dates(daily_root: Path, screen_day: date, limit: int) -> list[str]:
    dates: list[date] = []
    for child in daily_root.iterdir() if daily_root.exists() else []:
        if not child.is_dir():
            continue
        try:
            day = date.fromisoformat(child.name)
        except ValueError:
            continue
        if day >= screen_day or day.weekday() >= 5:
            continue
        if (child / "normalized" / "sector_top_gainers.json").exists():
            dates.append(day)
    return [day.isoformat() for day in sorted(dates)[-limit:]]


def _normalize_sector(row: dict[str, Any], screen_date: str) -> dict[str, Any]:
    date_key = screen_date.replace("-", ".")
    name = _text(row.get("名称") or row.get("板块"))
    return {
        "name": name,
        "clean_name": _clean_theme_name(name),
        "change_pct": _number(_find_by_prefix(row, f"涨跌幅(%) {date_key}")),
        "amount_wan": _amount_to_wan(_find_by_prefix(row, f"成交额 {date_key}")),
    }


def _sector_theme_tokens(rows: list[dict[str, Any]], limit: int) -> set[str]:
    tokens: set[str] = set()
    for row in rows[:limit]:
        name = _text(row.get("名称") or row.get("板块"))
        tokens.update(_theme_family_tokens(name))
    return tokens


def _mainline_theme(row: dict[str, Any], previous_theme_sets: list[set[str]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = _theme_family_tokens(row["name"])
    continuation_days = sum(1 for theme_set in previous_theme_sets if tokens & theme_set)
    return {
        "name": row["clean_name"],
        "change_pct": row.get("change_pct"),
        "amount_wan": row.get("amount_wan"),
        "continuation_days": continuation_days,
        "candidate_hits": _candidate_theme_hits(tokens, candidates),
    }


def _immediate_theme_overlap(current: list[dict[str, Any]], previous_tokens: set[str]) -> int:
    return sum(1 for row in current if _theme_family_tokens(row["name"]) & previous_tokens)


def _is_highly_concentrated(industry_rows: list[dict[str, Any]], rules: dict[str, Any]) -> bool:
    if not industry_rows:
        return False
    ratio = industry_rows[0].get("ratio_value")
    return isinstance(ratio, (int, float)) and ratio >= _rule_float(rules, "mainline.high_concentration_ratio", 0.5)


def _mainline_status(immediate_overlap: int, themes: list[dict[str, Any]], concentrated: bool, rules: dict[str, Any]) -> str:
    candidate_hit_count = sum(1 for theme in themes if theme.get("candidate_hits"))
    if immediate_overlap >= _rule_int(rules, "mainline.continuation_overlap_count", 2):
        return "主线延续"
    if concentrated and candidate_hit_count >= _rule_int(rules, "mainline.candidate_core_group_min_hits", 3):
        return "主线扩散"
    if immediate_overlap == 0:
        return "主线切换"
    return "弱延续"


def _mainline_summary(status: str, themes: list[dict[str, Any]], industry_rows: list[dict[str, Any]]) -> str:
    leaders = "、".join(theme["name"] for theme in themes[:3]) if themes else "-"
    concentration = ""
    if industry_rows:
        concentration = f"；Top50成交集中在{industry_rows[0].get('industry', '-')}({industry_rows[0].get('ratio', '-')})"
    return f"{leaders}居前，状态为{status}{concentration}"


def _candidate_theme_hits(tokens: set[str], candidates: list[dict[str, Any]]) -> list[str]:
    hits: list[str] = []
    for item in candidates:
        text = " ".join([item.get("industry_path", ""), item.get("industry_detail", ""), item.get("concepts", "")])
        if any(token and token in text for token in tokens):
            hits.append(f"{item.get('name')}({item.get('code')})")
    return hits[:5]


def _theme_family_tokens(name: str) -> set[str]:
    clean = _clean_theme_name(name)
    tokens = _split_theme_name(clean)
    for marker in ["通信", "光通信", "CPO", "PCB", "MLCC", "元件", "电子", "芯片", "算力", "数据中心", "消费电子", "煤炭", "电力"]:
        if marker in clean:
            tokens.add(marker)
    return {token for token in tokens if token}


def _clean_theme_name(name: str) -> str:
    return _text(name).replace("(申万)", "").replace("概念", "")


def _build_precheck(repo_root: Path, screen_day: date, candidates: list[dict[str, Any]], lookback_days: int, rules: dict[str, Any]) -> dict[str, Any]:
    daily_root = repo_root / "data" / "daily"
    lookback_dates = _available_lookback_dates(daily_root, screen_day, lookback_days)
    snapshots = {day: _stock_snapshot_by_code(daily_root / day / "normalized" / "stock_top_turnover.json", day) for day in lookback_dates}
    rows = [_precheck_candidate(item, lookback_dates, snapshots, rules) for item in candidates]
    return {
        "date": screen_day.isoformat(),
        "lookback_days": lookback_days,
        "dates": lookback_dates,
        "rows": rows,
    }


def _available_lookback_dates(daily_root: Path, screen_day: date, limit: int) -> list[str]:
    dates: list[date] = []
    for child in daily_root.iterdir() if daily_root.exists() else []:
        if not child.is_dir():
            continue
        try:
            day = date.fromisoformat(child.name)
        except ValueError:
            continue
        if day >= screen_day or day.weekday() >= 5:
            continue
        if (child / "normalized" / "stock_top_turnover.json").exists():
            dates.append(day)
    return [day.isoformat() for day in sorted(dates)[-limit:]]


def _stock_snapshot_by_code(path: Path, snapshot_date: str) -> dict[str, dict[str, Any]]:
    rows = _read_json(path, default=[])
    snapshots: dict[str, dict[str, Any]] = {}
    for rank, row in enumerate(rows, start=1):
        stock = _normalize_turnover_stock(row, rank, snapshot_date)
        if stock["code"]:
            snapshots[stock["code"]] = stock
    return snapshots


def _precheck_candidate(
    item: dict[str, Any],
    lookback_dates: list[str],
    snapshots: dict[str, dict[str, dict[str, Any]]],
    rules: dict[str, Any],
) -> dict[str, Any]:
    observations = [
        {"date": day, **snapshots[day][item["code"]]}
        for day in lookback_dates
        if item["code"] in snapshots.get(day, {})
    ]
    pre_change = _compound_change_pct([row.get("change_pct") for row in observations])
    amount_change = _value_change_pct(observations[0].get("amount_wan"), observations[-1].get("amount_wan")) if len(observations) >= 2 else None
    turnover_change = _value_change_pct(observations[0].get("turnover_pct"), observations[-1].get("turnover_pct")) if len(observations) >= 2 else None
    consecutive_up = _consecutive_up_days(observations)
    status = _precheck_status(pre_change, amount_change, consecutive_up, observations, rules)
    return {
        "code": item.get("code", ""),
        "name": item.get("name", ""),
        "available_days": len(observations),
        "dates": [row["date"] for row in observations],
        "pre_change_pct": pre_change,
        "consecutive_up_days": consecutive_up,
        "amount_change_pct": amount_change,
        "turnover_change_pct": turnover_change,
        "status": status,
        "observations": [
            {
                "date": row["date"],
                "price": row.get("price"),
                "change_pct": row.get("change_pct"),
                "amount_wan": row.get("amount_wan"),
                "turnover_pct": row.get("turnover_pct"),
                "turnover_rank": row.get("turnover_rank"),
            }
            for row in observations
        ],
    }


def _precheck_status(
    pre_change_pct: float | None,
    amount_change_pct: float | None,
    consecutive_up_days: int,
    observations: list[dict[str, Any]],
    rules: dict[str, Any],
) -> str:
    if len(observations) < 2:
        return "数据不足"
    latest_change = observations[-1].get("change_pct")
    if (
        _gte(pre_change_pct, _rule_float(rules, "precheck.overheat_change_pct", 15))
        or consecutive_up_days >= _rule_int(rules, "precheck.overheat_consecutive_up_days", 4)
        or _gte(latest_change, _rule_float(rules, "precheck.latest_overheat_change_pct", 9))
    ):
        return "已明显过热"
    if _gte(pre_change_pct, _rule_float(rules, "precheck.strong_trend_change_pct", 8)) or _gte(amount_change_pct, _rule_float(rules, "precheck.strong_amount_change_pct", 50)):
        return "强趋势，注意追高"
    if _gte(pre_change_pct, 0) and _gte(amount_change_pct, _rule_float(rules, "precheck.warm_amount_change_pct", 20)):
        return "温和转强"
    if pre_change_pct is not None and pre_change_pct < 0:
        return "低位转强待确认"
    return "走势平稳"


def _consecutive_up_days(observations: list[dict[str, Any]]) -> int:
    count = 0
    for row in reversed(observations):
        change = row.get("change_pct")
        if not isinstance(change, (int, float)) or change <= 0:
            break
        count += 1
    return count


def _compound_change_pct(changes: list[Any]) -> float | None:
    if not changes or any(not isinstance(change, (int, float)) for change in changes):
        return None
    value = 1.0
    for change in changes:
        value *= 1 + change / 100
    return (value - 1) * 100


def _value_change_pct(first: Any, latest: Any) -> float | None:
    if not isinstance(first, (int, float)) or not isinstance(latest, (int, float)) or first == 0:
        return None
    return (latest / first - 1) * 100


def _gte(value: Any, threshold: float) -> bool:
    return isinstance(value, (int, float)) and value >= threshold


def _precheck_row_for_code(precheck: dict[str, Any], code: str) -> dict[str, Any] | None:
    for row in precheck.get("rows", []):
        if row.get("code") == code:
            return row
    return None


def _build_candidate_groups(candidates: list[dict[str, Any]], hotspot: dict[str, Any], precheck: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    definitions = [
        ("主线核心", "看板块持续性、成交额排名和次日承接"),
        ("低位补涨", "看是否继续放量转强，避免一日游"),
        ("趋势延续", "看趋势是否保持但不追过快加速"),
        ("过热观察", "不追高，只看回踩和分歧后的承接"),
        ("数据强但新闻弱", "量价强，等待热点或新闻进一步确认"),
        ("继续观察", "信号不够集中，先放在备选池"),
    ]
    groups = {label: {"label": label, "watch_focus": focus, "stocks": []} for label, focus in definitions}

    for item in candidates:
        precheck_row = _precheck_row_for_code(precheck, item["code"])
        hotspot_row = _hotspot_row_for_code(hotspot, item["code"])
        label = _candidate_group_label(item, hotspot, hotspot_row, precheck_row, rules)
        groups[label]["stocks"].append(
            {
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "score": item.get("score"),
                "action": item.get("action", ""),
                "reason": _group_reason(item, hotspot_row, precheck_row),
            }
        )

    return {
        "groups": [groups[label] for label, _ in definitions],
        "grouped_count": sum(len(row["stocks"]) for row in groups.values()),
    }


def _candidate_group_label(
    item: dict[str, Any],
    hotspot: dict[str, Any],
    hotspot_row: dict[str, Any] | None,
    precheck_row: dict[str, Any] | None,
    rules: dict[str, Any],
) -> str:
    pre_status = _text(precheck_row.get("status") if precheck_row else "")
    hot_judgment = _text(hotspot_row.get("judgment") if hotspot_row else "")
    pre_change = precheck_row.get("pre_change_pct") if precheck_row else None
    score = item.get("score") or 0
    change_pct = item.get("change_pct")

    if item.get("action") == "暂不追高" or pre_status == "已明显过热" or _gte(change_pct, _rule_float(rules, "screen.overheat_change_pct", 9)):
        return "过热观察"
    if hotspot.get("enabled") and hotspot.get("ok") and hot_judgment and hot_judgment != "热点共振" and score >= _rule_int(rules, "grouping.data_strong_score", 80):
        return "数据强但新闻弱"
    if score >= _rule_int(rules, "grouping.main_core_score", 90) and item.get("turnover_rank", 999) <= _rule_int(rules, "grouping.main_core_turnover_rank", 20) and (not hotspot.get("enabled") or hot_judgment == "热点共振"):
        return "主线核心"
    if pre_status == "低位转强待确认" or (isinstance(pre_change, (int, float)) and pre_change < 0 and _gte(change_pct, _rule_float(rules, "grouping.low_rebound_today_change_pct", 1))):
        return "低位补涨"
    if pre_status in {"温和转强", "强趋势，注意追高"} or _gte(pre_change, _rule_float(rules, "grouping.trend_pre_change_pct", 3)):
        return "趋势延续"
    return "继续观察"


def _group_reason(
    item: dict[str, Any],
    hotspot_row: dict[str, Any] | None,
    precheck_row: dict[str, Any] | None,
) -> str:
    parts = [f"{item.get('score', '-')}分", f"成交额第{item.get('turnover_rank', '-')}"]
    if precheck_row:
        parts.append(_text(precheck_row.get("status")) or "体检无结论")
    if hotspot_row:
        parts.append(_text(hotspot_row.get("judgment")) or "热点无结论")
    return "；".join(parts)


def _build_action_plan(
    candidates: list[dict[str, Any]],
    groups: dict[str, Any],
    hotspot: dict[str, Any],
    precheck: dict[str, Any],
    regime: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    group_by_code = _group_by_code(groups)
    rows = [
        _action_plan_item(
            item=item,
            group_label=group_by_code.get(item["code"], "继续观察"),
            hotspot_row=_hotspot_row_for_code(hotspot, item["code"]),
            precheck_row=_precheck_row_for_code(precheck, item["code"]),
            regime=regime,
            rules=rules,
        )
        for item in candidates
    ]
    rows.sort(key=lambda row: (row["priority"], -row["score"], row["turnover_rank"]))
    for index, row in enumerate(rows, start=1):
        row["priority"] = index
    return {
        "date": candidates[0]["date"] if candidates else None,
        "items": rows,
    }


def _action_plan_item(
    *,
    item: dict[str, Any],
    group_label: str,
    hotspot_row: dict[str, Any] | None,
    precheck_row: dict[str, Any] | None,
    regime: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    watch_action, confirm_condition, invalid_condition = _action_rules(group_label, item, hotspot_row, precheck_row, regime, rules)
    return {
        "priority": _action_priority(group_label, item, rules),
        "code": item.get("code", ""),
        "name": item.get("name", ""),
        "score": item.get("score", 0),
        "turnover_rank": item.get("turnover_rank", 999),
        "group": group_label,
        "base_action": item.get("action", ""),
        "watch_action": watch_action,
        "confirm_condition": confirm_condition,
        "invalid_condition": invalid_condition,
        "hotspot_judgment": hotspot_row.get("judgment") if hotspot_row else None,
        "precheck_status": precheck_row.get("status") if precheck_row else None,
    }


def _action_rules(
    group_label: str,
    item: dict[str, Any],
    hotspot_row: dict[str, Any] | None,
    precheck_row: dict[str, Any] | None,
    regime: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[str, str, str]:
    market_note = "弱势市场下只看确认，不做追高" if regime.get("label") in {"弱势抱团", "风险释放"} else "市场环境允许时再提高关注"
    if group_label == "主线核心":
        return (
            "重点关注",
            f"板块继续在前排，个股成交额维持前{_rule_int(rules, 'action_plan.focus_keep_rank', 30)}且不放量长上影；{market_note}",
            f"跌出成交额前{_rule_int(rules, 'action_plan.focus_invalid_rank', 50)}，或高开回落且收盘转弱",
        )
    if group_label == "低位补涨":
        return (
            "观察确认",
            f"次日放量上涨，或缩量小回撤但仍留在成交额前{_rule_int(rules, 'action_plan.confirm_keep_rank', 50)}",
            "放量下跌，或热点主线退潮时仍无承接",
        )
    if group_label == "趋势延续":
        return (
            "不追涨",
            "只看分歧后的承接，回踩不破强势结构再继续观察",
            "继续急拉且换手放大，或跌破前一日强势区间",
        )
    if group_label == "过热观察":
        return (
            "暂不追高",
            "等待明显分歧后仍能稳住，回踩承接优先于盘中冲高",
            "高开冲高回落、放量炸板、或次日跌幅扩大",
        )
    if group_label == "数据强但新闻弱":
        return (
            "等待确认",
            "需要热点文本、板块强度或新闻催化补上确认",
            "量价走强但板块不跟，或新闻仍无明确支撑",
        )
    return (
            "继续观察",
            "保留备选，等待分组、热点或成交额排名进一步改善",
            f"连续掉出成交额前{_rule_int(rules, 'action_plan.fallback_invalid_rank', 80)}，或所在板块明显走弱",
    )


def _action_priority(group_label: str, item: dict[str, Any], rules: dict[str, Any]) -> int:
    base = {
        "主线核心": 10,
        "低位补涨": 30,
        "趋势延续": 40,
        "数据强但新闻弱": 50,
        "继续观察": 70,
        "过热观察": 90,
    }.get(group_label, 80)
    rank = item.get("turnover_rank", 999)
    score = item.get("score", 0)
    return base + min(20, int(rank) if isinstance(rank, int) else 20) - min(10, int(score) // 10)


def _build_hotspot_confirmation(
    repo_root: Path,
    screen_date: str,
    candidates: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "ok": False, "confirmations": []}
    hotspot_dir = repo_root / "data" / "hotspot" / screen_date
    hotspot_dir.mkdir(parents=True, exist_ok=True)
    client = MxHotspotClient(repo_root)

    market_result = client.market_hotspot(f"{screen_date} A股市场热点、热门板块、热门股票")
    if not market_result.ok:
        return {
            "enabled": True,
            "ok": False,
            "source": market_result.source,
            "error": market_result.error,
            "confirmations": [],
        }

    market_path = promote_text_artifact(market_result.raw_path, f"stock_market_hotspot_{screen_date}") or hotspot_dir / "market_hotspot.md"
    if market_path.parent != hotspot_dir:
        target = hotspot_dir / market_path.name
        target.write_text(market_result.content, encoding="utf-8")
        market_path = target
    elif not market_path.exists():
        market_path.write_text(market_result.content, encoding="utf-8")

    topic = _primary_hotspot_topic(sector_rows, candidates)
    news_result = client.finance_search(f"{screen_date} A股 {topic} 板块上涨原因 热点新闻 研报")
    news_path: Path | None = None
    if news_result.ok:
        news_path = hotspot_dir / f"finance_search_{screen_date}_{_safe_filename(topic)}.txt"
        news_path.write_text(news_result.content, encoding="utf-8")

    combined_text = "\n".join([market_result.content, news_result.content if news_result.ok else ""])
    confirmations = [_confirm_candidate(item, combined_text) for item in candidates]
    payload = {
        "enabled": True,
        "ok": True,
        "source": "stock-market-hotspot-discovery + mx-finance-search",
        "date": screen_date,
        "topic": topic,
        "market_hotspot_path": str(market_path),
        "finance_search_path": str(news_path) if news_path else None,
        "finance_search_error": news_result.error,
        "market_hotspot_excerpt": _excerpt(market_result.content, 500),
        "finance_search_excerpt": _excerpt(news_result.content, 500) if news_result.ok else "",
        "confirmations": confirmations,
    }
    _write_json(hotspot_dir / "hotspot_confirmation_raw.json", payload)
    return payload


def _primary_hotspot_topic(sector_rows: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> str:
    if sector_rows:
        return _text(sector_rows[0].get("名称") or sector_rows[0].get("板块")).replace("(申万)", "") or "市场热点"
    if candidates:
        return candidates[0].get("industry_detail") or candidates[0].get("industry") or "市场热点"
    return "市场热点"


def _confirm_candidate(item: dict[str, Any], text: str) -> dict[str, Any]:
    evidence_terms = []
    for term in [item.get("name"), item.get("industry"), item.get("industry_detail"), *_theme_terms(item.get("concepts", ""))]:
        term_text = _text(term)
        if term_text and term_text in text and term_text not in evidence_terms:
            evidence_terms.append(term_text)
    data_signal = f"成交额第{item['turnover_rank']}，{item.get('industry_detail') or item.get('industry') or '-'}，涨跌幅{_fmt_pct(item.get('change_pct'))}"
    if evidence_terms:
        judgment = "热点共振"
        evidence = "命中：" + "、".join(evidence_terms[:4])
    else:
        judgment = "数据强，待新闻确认"
        evidence = "热点文本未直接命中个股/行业关键词"
    if item.get("change_pct") is not None and item["change_pct"] > 9:
        judgment = "风险观察"
        evidence += "；涨幅接近涨停"
    return {
        "code": item.get("code", ""),
        "name": item.get("name", ""),
        "data_signal": data_signal,
        "evidence": evidence,
        "judgment": judgment,
    }


def _hotspot_row_for_code(hotspot: dict[str, Any], code: str) -> dict[str, Any] | None:
    for row in hotspot.get("confirmations", []):
        if row.get("code") == code:
            return row
    return None


def _theme_terms(concepts: str) -> list[str]:
    useful = []
    for term in _text(concepts).split("、"):
        if term and any(marker in term for marker in ["CPO", "通信", "算力", "芯片", "MLCC", "PCB", "光通信", "数据中心", "消费电子"]):
            useful.append(term)
    return useful[:8]


def _excerpt(text: str, limit: int) -> str:
    compact = " ".join(_text(text).split())
    return compact[:limit]


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value)[:40] or "topic"


def _load_rules(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "backend" / "config" / "stock_screen_rules.json"
    return _read_json(path, default={})


def _rule_value(rules: dict[str, Any], path: str, default: Any) -> Any:
    current: Any = rules
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _rule_int(rules: dict[str, Any], path: str, default: int) -> int:
    value = _rule_value(rules, path, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rule_float(rules: dict[str, Any], path: str, default: float) -> float:
    value = _rule_value(rules, path, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _find_by_prefix(row: dict[str, Any], prefix: str) -> Any:
    for key, value in row.items():
        if str(key).startswith(prefix):
            return value
    return None


def _industry_level1(value: str) -> str:
    return value.split("-")[0] if value else ""


def _amount_to_wan(value: Any) -> float | None:
    text = _text(value).replace(",", "")
    if not text or text == "-":
        return None
    multiplier = 1.0
    if text.endswith("万"):
        text = text[:-1]
    elif text.endswith("亿"):
        text = text[:-1]
        multiplier = 10000.0
    elif text.endswith("元"):
        text = text[:-1]
        multiplier = 0.0001
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    text = _text(value)
    if not text or text == "-":
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def _fmt_signed(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:+.0f}"


def _parse_screen_date(value: str | None) -> date:
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
