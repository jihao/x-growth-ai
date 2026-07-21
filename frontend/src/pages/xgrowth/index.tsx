import { PageContainer } from '@ant-design/pro-components';
import { history, useLocation, useModel } from '@umijs/max';
import { Alert, Spin } from 'antd';
import React, { useEffect, useMemo, useState } from 'react';
import { api } from '@/xgrowth/api';
import { REVIEW_STORAGE_KEY, technicalKeys, type Page, type ReviewNote } from '@/xgrowth/appTypes';
import {
  ConcentrationPage,
  DataPage,
  HomePage,
  HistoryReportsPage,
  LearningPage,
  ReportsPage,
  ScreenPage,
  StockPage,
  StrategyPage,
  ToolsPage,
  WatchlistPage,
} from '@/xgrowth/components/AppSections';
import { UserManagementPage } from '@/xgrowth/components/AuthPages';
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
  StockStrategyDetail,
  StrategySearchResponse,
  StrategySummary,
  WatchlistItem,
} from '@/xgrowth/types';
import { sleep } from '@/xgrowth/utils/async';
import { loadReviewNotes } from '@/xgrowth/utils/reviewStorage';
import '@/xgrowth/styles.css';

const pageFromPath = (pathname: string): Page => {
  const segments = pathname.split('/').filter(Boolean);
  const xgrowthIndex = segments.indexOf('xgrowth');
  const key = segments[xgrowthIndex + 1] as Page | undefined;
  if (
    key &&
    ['home', 'screen', 'stock', 'strategy', 'concentration', 'reports', 'history', 'learning', 'data', 'tools', 'watchlist', 'users'].includes(key)
  ) {
    return key;
  }
  return 'home';
};

const stockCodeFromPath = (pathname: string): string | null => {
  const segments = pathname.split('/').filter(Boolean);
  const xgrowthIndex = segments.indexOf('xgrowth');
  if (segments[xgrowthIndex + 1] !== 'stock') return null;
  return normalizeStockRouteCode(segments[xgrowthIndex + 2]);
};

const normalizeStockRouteCode = (value?: string): string | null => {
  if (!value) return null;
  const decoded = decodeURIComponent(value).trim();
  const compact = decoded.split('.', 1)[0].replace(/\D/g, '');
  return compact ? compact.padStart(6, '0').slice(-6) : null;
};

