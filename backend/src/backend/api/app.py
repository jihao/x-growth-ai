from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.agent_tools import TOOL_NAMES, run_tool, tool_definitions
from backend.api import services


app = FastAPI(title="X-Growth AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return services.health_status()


@app.get("/api/agent/tools")
def agent_tools() -> dict:
    return {"count": len(TOOL_NAMES), "tools": tool_definitions()}


@app.post("/api/agent/tools/{tool_name}/run")
def run_agent_tool(tool_name: str, arguments: dict | None = None) -> dict:
    result = run_tool(tool_name, arguments or {})
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/agent/model-config")
def agent_model_config() -> dict:
    return services.get_agent_model_config()


@app.put("/api/agent/model-config")
def update_agent_model_config(payload: dict) -> dict:
    return services.save_agent_model_config(payload)


@app.get("/api/market/overview")
def market_overview(date: str | None = None) -> dict:
    return services.market_overview(date)


@app.get("/api/market/concentration")
def market_concentration(
    date: str | None = None,
    lookback: int = Query(120, ge=20, le=260),
    universe: str = Query("top250", pattern="^(top250|all)$"),
) -> dict:
    return services.market_concentration(date=date, lookback=lookback, universe=universe)


@app.get("/api/stocks/search")
def stock_search(q: str = "", limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return services.search_stocks(q, limit)


@app.get("/api/stocks/{code}/kline")
def stock_kline(code: str, start: str | None = None, end: str | None = None) -> dict:
    return services.stock_kline(code, start, end)


@app.get("/api/stocks/{code}/indicators")
def stock_indicators(code: str, start: str | None = None, end: str | None = None) -> dict:
    return services.stock_indicators(code, start, end)


@app.get("/api/screen/candidates")
def screen_candidates(date: str | None = None, limit: int = Query(50, ge=1, le=200), refresh: bool = False) -> dict:
    if refresh:
        return services.screen_candidate_cache_refresh(date, limit)
    return services.screen_candidates(date, limit)


@app.get("/api/reports")
def reports() -> list[dict]:
    return services.reports_index()


@app.get("/api/reports/{report_id}")
def report_detail(report_id: str) -> dict:
    try:
        return services.report_detail(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc


@app.get("/api/review/daily")
def daily_review_dashboard(date: str | None = None) -> dict:
    return services.daily_review_dashboard(date=date, refresh=False)


@app.post("/api/review/daily/refresh")
def refresh_daily_review_dashboard(date: str | None = None) -> dict:
    return services.daily_review_dashboard(date=date, refresh=True)


@app.get("/api/learning")
def learning() -> list[dict]:
    return services.learning_index()


@app.get("/api/learning/{learning_id}")
def learning_detail(learning_id: str) -> dict:
    try:
        return services.learning_detail(learning_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="learning document not found") from exc


@app.get("/api/strategies/backtests")
def strategy_backtests() -> dict:
    return services.strategy_backtests()


@app.get("/api/strategies/candidate-rolling-backtest")
def candidate_rolling_backtest(
    lookback: int = Query(90, ge=20, le=160),
    limit: int = Query(30, ge=5, le=100),
    refresh: bool = False,
) -> dict:
    return services.candidate_rolling_backtest(lookback=lookback, limit=limit, refresh=refresh)


@app.get("/api/strategies/backtests/{code}")
def stock_strategy_detail(code: str) -> dict:
    return services.stock_strategy_detail(code)


@app.post("/api/strategies/backtests/{code}/run")
def run_stock_strategy_backtest(code: str) -> dict:
    return services.trigger_stock_backtest(code)
