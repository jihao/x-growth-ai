from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.analysis.kline_patterns import recognize_kline_patterns, summarize_patterns
from backend.api import services
from backend.api.services import ApiContext
from backend.knowledge.strategy_library import get_strategy, list_strategies, search_strategies


JsonObject = dict[str, Any]
ToolHandler = Callable[..., Any]


@dataclasses.dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: JsonObject
    handler: ToolHandler

    def definition(self) -> JsonObject:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _schema(properties: JsonObject, required: list[str] | None = None) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _date_param(description: str = "交易日期，支持 YYYY-MM-DD 或 YYYYMMDD；为空则使用数据库最新交易日") -> JsonObject:
    return {"type": "string", "description": description}


def _code_param() -> JsonObject:
    return {"type": "string", "description": "股票代码，支持 300308、300308.SZ、SH600000 等常见写法"}


def _limit_param(default: int, minimum: int = 1, maximum: int = 200) -> JsonObject:
    return {
        "type": "integer",
        "description": f"返回数量，默认 {default}",
        "default": default,
        "minimum": minimum,
        "maximum": maximum,
    }


def _ctx_kwargs(ctx: ApiContext | None) -> JsonObject:
    return {"ctx": ctx} if ctx is not None else {}


def _health_status(ctx: ApiContext | None = None) -> Any:
    return services.health_status(ctx=ctx)


def _market_overview(date: str | None = None, ctx: ApiContext | None = None) -> Any:
    return services.market_overview(date=date, ctx=ctx)


def _market_concentration(
    date: str | None = None,
    lookback: int = 120,
    universe: str = "top250",
    ctx: ApiContext | None = None,
) -> Any:
    return services.market_concentration(date=date, lookback=lookback, universe=universe, ctx=ctx)


def _search_stocks(q: str, limit: int = 20, ctx: ApiContext | None = None) -> Any:
    return services.search_stocks(q=q, limit=limit, ctx=ctx)


def _stock_kline(
    code: str,
    start: str | None = None,
    end: str | None = None,
    ctx: ApiContext | None = None,
) -> Any:
    return services.stock_kline(code=code, start=start, end=end, ctx=ctx)


def _stock_indicators(
    code: str,
    start: str | None = None,
    end: str | None = None,
    ctx: ApiContext | None = None,
) -> Any:
    return services.stock_indicators(code=code, start=start, end=end, ctx=ctx)


def _kline_patterns(
    code: str,
    start: str | None = None,
    end: str | None = None,
    ctx: ApiContext | None = None,
) -> Any:
    payload = services.stock_kline(code=code, start=start, end=end, ctx=ctx)
    patterns = recognize_kline_patterns(payload.get("rows", []))
    return {
        "code": payload.get("code"),
        "ts_code": payload.get("ts_code"),
        "name": payload.get("name"),
        "count": len(payload.get("rows", [])),
        "patterns": patterns,
        "summary": summarize_patterns(patterns),
    }


def _screen_candidates(date: str | None = None, limit: int = 50, ctx: ApiContext | None = None) -> Any:
    return services.screen_candidates(date=date, limit=limit, ctx=ctx)


def _daily_review_dashboard(date: str | None = None, ctx: ApiContext | None = None) -> Any:
    return services.daily_review_dashboard(date=date, refresh=False, ctx=ctx)


def _strategy_backtests(ctx: ApiContext | None = None) -> Any:
    return services.strategy_backtests(ctx=ctx)


def _candidate_rolling_backtest(
    lookback: int = 90,
    limit: int = 30,
    refresh: bool = False,
    ctx: ApiContext | None = None,
) -> Any:
    return services.candidate_rolling_backtest(lookback=lookback, limit=limit, refresh=refresh, ctx=ctx)


def _stock_strategy_detail(code: str, ctx: ApiContext | None = None) -> Any:
    return services.stock_strategy_detail(code=code, ctx=ctx)


def _list_strategies(ctx: ApiContext | None = None) -> Any:
    return {"total": len(list_strategies()), "strategies": list_strategies()}


def _search_strategy(query: str, top_k: int = 3, ctx: ApiContext | None = None) -> Any:
    return search_strategies(query=query, top_k=top_k)


def _get_strategy(filename_or_title: str, ctx: ApiContext | None = None) -> Any:
    strategy = get_strategy(filename_or_title)
    if strategy is None:
        return {"error": f"未找到战法: {filename_or_title}"}
    return strategy


