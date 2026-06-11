#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补齐 astocks_qfq.db 中缺失的 A 股前复权日线数据到昨天。

功能：
1. 使用 baostock 交易日历找出数据库全市场最大交易日之后到昨天的交易日。
2. 逐只股票检查这些交易日中本地缺失的记录。
3. 按连续交易日区间从 baostock 下载前复权日线并写入 daily_qfq。

使用方法：
    python backfill_qfq_to_yesterday.py
    python backfill_qfq_to_yesterday.py astocks_qfq.db
    python backfill_qfq_to_yesterday.py astocks_qfq.db --end-date 2026-06-09

说明：
    baostock adjustflag="2" 为官方前复权口径。
"""

import argparse
import os
import socket
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta

import baostock as bs


DEFAULT_DB = "astocks_qfq.db"
FIELDS = "date,open,high,low,close,volume,amount"

socket.setdefaulttimeout(20)


def compact_date(value):
    """Return YYYYMMDD."""
    value = str(value)
    if "-" in value:
        return value.replace("-", "")
    return value


def dashed_date(value):
    """Return YYYY-MM-DD."""
    value = str(value)
    if "-" in value:
        parts = value.split("-")
        return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def next_calendar_day(compact):
    dt = datetime.strptime(compact, "%Y%m%d").date()
    return (dt + timedelta(days=1)).strftime("%Y%m%d")


def default_end_date():
    return (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def login():
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Baostock 登录失败: {lg.error_msg}")


def relogin():
    try:
        bs.logout()
    except Exception:
        pass
    time.sleep(0.5)
    login()


def get_trading_dates(start_date, end_date):
    """Return trading dates in YYYYMMDD format."""
    rs = bs.query_trade_dates(
        start_date=dashed_date(start_date),
        end_date=dashed_date(end_date),
    )
    if rs.error_code != "0":
        raise RuntimeError(f"获取交易日历失败: {rs.error_msg}")

    fields = list(getattr(rs, "fields", []) or [])
    dates = []
    while rs.next():
        row = rs.get_row_data()
        if fields:
            item = dict(zip(fields, row))
            calendar_date = item.get("calendar_date") or item.get("date")
            is_trading_day = item.get("is_trading_day")
        else:
            calendar_date = row[0]
            is_trading_day = row[1] if len(row) > 1 else "1"

        if calendar_date and str(is_trading_day) == "1":
            dates.append(compact_date(calendar_date))

    return dates


def ts_code_to_bs_code(ts_code):
    code, market = ts_code.split(".")
    return f"{market.lower()}.{code}"


def group_by_calendar_ranges(missing_dates, trading_dates):
    """Group missing trading dates into continuous ranges by trading calendar order."""
    if not missing_dates:
        return []

    order = {trade_date: i for i, trade_date in enumerate(trading_dates)}
    ordered = sorted(missing_dates, key=lambda item: order[item])

    ranges = []
    start = prev = ordered[0]
    prev_idx = order[prev]

    for current in ordered[1:]:
        current_idx = order[current]
        if current_idx == prev_idx + 1:
            prev = current
            prev_idx = current_idx
            continue

        ranges.append((start, prev))
        start = prev = current
        prev_idx = current_idx

    ranges.append((start, prev))
    return ranges


def download_range(bs_code, start_date, end_date, retries):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            rs = bs.query_history_k_data_plus(
                code=bs_code,
                fields=FIELDS,
                start_date=dashed_date(start_date),
                end_date=dashed_date(end_date),
                frequency="d",
                adjustflag="2",
            )
            if rs.error_code != "0":
                raise RuntimeError(rs.error_msg)

            rows = []
            while rs.next():
                row = rs.get_row_data()
                if row and row[0] and row[4]:
                    rows.append(row)
            return rows
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
                relogin()

    raise RuntimeError(last_error)


def insert_rows(cursor, ts_code, rows):
    inserted = 0
    for row in rows:
        cursor.execute(
            """
            INSERT OR REPLACE INTO daily_qfq
                (ts_code, trade_date, open, high, low, close_qfq, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_code,
                compact_date(row[0]),
                float(row[1]) if row[1] else None,
                float(row[2]) if row[2] else None,
                float(row[3]) if row[3] else None,
                float(row[4]) if row[4] else None,
                int(float(row[5])) if row[5] else None,
                float(row[6]) if row[6] else None,
            ),
        )
        inserted += 1
    return inserted


