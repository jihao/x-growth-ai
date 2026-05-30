from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from backend.report.daily_review import DailyReviewConfig, generate_daily_review
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
        help="Skip FinClaw live data attempts and generate the analysis template only.",
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

    args = parser.parse_args()

    if args.command == "daily-review":
        config = DailyReviewConfig(
            review_date=args.date,
            output_path=Path(args.output) if args.output else None,
            use_live_data=not args.no_live_data,
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


if __name__ == "__main__":
    main()
