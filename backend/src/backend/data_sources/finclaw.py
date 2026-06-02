from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FinClawResult:
    ok: bool
    payload: dict[str, Any]
    error: str | None = None


class FinClawClient:
    """Thin wrapper around the copied FinClaw cn-stock-data CLI."""

    def __init__(self, repo_root: Path) -> None:
        self.script = repo_root / ".skills" / "FinClaw" / "cn-stock-data" / "scripts" / "cn_stock_data.py"

    def kline(self, code: str, start: str, end: str | None = None, count: int = 0) -> FinClawResult:
        args = ["kline", "--code", code, "--freq", "daily", "--start", start]
        if end:
            args.extend(["--end", end])
        if count:
            args.extend(["--count", str(count)])
        return self._run(args)

    def quote(self, codes: list[str]) -> FinClawResult:
        return self._run(["quote", "--code", ",".join(codes)])

    def north_flow(self) -> FinClawResult:
        return self._run(["north_flow"])

    def status(self) -> FinClawResult:
        return self._run(["status"])

    def _run(self, args: list[str]) -> FinClawResult:
        if not self.script.exists():
            return FinClawResult(False, {}, f"FinClaw script not found: {self.script}")

        command = [sys.executable, str(self.script), *args]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except subprocess.TimeoutExpired:
            return FinClawResult(False, {}, "FinClaw request timed out after 45 seconds")

        if completed.returncode != 0:
            return FinClawResult(False, {}, (completed.stderr or completed.stdout).strip())

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return FinClawResult(False, {}, f"FinClaw returned non-JSON output: {exc}")

        if not payload.get("ok", True):
            return FinClawResult(False, payload, payload.get("error") or "FinClaw returned ok=false")

        return FinClawResult(True, payload)