def _stock_agent_brief(code: str, date: str | None = None, ctx: ApiContext | None = None) -> Any:
    model_config = services.get_agent_model_config(ctx)
    indicators = services.stock_indicators(code=code, ctx=ctx)
    patterns_payload = _kline_patterns(code=code, ctx=ctx)
    strategy_detail = services.stock_strategy_detail(code=code, ctx=ctx)
    candidate = _candidate_for_code(code, date=date, ctx=ctx)
    strategy_query = _strategy_query(candidate, indicators, patterns_payload)
    strategies = search_strategies(strategy_query, top_k=3)
    return _build_stock_agent_brief(
        code=indicators.get("code") or code,
        name=indicators.get("name") or (candidate or {}).get("name") or code,
        candidate=candidate,
        indicators=indicators,
        patterns_payload=patterns_payload,
        strategy_detail=strategy_detail,
        strategy_query=strategy_query,
        strategies=strategies,
        model_config=model_config,
    )


def _candidate_for_code(code: str, date: str | None = None, ctx: ApiContext | None = None) -> dict[str, Any] | None:
    target = str(code).split(".", 1)[0].zfill(6)
    try:
        candidates = services.screen_candidates(date=date, limit=200, ctx=ctx).get("rows", [])
    except Exception:
        return None
    for row in candidates:
        if str(row.get("code", "")).zfill(6) == target:
            return row
    return None


def _strategy_query(candidate: dict[str, Any] | None, indicators: dict[str, Any], patterns_payload: dict[str, Any]) -> str:
    parts: list[str] = []
    if candidate:
        parts.extend(
            [
                str(candidate.get("group") or ""),
                str(candidate.get("action_hint") or ""),
                str(candidate.get("macd_status") or ""),
                str(candidate.get("kdj_status") or ""),
            ]
        )
        rsi = candidate.get("rsi14")
        if rsi is not None:
            parts.append(f"RSI{_fmt_num(rsi)}")
        parts.extend(str(item) for item in candidate.get("reasons", [])[:4])
        parts.extend(str(item) for item in candidate.get("risks", [])[:3])

    trend = (indicators.get("analysis") or {}).get("trend") or {}
    parts.append(str(trend.get("status") or ""))
    parts.extend(pattern.get("name", "") for pattern in patterns_payload.get("patterns", [])[:4])
    return " ".join(part for part in parts if part).strip() or str(indicators.get("name") or indicators.get("code") or "")


