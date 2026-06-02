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
    limit: int = 15
    with_hotspot: bool = False


def generate_stock_screen(config: StockScreenConfig) -> Path:
    repo_root = _find_repo_root()
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

    candidates = _screen_candidates(
        turnover_rows=turnover_rows,
        sector_rows=sector_rows,
        industry_rows=industry_rows,
        regime=regime,
        limit=config.limit,
        screen_date=screen_day.isoformat(),
    )

    screen_dir = repo_root / "data" / "screen" / screen_day.isoformat()
    screen_normalized = screen_dir / "normalized"
    screen_normalized.mkdir(parents=True, exist_ok=True)
    _write_json(screen_normalized / "stock_screen_candidates.json", candidates)
    hotspot = _build_hotspot_confirmation(repo_root, screen_day.isoformat(), candidates, sector_rows, config.with_hotspot)
    if hotspot["enabled"]:
        _write_json(screen_normalized / "hotspot_confirmation.json", hotspot)
    manifest_path = _write_manifest(screen_dir, candidates, daily_dir, hotspot)

    output_path = config.output_path or repo_root / "reports" / f"x_growth_stock_screen_{screen_day.isoformat()}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = _render_markdown(screen_day, candidates, regime, comparison, manifest_path, hotspot)
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
) -> list[dict[str, Any]]:
    strong_industries = _strong_industries(industry_rows)
    strong_themes = _strong_theme_tokens(sector_rows)
    market_penalty = _market_penalty(regime)

    candidates: list[dict[str, Any]] = []
    for rank, row in enumerate(turnover_rows[:80], start=1):
        stock = _normalize_turnover_stock(row, rank, screen_date)
        score, reasons, risks = _score_stock(stock, strong_industries, strong_themes, market_penalty, regime)
        if score < 45:
            continue
        candidates.append(
            {
                **stock,
                "score": score,
                "reasons": reasons,
                "risks": risks,
                "action": _candidate_action(score, stock, risks, regime),
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
) -> tuple[int, list[str], list[str]]:
    score = 50 - market_penalty
    reasons: list[str] = []
    risks: list[str] = []

    rank = stock["turnover_rank"]
    if rank <= 10:
        score += 18
        reasons.append("成交额排名前10，资金关注度高")
    elif rank <= 30:
        score += 12
        reasons.append("成交额排名前30，资金参与度较高")
    elif rank <= 50:
        score += 6
        reasons.append("成交额进入前50")

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
        if 1 <= change_pct <= 6:
            score += 10
            reasons.append("涨幅温和偏强，尚未明显过热")
        elif 6 < change_pct <= 9:
            score += 3
            risks.append("涨幅偏高，追高风险上升")
        elif change_pct > 9:
            score -= 12
            risks.append("接近涨停或涨幅过热，不适合作为低风险观察点")
        elif change_pct < 0:
            score -= 6
            risks.append("当日逆势走弱")

    turnover_pct = stock.get("turnover_pct")
    if isinstance(turnover_pct, (int, float)):
        if 2 <= turnover_pct <= 8:
            score += 6
            reasons.append("换手率适中，流动性较好")
        elif turnover_pct > 12:
            score -= 5
            risks.append("换手率过高，短线分歧较大")

    volume_ratio = stock.get("volume_ratio")
    if isinstance(volume_ratio, (int, float)) and volume_ratio >= 1.2:
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


def _candidate_action(score: int, stock: dict[str, Any], risks: list[str], regime: dict[str, Any]) -> str:
    if stock.get("change_pct") is not None and stock["change_pct"] > 9:
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
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 系统选股报告｜{screen_day.isoformat()}",
        "",
        f"> 生成时间：{generated_at}｜定位：规则选股练习，不构成投资建议。",
        "",
        "## 1. 今日筛选结论",
        "",
        f"- 市场状态：{regime.get('label', '-')}｜{regime.get('tone', '-')}",
        f"- 候选数量：{len(candidates)}",
        f"- 本地落库：`{manifest_path}`",
        "",
        _screen_summary(candidates, regime, comparison),
        "",
        "## 2. 规则说明",
        "",
        "- 只从当日成交额前100中筛选，避免流动性太弱。",
        "- 优先选择所在行业进入 Top50 成交分布的股票。",
        "- 优先贴近当日强势板块/概念，但过滤明显过热的涨幅。",
        "- 弱势抱团或风险释放时降低分数，候选只作为观察清单。",
        "",
        "## 3. 候选股列表",
        "",
        "| 排名 | 股票 | 分数 | 涨跌幅 | 成交额 | 换手率 | 行业 | 动作 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for index, item in enumerate(candidates, start=1):
        lines.append(
            "| {rank} | {name}({code}) | {score} | {change} | {amount} | {turnover} | {industry} | {action} |".format(
                rank=index,
                name=item["name"],
                code=item["code"],
                score=item["score"],
                change=_fmt_pct(item.get("change_pct")),
                amount=_fmt_amount(item.get("amount_wan")),
                turnover=_fmt_pct(item.get("turnover_pct")),
                industry=item.get("industry_detail") or item.get("industry") or "-",
                action=item["action"],
            )
        )

    if hotspot.get("enabled"):
        lines.extend(["", "## 4. 热点确认", ""])
        lines.extend(_hotspot_block(hotspot))
        next_section = 5
    else:
        next_section = 4

    lines.extend(["", f"## {next_section}. 入选理由与风险", ""])
    for item in candidates:
        lines.extend(_candidate_card(item, _hotspot_row_for_code(hotspot, item["code"])))
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


def _candidate_card(item: dict[str, Any], hotspot_row: dict[str, Any] | None = None) -> list[str]:
    reasons = "；".join(item["reasons"]) if item["reasons"] else "规则命中较少"
    risks = "；".join(item["risks"]) if item["risks"] else "暂无显著规则风险"
    lines = [
        f"### {item['name']}({item['code']})｜{item['score']}分",
        "",
        f"- 动作：{item['action']}",
        f"- 行业/主题：{item.get('industry_detail') or item.get('industry') or '-'}",
        f"- 量价：涨跌幅 {_fmt_pct(item.get('change_pct'))}，成交额 {_fmt_amount(item.get('amount_wan'))}，换手率 {_fmt_pct(item.get('turnover_pct'))}，量比 {_fmt_num(item.get('volume_ratio'))}",
        f"- 入选理由：{reasons}",
        f"- 风险标签：{risks}",
    ]
    if hotspot_row:
        lines.append(f"- 热点确认：{hotspot_row.get('judgment', '-')}｜{hotspot_row.get('evidence', '-')}")
    return lines


def _write_manifest(screen_dir: Path, candidates: list[dict[str, Any]], daily_dir: Path, hotspot: dict[str, Any]) -> Path:
    path = screen_dir / "manifest.json"
    datasets = [
        {
            "name": "stock_screen_candidates",
            "ok": True,
            "row_count": len(candidates),
            "source": "backend-derived",
            "normalized_json": str(screen_dir / "normalized" / "stock_screen_candidates.json"),
        }
    ]
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


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
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
