from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class DatasetRecord:
    name: str
    ok: bool
    row_count: int = 0
    source: str = ""
    normalized_json: str | None = None
    normalized_csv: str | None = None
    raw_files: list[str] = field(default_factory=list)
    error: str | None = None


class DailyDataStore:
    """Persist raw skill artifacts and normalized rows by trading date."""

    def __init__(self, repo_root: Path, review_date: str) -> None:
        self.base_dir = repo_root / "data" / "daily" / review_date
        self.raw_dir = self.base_dir / "raw"
        self.normalized_dir = self.base_dir / "normalized"
        self.records: list[DatasetRecord] = []

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.normalized_dir.mkdir(parents=True, exist_ok=True)

    def save_dataset(
        self,
        name: str,
        rows: list[dict[str, Any]],
        *,
        source: str,
        raw_paths: list[Path | None] | None = None,
    ) -> None:
        json_path = self.normalized_dir / f"{name}.json"
        csv_path = self.normalized_dir / f"{name}.csv"

        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        _write_csv(csv_path, rows)

        raw_files = self._copy_raw_files(name, raw_paths or [])
        self.records.append(
            DatasetRecord(
                name=name,
                ok=True,
                row_count=len(rows),
                source=source,
                normalized_json=str(json_path),
                normalized_csv=str(csv_path),
                raw_files=[str(path) for path in raw_files],
            )
        )

    def save_failure(self, name: str, *, source: str, error: str | None) -> None:
        self.records.append(DatasetRecord(name=name, ok=False, source=source, error=error or "unknown error"))

    def save_cached_dataset(self, name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.save_dataset(name, rows, source="local-cache")
        return rows

    def save_summary(self, name: str, payload: dict[str, Any]) -> None:
        path = self.normalized_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.records.append(
            DatasetRecord(
                name=name,
                ok=True,
                row_count=1,
                source="backend-derived",
                normalized_json=str(path),
            )
        )

    def write_manifest(self) -> Path:
        path = self.base_dir / "manifest.json"
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "base_dir": str(self.base_dir),
            "datasets": [asdict(record) for record in self.records],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _copy_raw_files(self, name: str, paths: list[Path | None]) -> list[Path]:
        copied: list[Path] = []
        for raw_path in paths:
            if raw_path is None or not raw_path.exists():
                continue
            target = self.raw_dir / f"{name}{raw_path.suffix}"
            if target in copied:
                target = self.raw_dir / f"{name}_{len(copied) + 1}{raw_path.suffix}"
            shutil.copy2(raw_path, target)
            copied.append(target)
        return copied


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = _fieldnames(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                ordered.append(key)
                seen.add(key)
    return ordered or ["empty"]