const XGrowthPage: React.FC = () => {
  const location = useLocation();
  const page = pageFromPath(location.pathname);
  const routeStockCode = useMemo(() => stockCodeFromPath(location.pathname), [location.pathname]);
  const { initialState } = useModel('@@initialState');
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
  const [groupFilter, setGroupFilter] = useState('全部');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadCore() {
    setLoading(true);
    setError(null);
    try {
      const [healthData, overviewData, reportData, learningData, strategyData] = await Promise.all([
        api.health(),
        api.overview(),
        api.reports(),
        api.learning(),
        api.strategies(),
      ]);
      setHealth(healthData);
      setOverview(overviewData);
      setReports(reportData);
      setLearning(learningData);
      setStrategies((strategyData.summary as StrategySummary[]) ?? []);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '加载失败');
    } finally {
      setLoading(false);
    }

    api
      .candidates(200)
      .then((candidateData: CandidateResponse) => {
        setCandidates(candidateData.rows);
        const routeCandidate = routeStockCode ? candidateData.rows.find((item) => item.code === routeStockCode) : null;
        setSelected((current) => routeCandidate ?? (routeStockCode ? candidateFromCode(routeStockCode) : current ?? candidateData.rows[0] ?? null));
      })
      .catch((candidateError) => setError(candidateError instanceof Error ? candidateError.message : '候选池加载失败'));
    api
      .concentration(60, 'top250')
      .then(setConcentration)
      .catch((concentrationError) =>
        setError(concentrationError instanceof Error ? concentrationError.message : '集中度加载失败'),
      );
  }

  useEffect(() => {
    loadCore();
    setReviewNotes(loadReviewNotes());
  }, []);

  useEffect(() => {
    if (!routeStockCode || !candidates.length) return;
    const routeCandidate = candidates.find((item) => item.code === routeStockCode);
    if (routeCandidate && selected?.code !== routeCandidate.code) {
      setSelected(routeCandidate);
    } else if (!routeCandidate && selected?.code !== routeStockCode) {
      setSelected(candidateFromCode(routeStockCode));
    }
  }, [routeStockCode, candidates, selected?.code]);

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
    api.indicators(current.code).then(setIndicators).catch((indicatorError) => setError(indicatorError.message));
    api
      .klinePatterns(current.code)
      .then((payload) => {
        if (!cancelled) setPatterns(payload.result);
      })
      .catch((patternError) => setError(patternError instanceof Error ? patternError.message : 'K线形态加载失败'));
    api
      .searchStrategyKnowledge(strategyQueryForCandidate(current), 3)
      .then((payload) => {
        if (!cancelled) setMatchedStrategies(payload.result);
      })
      .catch((strategyError) => setError(strategyError instanceof Error ? strategyError.message : '战法匹配加载失败'));
    api
      .stockAgentBrief(current.code)
      .then((payload) => {
        if (!cancelled) setAgentBrief(payload.result);
      })
      .catch((briefError) => setError(briefError instanceof Error ? briefError.message : 'AI操作建议加载失败'))
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
        if (detail.status !== 'not_in_latest_backtest' && !missingStrategy) return;
        const job = await api.runStockBacktest(current.code);
        if (cancelled) return;
        setBacktestJob(job);
        if (['ready', 'done'].includes(job.status)) {
          setStockStrategies(await api.stockStrategies(current.code));
          return;
        }
        for (let attempt = 0; attempt < 20; attempt += 1) {
          await sleep(3000);
          if (cancelled) return;
          const next = await api.stockStrategies(current.code);
          setStockStrategies(next);
          if (next.status === 'ok') {
            setBacktestJob({ code: current.code, status: 'done', message: '单股策略回测已完成。' });
            return;
          }
          const nextJob = await api.runStockBacktest(current.code);
          setBacktestJob(nextJob);
          if (nextJob.status === 'failed') return;
        }
      } catch (strategyError) {
        if (!cancelled) setError(strategyError instanceof Error ? strategyError.message : '策略验证加载失败');
      }
    }
    loadStrategyWithAutoRun();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const filteredCandidates = useMemo(() => {
    if (groupFilter === '全部') return candidates;
    return candidates.filter((item) => item.group === groupFilter);
  }, [candidates, groupFilter]);
  const groupCounts = useMemo(() => {
    const next: Record<string, number> = { 全部: candidates.length };
    candidates.forEach((item) => {
      next[item.group] = (next[item.group] ?? 0) + 1;
    });
    return next;
  }, [candidates]);

  const openStock = (candidate: Candidate) => {
    setSelected(candidate);
    history.push(`/xgrowth/stock/${candidate.code}`);
  };

  const openWatchStock = (item: WatchlistItem) => {
    const candidate = candidates.find((row) => row.code === item.code);
    if (candidate) {
      openStock(candidate);
      return;
    }
    setSelected(candidateFromWatchlist(item));
    history.push(`/xgrowth/stock/${item.code}`);
  };

  const addToWatchlist = async (candidate: Candidate, source = 'candidate') => {
    try {
      const item = await api.addWatchlist({
        code: candidate.code,
        ts_code: candidate.ts_code,
        name: candidate.name,
        status: candidate.action_hint.includes('回踩') ? 'pullback' : 'watching',
        priority: candidate.score >= 85 ? 'high' : candidate.score >= 75 ? 'medium' : 'low',
        source,
        note: `${candidate.group} / ${candidate.action_hint}`,
        tags: [candidate.group, candidate.macd_status, candidate.kdj_status].filter(Boolean),
      });
      setNotice(`${item.name} 已加入观察池`);
    } catch (watchError) {
      setError(watchError instanceof Error ? watchError.message : '加入观察池失败');
    }
  };

  const currentUser = initialState?.currentUser
    ? {
        id: initialState.currentUser.id ?? Number(initialState.currentUser.userid ?? 0),
        username: initialState.currentUser.username ?? initialState.currentUser.name ?? '',
        display_name: initialState.currentUser.name ?? '',
        role: initialState.currentUser.role ?? initialState.currentUser.access ?? 'user',
        status: initialState.currentUser.status ?? 'active',
        created_at: '',
        updated_at: '',
        last_login_at: null,
      }
    : null;

  return (
    <PageContainer title={false}>
      {error && <Alert style={{ marginBottom: 12 }} message={error} type="error" showIcon />}
      {notice && <Alert style={{ marginBottom: 12 }} message={notice} type="success" showIcon closable onClose={() => setNotice(null)} />}
      {loading && <Spin style={{ marginBottom: 12 }} />}
      {page === 'home' && (
        <HomePage
          health={health}
          overview={overview}
          candidates={candidates}
          learning={learning}
          concentration={concentration}
          reviewNotes={reviewNotes}
          openStock={openStock}
        />
      )}
      {page === 'screen' && (
        <ScreenPage
          candidates={filteredCandidates}
          concentration={concentration}
          groupFilter={groupFilter}
          setGroupFilter={setGroupFilter}
          groupCounts={groupCounts}
          selected={selected}
          setSelected={setSelected}
          openStock={openStock}
          onAddWatch={addToWatchlist}
        />
      )}
      {page === 'stock' && (
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
          onAddWatch={addToWatchlist}
        />
      )}
      {page === 'strategy' && <StrategyPage strategies={strategies} selected={selected} matchedStrategies={matchedStrategies} />}
      {page === 'concentration' && <ConcentrationPage candidates={candidates} openStock={openStock} />}
      {page === 'reports' && <ReportsPage reports={reports} />}
      {page === 'history' && <HistoryReportsPage reports={reports} />}
      {page === 'learning' && <LearningPage learning={learning} />}
      {page === 'data' && <DataPage health={health} overview={overview} />}
      {page === 'tools' && <ToolsPage />}
      {page === 'watchlist' && <WatchlistPage onOpenStock={openWatchStock} />}
      {page === 'users' && currentUser && <UserManagementPage currentUser={currentUser} />}
    </PageContainer>
  );
};

