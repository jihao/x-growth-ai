from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.api import services


app = FastAPI(title="X-Growth AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return services.health_status()


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
def screen_candidates(date: str | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
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


@app.get("/api/strategies/backtests/{code}")
def stock_strategy_detail(code: str) -> dict:
    return services.stock_strategy_detail(code)


@app.post("/api/strategies/backtests/{code}/run")
def run_stock_strategy_backtest(code: str) -> dict:
    return services.trigger_stock_backtest(code)
