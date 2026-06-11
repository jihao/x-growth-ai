from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.data_sources.a_stock_data import normalize_code


KLINE_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,"
    "tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)


@dataclass(frozen=True)
class BaoStockKLineResult:
    ok: bool
    frame: pd.DataFrame
    source: str
    error: str | None = None


def baostock_symbol(code: str) -> str:
    normalized = normalize_code(code)
    if normalized.startswith(("6", "9")):
        return f"sh.{normalized}"
    if normalized.startswith(("4", "8")):
        return f"bj.{normalized}"
    return f"sz.{normalized}"


class BaoStockDataClient:
    """BaoStock daily K-line adapter with one login session per client."""

    def __init__(self) -> None:
        self._bs: Any | None = None
        self._logged_in = False

    def __enter__(self) -> BaoStockDataClient:
        self.login()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.logout()

    def login(self, retries: int = 3) -> None:
        if self._logged_in:
            return
        try:
            import baostock as bs
        except ModuleNotFoundError as exc:
            raise RuntimeError("baostock is not installed. Run `uv sync` in backend/ first.") from exc

        last_error = "unknown error"
        for attempt in range(1, retries + 1):
            result = bs.login()
            if result.error_code == "0":
                self._bs = bs
                self._logged_in = True
                return
            last_error = f"{result.error_code} {result.error_msg}"
            if attempt < retries:
                time.sleep(attempt)
        raise RuntimeError(f"baostock login failed: {last_error}")

    def logout(self) -> None:
        if self._logged_in and self._bs is not None:
            self._bs.logout()
        self._logged_in = False
        self._bs = None

    def fetch_daily_kline(
        self,
        code: str,
        start_date: str,
        end_date: str,
        *,
        adjustflag: str = "2",
    ) -> BaoStockKLineResult:
        self.login()
        assert self._bs is not None

        symbol = baostock_symbol(code)
        last_error: str | None = None
        for attempt in range(1, 3):
            try:
                result = self._bs.query_history_k_data_plus(
                    symbol,
                    KLINE_FIELDS,
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag=adjustflag,
                )
                if result.error_code != "0":
                    last_error = f"{symbol}: {result.error_code} {result.error_msg}"
                    if attempt < 2:
                        time.sleep(attempt)
                        continue
                    return BaoStockKLineResult(
                        ok=False,
                        frame=pd.DataFrame(),
                        source="baostock-query_history_k_data_plus",
                        error=last_error,
                    )

                rows: list[list[str]] = []
                while result.next():
                    rows.append(result.get_row_data())
                frame = pd.DataFrame(rows, columns=result.fields)
                return BaoStockKLineResult(
                    ok=True,
                    frame=normalize_kline_frame(frame),
                    source="baostock-query_history_k_data_plus",
                )
            except Exception as exc:
                last_error = f"{symbol}: {type(exc).__name__}: {exc}"
                if attempt < 2:
                    time.sleep(attempt)
                    continue
        return BaoStockKLineResult(
            ok=False,
            frame=pd.DataFrame(),
            source="baostock-query_history_k_data_plus",
            error=last_error or f"{symbol}: unknown error",
        )


def normalize_kline_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    result = frame.copy()
    if "tradestatus" in result.columns:
        result = result[result["tradestatus"].astype(str) == "1"]
    for column in [
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turn",
        "pctChg",
        "peTTM",
        "pbMRQ",
        "psTTM",
        "pcfNcfTTM",
    ]:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result.dropna(subset=["date", "open", "high", "low", "close"])
    result = result.sort_values("date").reset_index(drop=True)
    return result
