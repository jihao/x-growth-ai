#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
baostock 前复权日线数据下载器（稳健版）
=====================================

经验总结：
1. baostock 服务器对深市非主板(002/003/300/301)不稳定，经常超时
2. 每次登录会话约能持续查询200-300只，超过需要重新登录
3. 网络超时是暂时性的，重试3-5次通常能成功
4. adjustflag="2" 是官方前复权，质量最高，不要自己算
5. 不要用 mootdx 的 cum_factor 算前复权，它不含现金分红，偏差可达148%
6. 每次重试前 sleep 1-2秒，避免被封IP
7. 查询日期范围不要拆分年度，一次传完整范围（如2010-01-01到今天）

使用方法：
    python bs_qfq_downloader.py
    
输出：
    SQLite数据库，包含每只股票的前复权日线数据
"""

import baostock as bs
import sqlite3
import time
import sys
from datetime import datetime, timedelta


# ======================== 配置区 ========================
DB_PATH = "astocks_qfq.db"           # 输出数据库路径
START_DATE = "2010-01-01"             # 起始日期
END_DATE = datetime.now().strftime("%Y-%m-%d")  # 截止日期（默认今天）
MAX_RETRIES = 5                       # 每只股票最大重试次数
RETRY_DELAY = 2                       # 重试间隔（秒）
RELOGIN_INTERVAL = 200                # 每N只重新登录
# ========================================================


def create_db(db_path):
    """创建数据库表"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            ts_code TEXT PRIMARY KEY,
            stock_name TEXT,
            market TEXT,
            download_status TEXT DEFAULT 'pending',
            record_count INTEGER DEFAULT 0,
            last_update TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_qfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close_qfq REAL,
            volume REAL,
            amount REAL,
            UNIQUE(ts_code, trade_date)
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_qfq_code 
        ON daily_qfq(ts_code, trade_date)
    """)
    conn.commit()
    return conn


def get_stock_list():
    """从baostock获取所有A股股票列表"""
    stocks = []
    rs = bs.query_stock_basic()
    while (rs.error_code == '0') and rs.next():
        row = rs.get_row_data()
        code = row[0]        # sh.600000
        code_name = row[1]   # 浦发银行
        ipo_date = row[2]    # 1999-11-10
        out_date = row[3]    # 退市日期，空表示正常上市
        stock_type = row[4]  # 1=股票, 2=指数, 3=其他

        if stock_type != '1':
            continue
        if out_date:  # 已退市
            continue

        # 转换格式: sh.600000 → 600000.SH
        market_prefix, stock_code = code.split('.')
        ts_code = f"{stock_code}.{market_prefix.upper()}"
        stocks.append((ts_code, code_name, market_prefix))

    return sorted(stocks, key=lambda x: x[0])


def download_stock(bs_code, start_date, end_date):
    """
    下载单只股票的前复权日线
    bs_code: baostock格式 sh.600000
    返回: (成功标志, 数据行列表)
    """
    rs = bs.query_history_k_data_plus(
        code=bs_code,
        fields="date,open,high,low,close,volume,amount",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2"  # ★ 前复权，这是关键！
    )

    rows = []
    while (rs.error_code == '0') and rs.next():
        row = rs.get_row_data()
        # baostock返回的日期格式: 2024-01-15
        # 检查数据完整性（所有字段都应有值，除amount可能为空）
        if row[0] and row[4]:  # date和close必须有值
            rows.append(row)

    if rs.error_code != '0':
        return False, rows
    return True, rows


def save_to_db(conn, ts_code, rows):
    """保存数据到数据库（覆盖已有数据）"""
    c = conn.cursor()
    c.execute("DELETE FROM daily_qfq WHERE ts_code = ?", (ts_code,))
    
    for row in rows:
        trade_date = row[0].replace('-', '')  # 2024-01-15 → 20240115
        c.execute("""
            INSERT OR IGNORE INTO daily_qfq 
            (ts_code, trade_date, open, high, low, close_qfq, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ts_code, trade_date,
            float(row[1]) if row[1] else None,
            float(row[2]) if row[2] else None,
            float(row[3]) if row[3] else None,
            float(row[4]) if row[4] else None,
            float(row[5]) if row[5] else None,
            float(row[6]) if row[6] else None,
        ))
    
    conn.commit()
    return c.rowcount


