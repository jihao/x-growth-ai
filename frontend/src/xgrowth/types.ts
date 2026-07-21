export type Health = {
  ok: boolean;
  database: string;
  latest_date?: string;
  start_date?: string;
  stocks?: number;
  rows?: number;
};

export type AppUser = {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "user" | string;
  status: "active" | "disabled" | string;
  created_at: string;
  updated_at: string;
  last_login_at?: string | null;
};

export type AuthResponse = {
  user: AppUser;
  expires_at?: string;
};

export type TradingDaysResponse = {
  ok: boolean;
  source: string;
  dates: string[];
  latest: string | null;
  previous: string | null;
  count: number;
  start?: string | null;
  end?: string | null;
};

export type SystemStatus = {
  ok: boolean;
  generated_at: string;
  latest_trade_date?: string | null;
  database?: string;
  services: Array<{
    key: string;
    label: string;
    status: "ok" | "warning" | "error" | "running" | string;
    message: string;
  }>;
};

export type NotificationSummary = {
  count: number;
  items: Array<{
    id: string;
    title: string;
    status: string;
    message: string;
  }>;
};

export type AgentToolDefinition = {
  type: "function" | string;
  function: {
    name: string;
    description: string;
    parameters: {
      properties?: Record<string, unknown>;
      required?: string[];
      [key: string]: unknown;
    };
  };
};

export type AgentToolCatalog = {
  count: number;
  tools: AgentToolDefinition[];
};

export type ToolRunRecord = {
  id: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  result_summary: string;
  error?: string | null;
  duration_ms: number;
  user_id?: number | null;
  created_at: string;
};

export type WatchlistStatus = "watching" | "pullback" | "breakout" | "holding" | "paused" | "removed" | string;
export type WatchlistPriority = "high" | "medium" | "low" | string;

export type WatchlistItem = {
  id: number;
  code: string;
  ts_code?: string | null;
  name: string;
  status: WatchlistStatus;
  priority: WatchlistPriority;
  source: string;
  note: string;
  tags: string[];
  target_price?: number | null;
  stop_loss?: number | null;
  user_id?: number | null;
  created_at: string;
  updated_at: string;
  last_seen_at: string;
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
  raw_date?: string;
  generated_at?: string;
  cache_version?: number;
  cache?: {
    status: "hit" | "created" | "refreshed" | string;
    path?: string;
    version?: number;
  };
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

export type AgentToolResponse<T> = {
  ok: boolean;
  tool: string;
  result: T;
  error?: string;
};

export type KlinePattern = {
  name: string;
  type: "bullish" | "bearish" | "neutral" | string;
  confidence: number;
  date?: string | null;
  description: string;
};

export type KlinePatternResponse = {
  code: string;
  ts_code: string;
  name: string;
  count: number;
  patterns: KlinePattern[];
  summary: {
    bias: "bullish" | "bearish" | "neutral" | "none" | string;
    counts: Record<string, number>;
    message: string;
  };
};

export type StrategyKnowledgeItem = {
  filename: string;
  title: string;
  sections: string[];
  excerpt: string;
  score?: number;
  matched_terms?: string[];
  key_conditions?: string[];
  buy_signals?: string[];
  sell_signals?: string[];
  risk_notes?: string[];
  content?: string;
};

export type StrategySearchResponse = {
  query: string;
  count: number;
  results: StrategyKnowledgeItem[];
};

export type StrategyListResponse = {
  total: number;
  strategies: StrategyKnowledgeItem[];
};

export type AgentBriefEvidence = {
  label: string;
  value: string | number;
  hint: string;
  tone: "active" | "watch" | "defensive" | "neutral" | string;
};

export type StockAgentBrief = {
  code: string;
  name: string;
  engine?: AgentModelEngine;
  status: string;
  action: string;
  tone: "active" | "watch" | "defensive" | "neutral" | string;
  summary: string;
  position_sizing: string;
  buy_signal: boolean;
  supporting_reasons: string[];
  risk_factors: string[];
  next_steps: string[];
  invalidation: string[];
  evidence: AgentBriefEvidence[];
  strategy_query: string;
  matched_strategies: StrategyKnowledgeItem[];
  pattern_summary?: KlinePatternResponse["summary"];
  source_tools: string[];
};

export type AgentModelEngine = {
  mode: "rules" | "llm" | string;
  label: string;
  model: string;
  base_url: string;
  api_key_configured: boolean;
  note: string;
};

export type AgentModelConfig = {
  mode: "rules" | "llm" | string;
  provider: string;
  base_url: string;
  model: string;
  temperature: number;
  max_tokens: number;
  updated_at?: string | null;
  api_key_configured: boolean;
  api_key_masked: string;
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

export type CandidateRollingBacktest = {
  status: string;
  generated_at?: string;
  method?: string;
  description?: string;
  start_date?: string;
  end_date?: string;
  parameters?: Record<string, string | number | boolean | null>;
  summary?: {
    total_return_pct?: number | null;
    annual_return_pct?: number | null;
    max_drawdown_pct?: number | null;
    trade_count?: number;
    closed_trade_count?: number;
    win_rate_pct?: number | null;
    average_holding_days?: number | null;
    final_equity?: number | null;
    open_positions?: number;
    entry_signal_count?: number;
    candidate_days?: number;
  };
  trades: Array<{
    code: string;
    name: string;
    entry_signal_date?: string | null;
    entry_date?: string | null;
    entry_price?: number | null;
    entry_reason?: string | null;
    exit_signal_date?: string | null;
    exit_date?: string | null;
    exit_price?: number | null;
    exit_reason?: string | null;
    status?: string;
    holding_days?: number | null;
    pnl?: number | null;
    return_pct?: number | null;
  }>;
  equity: Array<{
    date: string;
    cash: number | null;
    market_value: number | null;
    equity: number | null;
    positions: number;
  }>;
  daily_candidates?: Array<{
    date: string;
    count: number;
    top: Candidate[];
  }>;
  notes?: string[];
  cache?: {
    status: string;
    path: string;
  };
};
