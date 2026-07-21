from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.agent_tools import TOOL_NAMES, run_tool, tool_definitions
from backend.api import services


app = FastAPI(title="X-Growth AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_COOKIE = "x_growth_session"


def _session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def _current_user_or_401(request: Request) -> dict:
    user = services.current_user(_session_token(request))
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


@app.get("/api/health")
def health() -> dict:
    return services.health_status()


@app.get("/api/calendar/trading-days")
def calendar_trading_days(
    start: str | None = None,
    end: str | None = None,
    lookback: int = Query(260, ge=20, le=1200),
) -> dict:
    return services.trading_days(start=start, end=end, lookback=lookback)


@app.get("/api/tasks/system-status")
def tasks_system_status() -> dict:
    return services.system_status()


@app.get("/api/notifications/unread-count")
def notifications_unread_count() -> dict:
    return services.unread_notifications()


@app.post("/api/auth/register")
def auth_register(payload: dict) -> dict:
    try:
        return services.register_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auth/login")
def auth_login(payload: dict, response: Response) -> dict:
    try:
        session = services.login_user(payload)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    response.set_cookie(
        SESSION_COOKIE,
        session["token"],
        httponly=True,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
        path="/",
    )
    return {"user": session["user"], "expires_at": session["expires_at"]}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    services.logout_user(_session_token(request))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    user = services.current_user(_session_token(request))
    return {"user": user}


@app.get("/api/users")
def users_index(request: Request) -> list[dict]:
    try:
        return services.list_users(_current_user_or_401(request))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.put("/api/users/{user_id}")
def users_update(user_id: int, payload: dict, request: Request) -> dict:
    try:
        return services.update_user(user_id, payload, _current_user_or_401(request))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/watchlist")
def watchlist_index(status: str | None = None) -> list[dict]:
    return services.list_watchlist(status=status)


@app.post("/api/watchlist")
def watchlist_upsert(payload: dict, request: Request) -> dict:
    try:
        user = services.current_user(_session_token(request))
        return services.upsert_watchlist_item(payload, user_id=user["id"] if user else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/watchlist/{item_id}")
def watchlist_update(item_id: int, payload: dict) -> dict:
    try:
        return services.update_watchlist_item(item_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/watchlist/{item_id}")
def watchlist_delete(item_id: int) -> dict:
    try:
        return services.delete_watchlist_item(item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/agent/tools")
def agent_tools() -> dict:
    return {"count": len(TOOL_NAMES), "tools": tool_definitions()}


@app.get("/api/agent/tool-runs")
def agent_tool_runs(limit: int = Query(50, ge=1, le=200), tool_name: str | None = None) -> list[dict]:
    return services.list_tool_runs(limit=limit, tool_name=tool_name)


@app.post("/api/agent/tools/{tool_name}/run")
def run_agent_tool(tool_name: str, request: Request, arguments: dict | None = None) -> dict:
    payload = arguments or {}
    start = time.perf_counter()
    result = run_tool(tool_name, payload)
    duration_ms = int((time.perf_counter() - start) * 1000)
    user = services.current_user(_session_token(request))
    services.record_tool_run(
        tool_name=tool_name,
        arguments=payload,
        result=result,
        duration_ms=duration_ms,
        user_id=user["id"] if user else None,
    )
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