def _build_stock_agent_brief(
    code: str,
    name: str,
    candidate: dict[str, Any] | None,
    indicators: dict[str, Any],
    patterns_payload: dict[str, Any],
    strategy_detail: dict[str, Any],
    strategy_query: str,
    strategies: dict[str, Any],
    model_config: dict[str, Any],
) -> dict[str, Any]:
    analysis = indicators.get("analysis") or {}
    trend = analysis.get("trend") or {}
    pattern_summary = patterns_payload.get("summary") or {}
    pattern_bias = pattern_summary.get("bias") or "none"
    best_backtest = _best_backtest_summary(strategy_detail.get("summary", []))
    matched = strategies.get("results", [])
    action_hint = str((candidate or {}).get("action_hint") or "")
    score = (candidate or {}).get("score")
    risks = [str(item) for item in (candidate or {}).get("risks", [])]
    reasons = [str(item) for item in (candidate or {}).get("reasons", [])]

    trend_status = str(trend.get("status") or "趋势待判断")
    trend_positive = trend_status in {"强趋势", "趋势修复"}
    trend_weak = trend_status == "趋势偏弱"
    pattern_bullish = pattern_bias == "bullish"
    pattern_bearish = pattern_bias == "bearish"
    score_strong = isinstance(score, (int, float)) and score >= 85
    score_weak = isinstance(score, (int, float)) and score < 70
    high_risk = any(_contains_any(item, ["高", "风险", "过热", "顶", "回撤", "跌破"]) for item in risks + [action_hint])
    backtest_positive = bool(best_backtest and (best_backtest.get("total_return_pct") or 0) > 0 and (best_backtest.get("trade_count") or 0) > 0)

    if pattern_bearish or high_risk or trend_weak:
        status = "未形成买入信号"
        action = "不操作，等待风险释放"
        tone = "defensive"
        position = "空仓观察"
        summary = "当前存在偏空形态、趋势偏弱或风险标签，战法匹配只能作为观察线索，不能当作进场信号。"
    elif trend_positive and (score_strong or pattern_bullish) and backtest_positive:
        status = "接近观察买点"
        action = "等待触发后轻仓验证"
        tone = "active"
        position = "轻仓验证"
        summary = "趋势、候选评分/形态和策略验证相对配合，但仍需要等具体触发条件出现。"
    elif trend_positive or score_strong or pattern_bullish:
        status = "等待确认"
        action = "加入观察，等触发条件"
        tone = "watch"
        position = "观察仓位"
        summary = "已有部分积极线索，但还没有形成足够一致的买入条件。"
    else:
        status = "信号不足"
        action = "暂不操作"
        tone = "neutral"
        position = "不建仓"
        summary = "当前技术、形态和战法条件未形成清晰合力，先放入复盘观察。"

    support = _dedupe(
        [
            f"趋势状态：{trend_status}" if trend_status else "",
            f"候选评分：{score}" if score is not None else "",
            pattern_summary.get("message", ""),
            *(reasons[:3]),
            f"回测较优策略：{best_backtest.get('strategy_label') or best_backtest.get('strategy')}，收益{_fmt_num(best_backtest.get('total_return_pct'))}%" if best_backtest and best_backtest.get("total_return_pct") is not None else "",
            f"匹配战法：{matched[0].get('title')}" if matched else "",
        ]
    )
    risk_factors = _dedupe(
        [
            *(risks[:3]),
            "近期K线形态偏空，需等待止跌确认。" if pattern_bearish else "",
            "趋势偏弱，左侧信号需要降低权重。" if trend_weak else "",
            "缺少正收益回测样本，策略有效性待验证。" if not backtest_positive else "",
        ]
    )
    top_strategy = matched[0] if matched else {}
    buy_signals = top_strategy.get("buy_signals") or []
    risk_notes = top_strategy.get("risk_notes") or []
    next_steps = _dedupe(
        [
            f"等待触发：{buy_signals[0]}" if buy_signals else "等待价格、成交量和技术指标形成同向确认。",
            "若回踩关键均线/支撑位不破，再观察是否出现放量转强。",
            "确认前不把战法匹配当成买入信号。",
        ]
    )
    invalidation = _dedupe(
        [
            f"战法失效：{risk_notes[0]}" if risk_notes else "",
            "继续放量下跌或跌破关键支撑，撤销本次观察假设。",
            "若市场宽度转弱或候选评分跌出观察区，降低优先级。",
        ]
    )

    evidence = [
        {"label": "买入状态", "value": status, "hint": summary, "tone": tone},
        {"label": "仓位建议", "value": position, "hint": "这是研究/复盘仓位提示，不是实盘指令。", "tone": tone},
        {"label": "趋势", "value": trend_status, "hint": trend.get("hint") or "-", "tone": "active" if trend_positive else "defensive" if trend_weak else "watch"},
        {"label": "K线形态", "value": _pattern_bias_label(pattern_bias), "hint": pattern_summary.get("message") or "-", "tone": "active" if pattern_bullish else "defensive" if pattern_bearish else "watch"},
    ]
    if score is not None:
        evidence.append({"label": "候选评分", "value": _fmt_num(score), "hint": action_hint or "-", "tone": "active" if score_strong else "defensive" if score_weak else "watch"})
    if best_backtest:
        evidence.append(
            {
                "label": "回测策略",
                "value": best_backtest.get("strategy_label") or best_backtest.get("strategy") or "-",
                "hint": f"收益{_fmt_num(best_backtest.get('total_return_pct'))}%，交易{_fmt_num(best_backtest.get('trade_count'), decimals=0)}次",
                "tone": "active" if backtest_positive else "watch",
            }
        )

    return {
        "code": code,
        "name": name,
        "engine": {
            "mode": model_config.get("mode") or "rules",
            "label": "规则引擎" if model_config.get("mode") != "llm" else "OpenAI-compatible 模型",
            "model": model_config.get("model") or "",
            "base_url": model_config.get("base_url") or "",
            "api_key_configured": bool(model_config.get("api_key_configured")),
            "note": "当前结论由本地规则汇总生成，未调用外部模型。" if model_config.get("mode") != "llm" else "模型配置已保存；当前版本仍先用规则汇总生成结构化结论。",
        },
        "status": status,
        "action": action,
        "tone": tone,
        "summary": summary,
        "position_sizing": position,
        "buy_signal": status == "接近观察买点",
        "supporting_reasons": support[:5],
        "risk_factors": risk_factors[:5],
        "next_steps": next_steps[:4],
        "invalidation": invalidation[:4],
        "evidence": evidence,
        "strategy_query": strategy_query,
        "matched_strategies": matched,
        "pattern_summary": pattern_summary,
        "source_tools": ["stock_indicators", "kline_patterns", "search_strategy", "stock_strategy_detail", "screen_candidates"],
    }