def update_stock_status(conn, ts_code, status, count=0):
    """更新股票下载状态"""
    c = conn.cursor()
    c.execute("""
        UPDATE stocks SET 
            download_status = ?,
            record_count = ?,
            last_update = ?
        WHERE ts_code = ?
    """, (status, count, datetime.now().isoformat(), ts_code))
    conn.commit()


def main():
    print("=" * 60)
    print("baostock 前复权日线下载器")
    print("=" * 60)

    conn = create_db(DB_PATH)

    # 登录
    print("\n登录 baostock...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"登录失败: {lg.error_msg}")
        return
    print("登录成功")

    # 获取股票列表
    print(f"\n获取股票列表 ({START_DATE} ~ {END_DATE})...")
    all_stocks = get_stock_list()
    print(f"共 {len(all_stocks)} 只股票")

    # 写入股票列表到数据库
    c = conn.cursor()
    for ts_code, name, market in all_stocks:
        c.execute("""
            INSERT OR IGNORE INTO stocks (ts_code, stock_name, market)
            VALUES (?, ?, ?)
        """, (ts_code, name, market))
    conn.commit()

    # 统计
    stats = {'success': 0, 'skip': 0, 'fail': 0, 'retry': 0}
    t0 = time.time()
    process_count = 0  # 距上次登录的处理数

    for i, (ts_code, stock_name, market) in enumerate(all_stocks, 1):
        bs_code = f"{market}.{ts_code.replace('.SH', '').replace('.SZ', '')}"

        # 检查是否已成功下载
        c.execute("SELECT download_status FROM stocks WHERE ts_code = ?", (ts_code,))
        existing = c.fetchone()
        if existing and existing[0] == 'success':
            stats['skip'] += 1
            if i % 100 == 0:
                print(f"[{i}/{len(all_stocks)}] 跳过已下载, "
                      f"成功={stats['success']} 跳过={stats['skip']} 失败={stats['fail']}")
            continue

        # ★ 每200只重新登录，防止会话超时
        if process_count >= RELOGIN_INTERVAL:
            try:
                bs.logout()
            except:
                pass
            time.sleep(0.5)
            lg = bs.login()
            if lg.error_code != '0':
                print(f"重新登录失败: {lg.error_msg}")
                break
            process_count = 0

        # ★ 重试机制
        success = False
        last_rows = []
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                ok, rows = download_stock(bs_code, START_DATE, END_DATE)
                if ok and len(rows) > 0:
                    success = True
                    last_rows = rows
                    break
                elif ok and len(rows) == 0:
                    # 查询成功但无数据（可能IPO前），跳过
                    success = True
                    last_rows = rows
                    break
                else:
                    # 查询失败
                    if attempt < MAX_RETRIES:
                        stats['retry'] += 1
                        time.sleep(RETRY_DELAY)
            except Exception as e:
                if attempt < MAX_RETRIES:
                    stats['retry'] += 1
                    time.sleep(RETRY_DELAY)
                    # 重试前重新登录
                    try:
                        bs.logout()
                    except:
                        pass
                    time.sleep(0.5)
                    lg = bs.login()

        process_count += 1

        if success:
            count = save_to_db(conn, ts_code, last_rows)
            update_stock_status(conn, ts_code, 'success', count)
            stats['success'] += 1
        else:
            update_stock_status(conn, ts_code, 'failed')
            stats['fail'] += 1

        if i % 20 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(all_stocks) - i) / rate if rate > 0 else 0
            print(f"[{i}/{len(all_stocks)}] {ts_code} {stock_name} "
                  f"成功={stats['success']} 跳过={stats['skip']} 失败={stats['fail']} 重试={stats['retry']} "
                  f"| {rate:.1f}/s ETA={eta:.0f}s")
            sys.stdout.flush()

    # 登出
    try:
        bs.logout()
    except:
        pass
    conn.close()

    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    print("下载完成")
    print("=" * 60)
    print(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"成功: {stats['success']}  跳过: {stats['skip']}  "
          f"失败: {stats['fail']}  重试: {stats['retry']}")


if __name__ == '__main__':
    main()
