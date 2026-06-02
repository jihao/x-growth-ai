from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from backend.analysis.data_status import DailyStatus, collect_data_status
from backend.report.daily_review import DailyReviewConfig, generate_daily_review
from backend.report.stock_screen import StockScreenConfig, generate_stock_screen
from backend.report.watchlist import WatchlistConfig, generate_watchlist_snapshot
from backend.report.weekly_review import WeeklyReviewConfig, generate_weekly_review


@dataclass(frozen=True)
class BackfillResult:
    day: date
    status: str
    output: Path | None = None
    error: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate A-share research reports.")
    subparsers = parser.add_subparsers(dest="command")

    daily = subparsers.add_parser("daily-review", help="Generate an A-share daily review markdown report.")
    daily.add_argument("--date", default=None, help="Review date, YYYY-MM-DD. Defaults to last China trading weekday.")
    daily.add_argument("--output", default=None, help="Output markdown path.")
    daily.add_argument(
        "--no-live-data",
        action="store_true",
        help="Skip live data attempts and generate from valid local daily data when available.",
    )
    daily.add_argument(
        "--refresh-data",
        action="store_true",
        help="Ignore valid local daily data and force fresh mx skill requests.",
    )

    backfill = subparsers.add_parser("backfill", help="Generate daily reviews for a date range.")
    backfill.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    backfill.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    backfill.add_argument(
        "--no-live-data",
        action="store_true",
        help="Generate templates only; useful for testing the date loop.",
    )

    weekly = subparsers.add_parser("weekly-review", help="Generate a weekly review from local daily snapshots.")
    weekly.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    weekly.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    weekly.add_argument("--output", default=None, help="Output markdown path.")

    status = subparsers.add_parser("data-status", help="Inspect local daily data availability.")
    status.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    status.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")

    watchlist = subparsers.add_parser("watchlist-snapshot", help="Generate a watchlist snapshot markdown report.")
    watchlist.add_argument("--date", default=None, help="Snapshot date, YYYY-MM-DD. Defaults to last weekday.")
    watchlist.add_argument("--config", default=None, help="Watchlist JSON config path.")
    watchlist.add_argument("--output", default=None, help="Output markdown path.")
    watchlist.add_argument(
        "--no-live-data",
        action="store_true",
        help="Skip live data attempts and generate from valid local watchlist data when available.",
    )
    watchlist.add_argument(
        "--refresh-data",
        action="store_true",
        help="Ignore valid local watchlist data and force fresh external requests.",
    )

    screen = subparsers.add_parser("stock-screen", help="Generate a rule-based stock screen report from local daily data.")
    screen.add_argument("--date", default=None, help="Screen date, YYYY-MM-DD. Defaults to last weekday.")
    screen.add_argument("--output", default=None, help="Output markdown path.")
    screen.add_argument("--limit", type=int, default=15, help="Maximum number of candidates.")
    screen.add_argument(
        "--with-hotspot",
        action="store_true",
        help="Fetch mx hotspot/search skill results and add hotspot confirmation to the stock screen report.",
    )

    args = parser.parse_args()

    if args.command == "daily-review":
        config = DailyReviewConfig(
            review_date=args.date,
            output_path=Path(args.output) if args.output else None,
            use_live_data=not args.no_live_data,
            force_refresh=args.refresh_data,
        )
        output = generate_daily_review(config)
        print(output)
        return

    if args.command == "backfill":
        results = run_backfill(
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            use_live_data=not args.no_live_data,
        )
        print(_format_backfill_results(results))
        return

    if args.command == "weekly-review":
        output = generate_weekly_review(
            WeeklyReviewConfig(
                start_date=args.start,
                end_date=args.end,
                output_path=Path(args.output) if args.output else None,
            )
        )
        print(output)
        return

    if args.command == "data-status":
        rows = collect_data_status(
            repo_root=Path.cwd().parent if Path.cwd().name == "backend" else Path.cwd(),
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
        )
        print(_format_data_status(rows))
        return

    if args.command == "watchlist-snapshot":
        output = generate_watchlist_snapshot(
            WatchlistConfig(
                snapshot_date=args.date,
                config_path=Path(args.config) if args.config else None,
                output_path=Path(args.output) if args.output else None,
                use_live_data=not args.no_live_data,
                force_refresh=args.refresh_data,
            )
        )
        print(output)
        return

    if args.command == "stock-screen":
        output = generate_stock_screen(
            StockScreenConfig(
                screen_date=args.date,
                output_path=Path(args.output) if args.output else None,
                limit=args.limit,
                with_hotspot=args.with_hotspot,
            )
        )
        print(output)
        return

    parser.print_help()


