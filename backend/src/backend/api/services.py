from __future__ import annotations

import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.api.db import (
    connect,
    default_db_path,
    display_code,
    display_trade_date,
    find_repo_root,
    normalize_trade_date,
    normalize_ts_code,
    rows_to_dicts,
)
from backend.backtest.engine import BacktestCostConfig, run_single_backtest
from backend.backtest.indicators import add_technical_indicators
from backend.backtest.strategies import STRATEGIES, build_strategy_signals
from backend.data_sources.mx_hotspot import MxHotspotClient, promote_text_artifact
from backend.report.daily_review import DailyReviewConfig, generate_daily_review


_BACKTEST_LOCK = threading.Lock()
_BACKTEST_JOBS: dict[str, dict[str, Any]] = {}
REVIEW_CACHE_VERSION = 6


@dataclass(frozen=True)
class ApiContext:
    repo_root: Path
    db_path: Path


def context() -> ApiContext:
    root = find_repo_root()
    return ApiContext(repo_root=root, db_path=default_db_path(root))


def health_status(ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    db_exists = ctx.db_path.exists()
    payload: dict[str, Any] = {
        "ok": db_exists,
        "database": str(ctx.db_path),
        "database_exists": db_exists,
    }
    if not db_exists:
        return payload
    with connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) rows, COUNT(DISTINCT ts_code) stocks, MIN(trade_date) start_date, MAX(trade_date) latest_date FROM daily_qfq"
        ).fetchone()
    payload.update(
        {
            "rows": row["rows"],
            "stocks": row["stocks"],
            "start_date": display_trade_date(row["start_date"]),
            "latest_date": display_trade_date(row["latest_date"]),
        }
    )
    return payload


def latest_trade_date(conn: Any, target: str | None = None) -> str | None:
    normalized = normalize_trade_date(target)
    if normalized:
        row = conn.execute("SELECT MAX(trade_date) value FROM daily_qfq WHERE trade_date <= ?", (normalized,)).fetchone()
    else:
        row = conn.execute("SELECT MAX(trade_date) value FROM daily_qfq").fetchone()
    return row["value"] if row else None


def recent_trade_dates(conn: Any, end_date: str, count: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT trade_date
        FROM daily_qfq
        WHERE trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (end_date, count),
    ).fetchall()
    return sorted(row["trade_date"] for row in rows)


