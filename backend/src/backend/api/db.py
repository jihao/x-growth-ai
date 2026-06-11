from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    current = Path.cwd()
    if current.name == "backend":
        return current.parent
    return current


def default_db_path(repo_root: Path | None = None) -> Path:
    root = repo_root or find_repo_root()
    return root / "database" / "astocks_qfq.db"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def normalize_trade_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().replace("-", "")
    if len(cleaned) != 8 or not cleaned.isdigit():
        raise ValueError("date must be YYYY-MM-DD or YYYYMMDD")
    return cleaned


def display_trade_date(value: str | None) -> str | None:
    if not value or len(value) != 8:
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def normalize_ts_code(code: str) -> str:
    cleaned = code.strip().upper()
    if "." in cleaned:
        raw, market = cleaned.split(".", 1)
        if market in {"SH", "SZ", "BJ"}:
            return f"{raw}.{market}"
        if raw in {"SH", "SZ", "BJ"}:
            return f"{market}.{raw}"
    if cleaned.startswith(("SH", "SZ", "BJ")):
        cleaned = cleaned[2:]
    if cleaned.startswith(("6", "9")):
        return f"{cleaned}.SH"
    if cleaned.startswith(("4", "8")):
        return f"{cleaned}.BJ"
    return f"{cleaned}.SZ"


def display_code(ts_code: str) -> str:
    return ts_code.split(".", 1)[0]