def _best_backtest_summary(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get("total_return_pct") is not None]
    if not candidates:
        return rows[0] if rows else None
    return max(candidates, key=lambda row: (row.get("total_return_pct") or -999999, row.get("trade_count") or 0))


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _pattern_bias_label(value: str) -> str:
    if value == "bullish":
        return "偏多形态"
    if value == "bearish":
        return "偏空形态"
    if value == "neutral":
        return "整理观察"
    return "形态不足"


def _fmt_num(value: Any, decimals: int = 2) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(parsed):
        return "-"
    if decimals <= 0:
        return str(int(round(parsed)))
    return f"{parsed:.{decimals}f}"


TOOLS: tuple[AgentTool, ...] = (
    AgentTool(
        name="health_status",
        description="检查本地 A 股数据库是否存在，并返回股票数、日线行数、日期范围等状态。",
        parameters=_schema({}),
        handler=_health_status,
    ),
    AgentTool(
        name="market_overview",
        description="获取市场宽度概览，包括上涨/下跌家数、类涨停/跌停数量、成交额和风险状态。",
        parameters=_schema({"date": _date_param()}),
        handler=_market_overview,
    ),
    AgentTool(
        name="market_concentration",
        description="分析成交额集中度，包括 CR5/CR10/CR50、有效股票数和头部成交额结构。",
        parameters=_schema(
            {
                "date": _date_param(),
                "lookback": {
                    "type": "integer",
                    "description": "回看交易日数量，默认 120",
                    "default": 120,
                    "minimum": 20,
                    "maximum": 260,
                },
                "universe": {
                    "type": "string",
                    "description": "统计范围：top250 使用成交额前250，只看头部流动性；all 使用全市场。",
                    "enum": ["top250", "all"],
                    "default": "top250",
                },
            }
        ),
        handler=_market_concentration,
    ),
    AgentTool(
        name="search_stocks",
        description="按股票代码或名称搜索本地股票列表。",
        parameters=_schema(
            {
                "q": {"type": "string", "description": "股票代码或名称关键词"},
                "limit": _limit_param(20, 1, 100),
            },
            required=["q"],
        ),
        handler=_search_stocks,
    ),
    AgentTool(
        name="stock_kline",
        description="查询单只股票的前复权日 K 线数据。",
        parameters=_schema(
            {
                "code": _code_param(),
                "start": _date_param("开始日期，支持 YYYY-MM-DD 或 YYYYMMDD；为空则由服务层决定"),
                "end": _date_param("结束日期，支持 YYYY-MM-DD 或 YYYYMMDD；为空则由服务层决定"),
            },
            required=["code"],
        ),
        handler=_stock_kline,
    ),
    AgentTool(
        name="stock_indicators",
        description="查询单只股票 K 线并附加 MA、MACD、KDJ、RSI、TD 序列和背离/钝化分析。",
        parameters=_schema(
            {
                "code": _code_param(),
                "start": _date_param("开始日期，支持 YYYY-MM-DD 或 YYYYMMDD；为空则由服务层决定"),
                "end": _date_param("结束日期，支持 YYYY-MM-DD 或 YYYYMMDD；为空则由服务层决定"),
            },
            required=["code"],
        ),
        handler=_stock_indicators,
    ),
    AgentTool(
        name="kline_patterns",
        description="识别单只股票近期K线形态，包括十字星、锤子线、吞没、早晨/黄昏之星、横盘整理、N字上攻等。",
        parameters=_schema(
            {
                "code": _code_param(),
                "start": _date_param("开始日期，支持 YYYY-MM-DD 或 YYYYMMDD；为空则默认读取最近约240个交易日"),
                "end": _date_param("结束日期，支持 YYYY-MM-DD 或 YYYYMMDD；为空则使用数据库最新交易日"),
            },
            required=["code"],
        ),
        handler=_kline_patterns,
    ),
    AgentTool(
        name="screen_candidates",
        description="从本地行情库生成规则选股候选列表，返回评分、趋势、量价和技术信号。",
        parameters=_schema({"date": _date_param(), "limit": _limit_param(50, 1, 200)}),
        handler=_screen_candidates,
    ),
    AgentTool(
        name="daily_review_dashboard",
        description="读取或生成日评 dashboard 数据，聚合市场宽度、集中度、热点、候选股和操作边界。",
        parameters=_schema({"date": _date_param()}),
        handler=_daily_review_dashboard,
    ),
    AgentTool(
        name="strategy_backtests",
        description="读取最近一次技术策略回测汇总。",
        parameters=_schema({}),
        handler=_strategy_backtests,
    ),
    AgentTool(
        name="candidate_rolling_backtest",
        description="对近期选股候选池做滚动回测，评估候选池规则的阶段表现。",
        parameters=_schema(
            {
                "lookback": {
                    "type": "integer",
                    "description": "回测窗口交易日数量，默认 90",
                    "default": 90,
                    "minimum": 20,
                    "maximum": 160,
                },
                "limit": _limit_param(30, 5, 100),
                "refresh": {
                    "type": "boolean",
                    "description": "是否强制重建缓存；默认 false",
                    "default": False,
                },
            }
        ),
        handler=_candidate_rolling_backtest,
    ),
    AgentTool(
        name="stock_strategy_detail",
        description="读取单只股票在最近策略回测中的交易、权益曲线和信号详情。",
        parameters=_schema({"code": _code_param()}, required=["code"]),
        handler=_stock_strategy_detail,
    ),
    AgentTool(
        name="stock_agent_brief",
        description="汇总候选评分、趋势指标、K线形态、战法匹配和回测结果，生成一页式个股AI操作建议。",
        parameters=_schema(
            {
                "code": _code_param(),
                "date": _date_param("可选交易日期，支持 YYYY-MM-DD 或 YYYYMMDD；用于查找当日候选池信息"),
            },
            required=["code"],
        ),
        handler=_stock_agent_brief,
    ),
    AgentTool(
        name="list_strategies",
        description="列出内置短线战法知识库，用于了解可检索的战法范围。",
        parameters=_schema({}),
        handler=_list_strategies,
    ),
    AgentTool(
        name="search_strategy",
        description="根据当前市场/技术场景搜索匹配的短线战法，例如 放量突破、RSI超卖、分歧转一致、龙头二波。",
        parameters=_schema(
            {
                "query": {
                    "type": "string",
                    "description": "场景描述或技术关键词，例如 '放量突破 MA20 MACD金叉'、'低吸 超跌 RSI'。",
                },
                "top_k": _limit_param(3, 1, 10),
            },
            required=["query"],
        ),
        handler=_search_strategy,
    ),
    AgentTool(
        name="get_strategy",
        description="获取指定短线战法的完整 Markdown 内容和结构化摘要。",
        parameters=_schema(
            {
                "filename_or_title": {
                    "type": "string",
                    "description": "战法文件名或标题，例如 '01-放量突破战法.md' 或 '放量突破战法'。",
                }
            },
            required=["filename_or_title"],
        ),
        handler=_get_strategy,
    ),
)

