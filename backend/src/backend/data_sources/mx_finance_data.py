from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class MxFinanceDataResult:
    ok: bool
    rows: list[dict[str, Any]]
    xlsx_path: Path | None = None
    description_path: Path | None = None
    error: str | None = None


class MxFinanceDataClient:
    """Run the copied mx-finance-data skill script and parse its xlsx output."""

    def __init__(self, repo_root: Path) -> None:
        self.script = repo_root / ".skills" / "mx-skills" / "mx-finance-data" / "scripts" / "get_data.py"

    def query_index_snapshot(self, review_date: str) -> MxFinanceDataResult:
        query = (
            "查询上证指数、深证成指、创业板指、沪深300、中证500"
            f"在{review_date}的收盘点位、涨跌幅和成交额"
        )
        return self._run_and_parse_index_table(query, f"mx_finance_data_{review_date}_index_snapshot")

    def query_market_breadth(self, review_date: str) -> MxFinanceDataResult:
        query = f"查询{review_date} A股市场上涨家数、下跌家数、涨停家数、跌停家数、两市成交额"
        return self._run_and_parse_key_value_tables(query, f"mx_finance_data_{review_date}_market_breadth")

    def _run_and_parse_index_table(self, query: str, artifact_name: str) -> MxFinanceDataResult:
        if not self.script.exists():
            return MxFinanceDataResult(False, [], error=f"Skill script not found: {self.script}")

        completed = subprocess.run(
            [sys.executable, str(self.script), "--query", query],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        if completed.returncode != 0:
            return MxFinanceDataResult(False, [], error=output)

        xlsx_path = _extract_path(output, "文件")
        description_path = _extract_path(output, "描述")
        if xlsx_path is None or not xlsx_path.exists():
            return MxFinanceDataResult(False, [], error=f"Skill did not return a readable xlsx path. Output: {output}")
        xlsx_path, description_path = _promote_artifacts(xlsx_path, description_path, artifact_name)

        try:
            rows = _parse_index_rows(xlsx_path)
        except Exception as exc:
            return MxFinanceDataResult(False, [], xlsx_path=xlsx_path, description_path=description_path, error=f"{type(exc).__name__}: {exc}")

        if not rows:
            return MxFinanceDataResult(False, [], xlsx_path=xlsx_path, description_path=description_path, error="Skill xlsx contained no index rows")

        return MxFinanceDataResult(True, rows, xlsx_path=xlsx_path, description_path=description_path)

    def _run_and_parse_key_value_tables(self, query: str, artifact_name: str) -> MxFinanceDataResult:
        if not self.script.exists():
            return MxFinanceDataResult(False, [], error=f"Skill script not found: {self.script}")

        completed = subprocess.run(
            [sys.executable, str(self.script), "--query", query],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        if completed.returncode != 0:
            return MxFinanceDataResult(False, [], error=output)

        xlsx_path = _extract_path(output, "文件")
        description_path = _extract_path(output, "描述")
        if xlsx_path is None or not xlsx_path.exists():
            return MxFinanceDataResult(False, [], error=f"Skill did not return a readable xlsx path. Output: {output}")
        xlsx_path, description_path = _promote_artifacts(xlsx_path, description_path, artifact_name)

        try:
            rows = _parse_key_value_rows(xlsx_path)
        except Exception as exc:
            return MxFinanceDataResult(False, [], xlsx_path=xlsx_path, description_path=description_path, error=f"{type(exc).__name__}: {exc}")

        return MxFinanceDataResult(True, rows, xlsx_path=xlsx_path, description_path=description_path)


def _extract_path(output: str, label: str) -> Path | None:
    match = re.search(rf"^{label}:\s*(.+)$", output, flags=re.MULTILINE)
    if not match:
        return None
    return Path(match.group(1).strip())


def _promote_artifacts(xlsx_path: Path, description_path: Path | None, artifact_name: str) -> tuple[Path, Path | None]:
    target_xlsx = xlsx_path.with_name(f"{artifact_name}.xlsx")
    shutil.copy2(xlsx_path, target_xlsx)

    target_description = None
    if description_path and description_path.exists():
        target_description = description_path.with_name(f"{artifact_name}_description.txt")
        shutil.copy2(description_path, target_description)

    return target_xlsx, target_description


def _parse_index_rows(xlsx_path: Path) -> list[dict[str, Any]]:
    frame = pd.read_excel(xlsx_path)
    if frame.empty or len(frame.columns) < 2:
        return []

    indicator_col = frame.columns[0]
    rows_by_indicator = {
        str(row[indicator_col]).strip(): row
        for _, row in frame.iterrows()
        if str(row[indicator_col]).strip()
    }

    result: list[dict[str, Any]] = []
    for entity in frame.columns[1:]:
        entity_name, entity_code = _split_entity(str(entity))
        result.append(
            {
                "name": entity_name,
                "code": entity_code,
                "close": _cell(rows_by_indicator, "收盘价", entity),
                "pct_change": _cell(rows_by_indicator, "涨跌幅", entity),
                "amount": _cell(rows_by_indicator, "成交额", entity),
            }
        )
    return result


def _parse_key_value_rows(xlsx_path: Path) -> list[dict[str, Any]]:
    book = pd.ExcelFile(xlsx_path)
    rows: list[dict[str, Any]] = []
    for sheet in book.sheet_names:
        frame = pd.read_excel(xlsx_path, sheet_name=sheet)
        if frame.empty or len(frame.columns) < 2:
            continue
        indicator_col = frame.columns[0]
        value_col = frame.columns[1]
        for _, row in frame.iterrows():
            rows.append({"metric": row.get(indicator_col), "value": row.get(value_col)})
    return rows


def _split_entity(value: str) -> tuple[str, str]:
    match = re.match(r"(.+?)\((.+?)\)$", value)
    if not match:
        return value, "-"
    return match.group(1), match.group(2)


def _cell(rows_by_indicator: dict[str, Any], indicator: str, entity: str) -> Any:
    row = rows_by_indicator.get(indicator)
    if row is None:
        return None
    return row.get(entity)