def parse_args():
    parser = argparse.ArgumentParser(description="补齐 A 股前复权日线数据到昨天")
    parser.add_argument("db_path", nargs="?", default=DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--end-date", default=default_end_date(), help="补齐截止日期，默认昨天，格式 YYYYMMDD 或 YYYY-MM-DD")
    parser.add_argument("--start-date", default=None, help="强制指定扫描起始日期，格式 YYYYMMDD 或 YYYY-MM-DD")
    parser.add_argument("--sleep", type=float, default=0.05, help="每只股票处理后的暂停秒数")
    parser.add_argument("--retries", type=int, default=3, help="单个下载区间最大重试次数")
    parser.add_argument("--relogin-interval", type=int, default=200, help="每处理多少只股票重新登录 baostock")
    parser.add_argument("--commit-every", type=int, default=100, help="每处理多少只股票提交一次事务")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 只股票，调试用")
    parser.add_argument("--dry-run", action="store_true", help="只打印缺失情况，不下载写入")
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = args.db_path
    end_date = compact_date(args.end_date)

    if not os.path.exists(db_path):
        print(f"错误: 数据库不存在 {db_path}")
        return 1

    print("=" * 72)
    print("补齐 A 股前复权日线到昨天")
    print("=" * 72)
    print(f"数据库: {db_path}")
    print(f"截止日期: {end_date} ({dashed_date(end_date)})")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(trade_date) FROM daily_qfq WHERE trade_date!='SKIP'")
    row = cursor.fetchone()
    latest_db_date = row[0] if row and row[0] else None

    if args.start_date:
        start_date = compact_date(args.start_date)
    elif latest_db_date:
        start_date = next_calendar_day(compact_date(latest_db_date))
    else:
        start_date = "20100101"

    print(f"数据库最大交易日: {latest_db_date or '无'}")
    print(f"扫描起始日期: {start_date} ({dashed_date(start_date)})")

    if start_date > end_date:
        print("数据库最大交易日已经晚于或等于截止日期，无需补齐。")
        conn.close()
        return 0

    try:
        login()
        print("Baostock 登录成功")

        trading_dates = get_trading_dates(start_date, end_date)
        if not trading_dates:
            print("扫描区间内没有交易日，无需补齐。")
            return 0

        print(f"缺失交易日数量: {len(trading_dates)}")
        print("缺失交易日:")
        print("  " + ", ".join(trading_dates))
        print()

        cursor.execute("SELECT ts_code FROM stocks ORDER BY ts_code")
        stocks = [item[0] for item in cursor.fetchall()]
        if args.limit:
            stocks = stocks[: args.limit]

        print(f"待检查股票数: {len(stocks)}")
        if args.dry_run:
            print("dry-run 模式：只检查全市场缺失交易日，不下载写入。")
            return 0

        trading_set = set(trading_dates)
        checked = 0
        skipped = 0
        downloaded_rows = 0
        no_data_ranges = 0
        failed = 0
        errors = []
        t0 = time.time()

        for index, ts_code in enumerate(stocks, 1):
            checked += 1
            if args.relogin_interval and checked > 1 and (checked - 1) % args.relogin_interval == 0:
                relogin()

            cursor.execute(
                """
                SELECT trade_date
                FROM daily_qfq
                WHERE ts_code = ?
                  AND trade_date BETWEEN ? AND ?
                """,
                (ts_code, trading_dates[0], trading_dates[-1]),
            )
            existing = {item[0] for item in cursor.fetchall()}
            missing = trading_set - existing

            if not missing:
                skipped += 1
            else:
                bs_code = ts_code_to_bs_code(ts_code)
                ranges = group_by_calendar_ranges(missing, trading_dates)
                for range_start, range_end in ranges:
                    try:
                        rows = download_range(bs_code, range_start, range_end, args.retries)
                        if rows:
                            downloaded_rows += insert_rows(cursor, ts_code, rows)
                        else:
                            no_data_ranges += 1
                    except Exception as exc:
                        failed += 1
                        errors.append(f"{ts_code} {range_start}-{range_end}: {exc}")

            if args.commit_every and checked % args.commit_every == 0:
                conn.commit()

            if checked % 100 == 0 or checked == len(stocks):
                elapsed = time.time() - t0
                print(
                    f"进度: {checked}/{len(stocks)} | "
                    f"写入行:{downloaded_rows} 跳过股票:{skipped} "
                    f"无数据区间:{no_data_ranges} 失败区间:{failed} "
                    f"耗时:{elapsed:.1f}s"
                )
                sys.stdout.flush()

            if args.sleep > 0:
                time.sleep(args.sleep)

        conn.commit()

        cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT ts_code), MIN(trade_date), MAX(trade_date) FROM daily_qfq WHERE trade_date!='SKIP'"
        )
        total_rows, total_stocks, min_date, max_date = cursor.fetchone()

        print()
        print("=" * 72)
        print("补齐完成")
        print("=" * 72)
        print(f"写入行数: {downloaded_rows}")
        print(f"跳过股票: {skipped}")
        print(f"无数据区间: {no_data_ranges}")
        print(f"失败区间: {failed}")
        print(f"当前记录数: {total_rows}")
        print(f"当前有行情股票数: {total_stocks}")
        print(f"当前日期范围: {min_date} ~ {max_date}")

        if errors:
            print()
            print("前 20 个错误:")
            for error in errors[:20]:
                print(f"  {error}")

        return 0 if failed == 0 else 2
    finally:
        try:
            bs.logout()
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
