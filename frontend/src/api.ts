import type {
  AgentToolResponse,
  AgentModelConfig,
  CandidateResponse,
  CandidateRollingBacktest,
  BacktestJob,
  ConcentrationResponse,
  DailyReviewDashboard,
  Health,
  IndicatorResponse,
  LearningItem,
  MarkdownDetail,
  MarketOverview,
  KlinePatternResponse,
  ReportItem,
  StrategyListResponse,
  StrategySearchResponse,
  StockAgentBrief,
  StockStrategyDetail
} from "./types";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => getJson<Health>("/api/health"),
  overview: () => getJson<MarketOverview>("/api/market/overview"),
  concentration: (lookback = 120, universe = "top250") => getJson<ConcentrationResponse>(`/api/market/concentration?lookback=${lookback}&universe=${universe}`),
  candidates: (limit = 50, refresh = false) => getJson<CandidateResponse>(`/api/screen/candidates?limit=${limit}${refresh ? "&refresh=true" : ""}`),
  indicators: (code: string) => getJson<IndicatorResponse>(`/api/stocks/${code}/indicators`),
  reports: () => getJson<ReportItem[]>("/api/reports"),
  report: (id: string) => getJson<MarkdownDetail>(`/api/reports/${id}`),
  dailyReview: (date?: string) => getJson<DailyReviewDashboard>(`/api/review/daily${date ? `?date=${date}` : ""}`),
  refreshDailyReview: (date?: string) => postJson<DailyReviewDashboard>(`/api/review/daily/refresh${date ? `?date=${date}` : ""}`),
  learning: () => getJson<LearningItem[]>("/api/learning"),
  learningDetail: (id: string) => getJson<MarkdownDetail>(`/api/learning/${id}`),
  strategies: () => getJson<{ latest: string | null; summary: unknown[] }>("/api/strategies/backtests"),
  candidateRollingBacktest: (lookback = 60, limit = 20) => getJson<CandidateRollingBacktest>(`/api/strategies/candidate-rolling-backtest?lookback=${lookback}&limit=${limit}`),
  stockStrategies: (code: string) => getJson<StockStrategyDetail>(`/api/strategies/backtests/${code}`),
  runStockBacktest: (code: string) => postJson<BacktestJob>(`/api/strategies/backtests/${code}/run`),
  klinePatterns: (code: string) => postJson<AgentToolResponse<KlinePatternResponse>>(`/api/agent/tools/kline_patterns/run`, { code }),
  stockAgentBrief: (code: string) => postJson<AgentToolResponse<StockAgentBrief>>(`/api/agent/tools/stock_agent_brief/run`, { code }),
  searchStrategyKnowledge: (query: string, topK = 3) => postJson<AgentToolResponse<StrategySearchResponse>>(`/api/agent/tools/search_strategy/run`, { query, top_k: topK }),
  listStrategyKnowledge: () => postJson<AgentToolResponse<StrategyListResponse>>(`/api/agent/tools/list_strategies/run`, {}),
  getStrategyKnowledge: (filenameOrTitle: string) => postJson<AgentToolResponse<unknown>>(`/api/agent/tools/get_strategy/run`, { filename_or_title: filenameOrTitle }),
  agentModelConfig: () => getJson<AgentModelConfig>("/api/agent/model-config"),
  saveAgentModelConfig: (payload: Partial<AgentModelConfig> & { api_key?: string }) => putJson<AgentModelConfig>("/api/agent/model-config", payload)
};

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}
