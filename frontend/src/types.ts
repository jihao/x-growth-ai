export type Health = {
  ok: boolean;
  database: string;
  latest_date?: string;
  start_date?: string;
  stocks?: number;
  rows?: number;
};

export type MarketOverview = {
  date: string;
  previous_date: string;
  stock_count: number;
  up: number;
  down: number;
  flat: number;
  limit_up_like: number;
  limit_down_like: number;
  total_amount_yi: number;
  median_change_pct: number;
  risk_level: string;
};

export type ConcentrationRow = {
  date: string;
  raw_date: string;
  stock_count: number;
  total_amount_yi: number | null;
  cr5_pct: number | null;
  cr10_pct: number | null;
  cr50_pct: number | null;
  top5pct_concentration_pct: number | null;
  effective_count: number | null;
  layer_top5_pct: number | null;
  layer_6_10_pct: number | null;
  layer_11_20_pct: number | null;
  layer_21_50_pct: number | null;
  cr5_pct_change?: number | null;
  cr10_pct_change?: number | null;
  cr50_pct_change?: number | null;
  top5pct_concentration_pct_change?: number | null;
  effective_count_change?: number | null;
};

export type ConcentrationTopRow = {
  rank: number;
  code: string;
  ts_code: string;
  name: string;
  amount_yi: number | null;
  weight_pct: number | null;
  close: number | null;
  change_pct: number | null;
};

export type ConcentrationDistributionRow = {
  rank: number;
  rank_pct: number | null;
  code: string;
  ts_code: string;
  name: string;
  amount_yi: number | null;
  weight_pct: number | null;
  cumulative_weight_pct: number | null;
};

export type ConcentrationResponse = {
  date: string;
  raw_date: string;
  universe: "top250" | "all" | string;
  lookback: number;
  method: string;
  description: string;
  latest: ConcentrationRow | null;
  series: ConcentrationRow[];
  distribution: ConcentrationDistributionRow[];
  top: ConcentrationTopRow[];
};

export type Candidate = {
  code: string;
  ts_code: string;
  name: string;
  score: number;
  group: string;
  action_hint: string;
  close: number;
  change_pct: number | null;
  amount_yi: number;
  amount_rank: number;
  ret20_pct: number | null;
  ret60_pct: number | null;
  drawdown20_pct: number | null;
  macd_status: string;
  kdj_status: string;
  rsi14: number | null;
  td_buy_setup?: number | null;
  td_sell_setup?: number | null;
  td_signal?: "low9" | "high9" | string | null;
  reasons: string[];
  risks: string[];
};

export type CandidateResponse = {
  date: string;
  rows: Candidate[];
};

export type IndicatorRow = {
  date: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close: number;
  volume?: number | null;
  amount?: number | null;
  ma20: number | null;
  ma60: number | null;
  macd_dif: number | null;
  macd_dea: number | null;
  macd_hist: number | null;
  kdj_k: number | null;
  kdj_d: number | null;
  kdj_j: number | null;
  rsi14: number | null;
  td_buy_setup: number | null;
  td_sell_setup: number | null;
  td_signal: "low9" | "high9" | string | null;
  macd_top_divergence: boolean;
  macd_bottom_divergence: boolean;
  macd_top_passivation: boolean;
  macd_bottom_passivation: boolean;
};

export type IndicatorResponse = {
  code: string;
  ts_code: string;
  name: string;
  rows: IndicatorRow[];
  analysis?: StockTechnicalAnalysis;
};

export type StockTechnicalAnalysis = {
  trend?: {
    status: string;
    hint: string;
    ma20: number | null;
    ma60: number | null;
    distance_ma20_pct: number | null;
    distance_ma60_pct: number | null;
  };
  structure?: Array<{ type: string; label: string; hint: string }>;
  fibonacci?: {
    direction?: string;
    start_date?: string;
    end_date?: string;
    low?: number | null;
    high?: number | null;
    levels?: Array<{ ratio: number; label: string; price: number | null; distance_pct: number | null }>;
    nearest?: { ratio: number; label: string; price: number | null; distance_pct: number | null };
    hint?: string;
  };
  time_windows?: Array<{ window: number; distance: number; hint: string }>;
};

export type ReportItem = {
  id: string;
  title: string;
  type: string;
  path: string;
};

export type LearningItem = {
  id: string;
  title: string;
  path: string;
};

export type MarkdownDetail = {
  id: string;
  title: string;
  content: string;
};

export type DailyReviewSource = {
  name: string;
  ok: boolean;
  source: string;
  row_count?: number;
  error?: string | null;
  label?: string;
};

export type DailyReviewMissing = {
  name: string;
  label: string;
  reason: string;
};

export type DailyReviewSection = {
  title: string;
  skills: string[];
  source: string;
  summary?: string;
  [key: string]: unknown;
};

export type DailyReviewDashboard = {
  date: string;
  generated_at: string;
  archive?: {
    status: string;
    database: string;
    generated_at?: string | null;
    updated_at?: string | null;
    cache_version?: number;
  };
  data_sources: DailyReviewSource[];
  missing_data: DailyReviewMissing[];
  cache_paths: {
    manifest: string;
    normalized: string;
    raw: string;
  };
  sections: Record<string, DailyReviewSection>;
};

export type StrategySummary = {
  code: string;
  name: string;
  strategy: string;
  strategy_label: string;
  total_return_pct: number | null;
  buy_hold_return_pct: number | null;
  excess_return_pct: number | null;
  first_entry_date?: string | null;
  first_entry_signal_date?: string | null;
  first_entry_price?: number | null;
  first_entry_hold_return_pct?: number | null;
  first_entry_excess_return_pct?: number | null;
  max_drawdown_pct: number | null;
  trade_count: number;
  win_rate_pct: number | null;
};

export type StrategyTrade = {
  code: string;
  name: string;
  strategy: string;
  strategy_label: string;
  entry_date: string | null;
  entry_price: number | null;
  entry_reason: string | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  status: string;
  holding_days: number | null;
  pnl: number | null;
  return_pct: number | null;
};

export type StrategySignal = {
  date: string;
  signal: "buy" | "sell" | string;
  reason: string;
};

export type StockStrategyDetail = {
  code: string;
  status?: string;
  message?: string;
  run: string | null;
  summary: StrategySummary[];
  trades: StrategyTrade[];
  signals: Record<string, StrategySignal[]>;
};

export type BacktestJob = {
  code: string;
  status: "ready" | "queued" | "running" | "done" | "failed" | string;
  message: string;
  run?: string;
};