TOOL_NAMES = tuple(tool.name for tool in TOOLS)
TOOL_DEFINITIONS = [tool.definition() for tool in TOOLS]
_TOOL_MAP = {tool.name: tool for tool in TOOLS}


def tool_definitions() -> list[JsonObject]:
    return list(TOOL_DEFINITIONS)


def run_tool(name: str, arguments: Mapping[str, Any] | None = None, ctx: ApiContext | None = None) -> JsonObject:
    tool = _TOOL_MAP.get(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool: {name}", "available_tools": list(TOOL_NAMES)}

    raw_args = dict(arguments or {})
    validation_error = _validate_arguments(tool, raw_args)
    if validation_error:
        return {"ok": False, "tool": name, "error": validation_error}

    try:
        result = tool.handler(**raw_args, **_ctx_kwargs(ctx))
    except Exception as exc:
        return {"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "tool": name, "result": _json_ready(result)}


def _validate_arguments(tool: AgentTool, arguments: JsonObject) -> str | None:
    parameters = tool.parameters
    properties = parameters.get("properties", {})
    required = set(parameters.get("required", []))
    missing = sorted(key for key in required if key not in arguments or arguments[key] in (None, ""))
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"

    unknown = sorted(set(arguments) - set(properties))
    if unknown and parameters.get("additionalProperties") is False:
        return f"unknown argument(s): {', '.join(unknown)}"
    return None


def _json_ready(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _json_ready(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        json.dumps(value)
        return value
    except TypeError:
        if hasattr(value, "item"):
            return _json_ready(value.item())
        return str(value)
