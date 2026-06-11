import type {
  CandidateResponse,
  BacktestJob,
  ConcentrationResponse,
  DailyReviewDashboard,
  Health,
  IndicatorResponse,
  LearningItem,
  MarkdownDetail,
  MarketOverview,
  ReportItem,
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
  candidates: (limit = 50) => getJson<CandidateResponse>(`/api/screen/candidates?limit=${limit}`),
  indicators: (code: string) => getJson<IndicatorResponse>(`/api/stocks/${code}/indicators`),
  reports: () => getJson<ReportItem[]>("/api/reports"),
  report: (id: string) => getJson<MarkdownDetail>(`/api/reports/${id}`),
  dailyReview: (date?: string) => getJson<DailyReviewDashboard>(`/api/review/daily${date ? `?date=${date}` : ""}`),
  refreshDailyReview: (date?: string) => postJson<DailyReviewDashboard>(`/api/review/daily/refresh${date ? `?date=${date}` : ""}`),
  learning: () => getJson<LearningItem[]>("/api/learning"),
  learningDetail: (id: string) => getJson<MarkdownDetail>(`/api/learning/${id}`),
  strategies: () => getJson<{ latest: string | null; summary: unknown[] }>("/api/strategies/backtests"),
  stockStrategies: (code: string) => getJson<StockStrategyDetail>(`/api/strategies/backtests/${code}`),
  runStockBacktest: (code: string) => postJson<BacktestJob>(`/api/strategies/backtests/${code}/run`)
};

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}
