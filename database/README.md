# A 股前复权日线数据库说明

本目录保存从 baostock 下载的 A 股前复权日线数据，主要用于后续策略研究与回测。

核心数据源是 `astocks_qfq.db`，SQLite 格式，价格字段使用 baostock 官方前复权口径：`adjustflag="2"`。后续做策略回测时，建议优先使用该数据库中的 `daily_qfq` 表作为统一行情源。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `astocks_qfq.db` | A 股前复权日线 SQLite 数据库 |
| `bs_qfq_downloader.py` | 初始全量下载脚本，已用于构建初始数据库 |
| `update_daily.py` | 增量更新脚本，用于把数据库更新到最新交易日 |
| `backfill_qfq_to_yesterday.py` | 缺口补齐脚本，用于把数据库最大交易日之后的缺失交易日补到昨天 |

当前数据库概况：

| 指标 | 当前值 |
| --- | ---: |
| 数据库大小 | 约 1.8 GB |
| 日线记录数 | 9,842,921 |
| 股票数 | 5,201 |
| 最早交易日 | 20100104 |
| 最新交易日 | 20260430 |

以上统计来自当前 `astocks_qfq.db`，后续运行 `update_daily.py` 后会变化。

## 数据口径

- 市场范围：A 股股票。
- 时间频率：日线。
- 复权方式：前复权，使用 baostock `adjustflag="2"`。
- 日期格式：`YYYYMMDD` 字符串，例如 `20260430`。
- 股票代码格式：`000001.SZ`、`600000.SH`。
- 价格字段：`open`、`high`、`low`、`close_qfq` 均为前复权价格。
- 成交量字段：`volume`，来自 baostock。
- 成交额字段：`amount`，来自 baostock。

注意：前复权价格适合研究历史收益率、技术指标、择时信号和策略回测；如果研究真实成交价格、历史市值、分红送转事件本身，需额外使用未复权行情或公司行动数据。

## 数据表结构

### `stocks`

股票基础表。

```sql
CREATE TABLE stocks (
    ts_code TEXT PRIMARY KEY,
    name TEXT
);
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | TEXT | 股票代码，格式如 `000001.SZ` |
| `name` | TEXT | 股票名称 |

示例：

```text
000001.SZ | 平安银行
600000.SH | 浦发银行
```

### `daily_qfq`

前复权日线行情表。

```sql
CREATE TABLE daily_qfq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close_qfq REAL,
    volume INTEGER,
    amount REAL,
    UNIQUE (ts_code, trade_date)
);
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 自增主键 |
| `ts_code` | TEXT | 股票代码 |
| `trade_date` | TEXT | 交易日，`YYYYMMDD` |
| `open` | REAL | 前复权开盘价 |
| `high` | REAL | 前复权最高价 |
| `low` | REAL | 前复权最低价 |
| `close_qfq` | REAL | 前复权收盘价 |
| `volume` | INTEGER | 成交量 |
| `amount` | REAL | 成交额 |

索引：

```sql
CREATE UNIQUE INDEX sqlite_autoindex_daily_qfq_1
ON daily_qfq(ts_code, trade_date);

CREATE INDEX idx_daily_qfq_tscode ON daily_qfq(ts_code);
CREATE INDEX idx_daily_qfq_date ON daily_qfq(trade_date);
```

其中 `(ts_code, trade_date)` 唯一约束用于防止同一股票同一交易日重复写入。

## 常用查询

查看数据库整体范围：

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT ts_code) AS stocks,
    MIN(trade_date) AS start_date,
    MAX(trade_date) AS end_date
FROM daily_qfq;
```

查询单只股票日线：

```sql
SELECT
    trade_date,
    open,
    high,
    low,
    close_qfq,
    volume,
    amount
FROM daily_qfq
WHERE ts_code = '000001.SZ'
ORDER BY trade_date;
```

查询某个日期的全市场截面：

```sql
SELECT
    d.ts_code,
    s.name,
    d.open,
    d.high,
    d.low,
    d.close_qfq,
    d.volume,
    d.amount
FROM daily_qfq d
LEFT JOIN stocks s ON s.ts_code = d.ts_code
WHERE d.trade_date = '20260430'
ORDER BY d.ts_code;
```

检查最近交易日覆盖股票数：

```sql
SELECT trade_date, COUNT(DISTINCT ts_code) AS stock_count
FROM daily_qfq
GROUP BY trade_date
ORDER BY trade_date DESC
LIMIT 10;
```

## Python 使用示例

```python
import sqlite3
import pandas as pd

db_path = "database/astocks_qfq.db"

