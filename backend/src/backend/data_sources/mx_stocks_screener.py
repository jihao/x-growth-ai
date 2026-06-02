from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MxScreenerResult:
    ok: bool
    rows: list[dict[str, Any]]
    csv_path: Path | None = None
    description_path: Path | None = None
    error: str | None = None


class MxStocksScreenerClient:
    """Run the copied mx-stocks-screener skill script and parse CSV output."""

    def __init__(self, repo_root: Path) -> None:
        self.script = repo_root / ".skills" / "mx-skills" / "mx-stocks-screener" / "scripts" / "get_data.py"

    def top_gainers(self, review_date: str, limit: int = 20) -> MxScreenerResult:
        return self._run(
            query=f"在{review_date}的A股涨幅排名前{limit}，包含代码、名称、{review_date}涨跌幅、{review_date}成交额、所属行业",
            select_type="A股",
            artifact_name=f"mx_stocks_screener_{review_date}_stock_top_gainers",
        )

    def top_turnover(self, review_date: str, limit: int = 100) -> MxScreenerResult:
        return self._run(
            query=f"在{review_date}的A股成交额排名前{limit}，包含代码、名称、{review_date}涨跌幅、{review_date}成交额、所属行业",
            select_type="A股",
            artifact_name=f"mx_stocks_screener_{review_date}_stock_top_turnover",
        )

    def top_sectors(self, review_date: str, limit: int = 10) -> MxScreenerResult:
        return self._run(
            query=f"在{review_date}涨幅最大板块前{limit}，包含板块名称、{review_date}涨跌幅、{review_date}成交额、上涨家数、下跌家数",
            select_type="板块",
            artifact_name=f"mx_stocks_screener_{review_date}_sector_top_gainers",
        )

    def watchlist_snapshot(self, review_date: str, stocks: list[dict[str, Any]]) -> MxScreenerResult:
        names = "、".join(str(stock.get("name") or stock.get("code")) for stock in stocks)
        return self._run(
            query=(
                f"在{review_date}的{names}，包含代码、名称、收盘价、涨跌幅、成交额、"
                "换手率、市盈率TTM、市净率、所属行业"
            ),
            select_type="A股",
            artifact_name=f"mx_stocks_screener_{review_date}_watchlist_snapshot",
        )

    def _run(self, query: str, select_type: str, artifact_name: str) -> MxScreenerResult:
        if not self.script.exists():
            return MxScreenerResult(False, [], error=f"Skill script not found: {self.script}")

        completed = subprocess.run(
            [sys.executable, str(self.script), "--query", query, "--select-type", select_type],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        if completed.returncode != 0:
            return MxScreenerResult(False, [], error=output)

        csv_path = _extract_path(output, "CSV")
        description_path = _extract_path(output, "描述")
        if csv_path is None or not csv_path.exists():
            return MxScreenerResult(False, [], error=f"Skill did not return a readable csv path. Output: {output}")

        csv_path, description_path = _promote_artifacts(csv_path, description_path, artifact_name)
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        return MxScreenerResult(True, rows, csv_path=csv_path, description_path=description_path)


def normalize_watchlist_rows(rows: list[dict[str, Any]], review_date: str) -> list[dict[str, Any]]:
    date_key = review_date.replace("-", ".")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "date": review_date,
                "code": _text(row.get("代码")),
                "name": _text(row.get("名称") or row.get("股票简称")),
                "industry": _industry(row),
                "price": _number(_find_by_prefix(row, f"收盘价(日线不复权)(元) {date_key}") or _find_by_prefix(row, f"最新价(元) {date_key}")),
                "change_pct": _number(_find_by_prefix(row, f"涨跌幅(%) {date_key}")),
                "amount_wan": _amount_to_wan(_find_by_prefix(row, f"成交额(元) {date_key}")),
                "turnover_pct": _number(_find_by_prefix(row, f"换手率(%) {date_key}")),
                "pe_ttm": _number(_find_by_prefix(row, f"市盈率(TTM)(倍) {date_key}")),
                "pb": _number(_find_by_prefix(row, f"市净率(倍) {date_key}")),
                "concepts": _text(row.get("概念")),
            }
        )
    return normalized


def _extract_path(output: str, label: str) -> Path | None:
    match = re.search(rf"^{label}:\s*(.+)$", output, flags=re.MULTILINE)
    if not match:
        return None
    return Path(match.group(1).strip())


def _promote_artifacts(csv_path: Path, description_path: Path | None, artifact_name: str) -> tuple[Path, Path | None]:
    target_csv = csv_path.with_name(f"{artifact_name}.csv")
    shutil.copy2(csv_path, target_csv)

    target_description = None
    if description_path and description_path.exists():
        target_description = description_path.with_name(f"{artifact_name}_description.txt")
        shutil.copy2(description_path, target_description)

    return target_csv, target_description


def _find_by_prefix(row: dict[str, Any], prefix: str) -> Any:
    for key, value in row.items():
        if str(key).startswith(prefix):
            return value
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value: Any) -> float | None:
    text = _text(value)
    if not text or text == "-":
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _amount_to_wan(value: Any) -> float | None:
    text = _text(value).replace(",", "")
    if not text or text == "-":
        return None
    multiplier = 1.0
    if text.endswith("万"):
        text = text[:-1]
        multiplier = 1.0
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


def _industry(row: dict[str, Any]) -> str:
    value = _text(row.get("申万行业分类") or row.get("东财行业总分类"))
    return value.split("-")[-1] if value else ""