def run_backfill(start: date, end: date, use_live_data: bool = True) -> list[BackfillResult]:
    if end < start:
        raise SystemExit("--end must be greater than or equal to --start")

    results: list[BackfillResult] = []
    current = start
    while current <= end:
        if current.weekday() >= 5:
            results.append(BackfillResult(current, "skipped_weekend"))
        else:
            try:
                output = generate_daily_review(
                    DailyReviewConfig(
                        review_date=current.isoformat(),
                        use_live_data=use_live_data,
                    )
                )
                results.append(BackfillResult(current, "ok", output=output))
            except Exception as exc:
                results.append(BackfillResult(current, "failed", error=f"{type(exc).__name__}: {exc}"))
        current += timedelta(days=1)
    return results


def _format_backfill_results(results: list[BackfillResult]) -> str:
    lines = ["Backfill summary:"]
    for result in results:
        suffix = f" -> {result.output}" if result.output else ""
        if result.error:
            suffix = f" -> {result.error}"
        lines.append(f"{result.day.isoformat()} {result.status}{suffix}")

    ok = sum(1 for result in results if result.status == "ok")
    skipped = sum(1 for result in results if result.status.startswith("skipped"))
    failed = sum(1 for result in results if result.status == "failed")
    lines.append(f"Total: {len(results)} days, {ok} ok, {skipped} skipped, {failed} failed")
    return "\n".join(lines)


def _format_data_status(rows: list[DailyStatus]) -> str:
    headers = ["日期", "指数", "宽度", "板块", "涨幅榜", "成交榜", "状态", "备注"]
    table = ["\t".join(headers)]

    for row in rows:
        if row.status == "skipped_weekend":
            table.append("\t".join([row.day.isoformat(), "-", "-", "-", "-", "-", "跳过", "周末"]))
            continue

        cells = {dataset.name: _dataset_status_label(dataset.status, dataset.row_count) for dataset in row.datasets}
        table.append(
            "\t".join(
                [
                    row.day.isoformat(),
                    cells.get("index_snapshot", "-"),
                    cells.get("market_breadth", "-"),
                    cells.get("sector_top_gainers", "-"),
                    cells.get("stock_top_gainers", "-"),
                    cells.get("stock_top_turnover", "-"),
                    _daily_status_label(row.status),
                    "；".join(row.notes) if row.notes else "-",
                ]
            )
        )

    summary = _data_status_summary(rows)
    table.append("")
    table.append(summary)
    return "\n".join(table)


def _dataset_status_label(status: str, row_count: int) -> str:
    if status == "ok":
        return f"OK({row_count})"
    if status == "cache":
        return f"缓存({row_count})"
    if status == "failed":
        return "失败"
    if status == "missing":
        return "缺失"
    return status


def _daily_status_label(status: str) -> str:
    labels = {
        "complete": "完整",
        "usable_with_cache": "可用-含缓存",
        "partial": "部分可用",
        "unusable": "不可用",
        "missing": "缺失",
        "skipped_weekend": "跳过",
    }
    return labels.get(status, status)


def _data_status_summary(rows: list[DailyStatus]) -> str:
    trading_rows = [row for row in rows if row.status != "skipped_weekend"]
    complete = sum(1 for row in trading_rows if row.status == "complete")
    cache = sum(1 for row in trading_rows if row.status == "usable_with_cache")
    partial = sum(1 for row in trading_rows if row.status == "partial")
    missing = sum(1 for row in trading_rows if row.status in {"missing", "unusable"})
    skipped = sum(1 for row in rows if row.status == "skipped_weekend")
    return (
        f"合计：{len(trading_rows)} 个工作日，{complete} 完整，{cache} 可用-含缓存，"
        f"{partial} 部分可用，{missing} 缺失/不可用，{skipped} 周末跳过"
    )


if __name__ == "__main__":
    main()
