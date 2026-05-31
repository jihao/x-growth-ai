from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from typing import Any

import requests


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass(frozen=True)
class SourceResult:
    ok: bool
    rows: list[dict[str, Any]]
    source: str
    error: str | None = None


def normalize_code(code: str) -> str:
    cleaned = code.strip().upper()
    if "." in cleaned:
        cleaned = cleaned.split(".")[0]
    if cleaned.startswith(("SH", "SZ", "BJ")):
        cleaned = cleaned[2:]
    return cleaned


def market_prefix(code: str) -> str:
    normalized = normalize_code(code)
    if normalized.startswith(("6", "9")):
        return "sh"
    if normalized.startswith("8"):
        return "bj"
    return "sz"


def tencent_symbol(code: str) -> str:
    cleaned = code.strip().lower()
    if cleaned.startswith(("sh", "sz", "bj")):
        return cleaned
    if "." in cleaned:
        raw, market = cleaned.split(".", 1)
        return f"{market}{raw}" if market in {"sh", "sz", "bj"} else f"{market_prefix(raw)}{raw}"
    normalized = normalize_code(code)
    return f"{market_prefix(normalized)}{normalized}"


def eastmoney_secid(code: str) -> str:
    normalized = normalize_code(code)
    market = "1" if normalized.startswith(("6", "9")) else "0"
    return f"{market}.{normalized}"


class AStockDataClient:
    """Small adapter for the stable snippets from .skills/a-stock-data."""

    def fetch_quotes(self, codes: list[str]) -> SourceResult:
        if not codes:
            return SourceResult(ok=True, rows=[], source="tencent-quote")

        symbols = [tencent_symbol(code) for code in codes]
        url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            payload = urllib.request.urlopen(request, timeout=10).read().decode("gbk")
        except Exception as exc:
            return SourceResult(ok=False, rows=[], source="tencent-quote", error=f"{type(exc).__name__}: {exc}")

        rows: list[dict[str, Any]] = []
        for line in payload.strip().split(";"):
            row = _parse_tencent_line(line)
            if row:
                rows.append(row)

        missing = sorted(set(normalize_code(code) for code in codes) - {str(row.get("code")) for row in rows})
        if missing:
            return SourceResult(
                ok=bool(rows),
                rows=rows,
                source="tencent-quote",
                error=f"missing quotes: {', '.join(missing)}",
            )
        return SourceResult(ok=True, rows=rows, source="tencent-quote")

    def fetch_stock_info(self, codes: list[str]) -> SourceResult:
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        session = requests.Session()
        session.headers.update({"User-Agent": UA})

        for code in codes:
            normalized = normalize_code(code)
            row, error = self._fetch_one_stock_info(session, normalized)
            if row:
                rows.append(row)
            elif error:
                errors.append(error)

        return SourceResult(
            ok=not errors or bool(rows),
            rows=rows,
            source="eastmoney-stock-info",
            error="; ".join(errors) if errors else None,
        )

    def _fetch_one_stock_info(self, session: requests.Session, normalized: str) -> tuple[dict[str, Any] | None, str | None]:
        last_error: str | None = None
        for _ in range(2):
            try:
                response = session.get(
                    "https://push2.eastmoney.com/api/qt/stock/get",
                    params={
                        "secid": eastmoney_secid(normalized),
                        "fields": "f57,f58,f127,f116,f117,f85,f84,f189",
                    },
                    headers={"Referer": "https://quote.eastmoney.com/"},
                    timeout=10,
                )
                payload = response.json()
                data = payload.get("data") or {}
                if payload.get("rc") != 0 or not data:
                    last_error = f"{normalized}: rc={payload.get('rc')}"
                    continue
                return (
                    {
                        "code": str(data.get("f57") or normalized),
                        "name": data.get("f58") or "",
                        "industry": data.get("f127") or "",
                        "total_market_cap": _to_float(data.get("f116")),
                        "float_market_cap": _to_float(data.get("f117")),
                        "list_date": _format_list_date(data.get("f189")),
                    },
                    None,
                )
            except Exception as exc:
                last_error = f"{normalized}: {type(exc).__name__}: {exc}"
        return None, last_error


def _parse_tencent_line(line: str) -> dict[str, Any] | None:
    if not line.strip() or "=" not in line or '"' not in line:
        return None
    key = line.split("=")[0].split("_")[-1]
    values = line.split('"')[1].split("~")
    if len(values) < 53:
        return None

    return {
        "code": key[2:],
        "symbol": key,
        "name": values[1],
        "price": _to_float(values[3]),
        "last_close": _to_float(values[4]),
        "open": _to_float(values[5]),
        "change_amount": _to_float(values[31]),
        "change_pct": _to_float(values[32]),
        "high": _to_float(values[33]),
        "low": _to_float(values[34]),
        "amount_wan": _to_float(values[37]),
        "turnover_pct": _to_float(values[38]),
        "pe_ttm": _to_float(values[39]),
        "amplitude_pct": _to_float(values[43]),
        "market_cap_yi": _to_float(values[44]),
        "float_market_cap_yi": _to_float(values[45]),
        "pb": _to_float(values[46]),
        "limit_up": _to_float(values[47]),
        "limit_down": _to_float(values[48]),
        "volume_ratio": _to_float(values[49]),
        "pe_static": _to_float(values[52]),
    }


def _to_float(value: Any) -> float | None:
    if value in {None, "", "-"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_list_date(value: Any) -> str:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
