import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { REVIEW_STORAGE_KEY, technicalKeys, type Page, type ReviewNote } from "./appTypes";
import { AppShell } from "./components/AppShell";
import { AuthPage, UserManagementPage } from "./components/AuthPages";
import {
  ConcentrationPage,
  DataPage,
  HomePage,
  HistoryReportsPage,
  LearningPage,
  ReportsPage,
  ScreenPage,
  StockPage,
  StrategyPage
} from "./components/AppSections";
import type {
  BacktestJob,
  Candidate,
  CandidateResponse,
  ConcentrationResponse,
  Health,
  IndicatorResponse,
  KlinePatternResponse,
  LearningItem,
  MarketOverview,
  ReportItem,
  StockAgentBrief,
  StrategySearchResponse,
  StockStrategyDetail,
  StrategySummary
} from "./types";
import type { AppUser } from "./types";
import { sleep } from "./utils/async";
import { loadReviewNotes } from "./utils/reviewStorage";

export function App() {
  const [page, setPage] = useState<Page>("home");
  const [health, setHealth] = useState<Health | null>(null);
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [indicators, setIndicators] = useState<IndicatorResponse | null>(null);
  const [patterns, setPatterns] = useState<KlinePatternResponse | null>(null);
  const [matchedStrategies, setMatchedStrategies] = useState<StrategySearchResponse | null>(null);
  const [agentBrief, setAgentBrief] = useState<StockAgentBrief | null>(null);
  const [agentBriefLoading, setAgentBriefLoading] = useState(false);
  const [stockStrategies, setStockStrategies] = useState<StockStrategyDetail | null>(null);
  const [backtestJob, setBacktestJob] = useState<BacktestJob | null>(null);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [learning, setLearning] = useState<LearningItem[]>([]);
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [concentration, setConcentration] = useState<ConcentrationResponse | null>(null);
  const [reviewNotes, setReviewNotes] = useState<Record<string, ReviewNote>>({});
  const [groupFilter, setGroupFilter] = useState("全部");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState<AppUser | null>(null);
  const [authChecking, setAuthChecking] = useState(true);

  useEffect(() => {
    api.me()
      .then((payload) => setCurrentUser(payload.user))
      .catch(() => setCurrentUser(null))
      .finally(() => setAuthChecking(false));
  }, []);

  async function loadCore() {
    setLoading(true);
    setError(null);
    try {
      const [healthData, overviewData, reportData, learningData, strategyData] = await Promise.all([
        api.health(),
        api.overview(),
        api.reports(),
        api.learning(),
        api.strategies()
      ]);
      setHealth(healthData);
      setOverview(overviewData);
      setReports(reportData);
      setLearning(learningData);
      setStrategies((strategyData.summary as StrategySummary[]) ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }

    api.candidates(50)
      .then((candidateData: CandidateResponse) => {
        setCandidates(candidateData.rows);
        setSelected((current) => current ?? candidateData.rows[0] ?? null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "候选池加载失败"));
    api.concentration(60, "top250")
      .then(setConcentration)
      .catch((err) => setError(err instanceof Error ? err.message : "集中度加载失败"));
  }

  useEffect(() => {
    if (!currentUser) return;
    loadCore();
    setReviewNotes(loadReviewNotes());
  }, [currentUser?.id]);

  async function logout() {
    await api.logout().catch(() => undefined);
    setCurrentUser(null);
    setPage("home");
  }

  function saveReviewNote(note: ReviewNote) {
    setReviewNotes((current) => {
      const next = { ...current, [note.code]: note };
      window.localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    const current = selected;
    setPatterns(null);
    setMatchedStrategies(null);
    setAgentBrief(null);
    setAgentBriefLoading(true);
    api.indicators(current.code).then(setIndicators).catch((err) => setError(err.message));
    api.klinePatterns(current.code)
      .then((payload) => {
        if (!cancelled) setPatterns(payload.result);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "K线形态加载失败"));
    api.searchStrategyKnowledge(strategyQueryForCandidate(current), 3)
      .then((payload) => {
        if (!cancelled) setMatchedStrategies(payload.result);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "战法匹配加载失败"));
    api.stockAgentBrief(current.code)
      .then((payload) => {
        if (!cancelled) setAgentBrief(payload.result);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "AI操作建议加载失败"))
      .finally(() => {
        if (!cancelled) setAgentBriefLoading(false);
      });
    async function loadStrategyWithAutoRun() {
      try {
        setBacktestJob(null);
        const detail = await api.stockStrategies(current.code);
        if (cancelled) return;
        setStockStrategies(detail);
        const missingStrategy = !technicalKeys.every((key) => detail.summary.some((item) => item.strategy === key));
        if (detail.status !== "not_in_latest_backtest" && !missingStrategy) return;
        const job = await api.runStockBacktest(current.code);
        if (cancelled) return;
        setBacktestJob(job);
        if (["ready", "done"].includes(job.status)) {
          setStockStrategies(await api.stockStrategies(current.code));
          return;
        }
        for (let attempt = 0; attempt < 20; attempt += 1) {
          await sleep(3000);
          if (cancelled) return;
          const next = await api.stockStrategies(current.code);
          setStockStrategies(next);
          if (next.status === "ok") {
            setBacktestJob({ code: current.code, status: "done", message: "单股策略回测已完成。" });
            return;
          }
          const nextJob = await api.runStockBacktest(current.code);
          setBacktestJob(nextJob);
          if (nextJob.status === "failed") return;
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "策略验证加载失败");
      }
    }
    loadStrategyWithAutoRun();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const filteredCandidates = useMemo(() => {
    if (groupFilter === "全部") return candidates;
    return candidates.filter((item) => item.group === groupFilter);
  }, [candidates, groupFilter]);

  if (authChecking) return <div className="app-boot">正在检查登录状态...</div>;
  if (!currentUser) return <AuthPage onAuthenticated={setCurrentUser} />;

  return (
    <AppShell page={page} error={error} loading={loading} user={currentUser} onPageChange={setPage} onRefresh={loadCore} onLogout={logout}>
      {page === "home" && (
        <HomePage
          health={health}
          overview={overview}
          candidates={candidates}
          learning={learning}
          concentration={concentration}
          reviewNotes={reviewNotes}
          openStock={(candidate) => {
            setSelected(candidate);
            setPage("stock");
          }}
        />
      )}
      {page === "screen" && (
        <ScreenPage
          candidates={filteredCandidates}
          concentration={concentration}
          groupFilter={groupFilter}
          setGroupFilter={setGroupFilter}
          selected={selected}
          setSelected={setSelected}
          openStock={(candidate) => {
            setSelected(candidate);
            setPage("stock");
          }}
        />
      )}
      {page === "stock" && (
        <StockPage
          selected={selected}
          agentBrief={agentBrief}
          agentBriefLoading={agentBriefLoading}
          indicators={indicators}
          patterns={patterns}
          matchedStrategies={matchedStrategies}
          strategyDetail={stockStrategies}
          backtestJob={backtestJob}
          reviewNote={selected ? reviewNotes[selected.code] : undefined}
          onSaveReview={saveReviewNote}
        />
      )}
      {page === "strategy" && <StrategyPage strategies={strategies} selected={selected} matchedStrategies={matchedStrategies} />}
      {page === "concentration" && (
        <ConcentrationPage
          candidates={candidates}
          openStock={(candidate) => {
            setSelected(candidate);
            setPage("stock");
          }}
        />
      )}
      {page === "reports" && <ReportsPage reports={reports} />}
      {page === "history" && <HistoryReportsPage reports={reports} />}
      {page === "learning" && <LearningPage learning={learning} />}
      {page === "data" && <DataPage health={health} overview={overview} />}
      {page === "users" && <UserManagementPage currentUser={currentUser} />}
    </AppShell>
  );
}

function strategyQueryForCandidate(candidate: Candidate): string {
  return [
    candidate.group,
    candidate.action_hint,
    candidate.macd_status,
    candidate.kdj_status,
    candidate.rsi14 !== null && candidate.rsi14 !== undefined ? `RSI${candidate.rsi14.toFixed(1)}` : "",
    ...(candidate.reasons ?? []),
    ...(candidate.risks ?? [])
  ].filter(Boolean).join(" ");
}
