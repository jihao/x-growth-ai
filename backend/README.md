# x-growth-ai backend

Python backend for A-share research workflows. The first milestone is Markdown
daily and weekly review reports that can run with or without live market data.

## Usage

```bash
uv run x-growth-backend daily-review
uv run x-growth-backend daily-review --date 2026-05-29
uv run x-growth-backend daily-review --no-live-data
uv run x-growth-backend backfill --start 2026-05-25 --end 2026-05-29
uv run x-growth-backend weekly-review --start 2026-05-25 --end 2026-05-29
```

Reports are written to the repository-level `reports/` directory.

Each run also writes a local data snapshot:

```text
data/daily/YYYY-MM-DD/
  manifest.json
  raw/          # copied skill artifacts, such as xlsx/csv/txt
  normalized/   # parsed JSON/CSV datasets and derived metrics
```

When there is an earlier snapshot under `data/daily/`, the report automatically
adds day-over-day changes for concentration, market breadth, and Top50 industry
turnover share.

`backfill` runs dates in order and skips Saturdays and Sundays. It does not yet
apply an A-share holiday calendar; holiday-like failures are reported in the
command summary.

## Data sources

- Index snapshot: `.skills/mx-skills/mx-finance-data/scripts/get_data.py`
- Market breadth: `.skills/mx-skills/mx-finance-data/scripts/get_data.py`
- Stock/sector screens: `.skills/mx-skills/mx-stocks-screener/scripts/get_data.py`
- K-line wrapper: `.skills/FinClaw/cn-stock-data/scripts/cn_stock_data.py`

The backend does not fetch market data directly. It calls scripts from `.skills/`
and only parses their generated artifacts into the Markdown report. If the local
proxy or network cannot reach the skill's upstream service, the command still
writes a complete report template and records the data gap in the final section.