function strategyQueryForCandidate(candidate: Candidate): string {
  return [
    candidate.group,
    candidate.action_hint,
    candidate.macd_status,
    candidate.kdj_status,
    candidate.rsi14 !== null && candidate.rsi14 !== undefined ? `RSI${candidate.rsi14.toFixed(1)}` : '',
    ...(candidate.reasons ?? []),
    ...(candidate.risks ?? []),
  ]
    .filter(Boolean)
    .join(' ');
}

function candidateFromWatchlist(item: WatchlistItem): Candidate {
  return {
    code: item.code,
    ts_code: item.ts_code || item.code,
    name: item.name,
    score: item.priority === 'high' ? 85 : item.priority === 'low' ? 65 : 75,
    group: item.tags[0] || '观察池',
    action_hint: statusLabel(item.status),
    close: item.target_price ?? 0,
    change_pct: null,
    amount_yi: 0,
    amount_rank: 0,
    ret20_pct: null,
    ret60_pct: null,
    drawdown20_pct: null,
    macd_status: item.tags[1] || '-',
    kdj_status: item.tags[2] || '-',
    rsi14: null,
    td_signal: null,
    reasons: item.note ? [item.note] : ['来自观察池'],
    risks: item.stop_loss ? [`止损参考 ${item.stop_loss}`] : [],
  };
}

function candidateFromCode(code: string): Candidate {
  return {
    code,
    ts_code: code,
    name: code,
    score: 0,
    group: 'URL指定',
    action_hint: '打开个股分析',
    close: 0,
    change_pct: null,
    amount_yi: 0,
    amount_rank: 0,
    ret20_pct: null,
    ret60_pct: null,
    drawdown20_pct: null,
    macd_status: '-',
    kdj_status: '-',
    rsi14: null,
    td_signal: null,
    reasons: ['来自路由股票编码'],
    risks: [],
  };
}

function statusLabel(status: string): string {
  return {
    watching: '观察中',
    pullback: '等回踩',
    breakout: '突破确认',
    holding: '持有跟踪',
    paused: '暂停观察',
    removed: '已移除',
  }[status] ?? status;
}

export default XGrowthPage;
