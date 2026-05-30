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
        self.script = repo_root / "skills" / "mx-skills" / "mx-stocks-screener" / "scripts" / "get_data.py"

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
