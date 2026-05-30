from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any


REQUIRED_DATASETS = (
    "index_snapshot",
    "market_breadth",
    "sector_top_gainers",
    "stock_top_gainers",
    "stock_top_turnover",
)

DATASET_LABELS = {
    "index_snapshot": "指数",
    "market_breadth": "宽度",
    "sector_top_gainers": "板块",
    "stock_top_gainers": "涨幅榜",
    "stock_top_turnover": "成交榜",
}


@dataclass(frozen=True)
class DatasetStatus:
    name: str
    label: str
    status: str
    row_count: int = 0
    source: str = ""
    error: str | None = None


@dataclass(frozen=True)
class DailyStatus:
    day: date
    status: str
    datasets: list[DatasetStatus] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def collect_data_status(repo_root: Path, start: date, end: date) -> list[DailyStatus]:
    if end < start:
        raise ValueError("end must be greater than or equal to start")

    rows: list[DailyStatus] = []
    current = start
    while current <= end:
        if current.weekday() >= 5:
            rows.append(DailyStatus(day=current, status="skipped_weekend", notes=["周末跳过"]))
        else:
            rows.append(_collect_one_day(repo_root, current))
        current += timedelta(days=1)
    return rows


def _collect_one_day(repo_root: Path, day: date) -> DailyStatus:
    day_dir = repo_root / "data" / "daily" / day.isoformat()
    normalized_dir = day_dir / "normalized"
    manifest_path = day_dir / "manifest.json"

    if not day_dir.exists():
        return DailyStatus(day=day, status="missing", notes=["未找到落库目录"])

    manifest: dict[str, Any] | None = None
    notes: list[str] = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            notes.append(f"manifest 解析失败：{exc}")
    else:
        notes.append("缺少 manifest.json")

    records = manifest.get("datasets", []) if manifest else []
    datasets = [_dataset_status(name, normalized_dir, records) for name in REQUIRED_DATASETS]

    if all(dataset.status in {"ok", "cache"} for dataset in datasets):
        status = "complete" if all(dataset.status == "ok" for dataset in datasets) else "usable_with_cache"
    elif any(dataset.status in {"ok", "cache"} for dataset in datasets):
        status = "partial"
    else:
        status = "unusable"

    quota_failures = [
        dataset.label
        for dataset in datasets
        if dataset.error and ("403" in dataset.error or "使用次数已达上限" in dataset.error)
    ]
    if quota_failures:
        notes.append(f"接口额度失败：{', '.join(quota_failures)}")

    missing = [dataset.label for dataset in datasets if dataset.status == "missing"]
    if missing:
        notes.append(f"缺失：{', '.join(missing)}")

    failed = [dataset.label for dataset in datasets if dataset.status == "failed"]
    if failed:
        notes.append(f"失败：{', '.join(failed)}")

    return DailyStatus(day=day, status=status, datasets=datasets, notes=notes)


def _dataset_status(name: str, normalized_dir: Path, records: list[dict[str, Any]]) -> DatasetStatus:
    label = DATASET_LABELS.get(name, name)
    dataset_records = [record for record in records if record.get("name") == name]
    ok_records = [record for record in dataset_records if record.get("ok") is True]
    failure_records = [record for record in dataset_records if record.get("ok") is False]
    latest_failure = failure_records[-1] if failure_records else None
    latest_ok = ok_records[-1] if ok_records else None

    fallback_path = normalized_dir / f"{name}.json"
    if latest_ok:
        source = str(latest_ok.get("source") or "")
        status = "cache" if source == "local-cache" else "ok"
        return DatasetStatus(
            name=name,
            label=label,
            status=status,
            row_count=_safe_int(latest_ok.get("row_count")),
            source=source,
            error=_compact_error(latest_failure.get("error")) if latest_failure else None,
        )

    if fallback_path.exists():
        return DatasetStatus(
            name=name,
            label=label,
            status="cache",
            row_count=_count_json_rows(fallback_path),
            source="normalized-file",
            error=_compact_error(latest_failure.get("error")) if latest_failure else None,
        )

    if latest_failure:
        return DatasetStatus(
            name=name,
            label=label,
            status="failed",
            source=str(latest_failure.get("source") or ""),
            error=_compact_error(latest_failure.get("error")),
        )

    return DatasetStatus(name=name, label=label, status="missing")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _count_json_rows(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return 1
    return 0


def _compact_error(error: Any) -> str | None:
    if not error:
        return None
    text = " ".join(str(error).split())
    return text if len(text) <= 120 else f"{text[:117]}..."