def market_overview(date: str | None = None, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    with connect(ctx.db_path) as conn:
        current = latest_trade_date(conn, date)
        if current is None:
            return {"date": None, "error": "no market data"}
        dates = recent_trade_dates(conn, current, 2)
        previous = dates[0] if len(dates) == 2 else None
        current_frame = pd.read_sql_query(
            """
            SELECT ts_code, close_qfq, amount
            FROM daily_qfq
            WHERE trade_date = ?
            """,
            conn,
            params=(current,),
        )
        previous_frame = pd.read_sql_query(
            """
            SELECT ts_code, close_qfq AS previous_close
            FROM daily_qfq
            WHERE trade_date = ?
            """,
            conn,
            params=(previous,),
        ) if previous else pd.DataFrame(columns=["ts_code", "previous_close"])

    frame = current_frame.merge(previous_frame, on="ts_code", how="left")
    frame["change_pct"] = (frame["close_qfq"] / frame["previous_close"] - 1) * 100
    up = int((frame["change_pct"] > 0).sum())
    down = int((frame["change_pct"] < 0).sum())
    flat = int((frame["change_pct"] == 0).sum())
    strong = int((frame["change_pct"] >= 9.8).sum())
    weak = int((frame["change_pct"] <= -9.8).sum())
    total_amount = float(frame["amount"].fillna(0).sum())
    median_change = _safe_float(frame["change_pct"].median())
    risk_level = "积极" if up > down * 1.4 else "谨慎" if down > up * 1.2 else "均衡"
    return {
        "date": display_trade_date(current),
        "raw_date": current,
        "previous_date": display_trade_date(previous),
        "stock_count": int(len(frame)),
        "up": up,
        "down": down,
        "flat": flat,
        "limit_up_like": strong,
        "limit_down_like": weak,
        "total_amount_yi": total_amount / 100000000,
        "median_change_pct": median_change,
        "risk_level": risk_level,
    }


def market_concentration(
    date: str | None = None,
    lookback: int = 120,
    universe: str = "top250",
    ctx: ApiContext | None = None,
) -> dict[str, Any]:
    ctx = ctx or context()
    safe_lookback = min(max(int(lookback or 120), 20), 260)
    safe_universe = universe if universe in {"top250", "all"} else "top250"
    with connect(ctx.db_path) as conn:
        current = latest_trade_date(conn, date)
        if current is None:
            return {"date": None, "rows": [], "top": []}
        dates = recent_trade_dates(conn, current, safe_lookback)
        if not dates:
            return {"date": display_trade_date(current), "raw_date": current, "rows": [], "top": []}
        placeholders = ",".join("?" for _ in dates)
        frame = pd.read_sql_query(
            f"""
            SELECT d.trade_date, d.ts_code, d.amount, d.close_qfq, s.name
            FROM daily_qfq d
            LEFT JOIN stocks s ON s.ts_code = d.ts_code
            WHERE d.trade_date IN ({placeholders})
              AND d.amount IS NOT NULL
              AND d.amount > 0
            ORDER BY d.trade_date, d.amount DESC
            """,
            conn,
            params=dates,
        )
        previous_dates = recent_trade_dates(conn, current, 2)
        previous = previous_dates[0] if len(previous_dates) == 2 else None
        previous_close = pd.read_sql_query(
            """
            SELECT ts_code, close_qfq AS previous_close
            FROM daily_qfq
            WHERE trade_date = ?
            """,
            conn,
            params=(previous,),
        ) if previous else pd.DataFrame(columns=["ts_code", "previous_close"])

    if frame.empty:
        return {"date": display_trade_date(current), "raw_date": current, "rows": [], "top": []}

    series: list[dict[str, Any]] = []
    latest_slice = pd.DataFrame()
    for trade_date, group in frame.groupby("trade_date", sort=True):
        ranked = group.sort_values("amount", ascending=False).reset_index(drop=True)
        if safe_universe == "top250":
            ranked = ranked.head(250).copy()
        if ranked.empty:
            continue
        ranked["weight"] = ranked["amount"] / float(ranked["amount"].sum())
        weights = ranked["weight"].to_list()
        layer_1_5 = sum(weights[:5]) * 100
        layer_6_10 = sum(weights[5:10]) * 100
        layer_11_20 = sum(weights[10:20]) * 100
        layer_21_50 = sum(weights[20:50]) * 100
        top5_pct_count = max(1, math.ceil(len(weights) * 0.05))
        eff_n = 1 / sum(weight * weight for weight in weights) if weights else 0
        row = {
            "date": display_trade_date(trade_date),
            "raw_date": trade_date,
            "stock_count": int(len(ranked)),
            "total_amount_yi": _safe_float(float(ranked["amount"].sum()) / 100000000),
            "cr5_pct": _safe_float(layer_1_5),
            "cr10_pct": _safe_float(layer_1_5 + layer_6_10),
            "cr50_pct": _safe_float(layer_1_5 + layer_6_10 + layer_11_20 + layer_21_50),
            "top5pct_concentration_pct": _safe_float(sum(weights[:top5_pct_count]) * 100),
            "effective_count": _safe_float(eff_n),
            "layer_top5_pct": _safe_float(layer_1_5),
            "layer_6_10_pct": _safe_float(layer_6_10),
            "layer_11_20_pct": _safe_float(layer_11_20),
            "layer_21_50_pct": _safe_float(layer_21_50),
        }
        series.append(row)
        if trade_date == current:
            latest_slice = ranked

    if latest_slice.empty:
        latest_raw = series[-1]["raw_date"] if series else current
        latest_slice = frame[frame["trade_date"] == latest_raw].sort_values("amount", ascending=False)
        if safe_universe == "top250":
            latest_slice = latest_slice.head(250).copy()
        latest_slice["weight"] = latest_slice["amount"] / float(latest_slice["amount"].sum())

    distribution_rows = []
    cumulative_weight = 0.0
    total_ranked = max(1, len(latest_slice))
    for rank, row in enumerate(latest_slice.to_dict("records"), start=1):
        weight_pct = float(row.get("weight") or 0) * 100
        cumulative_weight += weight_pct
        distribution_rows.append(
            {
                "rank": rank,
                "rank_pct": _safe_float(rank / total_ranked * 100),
                "code": display_code(row["ts_code"]),
                "ts_code": row["ts_code"],
                "name": _clean_name(row.get("name") or display_code(row["ts_code"])),
                "amount_yi": _safe_float(float(row.get("amount") or 0) / 100000000),
                "weight_pct": _safe_float(weight_pct),
                "cumulative_weight_pct": _safe_float(cumulative_weight),
            }
        )

    latest_top = latest_slice.head(20).merge(previous_close, on="ts_code", how="left")
    top_rows = []
    for rank, row in enumerate(latest_top.to_dict("records"), start=1):
        previous_price = row.get("previous_close")
        close = row.get("close_qfq")
        change_pct = (close / previous_price - 1) * 100 if previous_price and close else None
        top_rows.append(
            {
                "rank": rank,
                "code": display_code(row["ts_code"]),
                "ts_code": row["ts_code"],
                "name": _clean_name(row.get("name") or display_code(row["ts_code"])),
                "amount_yi": _safe_float(float(row.get("amount") or 0) / 100000000),
                "weight_pct": _safe_float(float(row.get("weight") or 0) * 100),
                "close": _safe_float(close),
                "change_pct": _safe_float(change_pct),
            }
        )

    latest = series[-1] if series else None
    previous_row = series[-2] if len(series) >= 2 else None
    deltas = {}
    if latest and previous_row:
        for key in ("cr5_pct", "cr10_pct", "cr50_pct", "top5pct_concentration_pct", "effective_count"):
            deltas[f"{key}_change"] = _safe_float((latest.get(key) or 0) - (previous_row.get(key) or 0))

    return {
        "date": display_trade_date(current),
        "raw_date": current,
        "universe": safe_universe,
        "lookback": safe_lookback,
        "method": "成交额 Top250 权重" if safe_universe == "top250" else "全市场成交额权重",
        "description": "权重=个股当日成交额/样本股票当日成交额合计，用于观察资金是否集中在少数股票。",
        "latest": {**latest, **deltas} if latest else None,
        "series": _json_ready(series),
        "distribution": _json_ready(distribution_rows),
        "top": _json_ready(top_rows),
    }


def search_stocks(q: str, limit: int = 20, ctx: ApiContext | None = None) -> list[dict[str, Any]]:
    ctx = ctx or context()
    query = f"%{q.strip().upper()}%"
    with connect(ctx.db_path) as conn:
        rows = conn.execute(
            """
            SELECT ts_code, name
            FROM stocks
            WHERE ts_code LIKE ? OR name LIKE ?
            ORDER BY ts_code
            LIMIT ?
            """,
            (query, query, limit),
        ).fetchall()
    return [{"code": display_code(row["ts_code"]), "ts_code": row["ts_code"], "name": _clean_name(row["name"])} for row in rows]


def stock_kline(code: str, start: str | None = None, end: str | None = None, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    ts_code = normalize_ts_code(code)
    with connect(ctx.db_path) as conn:
        current = latest_trade_date(conn, end)
        if current is None:
            return {"code": display_code(ts_code), "ts_code": ts_code, "rows": []}
        start_date = normalize_trade_date(start)
        if start_date is None:
            dates = recent_trade_dates(conn, current, 240)
            start_date = dates[0] if dates else current
        rows = conn.execute(
            """
            SELECT d.trade_date, d.open, d.high, d.low, d.close_qfq, d.volume, d.amount, s.name
            FROM daily_qfq d
            LEFT JOIN stocks s ON s.ts_code = d.ts_code
            WHERE d.ts_code = ?
              AND d.trade_date BETWEEN ? AND ?
            ORDER BY d.trade_date
            """,
            (ts_code, start_date, current),
        ).fetchall()
    data = [
        {
            "date": display_trade_date(row["trade_date"]),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close_qfq"],
            "volume": row["volume"],
            "amount": row["amount"],
        }
        for row in rows
    ]
    name = _clean_name(rows[0]["name"]) if rows else display_code(ts_code)
    return {"code": display_code(ts_code), "ts_code": ts_code, "name": name, "rows": data}


def stock_indicators(code: str, start: str | None = None, end: str | None = None, ctx: ApiContext | None = None) -> dict[str, Any]:
    payload = stock_kline(code, start=start, end=end, ctx=ctx)
    frame = pd.DataFrame(payload["rows"])
    if frame.empty:
        return {**payload, "rows": []}
    indicator_frame = frame.rename(columns={"close": "close"}).copy()
    enriched = add_technical_indicators(indicator_frame)
    rows = []
    for row in enriched.to_dict("records"):
        rows.append(
            {
                "date": row["date"],
                "open": _safe_float(row.get("open")),
                "high": _safe_float(row.get("high")),
                "low": _safe_float(row.get("low")),
                "close": _safe_float(row.get("close")),
                "volume": _safe_float(row.get("volume")),
                "amount": _safe_float(row.get("amount")),
                "ma20": _safe_float(row.get("ma20")),
                "ma60": _safe_float(row.get("ma60")),
                "macd_dif": _safe_float(row.get("macd_dif")),
                "macd_dea": _safe_float(row.get("macd_dea")),
                "macd_hist": _safe_float(row.get("macd_hist")),
                "kdj_k": _safe_float(row.get("kdj_k")),
                "kdj_d": _safe_float(row.get("kdj_d")),
                "kdj_j": _safe_float(row.get("kdj_j")),
                "rsi14": _safe_float(row.get("rsi14")),
                "td_buy_setup": _safe_float(row.get("td_buy_setup")),
                "td_sell_setup": _safe_float(row.get("td_sell_setup")),
                "td_signal": row.get("td_signal"),
                "macd_top_divergence": bool(row.get("macd_top_divergence")),
                "macd_bottom_divergence": bool(row.get("macd_bottom_divergence")),
                "macd_top_passivation": bool(row.get("macd_top_passivation")),
                "macd_bottom_passivation": bool(row.get("macd_bottom_passivation")),
            }
        )
    return {**payload, "rows": rows, "analysis": _stock_indicator_analysis(enriched)}


def screen_candidates(date: str | None = None, limit: int = 50, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    with connect(ctx.db_path) as conn:
        current = latest_trade_date(conn, date)
        if current is None:
            return {"date": None, "rows": []}
        dates = recent_trade_dates(conn, current, 90)
        latest_rows = conn.execute(
            """
            SELECT ts_code
            FROM daily_qfq
            WHERE trade_date = ?
              AND amount IS NOT NULL
            ORDER BY amount DESC
            LIMIT 800
            """,
            (current,),
        ).fetchall()
        liquid_codes = [row["ts_code"] for row in latest_rows]
        if not dates or not liquid_codes:
            return {"date": display_trade_date(current), "raw_date": current, "rows": []}
        date_placeholders = ",".join("?" for _ in dates)
        code_placeholders = ",".join("?" for _ in liquid_codes)
        frame = pd.read_sql_query(
            f"""
            SELECT d.ts_code, s.name, d.trade_date, d.open, d.high, d.low, d.close_qfq AS close,
                   d.volume, d.amount
            FROM daily_qfq d
            LEFT JOIN stocks s ON s.ts_code = d.ts_code
            WHERE d.trade_date IN ({date_placeholders})
              AND d.ts_code IN ({code_placeholders})
            ORDER BY d.ts_code, d.trade_date
            """,
            conn,
            params=[*dates, *liquid_codes],
        )

    if frame.empty:
        return {"date": display_trade_date(current), "rows": []}
    rows = _score_candidates(frame, current, limit)
    return {"date": display_trade_date(current), "raw_date": current, "rows": rows}


def _stock_indicator_analysis(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    last = frame.iloc[-1]
    close = float(last["close"])
    ma20 = float(last["ma20"])
    ma60 = float(last["ma60"])
    trend_status = "强趋势" if close > ma20 > ma60 else "趋势修复" if close > ma20 else "趋势偏弱" if close < ma60 else "震荡观察"
    trend_hint = (
        "收盘价位于MA20和MA60上方，趋势过滤偏积极。"
        if trend_status == "强趋势"
        else "收盘价重新站上MA20，但中期趋势仍需确认。"
        if trend_status == "趋势修复"
        else "收盘价低于MA60，左侧信号需要更谨慎。"
        if trend_status == "趋势偏弱"
        else "价格处在均线之间，适合等待方向选择。"
    )
    recent = frame.tail(10)
    structure_flags = []
    if bool(recent["macd_bottom_divergence"].any()):
        structure_flags.append({"type": "bottom_divergence", "label": "MACD底背离", "hint": "价格创新低但DIF未同步创新低，只作为止跌观察。"})
    if bool(recent["macd_top_divergence"].any()):
        structure_flags.append({"type": "top_divergence", "label": "MACD顶背离", "hint": "价格创新高但DIF未同步创新高，警惕动能衰减。"})
    if bool(recent["macd_bottom_passivation"].any()):
        structure_flags.append({"type": "bottom_passivation", "label": "底钝化", "hint": "MACD仍偏弱但柱线改善，等待结构确认。"})
    if bool(recent["macd_top_passivation"].any()):
        structure_flags.append({"type": "top_passivation", "label": "顶钝化", "hint": "MACD仍偏强但柱线走弱，追高要谨慎。"})
    return {
        "trend": {
            "status": trend_status,
            "hint": trend_hint,
            "ma20": _safe_float(ma20),
            "ma60": _safe_float(ma60),
            "distance_ma20_pct": _safe_float((close / ma20 - 1) * 100 if ma20 else None),
            "distance_ma60_pct": _safe_float((close / ma60 - 1) * 100 if ma60 else None),
        },
        "structure": structure_flags,
        "fibonacci": _fibonacci_analysis(frame),
        "time_windows": _fibonacci_time_windows(frame),
    }


def _fibonacci_analysis(frame: pd.DataFrame, lookback: int = 120) -> dict[str, Any]:
    window = frame.tail(min(lookback, len(frame))).reset_index(drop=True)
    if len(window) < 20:
        return {"levels": []}
    low_idx = int(window["low"].idxmin())
    high_idx = int(window["high"].idxmax())
    swing_low = float(window.loc[low_idx, "low"])
    swing_high = float(window.loc[high_idx, "high"])
    current = float(window.iloc[-1]["close"])
    if swing_high <= swing_low:
        return {"levels": []}
    up_swing = low_idx < high_idx
    span = swing_high - swing_low
    ratios = [0.236, 0.382, 0.5, 0.618]
    levels = []
    for ratio in ratios:
        price = swing_high - span * ratio if up_swing else swing_low + span * ratio
        levels.append({"ratio": ratio, "label": f"{ratio * 100:.1f}%", "price": _safe_float(price), "distance_pct": _safe_float((current / price - 1) * 100 if price else None)})
    nearest = min(levels, key=lambda item: abs(item["distance_pct"] or 999))
    return {
        "direction": "上涨回调" if up_swing else "下跌反弹",
        "start_date": window.loc[low_idx if up_swing else high_idx, "date"],
        "end_date": window.loc[high_idx if up_swing else low_idx, "date"],
        "low": _safe_float(swing_low),
        "high": _safe_float(swing_high),
        "levels": levels,
        "nearest": nearest,
        "hint": f"当前最接近{nearest['label']}斐波那契位，仅作支撑/压力参考。",
    }


def _fibonacci_time_windows(frame: pd.DataFrame, lookback: int = 120) -> list[dict[str, Any]]:
    window = frame.tail(min(lookback, len(frame))).reset_index(drop=True)
    if len(window) < 20:
        return []
    pivot_idx = int(window["low"].idxmin())
    current_bars = len(window) - 1 - pivot_idx
    result = []
    for fib in [5, 8, 13, 21, 34, 55, 89]:
        distance = current_bars - fib
        if abs(distance) <= 3:
            result.append({"window": fib, "distance": distance, "hint": "接近斐波那契时间窗口，观察是否变盘，不单独作为交易信号。"})
    return result


def _dashboard_review_date(value: str | None, ctx: ApiContext) -> str:
    normalized = normalize_trade_date(value)
    if normalized:
        return display_trade_date(normalized)
    with connect(ctx.db_path) as conn:
        latest = latest_trade_date(conn)
    return display_trade_date(latest) if latest else date.today().isoformat()


def _review_archive_path(ctx: ApiContext) -> Path:
    return ctx.repo_root / "database" / "review_cache.db"


def _connect_review_archive(ctx: ApiContext) -> sqlite3.Connection:
    path = _review_archive_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_review_archive (
            review_date TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            generated_at TEXT,
            updated_at TEXT NOT NULL,
            cache_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    return conn


def _load_daily_review_archive(ctx: ApiContext, review_date: str) -> dict[str, Any] | None:
    with _connect_review_archive(ctx) as conn:
        row = conn.execute(
            """
            SELECT payload_json, generated_at, updated_at, cache_version
            FROM daily_review_archive
            WHERE review_date = ?
            """,
            (review_date,),
        ).fetchone()
    if not row:
        return None
    if int(row["cache_version"] or 0) < REVIEW_CACHE_VERSION:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except json.JSONDecodeError:
        return None
    payload["archive"] = {
        "status": "archived",
        "database": str(_review_archive_path(ctx)),
        "generated_at": row["generated_at"],
        "updated_at": row["updated_at"],
        "cache_version": row["cache_version"],
    }
    return payload


def _save_daily_review_archive(ctx: ApiContext, review_date: str, payload: dict[str, Any]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _connect_review_archive(ctx) as conn:
        conn.execute(
            """
            INSERT INTO daily_review_archive(review_date, payload_json, generated_at, updated_at, cache_version)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(review_date) DO UPDATE SET
                payload_json = excluded.payload_json,
                generated_at = excluded.generated_at,
                updated_at = excluded.updated_at,
                cache_version = excluded.cache_version
            """,
            (
                review_date,
                json.dumps(payload, ensure_ascii=False, default=str),
                payload.get("generated_at"),
                now,
                REVIEW_CACHE_VERSION,
            ),
        )
        conn.commit()


def _ensure_hotspot_cache(ctx: ApiContext, review_date: str, refresh: bool = False) -> None:
    normalized_dir = ctx.repo_root / "data" / "daily" / review_date / "normalized"
    raw_dir = ctx.repo_root / "data" / "daily" / review_date / "raw"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    hotspot_path = normalized_dir / "hotspot_summary.json"
    events_path = normalized_dir / "news_events.json"
    if not refresh and hotspot_path.exists() and events_path.exists():
        return

    client = MxHotspotClient(ctx.repo_root)
    records: list[dict[str, Any]] = []
    hotspot_result = client.market_hotspot(f"{review_date} A股市场热点、热门板块、热门股票、复盘摘要")
    if hotspot_result.ok:
        raw_path = promote_text_artifact(hotspot_result.raw_path, f"daily_review_hotspot_{review_date}")
        target = raw_dir / "hotspot_summary.txt"
        target.write_text(hotspot_result.content, encoding="utf-8")
        payload = {
            "date": review_date,
            "source": hotspot_result.source,
            "content": hotspot_result.content,
            "excerpt": _excerpt(hotspot_result.content, 800),
            "raw_file": str(raw_path or target),
        }
        hotspot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append({"name": "hotspot_summary", "ok": True, "row_count": 1, "source": hotspot_result.source, "normalized_json": str(hotspot_path), "raw_files": [str(raw_path or target)]})
    else:
        records.append({"name": "hotspot_summary", "ok": False, "source": hotspot_result.source, "error": hotspot_result.error or "unknown error"})

    news_result = client.finance_search(f"{review_date} A股 今日核心事件 政策 产业 新闻 热点 板块")
    if news_result.ok:
        raw_path = promote_text_artifact(news_result.raw_path, f"daily_review_events_{review_date}")
        target = raw_dir / "news_events.txt"
        target.write_text(news_result.content, encoding="utf-8")
        payload = {
            "date": review_date,
            "source": news_result.source,
            "content": news_result.content,
            "excerpt": _excerpt(news_result.content, 1000),
            "raw_file": str(raw_path or target),
        }
        events_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append({"name": "news_events", "ok": True, "row_count": 1, "source": news_result.source, "normalized_json": str(events_path), "raw_files": [str(raw_path or target)]})
    else:
        records.append({"name": "news_events", "ok": False, "source": news_result.source, "error": news_result.error or "unknown error"})
    _append_manifest_records(ctx.repo_root / "data" / "daily" / review_date / "manifest.json", records)


def _append_manifest_records(path: Path, records: list[dict[str, Any]]) -> None:
    manifest = _read_json(path, default={"generated_at": datetime.now().isoformat(timespec="seconds"), "datasets": []})
    existing = {item.get("name"): item for item in manifest.get("datasets", []) if isinstance(item, dict)}
    for record in records:
        existing[record["name"]] = record
    manifest["datasets"] = list(existing.values())
    manifest["generated_at"] = datetime.now().isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _daily_review_sources(manifest: dict[str, Any], extra_sqlite: bool = False) -> list[dict[str, Any]]:
    rows = []
    if extra_sqlite:
        rows.append({"name": "sqlite_market", "ok": True, "source": "sqlite", "label": "本地行情数据库"})
    for item in manifest.get("datasets", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "name": item.get("name"),
                "ok": bool(item.get("ok")),
                "source": item.get("source") or "-",
                "row_count": item.get("row_count", 0),
                "error": item.get("error"),
            }
        )
    return rows


def _daily_review_missing(manifest: dict[str, Any], hotspot: Any, news_events: Any) -> list[dict[str, str]]:
    expected = {
        "index_snapshot": "指数行情",
        "market_breadth": "市场宽度",
        "sector_top_gainers": "板块涨幅榜",
        "stock_top_gainers": "个股涨幅榜",
        "stock_top_turnover": "成交额榜",
        "concentration_metrics": "集中度",
        "industry_top50_turnover": "Top50行业分布",
    }
    by_name = {item.get("name"): item for item in manifest.get("datasets", []) if isinstance(item, dict)}
    missing = [
        {"name": name, "label": label, "reason": by_name.get(name, {}).get("error") or "缓存缺失或数据源未返回"}
        for name, label in expected.items()
        if not by_name.get(name, {}).get("ok")
    ]
    if not hotspot:
        missing.append({"name": "hotspot_summary", "label": "热点摘要", "reason": "热点 skill 暂未返回或未缓存"})
    if not news_events:
        missing.append({"name": "news_events", "label": "核心事件", "reason": "资讯搜索 skill 暂未返回或未缓存"})
    missing.extend(
        [
            {"name": "ddx", "label": "DDX/主力资金", "reason": "当前未接入主力资金数据源，不参与结论"},
            {"name": "northbound", "label": "北向资金", "reason": "当前未接入稳定北向资金数据源，不参与结论"},
            {"name": "dragon_tiger", "label": "龙虎榜", "reason": "当前未接入龙虎榜数据源，不参与结论"},
            {"name": "seal_rate", "label": "涨停封板率", "reason": "当前没有炸板/封单明细，不参与结论"},
        ]
    )
    return missing


def _market_summary(overview: dict[str, Any], indexes: list[dict[str, Any]]) -> str:
    up = overview.get("up") or 0
    down = overview.get("down") or 0
    amount = overview.get("total_amount_yi")
    strongest = None
    if indexes:
        strongest = max(indexes, key=lambda row: _safe_float(row.get("pct_change")) or -999)
    index_text = f"，{strongest.get('name')}领涨 {strongest.get('pct_change')}%" if strongest else ""
    if up > down * 1.3:
        return f"上涨家数明显多于下跌家数，市场宽度偏积极{index_text}；全市场成交额约 {_fmt_number(amount)} 亿。"
    if down > up * 1.2:
        return f"下跌家数占优，赚钱效应偏弱{index_text}；全市场成交额约 {_fmt_number(amount)} 亿。"
    return f"涨跌家数接近，市场处于结构性分化{index_text}；全市场成交额约 {_fmt_number(amount)} 亿。"


def _concentration_context(latest: dict[str, Any] | None) -> str:
    if not latest:
        return "等待集中度数据加载。"
    cr10 = latest.get("cr10_pct") or 0
    cr50 = latest.get("cr50_pct") or 0
    effective = latest.get("effective_count")
    if cr50 >= 30 or cr10 >= 15:
        return f"成交额向头部集中，CR10 {cr10:.2f}%，CR50 {cr50:.2f}%，追高拥挤风险上升。"
    if effective and effective >= 80:
        return f"有效股票数约 {effective:.0f}，资金分布较宽，适合观察热点扩散而非只盯龙头。"
    return f"CR10 {cr10:.2f}%，CR50 {cr50:.2f}%，资金集中度处在可观察区间。"


def _industry_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无行业成交分布缓存。"
    top = rows[0]
    return f"{top.get('industry', '头部行业')} 占 Top50 成交约 {top.get('ratio', '-')}，代表股票：{top.get('stocks', '-')}。"


def _secondary_industry_rows(rows: list[dict[str, Any]], review_date: str) -> list[dict[str, Any]]:
    normalized = _normalize_turnover_rows(rows, review_date)[:50]
    total = sum(float(row.get("amount_yi") or 0) for row in normalized)
    if total <= 0:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        industry = str(row.get("industry") or "")
        parts = [part for part in industry.split("-") if part]
        secondary = parts[1] if len(parts) >= 2 else parts[0] if parts else "未分类"
        primary = parts[0] if parts else "未分类"
        row["primary_industry"] = primary
        row["secondary_industry"] = secondary
        groups.setdefault(secondary, []).append(row)
    result = []
    for secondary, items in groups.items():
        amount = sum(float(item.get("amount_yi") or 0) for item in items)
        weights = [float(item.get("amount_yi") or 0) / amount for item in items if amount > 0]
        hhi = sum(weight * weight for weight in weights) * 100 if weights else None
        leaders = sorted(items, key=lambda item: float(item.get("amount_yi") or 0), reverse=True)[:3]
        result.append(
            {
                "secondary_industry": secondary,
                "primary_industry": items[0].get("primary_industry") or "",
                "count": len(items),
                "amount_yi": _safe_float(amount),
                "ratio_pct": _safe_float(amount / total * 100),
                "hhi": _safe_float(hhi),
                "concentration": _hhi_label(hhi),
                "leaders": " · ".join(
                    f"{item.get('name')}({item.get('change_pct'):+.2f}%)"
                    if isinstance(item.get("change_pct"), (int, float))
                    else str(item.get("name") or "-")
                    for item in leaders
                ),
            }
        )
    return sorted(result, key=lambda item: float(item.get("amount_yi") or 0), reverse=True)


def _hhi_label(value: float | None) -> str:
    if value is None:
        return "待判断"
    if value >= 90:
        return "单票驱动"
    if value >= 50:
        return "双寡头"
    if value >= 20:
        return "偏集中"
    if value >= 12:
        return "较均衡"
    return "均衡"


def _sector_rotation_payload(
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    top_gainers: list[dict[str, Any]],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    previous_by_name = {str(row.get("secondary_industry")): row for row in previous_rows}
    current_by_name = {str(row.get("secondary_industry")): row for row in current_rows}
    combined_names = set(previous_by_name) | set(current_by_name)
    changes = []
    for name in combined_names:
        current = current_by_name.get(name)
        previous = previous_by_name.get(name)
        current_amount = _safe_float((current or {}).get("amount_yi")) or 0
        previous_amount = _safe_float((previous or {}).get("amount_yi")) or 0
        if current_amount <= 0 and previous_amount <= 0:
            continue
        change_pct = (current_amount / previous_amount - 1) * 100 if previous_amount > 0 else None
        direction = "流入" if current_amount > previous_amount else "流出"
        trend = (
            "新晋" if previous_amount <= 0 and current_amount > 0 else
            "退出" if current_amount <= 0 and previous_amount > 0 else
            "激增" if change_pct is not None and change_pct >= 30 else
            "增持" if change_pct is not None and change_pct >= 5 else
            "持平" if change_pct is not None and change_pct > -5 else
            "退潮"
        )
        changes.append(
            {
                "sector": name,
                "current_amount_yi": current_amount or None,
                "previous_amount_yi": previous_amount or None,
                "change_pct": _safe_float(change_pct),
                "direction": direction,
                "trend": trend,
                "driver": _rotation_driver(current or previous or {}, change_pct),
                "strength": _rotation_strength(change_pct, current or {}),
                "meaning": _rotation_meaning(name, trend, current or {}),
            }
        )
    changes.sort(key=lambda row: abs(float(row.get("change_pct") or 0)) if row.get("change_pct") is not None else 999, reverse=True)
    inflows = [row for row in changes if row["direction"] == "流入"][:3]
    outflows = [row for row in changes if row["direction"] == "流出"][:3]
    momentum = sorted(changes, key=lambda row: float(row.get("current_amount_yi") or 0), reverse=True)[:8]
    concept_rows = _concept_rows_from_gainers(top_gainers)[:8]
    signals = _rotation_signals(changes)
    style_rows = _style_judgement(comparison, current_rows, changes)
    return {
        "migration": [*inflows, *outflows],
        "style": style_rows,
        "momentum": momentum,
        "concepts": concept_rows,
        "signals": signals,
        "summary": _rotation_summary(changes),
    }


def _rotation_driver(row: dict[str, Any], change_pct: float | None) -> str:
    leaders = str(row.get("leaders") or "")
    if change_pct is None:
        return f"{leaders} 新进入 Top50 成交结构" if leaders else "新进入 Top50 成交结构"
    if change_pct >= 30:
        return f"{leaders} 带动成交额激增" if leaders else "成交额显著放大"
    if change_pct <= -30:
        return f"{leaders} 热度回落" if leaders else "成交额明显退潮"
    return f"{leaders} 维持活跃" if leaders else "成交额变化温和"


def _rotation_strength(change_pct: float | None, row: dict[str, Any]) -> str:
    hhi = _safe_float(row.get("hhi"))
    if change_pct is None or change_pct >= 30:
        return "强"
    if change_pct >= 5 and (hhi is None or hhi < 30):
        return "中强"
    if change_pct <= -20:
        return "弱"
    return "中等"


def _rotation_meaning(name: str, trend: str, row: dict[str, Any]) -> str:
    hhi = _safe_float(row.get("hhi"))
    if trend in {"激增", "新晋"}:
        return "资金加速流入，观察次日能否延续"
    if trend == "增持" and (hhi is None or hhi < 20):
        return "板块内较均衡，扩散质量较好"
    if trend == "退潮":
        return "成交额退潮，短线热度下降"
    if hhi and hhi >= 50:
        return "依赖少数股票，持续性需要确认"
    return f"{name}维持活跃，继续观察成交额排名"


def _concept_rows_from_gainers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows[:12]:
        concept_text = str(row.get("概念") or "")
        concepts = [item for item in concept_text.split("、") if item][:2]
        name = _clean_name(row.get("名称") or row.get("股票简称"))
        date_key = ""
        for key in row:
            if str(key).startswith("涨跌幅(%) "):
                date_key = str(key)
                break
        change = _safe_float(row.get(date_key))
        result.append(
            {
                "concept": "+".join(concepts) if concepts else _clean_name(row.get("申万行业分类") or "热门概念"),
                "stock": name,
                "change_pct": change,
                "driver": "涨幅居前，结合概念/行业观察持续性",
            }
        )
    return result


def _rotation_signals(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inflow = [row for row in changes if row.get("direction") == "流入"]
    outflow = [row for row in changes if row.get("direction") == "流出"]
    top_inflow = ", ".join(row["sector"] for row in inflow[:2]) or "-"
    top_outflow = ", ".join(row["sector"] for row in outflow[:2]) or "-"
    return [
        {"type": "加速上行", "sector": top_inflow, "strength": "强" if inflow and (inflow[0].get("change_pct") is None or (inflow[0].get("change_pct") or 0) > 20) else "中等", "meaning": "资金加速流入，若 HHI 低则上涨更可能扩散。"},
        {"type": "高位退潮", "sector": top_outflow, "strength": "中等", "meaning": "前期热点成交额下降，观察是否转向防守或新主线。"},
        {"type": "新晋方向", "sector": ", ".join(row["sector"] for row in changes if row.get("trend") == "新晋") or "-", "strength": "待确认", "meaning": "新进 Top50 的方向需要次日继续确认。"},
    ]


def _style_judgement(comparison: dict[str, Any], current_rows: list[dict[str, Any]], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    up_delta = _safe_float(comparison.get("up_count_delta"))
    down_delta = _safe_float(comparison.get("down_count_delta"))
    top_sector = current_rows[0] if current_rows else {}
    top_name = top_sector.get("secondary_industry") or "-"
    top_primary = top_sector.get("primary_industry") or "-"
    return [
        {"dimension": "大小盘", "judgement": "权重/大成交占优" if down_delta and down_delta > 0 else "扩散观察", "evidence": f"上涨家数变化 {up_delta if up_delta is not None else '-'}，下跌家数变化 {down_delta if down_delta is not None else '-'}。"},
        {"dimension": "成长/价值", "judgement": "成长方向更活跃" if top_primary in {"电子", "通信", "计算机", "机械设备"} else "风格待确认", "evidence": f"Top50 成交额第一方向为 {top_name} / {top_primary}。"},
        {"dimension": "防御/进攻", "judgement": "进攻主导" if top_primary not in {"银行", "煤炭", "公用事业"} else "防御占优", "evidence": "观察 Top50 是否由科技/成长/高弹性方向主导。"},
        {"dimension": "新旧能源", "judgement": "新能源偏弱" if any(row.get("sector") in {"电池", "光伏设备"} and row.get("direction") == "流出" for row in changes) else "新能源待确认", "evidence": "电池/光伏设备若成交额下降，说明资金可能切往其他主线。"},
    ]


def _rotation_summary(changes: list[dict[str, Any]]) -> str:
    inflow = [row for row in changes if row.get("direction") == "流入"]
    outflow = [row for row in changes if row.get("direction") == "流出"]
    inflow_text = "、".join(row["sector"] for row in inflow[:3]) or "暂无明显流入"
    outflow_text = "、".join(row["sector"] for row in outflow[:3]) or "暂无明显流出"
    return f"资金流入方向：{inflow_text}；流出方向：{outflow_text}。该判断来自 Top50 成交额二级板块环比，不包含主力净流入/DDX。"


def _sentiment_from_review(overview: dict[str, Any], concentration: dict[str, Any] | None, indexes: list[dict[str, Any]]) -> dict[str, Any]:
    up = float(overview.get("up") or 0)
    down = float(overview.get("down") or 0)
    total = max(1.0, up + down + float(overview.get("flat") or 0))
    up_score = min(100, max(0, up / total * 100))
    limit_score = min(100, (float(overview.get("limit_up_like") or 0) / max(1, float(overview.get("limit_down_like") or 0))) * 12)
    median = _safe_float(overview.get("median_change_pct")) or 0
    median_score = min(100, max(0, 50 + median * 12))
    index_score = 50.0
    if indexes:
        changes = [_safe_float(row.get("pct_change")) for row in indexes]
        valid = [item for item in changes if item is not None]
        if valid:
            index_score = min(100, max(0, 50 + sum(valid) / len(valid) * 12))
    cr50 = (concentration or {}).get("cr50_pct")
    concentration_penalty = 8 if cr50 and cr50 >= 28 else 0
    score = max(0, min(100, up_score * 0.35 + limit_score * 0.2 + median_score * 0.25 + index_score * 0.2 - concentration_penalty))
    label = "偏乐观" if score >= 65 else "偏悲观" if score <= 40 else "中性分化"
    return {
        "value": _safe_float(score),
        "label": label,
        "summary": f"情绪温度约 {score:.0f}/100，判断为{label}。该分数由涨跌家数、类涨停跌停、涨跌幅中位数、指数表现和集中度综合得到，不包含 DDX/北向资金。",
        "items": [
            {"label": "上涨占比", "value": _safe_float(up / total * 100), "unit": "%"},
            {"label": "类涨停", "value": overview.get("limit_up_like"), "unit": "家"},
            {"label": "涨跌幅中位数", "value": overview.get("median_change_pct"), "unit": "%"},
            {"label": "集中度惩罚", "value": concentration_penalty, "unit": "分"},
        ],
    }


def _liquidity_metrics(
    overview: dict[str, Any],
    top_turnover: list[dict[str, Any]],
    previous_overview: dict[str, Any] | None = None,
    previous_turnover: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized = _normalize_turnover_rows(top_turnover, overview.get("date") or "")
    previous_normalized = _normalize_turnover_rows(previous_turnover or [], previous_overview.get("date") if previous_overview else "")
    amounts = [row["amount_yi"] for row in normalized if row.get("amount_yi") is not None]
    previous_amounts = [row["amount_yi"] for row in previous_normalized if row.get("amount_yi") is not None]
    current_total = _safe_float(overview.get("total_amount_yi"))
    previous_total = _safe_float((previous_overview or {}).get("total_amount_yi"))
    top50_avg = _safe_float(sum(amounts[:50]) / len(amounts[:50])) if amounts[:50] else None
    previous_top50_avg = _safe_float(sum(previous_amounts[:50]) / len(previous_amounts[:50])) if previous_amounts[:50] else None
    max_row = max(normalized, key=lambda row: float(row.get("amount_yi") or 0), default={})
    min_top50 = min(amounts[:50]) if amounts[:50] else None
    return [
        {"label": "全市场成交额", "today": current_total, "previous": previous_total, "change_pct": _pct_change(current_total, previous_total), "unit": "亿", "judgement": "放量" if (current_total or 0) > (previous_total or 0) else "缩量"},
        {"label": "Top50平均成交额", "today": top50_avg, "previous": previous_top50_avg, "change_pct": _pct_change(top50_avg, previous_top50_avg), "unit": "亿", "judgement": "头部吸金" if (top50_avg or 0) > (previous_top50_avg or 0) else "头部降温"},
        {"label": f"最大成交({max_row.get('name') or '-'})", "today": max_row.get("amount_yi"), "previous": None, "change_pct": None, "unit": "亿", "judgement": "高流动性"},
        {"label": "最小成交(Top50)", "today": _safe_float(min_top50), "previous": None, "change_pct": None, "unit": "亿", "judgement": "中等" if min_top50 and min_top50 >= 30 else "偏低"},
    ]


def _normalize_turnover_rows(rows: list[dict[str, Any]], review_date: str) -> list[dict[str, Any]]:
    date_key = review_date.replace("-", ".")
    result = []
    for index, row in enumerate(rows, start=1):
        amount = _amount_to_yi(_find_by_prefix(row, f"成交额(元) {date_key}") or _find_by_prefix(row, "成交额"))
        result.append(
            {
                "rank": _safe_float(row.get("序号")) or index,
                "code": _clean_name(row.get("代码")),
                "name": _clean_name(row.get("名称") or row.get("股票简称")),
                "change_pct": _safe_float(_find_by_prefix(row, f"涨跌幅(%) {date_key}") or _find_by_prefix(row, "涨跌幅")),
                "amount_yi": amount,
                "industry": _clean_name(row.get("申万行业分类") or row.get("东财行业总分类")),
            }
        )
    return result


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return _safe_float((current / previous - 1) * 100)


def _sentiment_dashboard(
    overview: dict[str, Any],
    previous_overview: dict[str, Any],
    concentration: dict[str, Any] | None,
    indexes: list[dict[str, Any]],
    sentiment: dict[str, Any],
) -> list[dict[str, Any]]:
    up = overview.get("up") or 0
    down = overview.get("down") or 0
    limit_up = overview.get("limit_up_like") or 0
    limit_down = overview.get("limit_down_like") or 0
    index_changes = [_safe_float(row.get("pct_change")) for row in indexes]
    valid_index_changes = [item for item in index_changes if item is not None]
    avg_index = sum(valid_index_changes) / len(valid_index_changes) if valid_index_changes else None
    market_turnover = _safe_float(overview.get("total_amount_yi"))
    previous_turnover = _safe_float(previous_overview.get("total_amount_yi")) if previous_overview else None
    cr50 = _safe_float((concentration or {}).get("cr50_pct"))
    return [
        {"dimension": "市场广度", "metric": "涨跌比", "value": f"{up}/{down} = {up / down:.2f}" if down else "-", "score": _score_text(10 if up > down else 2 if down > up * 1.2 else 5), "sentiment": "乐观" if up > down else "悲观"},
        {"dimension": "市场广度", "metric": "涨停/跌停", "value": f"{limit_up}/{limit_down} = {limit_up / max(1, limit_down):.1f}", "score": _score_text(8 if limit_up > limit_down * 2 else 5), "sentiment": "偏乐观" if limit_up > limit_down else "中性"},
        {"dimension": "市场广度", "metric": "指数涨幅", "value": f"平均 {avg_index:.2f}%" if avg_index is not None else "-", "score": _score_text(8 if avg_index and avg_index > 0 else 3), "sentiment": "乐观" if avg_index and avg_index > 0 else "悲观"},
        {"dimension": "资金态度", "metric": "DDX", "value": "未接入", "score": "-", "sentiment": "不参与"},
        {"dimension": "资金态度", "metric": "成交额", "value": f"{market_turnover:.2f}亿({(_pct_change(market_turnover, previous_turnover) or 0):+.1f}%)" if market_turnover else "-", "score": _score_text(7 if (market_turnover or 0) > (previous_turnover or 0) else 4), "sentiment": "偏乐观" if (market_turnover or 0) > (previous_turnover or 0) else "偏谨慎"},
        {"dimension": "成交热度", "metric": "Top50/全市场", "value": f"{cr50:.1f}%" if cr50 is not None else "-", "score": _score_text(7 if cr50 and cr50 >= 20 else 5), "sentiment": "偏高" if cr50 and cr50 >= 20 else "中性"},
        {"dimension": "综合", "metric": "情绪温度", "value": f"{sentiment.get('value'):.0f}/100" if sentiment.get("value") is not None else "-", "score": _score_text(round((sentiment.get("value") or 0) / 10)), "sentiment": sentiment.get("label") or "-"},
    ]


def _score_text(value: int | float | str) -> str:
    if value == "-":
        return "-"
    numeric = max(0, min(10, int(value)))
    return f"{numeric}/10"


def _event_rows(hotspot: Any, news_events: Any, top_gainers: list[dict[str, Any]], secondary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in top_gainers[:3]:
        name = _clean_name(item.get("名称") or item.get("股票简称"))
        change_key = next((key for key in item if str(key).startswith("涨跌幅(%) ")), "")
        industry = _clean_name(item.get("申万行业分类") or item.get("东财行业总分类"))
        rows.append(
            {
                "event": f"{name}涨幅居前",
                "description": f"{name} 当日涨跌幅 {_safe_float(item.get(change_key)):+.2f}%，成交和概念热度靠前。" if change_key else f"{name} 位于涨幅榜前列。",
                "impact": industry,
                "signal": "强催化",
            }
        )
    if secondary_rows:
        top = secondary_rows[0]
        rows.append(
            {
                "event": f"{top.get('secondary_industry')}成交额居前",
                "description": f"Top50 中 {top.get('secondary_industry')} 上榜 {top.get('count')} 只，成交额 {top.get('amount_yi')} 亿。",
                "impact": f"{top.get('primary_industry')} · {top.get('secondary_industry')}",
                "signal": top.get("concentration") or "主题活跃",
            }
        )
    return rows[:6]


def _news_event_items(news_events: Any) -> list[dict[str, Any]]:
    content = str((news_events or {}).get("content") or (news_events or {}).get("excerpt") or "")
    if not content:
        return []
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return [{"title": "资讯摘要", "content": _excerpt(content, 500), "source": (news_events or {}).get("source") or "mx-finance-search"}]
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, list):
        return [{"title": "资讯摘要", "content": _excerpt(content, 500), "source": (news_events or {}).get("source") or "mx-finance-search"}]
    rows = []
    for item in data[:5]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "title": _clean_name(item.get("title") or item.get("name") or "资讯"),
                "content": _excerpt(str(item.get("content") or item.get("summary") or ""), 320),
                "source": _clean_name(item.get("source") or item.get("insName") or (news_events or {}).get("source") or "mx-finance-search"),
            }
        )
    return rows


def _event_summary(hotspot: Any, news_events: Any) -> str:
    if hotspot and hotspot.get("excerpt"):
        return hotspot["excerpt"]
    if news_events and news_events.get("excerpt"):
        return news_events["excerpt"]
    return "热点/事件数据暂未接入成功，本模块只展示缺口，不参与结论。"


def _action_boundaries(
    regime: dict[str, Any],
    sentiment: dict[str, Any],
    concentration: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
) -> list[dict[str, str]]:
    score = sentiment.get("value") or 50
    cr50 = (concentration or {}).get("cr50_pct") or 0
    focus = candidates[:4]
    items = [{"direction": "买入", "target": "—", "action": "无新买入信号，等待策略确认。", "rating": "—"}]
    for candidate in focus[:2]:
        items.append(
            {
                "direction": "关注",
                "target": f"{candidate.get('code')} {candidate.get('name')}",
                "action": "观察成交额排名、回踩承接和技术指标是否同步确认。",
                "rating": candidate.get("action_hint") or "等待确认",
            }
        )
    for candidate in focus[2:4]:
        items.append(
            {
                "direction": "持有/观察",
                "target": f"{candidate.get('code')} {candidate.get('name')}",
                "action": "若已在模拟观察池，优先跟踪风险标签和次日承接，不追高加仓。",
                "rating": candidate.get("group") or "观察",
            }
        )
    items.append({"direction": "减仓", "target": "—", "action": "维持学习仓位，不在高集中度或情绪分化时扩大假设仓位。", "rating": "防守" if cr50 >= 28 or score < 50 else "等待"})
    if cr50 >= 28:
        items.append({"direction": "风险", "target": "高位头部股", "action": "CR50偏高，优先等回踩和次日承接确认。", "rating": "防守"})
    return items


def _action_warning(regime: dict[str, Any], sentiment: dict[str, Any], concentration: dict[str, Any] | None) -> str:
    cr50 = (concentration or {}).get("cr50_pct")
    return (
        f"方向判断：{regime.get('label') or '结构行情'}，情绪为{sentiment.get('label') or '待判断'}。"
        f" CR50 {cr50:.2f}%。" if isinstance(cr50, (int, float)) else
        f"方向判断：{regime.get('label') or '结构行情'}，情绪为{sentiment.get('label') or '待判断'}。"
    ) + " 当前建议用于学习复盘，不作为实盘买卖指令；缺失 DDX/北向资金时更应降低确定性。"


def _daily_review_conclusions(
    overview: dict[str, Any],
    concentration: dict[str, Any] | None,
    regime: dict[str, Any],
    industry_rows: list[dict[str, Any]],
    sentiment: dict[str, Any],
    missing: list[dict[str, str]],
) -> list[str]:
    conclusions = [
        f"市场状态：{regime.get('label') or overview.get('risk_level') or '待判断'}，情绪为{sentiment.get('label')}。",
        _concentration_context(concentration),
        _industry_summary(industry_rows),
        "DDX、北向资金、龙虎榜、封板率当前未接入，不用于本次结论。",
    ]
    if missing:
        conclusions.append(f"仍有 {len(missing)} 项数据缺口，阅读时以已标注来源的模块为准。")
    return conclusions


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _find_by_prefix(row: dict[str, Any], prefix: str) -> Any:
    for key, value in row.items():
        if str(key).startswith(prefix):
            return value
    return None


def _amount_to_yi(value: Any) -> float | None:
    text = _clean_name(value).replace(",", "")
    if not text or text == "-":
        return None
    multiplier = 1.0
    if text.endswith("万亿"):
        text = text[:-2]
        multiplier = 10000.0
    elif text.endswith("亿"):
        text = text[:-1]
        multiplier = 1.0
    elif text.endswith("万"):
        text = text[:-1]
        multiplier = 0.0001
    elif text.endswith("元"):
        text = text[:-1]
        multiplier = 0.00000001
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _excerpt(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    return compact[:limit]


def _fmt_number(value: Any) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        return "-"
    return f"{numeric:.2f}"


def reports_index(ctx: ApiContext | None = None) -> list[dict[str, Any]]:
    ctx = ctx or context()
    report_dir = ctx.repo_root / "reports"
    result = []
    for path in sorted(report_dir.glob("*.md"), reverse=True):
        title = _first_markdown_title(path) or path.stem
        result.append({"id": path.stem, "title": title, "path": str(path), "type": _report_type(path.name)})
    return result


def report_detail(report_id: str, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    safe_id = Path(report_id).stem
    path = ctx.repo_root / "reports" / f"{safe_id}.md"
    if not path.exists():
        raise FileNotFoundError(safe_id)
    content = path.read_text(encoding="utf-8")
    return {"id": safe_id, "title": _first_markdown_title(path) or safe_id, "content": content}


def daily_review_dashboard(date: str | None = None, refresh: bool = False, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    review_date = _dashboard_review_date(date, ctx)
    if not refresh:
        archived = _load_daily_review_archive(ctx, review_date)
        if archived:
            return archived

    base_dir = ctx.repo_root / "data" / "daily" / review_date
    normalized_dir = base_dir / "normalized"

    if refresh or not (base_dir / "manifest.json").exists():
        generate_daily_review(
            DailyReviewConfig(
                review_date=review_date,
                use_live_data=True,
                force_refresh=refresh,
            )
        )

    _ensure_hotspot_cache(ctx, review_date, refresh=refresh)

    manifest = _read_json(base_dir / "manifest.json", default={"datasets": []})
    overview = market_overview(review_date, ctx)
    concentration = market_concentration(review_date, lookback=120, universe="top250", ctx=ctx)
    candidates = screen_candidates(review_date, limit=10, ctx=ctx)
    index_rows = _read_json(normalized_dir / "index_snapshot.json", default=[])
    breadth_rows = _read_json(normalized_dir / "market_breadth.json", default=[])
    sector_rows = _read_json(normalized_dir / "sector_top_gainers.json", default=[])
    top_gainers = _read_json(normalized_dir / "stock_top_gainers.json", default=[])
    top_turnover = _read_json(normalized_dir / "stock_top_turnover.json", default=[])
    industry_rows = _read_json(normalized_dir / "industry_top50_turnover.json", default=[])
    comparison = _read_json(normalized_dir / "daily_comparison.json", default={})
    previous_date = comparison.get("previous_date")
    previous_turnover = _read_json(ctx.repo_root / "data" / "daily" / str(previous_date) / "normalized" / "stock_top_turnover.json", default=[]) if previous_date else []
    previous_overview = market_overview(str(previous_date), ctx) if previous_date else {}
    regime = _read_json(normalized_dir / "market_regime.json", default={})
    hotspot = _read_json(normalized_dir / "hotspot_summary.json", default=None)
    news_events = _read_json(normalized_dir / "news_events.json", default=None)

    missing = _daily_review_missing(manifest, hotspot, news_events)
    data_sources = _daily_review_sources(manifest, extra_sqlite=True)
    sentiment = _sentiment_from_review(overview, concentration.get("latest"), index_rows)
    secondary_industries = _secondary_industry_rows(top_turnover, review_date)
    previous_secondary_industries = _secondary_industry_rows(previous_turnover, str(previous_date)) if previous_turnover and previous_date else []
    sector_rotation = _sector_rotation_payload(secondary_industries, previous_secondary_industries, top_gainers, comparison)
    conclusions = _daily_review_conclusions(overview, concentration.get("latest"), regime, industry_rows, sentiment, missing)

    payload = _json_ready(
        {
            "date": review_date,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "archive": {
                "status": "rebuilt" if refresh else "created",
                "database": str(_review_archive_path(ctx)),
            },
            "data_sources": data_sources,
            "missing_data": missing,
            "cache_paths": {
                "manifest": str(base_dir / "manifest.json"),
                "normalized": str(normalized_dir),
                "raw": str(base_dir / "raw"),
            },
            "sections": {
                "market": {
                    "title": "市场全景 KPI",
                    "skills": ["a-share-market-breadth", "a-share-sentiment"],
                    "source": "sqlite + mx-finance-data",
                    "overview": overview,
                    "indexes": index_rows,
                    "breadth": breadth_rows,
                    "summary": _market_summary(overview, index_rows),
                },
                "concentration": {
                    "title": "集中度风险仪表盘",
                    "skills": ["a-share-concentration-index", "a-share-concentration-risk"],
                    "source": "sqlite + backend-derived",
                    "latest": concentration.get("latest"),
                    "top": concentration.get("top", [])[:10],
                    "summary": _concentration_context(concentration.get("latest")),
                },
                "industries": {
                    "title": "板块 / 行业成交分布",
                    "skills": ["a-share-sector-rotation"],
                    "source": "mx-stocks-screener + backend-derived",
                    "sectors": sector_rows[:10],
                    "secondary_industries": secondary_industries[:10],
                    "industries": industry_rows[:10],
                    "summary": _industry_summary(industry_rows),
                },
                "rotation": {
                    "title": "资金轮动与板块切换",
                    "skills": ["a-share-sector-rotation"],
                    "source": "backend-derived Top50 comparison",
                    **sector_rotation,
                },
                "sentiment": {
                    "title": "资金与情绪",
                    "skills": ["a-share-sentiment", "a-share-liquidity-risk"],
                    "source": "sqlite + backend-derived",
                    "score": sentiment,
                    "dashboard": _sentiment_dashboard(overview, previous_overview, concentration.get("latest"), index_rows, sentiment),
                    "comparison": comparison,
                    "summary": sentiment["summary"],
                },
                "liquidity": {
                    "title": "流动性风险",
                    "skills": ["a-share-liquidity-risk"],
                    "source": "sqlite",
                    "metrics": _liquidity_metrics(overview, top_turnover, previous_overview, previous_turnover),
                    "top_turnover": _normalize_turnover_rows(top_turnover, review_date)[:10],
                },
                "events": {
                    "title": "今日核心事件",
                    "skills": ["stock-market-hotspot-discovery", "mx-finance-search"],
                    "source": "mx-skill/cache",
                    "hotspot": hotspot,
                    "news_events": news_events,
                    "items": _event_rows(hotspot, news_events, top_gainers, secondary_industries),
                    "news_items": _news_event_items(news_events),
                    "summary": _event_summary(hotspot, news_events),
                },
                "actions": {
                    "title": "操作边界",
                    "skills": ["综合研判"],
                    "source": "backend-derived",
                    "regime": regime,
                    "candidates": candidates.get("rows", []),
                    "items": _action_boundaries(regime, sentiment, concentration.get("latest"), candidates.get("rows", [])),
                    "warning": _action_warning(regime, sentiment, concentration.get("latest")),
                },
                "conclusions": {
                    "title": "核心结论",
                    "skills": ["综合研判"],
                    "source": "backend-derived",
                    "items": conclusions,
                },
            },
        }
    )
    _save_daily_review_archive(ctx, review_date, payload)
    payload["archive"] = {
        "status": "saved",
        "database": str(_review_archive_path(ctx)),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return payload


def learning_index(ctx: ApiContext | None = None) -> list[dict[str, Any]]:
    ctx = ctx or context()
    doc_dir = ctx.repo_root / "doc"
    rows = []
    for path in sorted(doc_dir.glob("*.md"), reverse=True) if doc_dir.exists() else []:
        rows.append({"id": path.stem, "title": _first_markdown_title(path) or path.stem, "path": str(path)})
    return rows


def learning_detail(learning_id: str, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    safe_id = Path(learning_id).stem
    path = ctx.repo_root / "doc" / f"{safe_id}.md"
    if not path.exists():
        raise FileNotFoundError(safe_id)
    content = path.read_text(encoding="utf-8")
    return {"id": safe_id, "title": _first_markdown_title(path) or safe_id, "content": content}


def strategy_backtests(ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    manifests = _technical_backtest_manifests(ctx, include_auto=False) or _technical_backtest_manifests(ctx)
    if not manifests:
        return {"runs": [], "latest": None, "summary": []}
    latest = manifests[0]
    summary_path = latest.parent / "normalized" / "summary.json"
    summary = pd.read_json(summary_path).to_dict("records") if summary_path.exists() else []
    return {
        "runs": [{"id": path.parent.name, "manifest": str(path)} for path in manifests],
        "latest": latest.parent.name,
        "summary": _json_ready(summary[:200]),
    }


def stock_strategy_detail(code: str, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    display = display_code(normalize_ts_code(code))
    manifests = _technical_backtest_manifests(ctx)
    for manifest in manifests:
        normalized = manifest.parent / "normalized"
        summary_path = normalized / "summary.json"
        trades_path = normalized / "trades.json"
        equity_path = normalized / "equity_curves.json"
        kline_path = normalized / f"kline_{display}.csv"
        if not summary_path.exists():
            continue
        summary = _records_for_code(summary_path, display)
        if not summary:
            continue
        trades = _records_for_code(trades_path, display) if trades_path.exists() else []
        summary = _augment_summary_with_first_entry_hold(summary, trades, kline_path)
        equity = _records_for_code(equity_path, display) if equity_path.exists() else []
        signals = _trade_execution_signals(trades)
        return {
            "code": display,
            "status": "ok",
            "message": "已读取最近一次技术回测结果。",
            "run": manifest.parent.name,
            "summary": _json_ready(summary),
            "trades": _json_ready(trades),
            "equity": _json_ready(equity),
            "signals": signals,
        }
    return {
        "code": display,
        "status": "not_in_latest_backtest",
        "message": "当前股票没有包含在最近一次技术回测股票池中，需要单独运行回测后才会有策略验证结果。",
        "run": None,
        "summary": [],
        "trades": [],
        "equity": [],
        "signals": {},
    }


def trigger_stock_backtest(code: str, ctx: ApiContext | None = None) -> dict[str, Any]:
    ctx = ctx or context()
    display = display_code(normalize_ts_code(code))
    detail = stock_strategy_detail(display, ctx)
    existing_strategies = {str(item.get("strategy")) for item in detail.get("summary", [])}
    if detail.get("status") == "ok" and set(STRATEGIES).issubset(existing_strategies):
        return {"code": display, "status": "ready", "message": "当前股票已有策略验证结果。"}
    with _BACKTEST_LOCK:
        job = _BACKTEST_JOBS.get(display)
        if job and job.get("status") in {"queued", "running"}:
            return {"code": display, **job}
        _BACKTEST_JOBS[display] = {"status": "queued", "message": "已加入后台回测队列。"}
    thread = threading.Thread(target=_run_stock_backtest_job, args=(display, ctx), daemon=True)
    thread.start()
    return {"code": display, **_BACKTEST_JOBS[display]}


def _run_stock_backtest_job(code: str, ctx: ApiContext) -> None:
    with _BACKTEST_LOCK:
        _BACKTEST_JOBS[code] = {"status": "running", "message": "正在基于本地 DB 生成单股策略回测。"}
    try:
        output = _generate_db_stock_backtest(code, ctx)
        with _BACKTEST_LOCK:
            _BACKTEST_JOBS[code] = {"status": "done", "message": "单股策略回测已完成。", "run": output.name}
    except Exception as exc:
        with _BACKTEST_LOCK:
            _BACKTEST_JOBS[code] = {"status": "failed", "message": f"{type(exc).__name__}: {exc}"}


def _generate_db_stock_backtest(code: str, ctx: ApiContext) -> Path:
    ts_code = normalize_ts_code(code)
    display = display_code(ts_code)
    with connect(ctx.db_path) as conn:
        end_raw = latest_trade_date(conn)
        if end_raw is None:
            raise ValueError("database has no daily_qfq rows")
        end_day = date.fromisoformat(display_trade_date(end_raw) or end_raw)
        start_day = _one_year_before(end_day)
        rows = conn.execute(
            """
            SELECT d.trade_date, d.open, d.high, d.low, d.close_qfq AS close, d.volume, d.amount, s.name
            FROM daily_qfq d
            LEFT JOIN stocks s ON s.ts_code = d.ts_code
            WHERE d.ts_code = ?
              AND d.trade_date BETWEEN ? AND ?
            ORDER BY d.trade_date
            """,
            (ts_code, start_day.strftime("%Y%m%d"), end_raw),
        ).fetchall()
    if len(rows) < 30:
        raise ValueError(f"not enough k-line rows for {display}")
    name = _clean_name(rows[0]["name"]) or display
    kline = pd.DataFrame(
        [
            {
                "date": display_trade_date(row["trade_date"]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "amount": row["amount"],
            }
            for row in rows
        ]
    )
    indicators = add_technical_indicators(kline)
    costs = BacktestCostConfig(initial_cash=200000.0, commission_rate=0.0003, min_commission=5.0, stamp_tax_rate=0.0005)
    summaries: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    signals_by_strategy: dict[str, pd.DataFrame] = {}
    for strategy_key, definition in STRATEGIES.items():
        signals = build_strategy_signals(indicators, strategy_key)
        signals_by_strategy[strategy_key] = signals
        result = run_single_backtest(
            indicators,
            signals,
            code=display,
            name=name,
            strategy=strategy_key,
            strategy_label=definition.label,
            costs=costs,
        )
        summaries.append(result.summary)
        trades.extend(result.trades)
        equity_rows.extend(result.equity_curve)

    run_dir = ctx.repo_root / "data" / "backtests" / f"technical_auto_{display}_{start_day.isoformat()}_{end_day.isoformat()}"
    normalized = run_dir / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    _write_api_frame(normalized / f"kline_{display}.csv", kline)
    _write_api_frame(normalized / f"indicators_{display}.csv", indicators)
    for strategy_key, frame in signals_by_strategy.items():
        _write_api_frame(normalized / f"signals_{display}_{strategy_key}.csv", frame)
    _write_api_records(normalized / "summary", summaries)
    _write_api_records(normalized / "trades", trades)
    _write_api_records(normalized / "equity_curves", equity_rows)
    manifest = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "source": "astocks_qfq.db",
        "auto_generated": True,
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "stocks": [{"code": display, "name": name}],
        "strategies": list(STRATEGIES),
        "costs": costs.__dict__,
    }
    (run_dir / "manifest.json").write_text(json.dumps(_json_ready(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


def _score_candidates(frame: pd.DataFrame, current: str, limit: int) -> list[dict[str, Any]]:
    frame = frame.sort_values(["ts_code", "trade_date"]).copy()
    latest = frame[frame["trade_date"] == current].copy()
    latest = latest.dropna(subset=["close", "amount"])
    latest["amount_rank"] = latest["amount"].rank(method="min", ascending=False)
    liquid_codes = set(latest.nsmallest(800, "amount_rank")["ts_code"])
    subset = frame[frame["ts_code"].isin(liquid_codes)].copy()

    feature_rows: list[dict[str, Any]] = []
    for ts_code, group in subset.groupby("ts_code", sort=False):
        group = group.sort_values("trade_date").reset_index(drop=True)
        if len(group) < 30:
            continue
        enriched = add_technical_indicators(group.rename(columns={"trade_date": "date"}))
        last = enriched.iloc[-1]
        previous = enriched.iloc[-2] if len(enriched) >= 2 else last
        tail20 = enriched.tail(20)
        tail60 = enriched.tail(60)
        close = float(last["close"])
        ma20 = float(tail20["close"].mean())
        high20 = float(tail20["high"].max())
        low20 = float(tail20["low"].min())
        amount20 = float(tail20["amount"].mean())
        change_pct = (close / float(previous["close"]) - 1) * 100 if previous["close"] else None
        ret20 = (close / float(tail20.iloc[0]["close"]) - 1) * 100 if len(tail20) >= 2 else None
        ret60 = (close / float(tail60.iloc[0]["close"]) - 1) * 100 if len(tail60) >= 2 else None
        drawdown20 = float((tail20["close"] / tail20["close"].cummax() - 1).min() * 100)
        consecutive_up = _consecutive_up_days(enriched)
        score, group_label, action_hint, reasons, risks = _candidate_score(
            amount_rank=int(latest.loc[latest["ts_code"] == ts_code, "amount_rank"].iloc[0]),
            change_pct=change_pct,
            ret20=ret20,
            ret60=ret60,
            close=close,
            ma20=ma20,
            high20=high20,
            low20=low20,
            amount=float(last["amount"] or 0),
            amount20=amount20,
            drawdown20=drawdown20,
            macd_dif=float(last["macd_dif"]),
            macd_dea=float(last["macd_dea"]),
            macd_hist=float(last["macd_hist"]),
            previous_macd_hist=float(previous["macd_hist"]),
            kdj_k=float(last["kdj_k"]),
            kdj_d=float(last["kdj_d"]),
            rsi14=float(last["rsi14"]) if not pd.isna(last["rsi14"]) else None,
            td_buy_setup=int(last["td_buy_setup"]) if not pd.isna(last["td_buy_setup"]) else 0,
            td_sell_setup=int(last["td_sell_setup"]) if not pd.isna(last["td_sell_setup"]) else 0,
            recent_low9=bool((enriched.tail(5)["td_buy_setup"] == 9).any()),
            recent_high9=bool((enriched.tail(5)["td_sell_setup"] == 9).any()),
            recent_bottom_divergence=bool(enriched.tail(10)["macd_bottom_divergence"].any()),
            recent_top_divergence=bool(enriched.tail(10)["macd_top_divergence"].any()),
            recent_bottom_passivation=bool(enriched.tail(10)["macd_bottom_passivation"].any()),
            recent_top_passivation=bool(enriched.tail(10)["macd_top_passivation"].any()),
            consecutive_up=consecutive_up,
        )
        feature_rows.append(
            {
                "code": display_code(ts_code),
                "ts_code": ts_code,
                "name": _clean_name(last.get("name") or display_code(ts_code)),
                "score": score,
                "group": group_label,
                "action_hint": action_hint,
                "close": close,
                "change_pct": _safe_float(change_pct),
                "amount_yi": float(last["amount"] or 0) / 100000000,
                "amount_rank": int(latest.loc[latest["ts_code"] == ts_code, "amount_rank"].iloc[0]),
                "ret20_pct": _safe_float(ret20),
                "ret60_pct": _safe_float(ret60),
                "drawdown20_pct": _safe_float(drawdown20),
                "macd_status": "多头" if last["macd_dif"] > last["macd_dea"] else "空头",
                "kdj_status": "转强" if last["kdj_k"] > last["kdj_d"] else "转弱",
                "rsi14": _safe_float(last["rsi14"]),
                "td_buy_setup": int(last["td_buy_setup"]),
                "td_sell_setup": int(last["td_sell_setup"]),
                "td_signal": last.get("td_signal"),
                "macd_top_divergence": bool(last.get("macd_top_divergence")),
                "macd_bottom_divergence": bool(last.get("macd_bottom_divergence")),
                "macd_top_passivation": bool(last.get("macd_top_passivation")),
                "macd_bottom_passivation": bool(last.get("macd_bottom_passivation")),
                "reasons": reasons,
                "risks": risks,
                "auxiliary": _auxiliary_evidence(ts_code),
            }
        )
    feature_rows.sort(key=lambda item: (-item["score"], item["amount_rank"]))
    return feature_rows[:limit]


def _candidate_score(**item: Any) -> tuple[int, str, str, list[str], list[str]]:
    score = 35
    reasons: list[str] = []
    risks: list[str] = []

    rank = item["amount_rank"]
    if rank <= 50:
        score += 22
        reasons.append("成交额进入全市场前50，流动性强")
    elif rank <= 100:
        score += 18
        reasons.append("成交额进入全市场前100")
    elif rank <= 300:
        score += 12
        reasons.append("成交额进入全市场前300")

    if item["amount20"] and item["amount"] >= item["amount20"] * 1.3:
        score += 8
        reasons.append("成交额较20日均值明显放大")
    if _gt(item["ret20"], 10):
        score += 10
        reasons.append("20日趋势较强")
    if _gt(item["ret60"], 20):
        score += 10
        reasons.append("60日趋势较强")
    if item["close"] > item["ma20"]:
        score += 8
        reasons.append("收盘价站上20日均线")
    if item["high20"] and item["close"] >= item["high20"] * 0.95:
        score += 6
        reasons.append("价格接近20日高位")
    if item["macd_dif"] > item["macd_dea"]:
        score += 8
        reasons.append("MACD处于多头")
    if item["macd_hist"] > item["previous_macd_hist"]:
        score += 4
        reasons.append("MACD柱动能改善")
    if item["kdj_k"] > item["kdj_d"]:
        score += 5
        reasons.append("KDJ短线转强")
    if item["rsi14"] is not None and 50 <= item["rsi14"] <= 75:
        score += 6
        reasons.append("RSI处于偏强但未极端区间")
    if item["recent_low9"]:
        score += 4
        reasons.append("近期出现TD低9，适合观察止跌转强")
    if item["recent_bottom_divergence"]:
        score += 4
        reasons.append("近期出现MACD底背离观察信号")
    if item["recent_bottom_passivation"]:
        reasons.append("MACD底钝化，等待结构确认")

    if _gt(item["change_pct"], 9):
        score -= 14
        risks.append("当日涨幅过高，追高风险上升")
    if item["rsi14"] is not None and item["rsi14"] > 80:
        score -= 8
        risks.append("RSI过热")
    if item["drawdown20"] < -20:
        score -= 8
        risks.append("近20日回撤较大")
    if item["consecutive_up"] >= 4:
        score -= 5
        risks.append("连续上涨天数较多")
    if item["recent_high9"]:
        score -= 6
        risks.append("近期出现TD高9，短线追高风险上升")
    if item["recent_top_divergence"]:
        score -= 4
        risks.append("近期出现MACD顶背离，动能可能衰减")
    if item["recent_top_passivation"]:
        risks.append("MACD顶钝化，追高需谨慎")

    score = max(0, min(100, int(round(score))))
    if risks and score < 70:
        group_label = "风险较高"
        action = "风险较高"
    elif any("过高" in risk or "过热" in risk for risk in risks):
        group_label = "过热观察"
        action = "过热不追"
    elif score >= 82:
        group_label = "主线核心"
        action = "重点观察"
    elif score >= 70:
        group_label = "低位转强" if _lt(item["ret20"], 0) else "趋势观察"
        action = "重点观察" if group_label == "低位转强" else "等待回踩"
    else:
        group_label = "继续观察"
        action = "等待回踩"
    return score, group_label, action, reasons[:6], risks[:4]


def _auxiliary_evidence(ts_code: str) -> dict[str, Any]:
    root = find_repo_root()
    evidence: dict[str, Any] = {"hotspot": None, "source": None}
    for path in sorted((root / "data" / "screen").glob("*/normalized/hotspot_confirmation.json"), reverse=True):
        try:
            payload = pd.read_json(path)
        except Exception:
            continue
        if "confirmations" not in payload:
            continue
    # Keep v1 explicit: auxiliary evidence is loaded by report references in UI, not used in scoring.
    return evidence


def _first_markdown_title(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        return None
    return None


def _report_type(name: str) -> str:
    if "stock_screen" in name:
        return "选股"
    if "daily_review" in name:
        return "日报"
    if "weekly_review" in name:
        return "周报"
    if "tech_backtest" in name:
        return "策略"
    return "报告"


def _consecutive_up_days(frame: pd.DataFrame) -> int:
    count = 0
    changes = frame["close"].diff().tail(10)
    for value in reversed(changes.tolist()):
        if pd.isna(value) or value <= 0:
            break
        count += 1
    return count


def _gt(value: Any, threshold: float) -> bool:
    return value is not None and not pd.isna(value) and float(value) > threshold


def _lt(value: Any, threshold: float) -> bool:
    return value is not None and not pd.isna(value) and float(value) < threshold


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _clean_name(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()


def _json_ready(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _technical_backtest_manifests(ctx: ApiContext, include_auto: bool = True) -> list[Path]:
    root = ctx.repo_root / "data" / "backtests"
    if not root.exists():
        return []
    manifests = list(root.glob("technical_*/manifest.json"))
    if not include_auto:
        manifests = [path for path in manifests if not path.parent.name.startswith("technical_auto_")]
    return sorted(manifests, key=lambda path: path.stat().st_mtime, reverse=True)


def _records_for_code(path: Path, code: str) -> list[dict[str, Any]]:
    frame = pd.read_json(path)
    if "code" not in frame.columns:
        return []
    normalized = frame["code"].astype(str).str.split(".").str[0].str.zfill(6)
    return frame[normalized == code].to_dict("records")


def _trade_execution_signals(trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    signals: dict[str, list[dict[str, Any]]] = {strategy: [] for strategy in STRATEGIES}
    for trade in trades:
        strategy = str(trade.get("strategy") or "")
        if strategy not in signals:
            continue
        entry_date = trade.get("entry_date")
        if entry_date:
            signals[strategy].append(
                {
                    "date": entry_date,
                    "signal": "buy",
                    "reason": trade.get("entry_reason") or "实际买入成交",
                    "signal_date": trade.get("entry_signal_date"),
                    "price": trade.get("entry_price"),
                    "source": "trade",
                }
            )
        exit_date = trade.get("exit_date")
        if exit_date and trade.get("status") == "closed":
            signals[strategy].append(
                {
                    "date": exit_date,
                    "signal": "sell",
                    "reason": trade.get("exit_reason") or "实际卖出成交",
                    "signal_date": trade.get("exit_signal_date"),
                    "price": trade.get("exit_price"),
                    "source": "trade",
                }
            )
    for rows in signals.values():
        rows.sort(key=lambda item: str(item.get("date") or ""))
    return _json_ready(signals)


def _augment_summary_with_first_entry_hold(summary: list[dict[str, Any]], trades: list[dict[str, Any]], kline_path: Path) -> list[dict[str, Any]]:
    if not kline_path.exists():
        return summary
    kline = pd.read_csv(kline_path)
    if kline.empty or "close" not in kline.columns:
        return summary
    final_close = _safe_float(kline.iloc[-1].get("close"))
    if final_close is None:
        return summary
    trades_by_strategy: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        strategy = str(trade.get("strategy") or "")
        if strategy:
            trades_by_strategy.setdefault(strategy, []).append(trade)
    for item in summary:
        strategy = str(item.get("strategy") or "")
        strategy_trades = sorted(
            trades_by_strategy.get(strategy, []),
            key=lambda trade: str(trade.get("entry_date") or ""),
        )
        first = strategy_trades[0] if strategy_trades else None
        entry_price = _safe_float(first.get("entry_price")) if first else None
        first_entry_hold = (final_close / entry_price - 1) * 100 if entry_price and entry_price > 0 else None
        item["first_entry_date"] = first.get("entry_date") if first else None
        item["first_entry_signal_date"] = first.get("entry_signal_date") if first else None
        item["first_entry_price"] = entry_price
        item["first_entry_hold_return_pct"] = first_entry_hold
        item["first_entry_excess_return_pct"] = (
            float(item["total_return_pct"]) - first_entry_hold
            if item.get("total_return_pct") is not None and first_entry_hold is not None
            else None
        )
    return summary


def _write_api_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_api_records(base_path: Path, records: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(records)
    frame.to_csv(base_path.with_suffix(".csv"), index=False)
    base_path.with_suffix(".json").write_text(json.dumps(_json_ready(records), ensure_ascii=False, indent=2), encoding="utf-8")


def _one_year_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)
