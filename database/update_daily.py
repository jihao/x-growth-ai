#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量更新 astocks_qfq.db 到最新交易日
=====================================

功能：
1. 同步股票列表（自动新增新股、移除退市股）
2. 下载最新K线数据（只下载缺失的日期，速度快）

使用方法：
    python update_daily.py              # 使用默认数据库路径
    python update_daily.py mydb.db      # 指定数据库路径

依赖：
    pip install baostock

经验总结：
1. adjustflag="2" 是官方前复权，质量最高
2. 每次运行自动与baostock股票列表同步
3. 只下载缺失的最新日期，速度极快（约30秒更新5000+只股票）
"""

import baostock as bs
import sqlite3
import socket
import time
import re
import sys
import os
from datetime import datetime, date

socket.setdefaulttimeout(15)


# ======================== 配置区 ========================
# 默认数据库路径（可由命令行参数覆盖）
DEFAULT_DB = "astocks_qfq.db"
# ========================================================


def normal_date(td):
    """统一日期格式 YYYY-MM-DD <-> YYYYMMDD"""
    if '-' in td:
        p = td.split('-')
        return f"{p[0]}-{p[1].zfill(2)}-{p[2].zfill(2)}", f"{p[0]}{p[1].zfill(2)}{p[2].zfill(2)}"
    return f"{td[:4]}-{td[4:6].zfill(2)}-{td[6:8].zfill(2)}", td


def main():
    # 解析命令行参数
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    
    if not os.path.exists(db_path):
        print(f"错误: 数据库不存在 {db_path}")
        print("请先运行 bs_qfq_downloader.py 创建数据库")
        return
    
    # 获取今天日期
    today = date.today()
    TODAY = today.strftime("%Y-%m-%d")
    UPDATE_DATE = today.strftime("%Y%m%d")
    
    print("=" * 60)
    print("增量更新 astocks_qfq.db")
    print("=" * 60)
    print(f"数据库: {db_path}")
    print(f"更新日期: {UPDATE_DATE} ({TODAY})")
    print()
    
    # 1. 登录 baostock
    lg = bs.login()
    if lg.error_code != '0':
        print(f"Baostock 登录失败: {lg.error_msg}")
        return
    print(f"Baostock 登录成功")
    
    # 2. 从 baostock 获取最新A股股票列表
    rs = bs.query_stock_basic()
    bs_stocks = []
    while (rs.error_code == '0') and rs.next():
        bs_stocks.append(rs.get_row_data())
    
    # 筛选A股（60x/00x/30x/68x）
    bs_a_codes = set()
    bs_name_map = {}
    for s in bs_stocks:
        code = s[0]
        name = s[1]
        if re.match(r'(sh\.60|sz\.00|sz\.30|sh\.68)\d+', code):
            ex, num = code.split('.')
            ts_code = f'{num}.{ex.upper()}'
            bs_a_codes.add(ts_code)
            bs_name_map[ts_code] = name
    
    print(f"baostock A股股票数: {len(bs_a_codes)}")
    
    # 3. 同步股票列表
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT ts_code FROM stocks")
    our_codes = set(r[0] for r in c.fetchall())
    
    new_stocks = bs_a_codes - our_codes
    removed_stocks = our_codes - bs_a_codes
    
    print(f"本地股票数: {len(our_codes)}")
    print(f"新增股票: {len(new_stocks)}")
    print(f"移除股票: {len(removed_stocks)}")
    
    # 移除不在baostock的股票（退市等）
    if removed_stocks:
        for code in removed_stocks:
            c.execute("DELETE FROM stocks WHERE ts_code = ?", (code,))
            c.execute("DELETE FROM daily_qfq WHERE ts_code = ?", (code,))
        conn.commit()
        print(f"  已移除: {list(removed_stocks)[:5]}{'...' if len(removed_stocks)>5 else ''}")
    
    # 新增股票
    if new_stocks:
        for code in new_stocks:
            c.execute("INSERT OR IGNORE INTO stocks(ts_code, name) VALUES(?, ?)",
                      (code, bs_name_map.get(code, '')))
        conn.commit()
        print(f"  已添加: {list(new_stocks)[:5]}{'...' if len(new_stocks)>5 else ''}")
    
    # 4. 获取最终股票列表
    c.execute("SELECT ts_code FROM stocks ORDER BY ts_code")
    stocks = [r[0] for r in c.fetchall()]
    print(f"\n最终股票总数: {len(stocks)}")
    print()
    
    # 5. 逐只更新K线数据
    updated = 0
    skipped = 0
    failed = 0
    errors = []
    t0 = time.time()
    
    for i, ts_code in enumerate(stocks):
        code, mkt = ts_code.split('.')
        bs_code = mkt.lower() + '.' + code
        
        # 查最新一条数据库记录
        c.execute(
            "SELECT CAST(trade_date AS TEXT) FROM daily_qfq WHERE ts_code=? AND trade_date!='SKIP' ORDER BY trade_date DESC LIMIT 1",
            (ts_code,)
        )
        row = c.fetchone()
        if row:
            _, latest_db = normal_date(row[0])
            if latest_db >= UPDATE_DATE:
                skipped += 1
                continue
        
        # 下载当天数据
        rs = bs.query_history_k_data_plus(
            code=bs_code,
            fields='date,open,high,low,close,volume,amount',
            start_date=TODAY, end_date=TODAY,
            frequency='d', adjustflag='2'
        )
        data = []
        if rs:
            while rs.next():
                data.append(rs.get_row_data())
        
        if data and data[0][4]:  # 有收盘价
            td = data[0][0].replace('-', '')
            try:
                c.execute(
                    "INSERT OR REPLACE INTO daily_qfq(ts_code,trade_date,open,high,low,close_qfq,volume,amount) VALUES(?,?,?,?,?,?,?,?)",
                    (ts_code, td,
                     float(data[0][1]) if data[0][1] else None,
                     float(data[0][2]) if data[0][2] else None,
                     float(data[0][3]) if data[0][3] else None,
                     float(data[0][4]) if data[0][4] else None,
                     int(float(data[0][5])) if data[0][5] else None,
                     float(data[0][6]) if data[0][6] else None)
                )
                updated += 1
            except Exception as e:
                failed += 1
                errors.append(f"{ts_code}: {e}")
        else:
            # 无当天数据（非交易日）
            skipped += 1
        
        # 每200只报告进度
        if (i + 1) % 200 == 0:
            print(f"  进度: {i+1}/{len(stocks)} | 更新:{updated} 跳过:{skipped} 失败:{failed}")
        
        time.sleep(0.05)
    
    conn.commit()
    conn.close()
    bs.logout()
    
    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print("增量更新完成")
    print("=" * 60)
    print(f"耗时: {elapsed:.1f}s")
    print(f"更新: {updated} 只")
    print(f"跳过: {skipped} 只 (已最新或非交易日)")
    print(f"失败: {failed} 只")
    if errors[:5]:
        for e in errors[:5]:
            print(f"  错误: {e}")


if __name__ == '__main__':
    main()