with sqlite3.connect(db_path) as conn:
    df = pd.read_sql_query(
        """
        SELECT trade_date, open, high, low, close_qfq, volume, amount
        FROM daily_qfq
        WHERE ts_code = ?
          AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        conn,
        params=("000001.SZ", "20200101", "20260430"),
    )

df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
df = df.set_index("trade_date")
df["ret"] = df["close_qfq"].pct_change()
```

做全市场回测时，建议按日期或股票分批读取，避免一次性把 1.8 GB 数据全部加载到内存。

## 更新数据库

进入 `database` 目录后运行：

```bash
python update_daily.py
```

或在项目根目录指定数据库路径：

```bash
python database/update_daily.py database/astocks_qfq.db
```

`update_daily.py` 会：

1. 登录 baostock。
2. 同步最新 A 股股票列表。
3. 删除 baostock 股票列表中已不存在的股票及其行情。
4. 添加新股。
5. 对每只股票检查本地最新交易日。
6. 只下载当天缺失数据并写入 `daily_qfq`。

如果当天不是交易日，或 baostock 当天数据尚未更新，脚本会跳过对应股票。

依赖：

```bash
pip install baostock
```

如果使用项目后端环境，也可以优先使用项目已有 Python 环境。

## 补齐缺失交易日

如果数据库最大交易日落后较多，优先使用 `backfill_qfq_to_yesterday.py` 补齐缺口。该脚本会先调用 baostock 交易日历，找出本地最大交易日之后到昨天之间的真实交易日，再逐只股票下载这些交易日的前复权日线。

先检查缺失交易日，不写入数据库：

```bash
cd /Users/hao/github/x-growth-ai/database
../backend/.venv/bin/python -u backfill_qfq_to_yesterday.py --dry-run
```

确认无误后执行补齐：

```bash
cd /Users/hao/github/x-growth-ai/database
../backend/.venv/bin/python -u backfill_qfq_to_yesterday.py 2>&1 | tee backfill_qfq.log
```

常用参数：

```bash
# 指定截止日期
../backend/.venv/bin/python -u backfill_qfq_to_yesterday.py --end-date 2026-06-09

# 强制从某个日期开始扫描
../backend/.venv/bin/python -u backfill_qfq_to_yesterday.py --start-date 2026-05-01

# 只处理前 20 只股票，用于测试
../backend/.venv/bin/python -u backfill_qfq_to_yesterday.py --limit 20
```

补齐完成后检查：

```bash
sqlite3 astocks_qfq.db "SELECT COUNT(*), COUNT(DISTINCT ts_code), MIN(trade_date), MAX(trade_date) FROM daily_qfq WHERE trade_date!='SKIP';"
sqlite3 astocks_qfq.db "SELECT trade_date, COUNT(DISTINCT ts_code) FROM daily_qfq WHERE trade_date!='SKIP' GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10;"
```

## 初始全量下载

`bs_qfq_downloader.py` 是全量下载脚本，适合在需要重建数据库时使用。当前数据库已经完成初始下载，日常不需要重复运行该脚本。

默认配置：

```python
DB_PATH = "astocks_qfq.db"
START_DATE = "2010-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")
MAX_RETRIES = 5
RETRY_DELAY = 2
RELOGIN_INTERVAL = 200
```

脚本经验规则：

- 使用 baostock 官方前复权 `adjustflag="2"`。
- 每处理约 200 只股票重新登录一次，降低会话失效概率。
- 单只股票失败后最多重试 5 次。
- 查询日期范围一次传完整区间，不按年份拆分。

重要注意：当前 `astocks_qfq.db` 的实际 `stocks` 表字段是 `ts_code, name`。`bs_qfq_downloader.py` 中的新建表结构包含 `stock_name, market, download_status, record_count, last_update` 等字段，这是全量重建脚本自身的结构。不要直接用它覆盖或混用当前数据库；如需重建，建议先备份当前 `astocks_qfq.db`，再在新的空数据库上运行并确认表结构与 `update_daily.py` 兼容。

## 回测使用建议

- 使用 `close_qfq` 计算收益率和技术指标。
- 同一策略内保持复权口径一致，不要混用未复权、后复权和前复权价格。
- 按 `trade_date` 升序计算信号，避免未来函数。
- 生成当日收盘后信号时，下一交易日开盘或收盘成交更符合回测约束。
- 全市场截面因子建议先限定日期范围，再 join 股票名称。
- 新股上市前没有行情，回测时应按实际可用数据自然进入股票池。
- 停牌日通常没有日线记录，不要默认补齐价格，除非策略明确需要停牌处理逻辑。
- 数据库更新后，先检查 `MAX(trade_date)` 和最近交易日覆盖股票数，再开始新一轮研究。

## 数据质量检查

常用检查 SQL：

```sql
-- 是否有重复键，正常应返回 0 行
SELECT ts_code, trade_date, COUNT(*) AS n
FROM daily_qfq
GROUP BY ts_code, trade_date
HAVING n > 1;

-- 检查空收盘价，正常应尽量为 0
SELECT COUNT(*)
FROM daily_qfq
WHERE close_qfq IS NULL;

-- 检查最近日期
SELECT MAX(trade_date)
FROM daily_qfq;

-- 检查股票级别数据范围
SELECT ts_code, MIN(trade_date), MAX(trade_date), COUNT(*)
FROM daily_qfq
WHERE ts_code IN ('000001.SZ', '600000.SH')
GROUP BY ts_code;
```

## 推荐读取约定

后续策略代码中建议统一封装一个行情读取函数，固定输出字段名：

```text
ts_code, trade_date, open, high, low, close, volume, amount
```

其中 `close` 可以从数据库字段 `close_qfq` 映射而来。这样上层策略逻辑不需要关心数据库内部字段名，也便于未来替换数据源。
