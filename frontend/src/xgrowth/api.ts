import type {
  AgentToolResponse,
  AgentModelConfig,
  AgentToolCatalog,
  AppUser,
  AuthResponse,
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
  StockStrategyDetail,
  SystemStatus,
  TradingDaysResponse,
  NotificationSummary,
  ToolRunRecord,
  WatchlistItem
} from "./types";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json() as Promise<T>;
}

export const api = {
  me: () => getJson<{ user: AppUser | null }>("/api/auth/me"),
  login: (payload: { username: string; password: string }) => postJson<AuthResponse>("/api/auth/login", payload),
  register: (payload: { username: string; password: string; display_name?: string }) => postJson<AppUser>("/api/auth/register", payload),
  logout: () => postJson<{ ok: boolean }>("/api/auth/logout"),
  users: () => getJson<AppUser[]>("/api/users"),
  updateUser: (id: number, payload: Partial<Pick<AppUser, "display_name" | "role" | "status">> & { password?: string }) => putJson<AppUser>(`/api/users/${id}`, payload),
  watchlist: (status?: string) => getJson<WatchlistItem[]>(`/api/watchlist${status && status !== "all" ? `?status=${encodeURIComponent(status)}` : ""}`),
  addWatchlist: (payload: Partial<WatchlistItem> & { code: string; name: string }) => postJson<WatchlistItem>("/api/watchlist", payload),
  updateWatchlist: (id: number, payload: Partial<WatchlistItem>) => putJson<WatchlistItem>(`/api/watchlist/${id}`, payload),
  removeWatchlist: (id: number) => deleteJson<{ ok: boolean }>(`/api/watchlist/${id}`),
  health: () => getJson<Health>("/api/health"),
  tradingDays: (lookback = 260) => getJson<TradingDaysResponse>(`/api/calendar/trading-days?lookback=${lookback}`),
  systemStatus: () => getJson<SystemStatus>("/api/tasks/system-status"),
  unreadNotifications: () => getJson<NotificationSummary>("/api/notifications/unread-count"),
  agentTools: () => getJson<AgentToolCatalog>("/api/agent/tools"),
  toolRuns: (limit = 50, toolName?: string) => getJson<ToolRunRecord[]>(`/api/agent/tool-runs?limit=${limit}${toolName ? `&tool_name=${encodeURIComponent(toolName)}` : ""}`),
  runAgentTool: <T = unknown>(toolName: string, payload: Record<string, unknown>) => postJson<AgentToolResponse<T>>(`/api/agent/tools/${toolName}/run`, payload),
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
    credentials: "include",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: "DELETE",
    credentials: "include"
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // Fall back to status text below.
  }
  return `${response.status} ${response.statusText}`;
}
