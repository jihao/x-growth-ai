import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  FileText,
  Info,
  LineChart,
  PieChart,
  RefreshCcw,
  Search,
  ShieldAlert,
  Target,
  type LucideIcon
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import { technicalKeys, type ReviewNote, type TechnicalKey } from "../appTypes";
import { MarketChart } from "./charts/MarketChart";
import { MarkdownView } from "./markdown/MarkdownView";
import { EmptyState, Metric, PanelTitle } from "./ui/Panel";
import {
  asRows,
  breadthLabel,
  formatIndexPoint,
  formatInt,
  formatNum,
  numberFromText,
  pct,
  ppText,
  ratioText,
  reviewCell,
  shortDate,
  signedPct,
  signedlessPct
} from "../utils/formatters";
import type {
  BacktestJob,
  Candidate,
  ConcentrationResponse,
  ConcentrationRow,
  DailyReviewDashboard,
  Health,
  IndicatorResponse,
  LearningItem,
  MarkdownDetail,
  MarketOverview,
  ReportItem,
  StockStrategyDetail,
  StrategySummary
} from "../types";

export function HomePage({
  health,
  overview,
  candidates,
  learning,
  concentration,
  reviewNotes,
  openStock
}: {
  health: Health | null;
  overview: MarketOverview | null;
  candidates: Candidate[];
  learning: LearningItem[];
  concentration: ConcentrationResponse | null;
  reviewNotes: Record<string, ReviewNote>;
  openStock: (candidate: Candidate) => void;
}) {
  const marketPlan = marketActionPlan(overview, concentration?.latest ?? null);
  const reviewQueue = buildReviewQueue(candidates, reviewNotes);
  return (
    <section className="grid-page">
      <div className="metric-row">
        <Metric label="最新交易日" value={health?.latest_date ?? "-"} />
        <Metric label="股票覆盖" value={formatInt(health?.stocks)} />
        <Metric label="市场状态" value={overview?.risk_level ?? "-"} />
        <Metric label="成交额" value={`${formatNum(overview?.total_amount_yi)}亿`} />
      </div>
      <section className="panel span-2">
        <PanelTitle icon={Activity} title="今日市场状态" />
        <div className={`market-plan ${marketPlan.level}`}>
          <strong>{marketPlan.title}</strong>
          <span>{marketPlan.summary}</span>
        </div>
        <div className="market-checks">
          {marketPlan.items.map((item) => (
            <div key={item.label}>
              <small>{item.label}</small>
              <strong>{item.value}</strong>
              <span>{item.hint}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <PanelTitle icon={PieChart} title="资金集中度" />
        <div className="data-layers">
          <div><strong>CR10 {pct(concentration?.latest?.cr10_pct)}</strong><span>{concentrationContext(concentration?.latest ?? null)}</span></div>
          <div><strong>有效股票数 {formatNum(concentration?.latest?.effective_count)}</strong><span>数值越低，说明成交额越集中在少数股票。</span></div>
        </div>
      </section>
      <section className="panel span-2">
        <PanelTitle icon={Target} title="今日候选" />
        <CandidateTable rows={candidates.slice(0, 10)} onOpenStock={openStock} compact />
      </section>
      <section className="panel">
        <PanelTitle icon={FileText} title="今日待复盘" />
        <ReviewQueue rows={reviewQueue} onOpenStock={openStock} />
      </section>
      <section className="panel">
        <PanelTitle icon={ShieldAlert} title="市场宽度" />
        <div className="breadth">
          <span className="up">上涨 {overview?.up ?? 0}</span>
          <span className="down">下跌 {overview?.down ?? 0}</span>
          <span>平盘 {overview?.flat ?? 0}</span>
          <span>类涨停 {overview?.limit_up_like ?? 0}</span>
        </div>
      </section>
      <section className="panel">
        <PanelTitle icon={BookOpen} title="学习资料" />
        <ul className="link-list">
          {learning.slice(0, 5).map((item) => (
            <li key={item.id}>{item.title}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}

export function ScreenPage({
  candidates,
  concentration,
  groupFilter,
  setGroupFilter,
  selected,
  setSelected,
  openStock
}: {
  candidates: Candidate[];
  concentration: ConcentrationResponse | null;
  groupFilter: string;
  setGroupFilter: (value: string) => void;
  selected: Candidate | null;
  setSelected: (value: Candidate) => void;
  openStock: (value: Candidate) => void;
}) {
  const groups = ["全部", "主线核心", "低位转强", "趋势观察", "过热观察", "风险较高", "继续观察"];
  const concentrationMap = useMemo(() => buildConcentrationMap(concentration), [concentration]);
  return (
    <section className="split-page">
      <div className="panel">
        <PanelTitle icon={Search} title="DB 规则候选池" />
        <div className="segmented">
          {groups.map((group) => (
            <button key={group} className={groupFilter === group ? "active" : ""} onClick={() => setGroupFilter(group)}>
              {group}
            </button>
          ))}
        </div>
        <CandidateTable rows={candidates} selected={selected} onSelect={setSelected} onOpenStock={openStock} concentrationMap={concentrationMap} />
      </div>
      <CandidateDetail candidate={selected} onOpenStock={openStock} concentrationInfo={selected ? concentrationMap.get(selected.code) : undefined} />
    </section>
  );
}

function ReviewQueue({
  rows,
  onOpenStock
}: {
  rows: Array<{ candidate: Candidate; reason: string; done: boolean; plan?: string }>;
  onOpenStock: (candidate: Candidate) => void;
}) {
  if (!rows.length) return <EmptyState text="暂无待复盘股票。" />;
  return (
    <div className="review-queue">
      {rows.slice(0, 6).map((item) => (
        <button key={item.candidate.code} className="review-queue-item" onClick={() => onOpenStock(item.candidate)}>
          <span className={item.done ? "review-status done" : "review-status"}>{item.done ? item.plan ?? "已复盘" : "待复盘"}</span>
          <strong>{item.candidate.name}</strong>
          <small>{item.candidate.code} / {item.reason}</small>
        </button>
      ))}
    </div>
  );
}

export function StockPage({
  selected,
  indicators,
  strategyDetail,
  backtestJob,
  reviewNote,
  onSaveReview
}: {
  selected: Candidate | null;
  indicators: IndicatorResponse | null;
  strategyDetail: StockStrategyDetail | null;
  backtestJob: BacktestJob | null;
  reviewNote?: ReviewNote;
  onSaveReview: (note: ReviewNote) => void;
}) {
  const [activeTechnical, setActiveTechnical] = useState<TechnicalKey>("macd");
  if (!selected) return <EmptyState text="先在选股页选择一只股票。" />;
  const rows = indicators?.rows ?? [];
  const activeSummary = strategyDetail?.summary?.find((item) => item.strategy === activeTechnical);
  const decision = stockDecision(selected, indicators?.analysis, activeSummary, activeTechnical);
  return (
    <section className="stock-workspace">
      <StockDecisionCard selected={selected} analysis={indicators?.analysis} strategyDetail={strategyDetail} activeStrategy={activeTechnical} decision={decision} />
      <ReviewJournal candidate={selected} decision={decision} note={reviewNote} onSave={onSaveReview} />
      <section className="panel quote-panel">
        <div className="stock-header">
          <PanelTitle icon={LineChart} title={`${selected.name}(${selected.code})`} />
          <div className="quote-meta">
            <span>最新 {formatNum(selected.close)}</span>
            <span className={(selected.change_pct ?? 0) >= 0 ? "positive" : "negative"}>{pct(selected.change_pct)}</span>
            <span>{selected.group}</span>
          </div>
        </div>
        <div className="chart-toolbar">
          {technicalKeys.map((item) => (
            <button key={item} className={activeTechnical === item ? "active" : ""} onClick={() => setActiveTechnical(item)}>
              {item.toUpperCase()}
            </button>
          ))}
        </div>
        <MarketChart rows={rows} analysis={indicators?.analysis} indicator={activeTechnical} strategy={activeTechnical} signals={strategyDetail?.signals?.[activeTechnical] ?? []} />
      </section>
      <div className="stock-side-column">
        <section className="panel">
          <PanelTitle icon={BarChart3} title="当前股票策略验证" />
          <StrategyForStock detail={strategyDetail} job={backtestJob} activeStrategy={activeTechnical} setActiveStrategy={setActiveTechnical} />
        </section>
      </div>
      <CandidateDetail candidate={selected} />
      <StockTechnicalAssist analysis={indicators?.analysis} />
    </section>
  );
}

export function StrategyPage({
  strategies,
  selected,
  strategyDetail
}: {
  strategies: StrategySummary[];
  selected: Candidate | null;
  strategyDetail: StockStrategyDetail | null;
}) {
  const filtered = selected ? strategies.filter((row) => String(row.code).padStart(6, "0") === selected.code) : strategies;
  return (
    <section className="grid-page">
      <section className="panel span-2">
        <PanelTitle icon={BarChart3} title={selected ? `${selected.name}(${selected.code}) 策略表现` : "策略表现"} />
        <p className="note">总览里的买入持有按完整回测区间计算；个股卡片里的首买持有按当前策略第一笔实际买入价计算。</p>
        <StrategySummaryTable rows={filtered.slice(0, 80)} />
      </section>
      <section className="panel">
        <PanelTitle icon={Activity} title="买卖明细" />
        <TradeList detail={strategyDetail} strategy="all" />
      </section>
    </section>
  );
}

function StockDecisionCard({
  selected,
  analysis,
  strategyDetail,
  activeStrategy,
  decision
}: {
  selected: Candidate;
  analysis?: IndicatorResponse["analysis"];
  strategyDetail: StockStrategyDetail | null;
  activeStrategy: TechnicalKey;
  decision?: ReturnType<typeof stockDecision>;
}) {
  const activeSummary = strategyDetail?.summary?.find((item) => item.strategy === activeStrategy);
  const currentDecision = decision ?? stockDecision(selected, analysis, activeSummary, activeStrategy);
  return (
    <section className="panel decision-card">
      <PanelTitle icon={ShieldAlert} title="综合判断" />
      <div className={`decision-banner ${currentDecision.tone}`}>
        <strong>{currentDecision.action}</strong>
        <span>{currentDecision.summary}</span>
      </div>
      <div className="decision-grid">
        {currentDecision.items.map((item) => (
          <div key={item.label}>
            <small>{item.label}</small>
            <strong>{item.value}</strong>
            <span>{item.hint}</span>
          </div>
        ))}
      </div>
      <div className="decision-points">
        <div>
          <strong>支持理由</strong>
          <ul>{currentDecision.positives.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
        <div>
          <strong>主要风险</strong>
          <ul>{currentDecision.risks.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      </div>
    </section>
  );
}

function ReviewJournal({
  candidate,
  decision,
  note,
  onSave
}: {
  candidate: Candidate;
  decision: ReturnType<typeof stockDecision>;
  note?: ReviewNote;
  onSave: (note: ReviewNote) => void;
}) {
  const [plan, setPlan] = useState<ReviewNote["plan"]>(note?.plan ?? reviewPlanFromAction(decision.action));
  const [reason, setReason] = useState(note?.reason ?? decision.positives.join("；"));
  const [waitFor, setWaitFor] = useState(note?.waitFor ?? "等待回踩到关键均线/支撑位，或策略信号重新确认。");
  const [risk, setRisk] = useState(note?.risk ?? decision.risks.join("；"));

  useEffect(() => {
    setPlan(note?.plan ?? reviewPlanFromAction(decision.action));
    setReason(note?.reason ?? decision.positives.join("；"));
    setWaitFor(note?.waitFor ?? "等待回踩到关键均线/支撑位，或策略信号重新确认。");
    setRisk(note?.risk ?? decision.risks.join("；"));
  }, [candidate.code, decision.action, note]);

  function submit() {
    onSave({
      code: candidate.code,
      name: candidate.name,
      date: todayString(),
      plan,
      reason: reason.trim(),
      waitFor: waitFor.trim(),
      risk: risk.trim(),
      updatedAt: new Date().toISOString()
    });
  }

  return (
    <section className="panel review-journal">
      <div className="review-heading">
        <PanelTitle icon={FileText} title="复盘记录" />
        <span>{note ? `上次保存 ${shortDate(note.date)} / ${note.plan}` : "本机保存，仅用于个人学习复盘"}</span>
      </div>
      <div className="review-form-grid">
        <label className="review-field">
          <span>观察结论</span>
          <select value={plan} onChange={(event) => setPlan(event.target.value as ReviewNote["plan"])}>
            <option value="观察">观察</option>
            <option value="等回踩">等回踩</option>
            <option value="模拟买入">模拟买入</option>
            <option value="放弃">放弃</option>
          </select>
        </label>
        <label className="review-field">
          <span>为什么关注</span>
          <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} />
        </label>
        <label className="review-field">
          <span>等待什么信号</span>
          <textarea value={waitFor} onChange={(event) => setWaitFor(event.target.value)} rows={3} />
        </label>
        <label className="review-field">
          <span>主要风险</span>
          <textarea value={risk} onChange={(event) => setRisk(event.target.value)} rows={3} />
        </label>
      </div>
      <div className="review-actions">
        <small>建议每天只记录“为什么看、等什么、错了怎么办”，避免把系统评分误当成确定性买点。</small>
        <button className="small-button" onClick={submit}>保存复盘</button>
      </div>
    </section>
  );
}

function StockTechnicalAssist({ analysis }: { analysis?: IndicatorResponse["analysis"] }) {
  if (!analysis) return null;
  const fibLevels = analysis.fibonacci?.levels ?? [];
  return (
    <section className="panel technical-assist">
      <PanelTitle icon={Info} title="徐小明式辅助分析" />
      <div className="assist-grid">
        <div>
          <strong>{analysis.trend?.status ?? "趋势待判断"}</strong>
          <span>{analysis.trend?.hint ?? "等待更多数据。"}</span>
          <small>MA20 {formatNum(analysis.trend?.ma20)} / MA60 {formatNum(analysis.trend?.ma60)}</small>
        </div>
        <div>
          <strong>{analysis.fibonacci?.direction ?? "斐波那契"}</strong>
          <span>{analysis.fibonacci?.hint ?? "暂无足够波段数据。"}</span>
          <small>{analysis.fibonacci?.start_date ?? "-"} 至 {analysis.fibonacci?.end_date ?? "-"}</small>
        </div>
      </div>
      <h3>结构信号</h3>
      <ul className="tag-list">
        {(analysis.structure?.length ? analysis.structure : [{ label: "暂无近期背离/钝化", hint: "继续以趋势和成交为主。" }]).map((item) => (
          <li key={`${item.label}-${item.hint}`} title={item.hint}>{item.label}</li>
        ))}
      </ul>
      <h3 className="inline-heading">
        斐波那契价位
        <TooltipHint text="这些价位是最近一段波段的回调/反弹参考位。上涨后回落接近38.2%、50%、61.8%时，常被当作支撑观察；下跌后反弹接近这些位置，则常被当作压力观察。它们不是买卖命令，需要和趋势、成交、TD9、MACD结构一起确认。列表里的百分比是当前价相对该价位的距离：正数表示当前价在该价位上方，负数表示当前价在该价位下方。" />
      </h3>
      <div className="fib-list">
        {fibLevels.length ? fibLevels.map((level) => (
          <div key={level.label}>
            <span>{level.label}</span>
            <strong>{formatNum(level.price)}</strong>
            <small>距现价 {pct(level.distance_pct)}</small>
          </div>
        )) : <p className="note">暂无足够波段数据。</p>}
      </div>
      <h3 className="inline-heading">
        时间窗口
        <TooltipHint text="时间窗口是从近期关键低点开始数 5、8、13、21、34、55、89 等斐波那契天数。接近这些天数时，市场有时更容易出现节奏变化，所以这里只作为变盘观察提醒，不是买入或卖出信号。" />
      </h3>
      <p className="note">
        {analysis.time_windows?.length
          ? analysis.time_windows.map((item) => `${item.window}日窗口${item.distance === 0 ? "当天" : item.distance > 0 ? `已过${item.distance}日` : `还差${Math.abs(item.distance)}日`}`).join("；")
          : "当前不在 5/8/13/21/34/55/89 日附近的时间窗口。"}
      </p>
    </section>
  );
}

export function ConcentrationPage({
  candidates,
  openStock
}: {
  candidates: Candidate[];
  openStock: (candidate: Candidate) => void;
}) {
  const [lookback, setLookback] = useState(120);
  const [universe, setUniverse] = useState<"top250" | "all">("top250");
  const [payload, setPayload] = useState<ConcentrationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.concentration(lookback, universe)
      .then((data) => {
        if (!cancelled) setPayload(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "集中度加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lookback, universe]);
  const latest = payload?.latest ?? null;
  return (
    <section className="concentration-page">
      <section className="panel span-2 concentration-hero">
        <div className="panel-heading">
          <PanelTitle icon={PieChart} title="Top250 成交额集中度" />
          <div className="segmented compact-segmented">
            {(["top250", "all"] as const).map((item) => (
              <button key={item} className={universe === item ? "active" : ""} onClick={() => setUniverse(item)}>
                {item === "top250" ? "Top250" : "全市场"}
              </button>
            ))}
          </div>
        </div>
        <div className="concentration-controls">
          <span>{payload?.date ?? "-"} / {payload?.method ?? "成交额权重"}</span>
          <div className="range-buttons">
            {[60, 120, 240].map((count) => (
              <button key={count} className={lookback === count ? "active" : ""} onClick={() => setLookback(count)}>
                {count}日
              </button>
            ))}
          </div>
        </div>
        <p className="note">
          {payload?.description ?? "权重=个股当日成交额/样本股票当日成交额合计。"}这里观察的是资金是否挤在少数股票里，不是官方指数成分权重。
        </p>
      </section>
      {error && <div className="alert span-2">{error}</div>}
      {loading && <div className="loading span-2">正在计算集中度...</div>}
      <section className="panel span-2">
        <PanelTitle icon={PieChart} title="权重集中曲线" />
        <p className="note">蓝线是单只股票成交额权重，橙线是从第 1 名开始累加后的权重。橙线越陡，说明少数股票吸走的成交额越多。</p>
        <WeightConcentrationChart rows={payload?.distribution ?? []} />
      </section>
      <section className="panel">
        <PanelTitle icon={Info} title="当前截面读法" />
        <div className="data-layers">
          <div><strong>前 5 大成分</strong><span>{pct(latest?.cr5_pct)}，用于判断头部是否特别拥挤。</span></div>
          <div><strong>前 10 大成分</strong><span>{pct(latest?.cr10_pct)}，更适合观察主线资金强弱。</span></div>
          <div><strong>前 50 大成分</strong><span>{pct(latest?.cr50_pct)}，用于判断热点是否从龙头扩散到板块群。</span></div>
        </div>
      </section>
      <div className="metric-row">
        <MetricWithHint
          label="CR5"
          value={pct(latest?.cr5_pct)}
          change={latest?.cr5_pct_change}
          hint="Top5 股票成交额占样本总成交额的比例。越高，说明资金越集中在头部少数股票。"
        />
        <MetricWithHint
          label="CR10"
          value={pct(latest?.cr10_pct)}
          change={latest?.cr10_pct_change}
          hint="Top10 股票成交额占比。它比 CR5 更平滑，常用于观察主线是否扩散。"
        />
        <MetricWithHint
          label="CR50"
          value={pct(latest?.cr50_pct)}
          change={latest?.cr50_pct_change}
          hint="Top50 股票成交额占比。若 CR5 很高但 CR50 没同步抬升，可能是少数龙头过度拥挤。"
        />
        <MetricWithHint
          label="有效股票数"
          value={formatNum(latest?.effective_count)}
          change={latest?.effective_count_change}
          hint="按成交额权重折算出的等效参与股票数。数值越小，市场越拥挤；数值越大，资金越分散。"
          inverseChange
        />
      </div>
      <section className="panel span-2">
        <PanelTitle icon={LineChart} title="集中度趋势" />
        <ConcentrationTrendChart rows={payload?.series ?? []} />
      </section>
      <section className="panel">
        <PanelTitle icon={Activity} title="资金分层" />
        <LayerShareChart rows={payload?.series ?? []} />
        <div className="explain-box">
          <strong>{concentrationLevel(latest)}</strong>
          <span>{concentrationExplain(latest)}</span>
        </div>
      </section>
      <section className="panel span-2">
        <PanelTitle icon={Target} title="当日 Top20 拥挤股票" />
        <p className="note">这些股票只是成交额权重靠前，表示关注度高；不等于应该追买，需要结合位置、回撤和策略信号。</p>
        <ConcentrationTopTable
          rows={payload?.top ?? []}
          candidates={candidates}
          onOpenStock={(row) => openStock(candidateFromConcentration(row, candidates))}
        />
      </section>
      <section className="panel">
        <PanelTitle icon={Info} title="新手读法" />
        <div className="data-layers">
          <div><strong>集中度上升</strong><span>资金更抱团，龙头可能更强，但追高风险也会同步增加。</span></div>
          <div><strong>集中度下降</strong><span>热点可能扩散，也可能主线退潮；要看上涨家数和成交额是否配合。</span></div>
          <div><strong>有效股票数下降</strong><span>少数股票吸走更多成交额，候选池需要更重视“过热不追”。</span></div>
        </div>
      </section>
    </section>
  );
}

function MetricWithHint({
  label,
  value,
  change,
  hint,
  inverseChange
}: {
  label: string;
  value: string;
  change?: number | null;
  hint: string;
  inverseChange?: boolean;
}) {
  const positiveChange = inverseChange ? (change ?? 0) < 0 : (change ?? 0) > 0;
  return (
    <div className="metric metric-with-hint">
      <span>
        {label}
        <TooltipHint text={hint} />
      </span>
      <strong>{value}</strong>
      <small className={positiveChange ? "negative" : "positive"}>
        较前日 {change === null || change === undefined ? "-" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}`}
      </small>
    </div>
  );
}

function TooltipHint({ text }: { text: string }) {
  return (
    <span className="tooltip-hint" tabIndex={0}>
      <Info size={13} />
      <em>{text}</em>
    </span>
  );
}

function WeightConcentrationChart({ rows }: { rows: ConcentrationResponse["distribution"] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const data = rows.filter((row) => row.rank_pct !== null && row.weight_pct !== null && row.cumulative_weight_pct !== null);
  if (data.length < 2) return <EmptyState text="暂无足够权重分布数据。" />;
  const width = 920;
  const height = 330;
  const pad = { left: 52, right: 56, top: 20, bottom: 42 };
  const maxWeight = Math.max(1, ...data.map((row) => Number(row.weight_pct))) * 1.18;
  const maxCumulative = Math.max(10, ...data.map((row) => Number(row.cumulative_weight_pct))) * 1.04;
  const xFor = (rankPct: number) => pad.left + rankPct / 100 * (width - pad.left - pad.right);
  const yWeight = (value: number) => pad.top + (1 - value / maxWeight) * (height - pad.top - pad.bottom);
  const yCumulative = (value: number) => pad.top + (1 - value / maxCumulative) * (height - pad.top - pad.bottom);
  const weightPoints = data.map((row) => `${xFor(Number(row.rank_pct))},${yWeight(Number(row.weight_pct))}`).join(" ");
  const cumulativePoints = data.map((row) => `${xFor(Number(row.rank_pct))},${yCumulative(Number(row.cumulative_weight_pct))}`).join(" ");
  const hover = hoverIndex === null ? data[0] : data[hoverIndex];
  const hoverX = xFor(Number(hover.rank_pct));
  const xTicks = [0, 5, 10, 20, 50, 100].filter((tick) => tick <= Number(data[data.length - 1].rank_pct ?? 100));
  const leftTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({ value: maxWeight * ratio, y: yWeight(maxWeight * ratio) }));
  const rightTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({ value: maxCumulative * ratio, y: yCumulative(maxCumulative * ratio) }));
  return (
    <div className="weight-chart-wrap">
      <svg
        className="weight-chart"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const rawX = (event.clientX - rect.left) / rect.width * width;
          const ratio = (rawX - pad.left) / (width - pad.left - pad.right);
          const index = Math.max(0, Math.min(data.length - 1, Math.round(ratio * (data.length - 1))));
          setHoverIndex(index);
        }}
      >
        <rect x="0" y="0" width={width} height={height} fill="#ffffff" />
        {leftTicks.map((tick) => (
          <g key={`left-${tick.value}`}>
            <line x1={pad.left} x2={width - pad.right} y1={tick.y} y2={tick.y} className="grid-line" />
            <text x="8" y={tick.y + 4} className="axis-text">{tick.value.toFixed(1)}%</text>
          </g>
        ))}
        {rightTicks.map((tick) => (
          <text key={`right-${tick.value}`} x={width - pad.right + 8} y={tick.y + 4} className="axis-text">{tick.value.toFixed(0)}%</text>
        ))}
        {xTicks.map((tick) => (
          <g key={tick}>
            <line x1={xFor(tick)} x2={xFor(tick)} y1={pad.top} y2={height - pad.bottom} className="soft-grid-line" />
            <text x={xFor(tick) - 12} y={height - 14} className="axis-text">{tick}%</text>
          </g>
        ))}
        <polyline fill="none" stroke="#2563eb" strokeWidth="2.4" points={weightPoints} />
        <polyline fill="none" stroke="#f97316" strokeWidth="2.4" points={cumulativePoints} />
        <line x1={pad.left} x2={pad.left} y1={pad.top} y2={height - pad.bottom} className="axis-line" />
        <line x1={width - pad.right} x2={width - pad.right} y1={pad.top} y2={height - pad.bottom} className="axis-line" />
        <line x1={pad.left} x2={width - pad.right} y1={height - pad.bottom} y2={height - pad.bottom} className="axis-line" />
        <text x="8" y="14" className="axis-text">单票权重</text>
        <text x={width - 72} y="14" className="axis-text">累计权重</text>
        <text x={width / 2 - 50} y={height - 4} className="axis-text">排名占样本比例</text>
        {hover && (
          <g className="crosshair">
            <line x1={hoverX} x2={hoverX} y1={pad.top} y2={height - pad.bottom} />
            <circle cx={hoverX} cy={yWeight(Number(hover.weight_pct))} r="4" fill="#2563eb" />
            <circle cx={hoverX} cy={yCumulative(Number(hover.cumulative_weight_pct))} r="4" fill="#f97316" />
          </g>
        )}
      </svg>
      {hover && (
        <div className="chart-tooltip weight-tooltip">
          <strong>第 {hover.rank} 名 {hover.name}</strong>
          <span>{hover.code} / 成交额 {formatNum(hover.amount_yi)}亿</span>
          <span>单票权重 {pct(hover.weight_pct)}</span>
          <span>累计权重 {pct(hover.cumulative_weight_pct)}</span>
          <span>排名占比 {pct(hover.rank_pct)}</span>
        </div>
      )}
      <div className="chart-legend">
        <span><i style={{ background: "#2563eb" }} />单票权重</span>
        <span><i style={{ background: "#f97316" }} />累计权重</span>
      </div>
    </div>
  );
}

function ConcentrationTrendChart({ rows }: { rows: ConcentrationRow[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const fields = [
    { key: "cr5_pct", label: "CR5", color: "#2563eb" },
    { key: "cr10_pct", label: "CR10", color: "#16a34a" },
    { key: "cr50_pct", label: "CR50", color: "#dc2626" },
    { key: "top5pct_concentration_pct", label: "Top5%", color: "#7c3aed" }
  ];
  const cleanRows = rows.filter((row) => row.cr5_pct !== null);
  if (cleanRows.length < 2) return <EmptyState text="暂无足够集中度趋势数据。" />;
  const width = 920;
  const height = 280;
  const pad = { left: 48, right: 18, top: 20, bottom: 34 };
  const values = fields.flatMap((field) => cleanRows.map((row) => Number(row[field.key as keyof ConcentrationRow])).filter(Number.isFinite));
  const max = Math.max(10, ...values) * 1.08;
  const xFor = (index: number) => pad.left + (index / (cleanRows.length - 1)) * (width - pad.left - pad.right);
  const yFor = (value: number) => pad.top + (1 - value / max) * (height - pad.top - pad.bottom);
  const hover = hoverIndex === null ? cleanRows[cleanRows.length - 1] : cleanRows[hoverIndex];
  const hoverX = hoverIndex === null ? xFor(cleanRows.length - 1) : xFor(hoverIndex);
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({ value: max * ratio, y: yFor(max * ratio) }));
  return (
    <div className="concentration-chart-wrap">
      <svg
        className="concentration-chart"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const rawX = (event.clientX - rect.left) / rect.width * width;
          const ratio = (rawX - pad.left) / (width - pad.left - pad.right);
          const index = Math.max(0, Math.min(cleanRows.length - 1, Math.round(ratio * (cleanRows.length - 1))));
          setHoverIndex(index);
        }}
      >
        <rect x="0" y="0" width={width} height={height} fill="#ffffff" />
        {yTicks.map((tick) => (
          <g key={tick.value}>
            <line x1={pad.left} x2={width - pad.right} y1={tick.y} y2={tick.y} className="grid-line" />
            <text x="8" y={tick.y + 4} className="axis-text">{tick.value.toFixed(1)}%</text>
          </g>
        ))}
        {fields.map((field) => (
          <polyline
            key={field.key}
            fill="none"
            stroke={field.color}
            strokeWidth="2.2"
            points={cleanRows.map((row, index) => `${xFor(index)},${yFor(Number(row[field.key as keyof ConcentrationRow] ?? 0))}`).join(" ")}
          />
        ))}
        {hover && (
          <g className="crosshair">
            <line x1={hoverX} x2={hoverX} y1={pad.top} y2={height - pad.bottom} />
            <circle cx={hoverX} cy={yFor(Number(hover.cr10_pct ?? 0))} r="4" fill="#111827" />
          </g>
        )}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const index = Math.min(cleanRows.length - 1, Math.round(ratio * (cleanRows.length - 1)));
          return <text key={ratio} x={xFor(index) - 22} y={height - 10} className="axis-text">{shortDate(cleanRows[index].date)}</text>;
        })}
      </svg>
      {hover && (
        <div className="chart-tooltip concentration-tooltip">
          <strong>{hover.date}</strong>
          <span>CR5 {pct(hover.cr5_pct)} / CR10 {pct(hover.cr10_pct)}</span>
          <span>CR50 {pct(hover.cr50_pct)}</span>
          <span>Top5% {pct(hover.top5pct_concentration_pct)}</span>
          <span>有效股票数 {formatNum(hover.effective_count)}</span>
        </div>
      )}
      <div className="chart-legend">
        {fields.map((field) => <span key={field.key}><i style={{ background: field.color }} />{field.label}</span>)}
      </div>
    </div>
  );
}

function LayerShareChart({ rows }: { rows: ConcentrationRow[] }) {
  const latest = rows[rows.length - 1];
  if (!latest) return <EmptyState text="暂无资金分层数据。" />;
  const layers = [
    { label: "1-5", value: latest.layer_top5_pct ?? 0, color: "#2563eb", hint: "头部 5 只" },
    { label: "6-10", value: latest.layer_6_10_pct ?? 0, color: "#16a34a", hint: "第 6 到 10 只" },
    { label: "11-20", value: latest.layer_11_20_pct ?? 0, color: "#f59e0b", hint: "第 11 到 20 只" },
    { label: "21-50", value: latest.layer_21_50_pct ?? 0, color: "#dc2626", hint: "第 21 到 50 只" }
  ];
  return (
    <div className="layer-chart">
      {layers.map((layer) => (
        <div key={layer.label} className="layer-row" title={`${layer.hint}成交额占比 ${pct(layer.value)}`}>
          <span>{layer.label}</span>
          <div><i style={{ width: `${Math.max(2, layer.value * 3)}px`, background: layer.color }} /></div>
          <strong>{pct(layer.value)}</strong>
        </div>
      ))}
    </div>
  );
}

function ConcentrationTopTable({
  rows,
  candidates,
  onOpenStock
}: {
  rows: ConcentrationResponse["top"];
  candidates: Candidate[];
  onOpenStock: (row: ConcentrationResponse["top"][number]) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>排名</th>
            <th>股票</th>
            <th>成交额</th>
            <th>权重</th>
            <th>收盘</th>
            <th>涨跌</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.ts_code}>
              <td>{row.rank}</td>
              <td>
                <button className="link-button" onClick={() => onOpenStock(row)}>
                  {row.name}
                </button>
                <small>{row.code}{candidates.some((candidate) => candidate.code === row.code) ? " / 候选池" : ""}</small>
              </td>
              <td>{formatNum(row.amount_yi)}亿</td>
              <td>{pct(row.weight_pct)}</td>
              <td>{formatNum(row.close)}</td>
              <td className={(row.change_pct ?? 0) >= 0 ? "positive" : "negative"}>{pct(row.change_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ReportsPage({ reports }: { reports: ReportItem[] }) {
  const [reviewDate, setReviewDate] = useState(latestDailyReportDate(reports));
  const [review, setReview] = useState<DailyReviewDashboard | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(reports[0]?.id ?? null);
  const [detail, setDetail] = useState<MarkdownDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadReview(force = false, targetDate = reviewDate) {
    setReviewLoading(true);
    setReviewError(null);
    try {
      const payload = force ? await api.refreshDailyReview(targetDate) : await api.dailyReview(targetDate);
      setReview(payload);
      setReviewDate(payload.date);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "复盘日报加载失败");
    } finally {
      setReviewLoading(false);
    }
  }

  useEffect(() => {
    loadReview(false);
  }, []);

  function changeReviewDate(value: string) {
    setReviewDate(value);
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      loadReview(false, value);
    }
  }

  useEffect(() => {
    if (!selectedId) return;
    api.report(selectedId).then(setDetail).catch((err) => setError(err.message));
  }, [selectedId]);

  return (
    <section className="daily-review-page">
      <section className="panel review-control-panel">
        <PanelTitle icon={FileText} title="复盘日报" />
        <label className="date-control">
          <span>复盘日期</span>
          <input type="date" value={reviewDate} onChange={(event) => changeReviewDate(event.target.value)} />
        </label>
        <div className="review-button-row">
          <button className="small-button" onClick={() => loadReview(false)} disabled={reviewLoading}>生成/读取</button>
          <button className="small-button" onClick={() => loadReview(true)} disabled={reviewLoading}>
            <RefreshCcw size={14} /> 刷新技能数据
          </button>
        </div>
        {reviewLoading && <div className="loading">正在准备复盘日报...</div>}
        {reviewError && <div className="alert">{reviewError}</div>}
        {review && <DataCompleteness review={review} />}
        <h3>历史 Markdown</h3>
        <div className="report-grid compact">
          {reports.slice(0, 12).map((item) => (
            <button className={`report-item ${selectedId === item.id ? "active" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}>
              <span>{item.type}</span>
              <strong>{item.title}</strong>
              <small>{item.id}</small>
            </button>
          ))}
        </div>
      </section>
      <DailyReviewView review={review} />
      <section className="panel reader-panel daily-markdown-panel">
        {error && <div className="alert">{error}</div>}
        {detail ? (
          <>
            <PanelTitle icon={FileText} title={detail.title} />
            <MarkdownView content={detail.content} />
          </>
        ) : (
          <EmptyState text="选择一张历史 Markdown 查看正文。" />
        )}
      </section>
    </section>
  );
}

function DataCompleteness({ review }: { review: DailyReviewDashboard }) {
  const ok = review.data_sources.filter((item) => item.ok).length;
  const total = review.data_sources.length;
  return (
    <div className="data-completeness">
      <strong>{ok}/{total} 数据源可用</strong>
      <span>{archiveStatus(review.archive?.status)} · {review.archive?.database ?? "文件缓存"}</span>
      <span>生成时间 {review.generated_at}</span>
      <small title={review.cache_paths.normalized}>{review.cache_paths.normalized}</small>
      <div className="source-pills">
        {review.data_sources.map((item) => (
          <span key={`${item.name}-${item.source}`} className={item.ok ? "source-pill ok" : "source-pill missing"} title={item.error ?? item.source}>
            {item.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function DailyReviewView({ review }: { review: DailyReviewDashboard | null }) {
  if (!review) return <section className="panel daily-review-main"><EmptyState text="选择日期后生成复盘日报。" /></section>;
  const market = review.sections.market;
  const concentration = review.sections.concentration;
  const industries = review.sections.industries;
  const sentiment = review.sections.sentiment;
  const liquidity = review.sections.liquidity;
  const rotation = review.sections.rotation;
  const events = review.sections.events;
  const actions = review.sections.actions;
  const conclusions = review.sections.conclusions;
  const overview = market?.overview as MarketOverview | undefined;
  const sentimentScore = sentiment?.score as { value?: number; label?: string; items?: Array<Record<string, unknown>> } | undefined;
  return (
    <section className="panel daily-review-main">
      <div className="daily-review-hero">
        <div>
          <span>X-Growth AI · 学习型市场复盘</span>
          <h2>A股复盘日报</h2>
          <p>{review.date} | SQLite 主行情 + mx-skills 辅助数据 | {String(market?.summary ?? "等待数据生成。")}</p>
        </div>
        <div className="review-score">
          <small>情绪温度</small>
          <strong>{formatNum(sentimentScore?.value)}</strong>
          <span>{sentimentScore?.label ?? "-"}</span>
        </div>
      </div>

      <ReviewBlock section={market} tooltip="市场宽度来自 mx-finance-data 与 SQLite 自算涨跌家数；用于判断指数上涨是否有多数股票配合。">
        <MarketKpiReport overview={overview} indexes={asRows(market?.indexes)} />
      </ReviewBlock>

      <ReviewBlock section={concentration} tooltip="集中度按成交额权重计算。CR10/CR50 越高，说明资金越集中在少数股票，追高拥挤风险越高。">
        <ConcentrationRiskReport latest={concentration?.latest as ConcentrationRow | undefined} date={review.date} />
      </ReviewBlock>

      <ReviewBlock section={{ ...industries, title: "板块集中度深度分析", skills: ["Top50 板块 HHI", "二级板块映射"] }} tooltip="按 Top50 成交额榜的二级行业聚合，HHI 越高说明板块越依赖少数股票。">
        <SectorDepthReport rows={asRows(industries?.secondary_industries)} />
      </ReviewBlock>

      <ReviewBlock section={{ ...industries, title: "一级行业成交额分布", skills: ["Top50 成交额权重", "行业映射"] }} tooltip="按一级行业统计 Top50 成交额占比，用来观察资金是否集中在少数大方向。">
        <PrimaryIndustryReport rows={asRows(industries?.industries)} />
      </ReviewBlock>

      <ReviewBlock section={{ ...sentiment, title: "资金流向分析", skills: ["a-share-money-flow", "Web资讯综合"] }} tooltip="当前没有稳定 DDX/北向资金源，主力资金表只标记缺口；板块资金用 Top50 成交额结构辅助观察。">
        <MoneyFlowReport secondaryRows={asRows(industries?.secondary_industries)} />
      </ReviewBlock>

      <ReviewBlock section={rotation} tooltip="对比今日与前一交易日 Top50 成交额中的二级板块，识别资金流入、流出和风格切换。">
        <SectorRotationReport rotation={rotation} />
      </ReviewBlock>

      <ReviewBlock section={{ ...rotation, title: "板块动量分析", skills: ["Top50 成交额趋势"] }} tooltip="用 Top50 成交额趋势和涨幅榜概念观察板块动量，不等同于买入信号。">
        <SectorMomentumReport rotation={rotation} />
      </ReviewBlock>

      <ReviewBlock section={liquidity} tooltip="流动性风险来自 SQLite 成交额和成交额榜，重点看头部股票是否吸走过多成交。">
        <LiquidityRiskReport rows={asRows(liquidity?.metrics)} />
      </ReviewBlock>

      <ReviewBlock section={{ ...sentiment, title: "情绪仪表盘", skills: ["a-share-sentiment"] }} tooltip="情绪仪表盘聚合市场宽度、成交额、集中度和指数表现；未接入 DDX 的项会明确标注。">
        <SentimentDashboard rows={asRows(sentiment?.dashboard)} />
      </ReviewBlock>

      <ReviewBlock section={events} tooltip="热点和核心事件来自 mx 文本技能，作为解释层辅助证据，不直接决定评分。">
        <EventReport rows={asRows(events?.items)} newsRows={asRows(events?.news_items)} />
      </ReviewBlock>

      <ReviewBlock section={actions} tooltip="操作边界是学习型观察建议，不是买卖指令。">
        <ActionAdviceReport actions={actions} />
      </ReviewBlock>

      <ReviewBlock section={conclusions} tooltip="核心结论只使用已标注来源的数据；缺失数据会单独列出。">
        <CoreConclusionReport conclusions={conclusions} missing={review.missing_data} />
      </ReviewBlock>
    </section>
  );
}

function ReviewBlock({ section, tooltip, children }: { section?: DailyReviewDashboard["sections"][string]; tooltip: string; children: ReactNode }) {
  if (!section) return null;
  return (
    <section className="review-block">
      <div className="review-block-heading">
        <div>
          <div className="review-title-line">
            <h3>{section.title}</h3>
            <div className="skill-tags">
              {section.skills.map((skill) => <span key={skill}>{skill}</span>)}
            </div>
          </div>
          <span>{section.source}</span>
        </div>
        <TooltipHint text={tooltip} />
      </div>
      {children}
      {section.summary && <p className="review-summary">{section.summary}</p>}
    </section>
  );
}

function MarketKpiReport({ overview, indexes }: { overview?: MarketOverview; indexes: Array<Record<string, unknown>> }) {
  const kpis = indexes.slice(0, 4);
  return (
    <>
      <div className="report-kpi-grid">
        {kpis.map((row) => {
          const close = numberFromText(row.close);
          const change = numberFromText(row.pct_change);
          return (
            <div className="report-kpi-card" key={String(row.name ?? row.code)}>
              <span>{reviewCell(row.name)}</span>
              <strong className={(change ?? 0) >= 0 ? "report-up" : "report-down"}>{formatIndexPoint(close)}</strong>
              <small className={(change ?? 0) >= 0 ? "report-up" : "report-down"}>较前日 {signedPct(change)} {(change ?? 0) >= 0 ? "▲" : "▼"}</small>
            </div>
          );
        })}
      </div>
      <table className="report-matrix">
        <thead>
          <tr>
            <th>指标</th>
            <th>今日</th>
            <th>vs 前一日</th>
            <th>信号</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>上涨 / 下跌</td>
            <td><strong className="report-up">{overview?.up ?? "-"} ↑ / {overview?.down ?? "-"} ↓</strong></td>
            <td>涨跌比 {ratioText(overview?.up, overview?.down)}，{breadthLabel(overview)}</td>
            <td><SignalBadge tone="warn" text={overview?.risk_level === "积极" ? "普涨扩散" : "指数行情"} /></td>
          </tr>
          <tr>
            <td>涨停 / 跌停</td>
            <td><strong>{overview?.limit_up_like ?? "-"}类涨停 / {overview?.limit_down_like ?? "-"}类跌停</strong></td>
            <td>结构性活跃，观察是否集中于主线行业</td>
            <td><SignalBadge tone="info" text="结构性" /></td>
          </tr>
          <tr>
            <td>全市场成交额</td>
            <td><strong className="report-info">{formatNum(overview?.total_amount_yi)}亿</strong></td>
            <td>成交额用于判断增量资金是否配合</td>
            <td><SignalBadge tone="up" text="量能" /></td>
          </tr>
          <tr>
            <td>涨跌幅中位数</td>
            <td><strong className={(overview?.median_change_pct ?? 0) >= 0 ? "report-up" : "report-down"}>{pct(overview?.median_change_pct)}</strong></td>
            <td>比指数更接近多数股票体验</td>
            <td><SignalBadge tone={(overview?.median_change_pct ?? 0) >= 0 ? "up" : "danger"} text="赚钱效应" /></td>
          </tr>
          <tr>
            <td>主力资金(DDX)</td>
            <td colSpan={2}><strong>暂无稳定数据源</strong>，本次不纳入情绪分和结论</td>
            <td><SignalBadge tone="warn" text="待接入" /></td>
          </tr>
        </tbody>
      </table>
    </>
  );
}

function ConcentrationRiskReport({ latest, date }: { latest?: ConcentrationRow; date: string }) {
  const rows = [
    { group: "个股\n集中度", label: "CR5", value: latest?.cr5_pct, change: latest?.cr5_pct_change, signal: "微升", tone: "warn" },
    { group: "个股\n集中度", label: "CR10", value: latest?.cr10_pct, change: latest?.cr10_pct_change, signal: "微升", tone: "warn" },
    { group: "个股\n集中度", label: "CR50", value: latest?.cr50_pct, change: latest?.cr50_pct_change, signal: "上升", tone: "info" },
    { group: "分层\n结构", label: "CR 1-5", value: latest?.layer_top5_pct, change: null, signal: "头部集中", tone: "up" },
    { group: "分层\n结构", label: "CR 6-10", value: latest?.layer_6_10_pct, change: null, signal: "中段观察", tone: "warn" },
    { group: "分层\n结构", label: "CR 11-20", value: latest?.layer_11_20_pct, change: null, signal: "中位支撑", tone: "info" },
    { group: "分层\n结构", label: "CR 21-50", value: latest?.layer_21_50_pct, change: null, signal: "尾部分散", tone: "up" },
    { group: "市场\n结构", label: "Top5%集中度", value: latest?.top5pct_concentration_pct, change: latest?.top5pct_concentration_pct_change, signal: "观察上限", tone: "warn" },
    { group: "市场\n结构", label: "有效股票数", value: latest?.effective_count, change: latest?.effective_count_change, signal: "扩散程度", tone: "info", percent: false },
  ];
  return (
    <table className="report-matrix report-risk-table">
      <thead>
        <tr>
          <th>风险维度</th>
          <th>指标</th>
          <th>{shortDate(date)}</th>
          <th>前一日</th>
          <th>变化</th>
          <th>信号</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const firstInGroup = index === 0 || rows[index - 1].group !== row.group;
          const rowSpan = rows.filter((item) => item.group === row.group).length;
          const previous = typeof row.change === "number" && typeof row.value === "number" ? row.value - row.change : null;
          return (
            <tr key={`${row.group}-${row.label}`}>
              {firstInGroup && <td className="risk-group-cell" rowSpan={rowSpan}>{row.group.split("\n").map((part) => <span key={part}>{part}</span>)}</td>}
              <td>{row.label}</td>
              <td>{row.percent === false ? formatNum(row.value) : pct(row.value)}</td>
              <td>{row.percent === false ? formatNum(previous) : pct(previous)}</td>
              <td className={(row.change ?? 0) >= 0 ? "report-up" : "report-down"}>{ppText(row.change)}</td>
              <td><SignalBadge tone={row.tone as "up" | "warn" | "info" | "danger"} text={row.signal} /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SectorDepthReport({ rows }: { rows: Array<Record<string, unknown>> }) {
  const visible = rows.slice(0, 8);
  if (!visible.length) return <EmptyState text="暂无二级板块聚合数据。" />;
  return (
    <table className="report-matrix">
      <thead>
        <tr>
          <th>二级板块</th>
          <th>上榜数</th>
          <th>成交额(亿)</th>
          <th>占Top50%</th>
          <th>HHI</th>
          <th>集中度</th>
          <th>热门股票 Top3</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((row) => (
          <tr key={String(row.secondary_industry)}>
            <td><strong>{reviewCell(row.secondary_industry)}</strong></td>
            <td>{reviewCell(row.count)}</td>
            <td>{formatNum(numberFromText(row.amount_yi))}</td>
            <td>{signedlessPct(numberFromText(row.ratio_pct))}</td>
            <td>{formatNum(numberFromText(row.hhi))}</td>
            <td><SignalBadge tone={concentrationTone(String(row.concentration))} text={String(row.concentration ?? "-")} /></td>
            <td className="report-left-cell">{reviewCell(row.leaders)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PrimaryIndustryReport({ rows }: { rows: Array<Record<string, unknown>> }) {
  const visible = rows.slice(0, 8);
  if (!visible.length) return <EmptyState text="暂无一级行业成交分布。" />;
  return (
    <table className="report-matrix">
      <thead>
        <tr>
          <th>一级行业</th>
          <th>上榜数</th>
          <th>成交额(亿)</th>
          <th>占Top50%</th>
          <th>代表性板块</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((row) => (
          <tr key={String(row.industry)}>
            <td><strong>{reviewCell(row.industry)}</strong></td>
            <td>{reviewCell(row.count)}</td>
            <td>{amountYiText(row.amount_yuan, row.amount)}</td>
            <td>{reviewCell(row.ratio)}</td>
            <td className="report-left-cell">{reviewCell(row.stocks)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MoneyFlowReport({ secondaryRows }: { secondaryRows: Array<Record<string, unknown>> }) {
  const top = secondaryRows.slice(0, 2);
  const rows = [
    { metric: "上证DDX", signal: "暂无", judge: "当前未接入稳定 DDX 数据源，不参与结论", tone: "warn" },
    { metric: "深证DDX", signal: "暂无", judge: "当前未接入稳定 DDX 数据源，不参与结论", tone: "warn" },
    { metric: "创业板DDX", signal: "暂无", judge: "当前未接入稳定 DDX 数据源，不参与结论", tone: "warn" },
    { metric: "科创综指DDX", signal: "暂无", judge: "当前未接入稳定 DDX 数据源，不参与结论", tone: "warn" },
    ...top.map((row) => ({
      metric: `${row.secondary_industry}板块(${row.count}只)`,
      signal: `${formatNum(numberFromText(row.amount_yi))}亿`,
      judge: `HHI=${formatNum(numberFromText(row.hhi))}，${row.concentration}；${row.leaders}`,
      tone: concentrationTone(String(row.concentration)),
    })),
  ];
  return (
    <table className="report-matrix">
      <thead>
        <tr>
          <th>指标</th>
          <th>信号</th>
          <th>判断</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.metric}>
            <td>{row.metric}</td>
            <td><SignalBadge tone={row.tone as "up" | "warn" | "info" | "danger"} text={row.signal} /></td>
            <td className="report-left-cell">{row.judge}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SectorRotationReport({ rotation }: { rotation?: DailyReviewDashboard["sections"][string] }) {
  const migration = asRows(rotation?.migration);
  const style = asRows(rotation?.style);
  return (
    <div className="report-subsections">
      <h4>6.1 板块资金迁移</h4>
      <table className="report-matrix">
        <thead>
          <tr>
            <th>方向</th>
            <th>板块</th>
            <th>成交额变化</th>
            <th>驱动</th>
          </tr>
        </thead>
        <tbody>
          {migration.map((row) => (
            <tr key={`${row.direction}-${row.sector}`}>
              <td><span className={row.direction === "流入" ? "flow-in" : "flow-out"}>{row.direction === "流入" ? "↑" : "↓"} {reviewCell(row.direction)}</span></td>
              <td>{reviewCell(row.sector)}</td>
              <td>{amountChangeText(row.previous_amount_yi, row.current_amount_yi, row.change_pct)}</td>
              <td className="report-left-cell">{reviewCell(row.driver)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>6.2 风格判断</h4>
      <table className="report-matrix">
        <thead>
          <tr>
            <th>维度</th>
            <th>判断</th>
            <th>证据</th>
          </tr>
        </thead>
        <tbody>
          {style.map((row) => (
            <tr key={String(row.dimension)}>
              <td>{reviewCell(row.dimension)}</td>
              <td><strong className="report-up">{reviewCell(row.judgement)}</strong></td>
              <td className="report-left-cell">{reviewCell(row.evidence)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectorMomentumReport({ rotation }: { rotation?: DailyReviewDashboard["sections"][string] }) {
  const momentum = asRows(rotation?.momentum);
  const concepts = asRows(rotation?.concepts);
  const signals = asRows(rotation?.signals);
  return (
    <div className="report-subsections">
      <h4>7.1 Top板块成交额</h4>
      <table className="report-matrix">
        <thead>
          <tr>
            <th>板块</th>
            <th>今日(亿)</th>
            <th>前一日(亿)</th>
            <th>变化</th>
            <th>趋势</th>
          </tr>
        </thead>
        <tbody>
          {momentum.map((row) => (
            <tr key={String(row.sector)}>
              <td>{reviewCell(row.sector)}</td>
              <td>{formatNum(numberFromText(row.current_amount_yi))}</td>
              <td>{formatNum(numberFromText(row.previous_amount_yi))}</td>
              <td className={(numberFromText(row.change_pct) ?? 0) >= 0 ? "report-up" : "report-down"}>{signedPct(numberFromText(row.change_pct))}</td>
              <td><SignalBadge tone={trendTone(String(row.trend))} text={String(row.trend ?? "-")} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>7.2 概念板块涨幅排名</h4>
      <table className="report-matrix">
        <thead>
          <tr>
            <th>概念</th>
            <th>代表股</th>
            <th>涨幅</th>
            <th>驱动</th>
          </tr>
        </thead>
        <tbody>
          {concepts.map((row) => (
            <tr key={`${row.concept}-${row.stock}`}>
              <td>{reviewCell(row.concept)}</td>
              <td>{reviewCell(row.stock)}</td>
              <td className={(numberFromText(row.change_pct) ?? 0) >= 0 ? "report-up" : "report-down"}>{signedPct(numberFromText(row.change_pct))}</td>
              <td className="report-left-cell">{reviewCell(row.driver)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>7.3 轮动信号识别</h4>
      <table className="report-matrix">
        <thead>
          <tr>
            <th>信号类型</th>
            <th>板块</th>
            <th>强度</th>
            <th>意义</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((row) => (
            <tr key={String(row.type)}>
              <td>{reviewCell(row.type)}</td>
              <td>{reviewCell(row.sector)}</td>
              <td><SignalBadge tone={strengthTone(String(row.strength))} text={String(row.strength ?? "-")} /></td>
              <td className="report-left-cell">{reviewCell(row.meaning)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LiquidityRiskReport({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows.length) return <EmptyState text="暂无流动性数据。" />;
  return (
    <table className="report-matrix">
      <thead>
        <tr>
          <th>指标</th>
          <th>今日</th>
          <th>前一日</th>
          <th>变化</th>
          <th>判断</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={String(row.label)}>
            <td>{reviewCell(row.label)}</td>
            <td>{metricWithUnit(row.today, row.unit)}</td>
            <td>{metricWithUnit(row.previous, row.unit)}</td>
            <td className={(numberFromText(row.change_pct) ?? 0) >= 0 ? "report-up" : "report-down"}>{signedPct(numberFromText(row.change_pct))}</td>
            <td><SignalBadge tone={liquidityTone(String(row.judgement))} text={String(row.judgement ?? "-")} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SentimentDashboard({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows.length) return <EmptyState text="暂无情绪仪表盘数据。" />;
  return (
    <table className="report-matrix report-risk-table">
      <thead>
        <tr>
          <th>维度</th>
          <th>指标</th>
          <th>数值</th>
          <th>评分</th>
          <th>情绪</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const firstInGroup = index === 0 || rows[index - 1].dimension !== row.dimension;
          const rowSpan = rows.filter((item) => item.dimension === row.dimension).length;
          return (
            <tr key={`${row.dimension}-${row.metric}`}>
              {firstInGroup && <td className="risk-group-cell" rowSpan={rowSpan}>{reviewCell(row.dimension)}</td>}
              <td>{reviewCell(row.metric)}</td>
              <td>{reviewCell(row.value)}</td>
              <td>{reviewCell(row.score)}</td>
              <td><strong className={sentimentClass(String(row.sentiment))}>{reviewCell(row.sentiment)}</strong></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function EventReport({ rows, newsRows }: { rows: Array<Record<string, unknown>>; newsRows: Array<Record<string, unknown>> }) {
  if (!rows.length) return <EmptyState text="暂无核心事件数据。" />;
  return (
    <div className="report-subsections">
      <table className="report-matrix event-table">
        <thead>
          <tr>
            <th>事件</th>
            <th>影响板块</th>
            <th>信号</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.event)}>
              <td className="report-left-cell"><strong>{reviewCell(row.event)}</strong><br />{reviewCell(row.description)}</td>
              <td>{reviewCell(row.impact)}</td>
              <td><SignalBadge tone={eventTone(String(row.signal))} text={String(row.signal ?? "-")} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActionAdviceReport({ actions }: { actions?: DailyReviewDashboard["sections"][string] }) {
  const rows = asRows(actions?.items);
  return (
    <>
      <table className="report-matrix">
        <thead>
          <tr>
            <th>方向</th>
            <th>标的/板块</th>
            <th>操作</th>
            <th>评级</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.direction}-${index}`}>
              <td>{reviewCell(row.direction)}</td>
              <td>{reviewCell(row.target)}</td>
              <td className="report-left-cell">{reviewCell(row.action)}</td>
              <td><SignalBadge tone={adviceTone(String(row.rating))} text={String(row.rating ?? "-")} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="danger-note">{String(actions?.warning ?? "方向判断：等待更多确认信号。")}</div>
    </>
  );
}

function CoreConclusionReport({ conclusions, missing }: { conclusions?: DailyReviewDashboard["sections"][string]; missing: Array<{ name: string; label: string; reason: string }> }) {
  const items = conclusions?.items as string[] | undefined;
  return (
    <>
      <ol className="review-conclusions">
        {(items ?? []).map((item) => <li key={item}>{item}</li>)}
      </ol>
      <div className="missing-list">
        {missing.map((item) => (
          <span key={item.name} title={item.reason}>{item.label}</span>
        ))}
      </div>
    </>
  );
}

function ReviewTable({ rows, columns }: { rows: Array<Record<string, unknown>>; columns: Array<[string, string]> }) {
  if (!rows.length) return <EmptyState text="暂无数据。" />;
  return (
    <div className="table-wrap compact-table">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column[0]}>{column[1]}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => <td key={column[0]}>{reviewCell(row[column[0]])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SignalBadge({ tone, text }: { tone: "up" | "warn" | "info" | "danger"; text: string }) {
  return <span className={`signal-badge ${tone}`}>{text}</span>;
}

export function LearningPage({ learning }: { learning: LearningItem[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(learning[0]?.id ?? null);
  const [detail, setDetail] = useState<MarkdownDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    api.learningDetail(selectedId).then(setDetail).catch((err) => setError(err.message));
  }, [selectedId]);
  return (
    <MarkdownLibrary
      icon={BookOpen}
      title="学习中心"
      items={learning.map((item) => ({ ...item, kind: "学习资料" }))}
      selectedId={selectedId}
      setSelectedId={setSelectedId}
      detail={detail}
      error={error}
    />
  );
}

function MarkdownLibrary({
  icon,
  title,
  items,
  selectedId,
  setSelectedId,
  detail,
  error
}: {
  icon: LucideIcon;
  title: string;
  items: Array<{ id: string; title: string; kind: string }>;
  selectedId: string | null;
  setSelectedId: (id: string) => void;
  detail: MarkdownDetail | null;
  error: string | null;
}) {
  return (
    <section className="reader-layout">
      <section className="panel">
        <PanelTitle icon={icon} title={title} />
        <div className="report-grid compact">
          {items.map((item) => (
            <button className={`report-item ${selectedId === item.id ? "active" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}>
              <span>{item.kind}</span>
              <strong>{item.title}</strong>
              <small>{item.id}</small>
            </button>
          ))}
        </div>
      </section>
      <section className="panel reader-panel">
        {error && <div className="alert">{error}</div>}
        {detail ? (
          <>
            <PanelTitle icon={FileText} title={detail.title} />
            <MarkdownView content={detail.content} />
          </>
        ) : (
          <EmptyState text="选择一张卡片查看正文。" />
        )}
      </section>
    </section>
  );
}

export function DataPage({ health, overview }: { health: Health | null; overview: MarketOverview | null }) {
  return (
    <section className="grid-page">
      <div className="metric-row">
        <Metric label="数据库" value={health?.ok ? "可用" : "不可用"} />
        <Metric label="起始日期" value={health?.start_date ?? "-"} />
        <Metric label="最新日期" value={health?.latest_date ?? "-"} />
        <Metric label="记录数" value={formatInt(health?.rows)} />
      </div>
      <section className="panel span-2">
        <PanelTitle icon={Database} title="数据分层" />
        <div className="data-layers">
          <div><strong>主数据源</strong><span>astocks_qfq.db 前复权日线，负责行情、指标、回测。</span></div>
          <div><strong>派生数据</strong><span>候选评分、策略结果、信号历史。</span></div>
          <div><strong>辅助证据</strong><span>妙想热点、日报、新闻摘要，只做解释，不直接决定评分。</span></div>
        </div>
      </section>
      <section className="panel">
        <PanelTitle icon={ShieldAlert} title="最新市场覆盖" />
        <p>最新截面：{overview?.date ?? "-"}</p>
        <p>股票数：{formatInt(overview?.stock_count)}</p>
      </section>
    </section>
  );
}

function CandidateTable({
  rows,
  selected,
  onSelect,
  onOpenStock,
  concentrationMap,
  compact
}: {
  rows: Candidate[];
  selected?: Candidate | null;
  onSelect?: (candidate: Candidate) => void;
  onOpenStock?: (candidate: Candidate) => void;
  concentrationMap?: Map<string, ConcentrationResponse["distribution"][number]>;
  compact?: boolean;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>评分</th>
            <th>分组</th>
            {!compact && <th>建议</th>}
            <th>涨跌</th>
            <th>成交额</th>
            {!compact && <th>拥挤度</th>}
            {!compact && <th>技术状态</th>}
            {!compact && <th>操作</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.ts_code} className={selected?.ts_code === row.ts_code ? "selected" : ""} onClick={() => onSelect?.(row)}>
              <td>
                <button className="link-button" onClick={(event) => {
                  event.stopPropagation();
                  onOpenStock?.(row);
                }}>
                  {row.name}
                </button>
                <small>{row.code}</small>
              </td>
              <td><span className="score">{row.score}</span></td>
              <td>{row.group}</td>
              {!compact && <td>{row.action_hint}</td>}
              <td className={(row.change_pct ?? 0) >= 0 ? "positive" : "negative"}>{pct(row.change_pct)}</td>
              <td>{formatNum(row.amount_yi)}亿</td>
              {!compact && <td><ConcentrationBadge item={concentrationMap?.get(row.code)} /></td>}
              {!compact && <td>{row.macd_status} / {row.kdj_status} / RSI {formatNum(row.rsi14)} / {td9Status(row)}</td>}
              {!compact && <td><button className="small-button" onClick={(event) => {
                event.stopPropagation();
                onOpenStock?.(row);
              }}>详情</button></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConcentrationBadge({ item }: { item?: ConcentrationResponse["distribution"][number] }) {
  if (!item) return <span className="muted-pill">非Top250</span>;
  const label = item.rank <= 10 ? "Top10拥挤" : item.rank <= 20 ? "Top20活跃" : item.rank <= 50 ? "Top50主线" : "Top250";
  const tone = item.rank <= 20 ? "hot" : item.rank <= 50 ? "watch" : "calm";
  return (
    <span className={`concentration-badge ${tone}`} title={`成交额排名第 ${item.rank}，单票权重 ${pct(item.weight_pct)}，累计权重 ${pct(item.cumulative_weight_pct)}`}>
      {label}
    </span>
  );
}

function CandidateDetail({
  candidate,
  onOpenStock,
  concentrationInfo
}: {
  candidate: Candidate | null;
  onOpenStock?: (candidate: Candidate) => void;
  concentrationInfo?: ConcentrationResponse["distribution"][number];
}) {
  if (!candidate) return <EmptyState text="选择候选股后查看详情。" />;
  return (
    <section className="panel detail-panel">
      <div className="panel-heading">
        <PanelTitle icon={Target} title={`${candidate.name}(${candidate.code})`} />
        {onOpenStock && <button className="small-button" onClick={() => onOpenStock(candidate)}>打开个股分析</button>}
      </div>
      <div className="metric-row tight">
        <Metric label="评分" value={candidate.score} />
        <Metric label="分组" value={candidate.group} />
        <Metric label="建议" value={candidate.action_hint} />
      </div>
      <h3>资金拥挤度</h3>
      {concentrationInfo ? (
        <div className="concentration-detail">
          <ConcentrationBadge item={concentrationInfo} />
          <span>成交额排名第 {concentrationInfo.rank}，单票权重 {pct(concentrationInfo.weight_pct)}，累计到这里约 {pct(concentrationInfo.cumulative_weight_pct)}。</span>
          <small>{concentrationInfo.rank <= 20 ? "关注度很高，适合等回踩或策略信号确认，不适合只因为热门就追。" : "成交活跃但不算最拥挤，仍要结合趋势和回撤判断。"}</small>
        </div>
      ) : (
        <p className="note">当前不在 Top250 成交额样本内，说明资金关注度相对靠后；要更重视流动性和成交连续性。</p>
      )}
      <h3>客观理由</h3>
      <ul className="tag-list">{candidate.reasons.map((item) => <li key={item}>{item}</li>)}</ul>
      <h3>TD9 序列</h3>
      <div className="td9-guide">
        <strong>{td9Status(candidate)}</strong>
        <span>{td9Guide(candidate)}</span>
      </div>
      <h3>风险标签</h3>
      <ul className="tag-list risk">{candidate.risks.length ? candidate.risks.map((item) => <li key={item}>{item}</li>) : <li>暂无显著规则风险</li>}</ul>
      <h3>辅助证据</h3>
      <p className="note">妙想热点和报告引用只作为解释层，不参与 DB 客观评分。</p>
    </section>
  );
}

function StrategySummaryTable({ rows }: { rows: StrategySummary[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>策略</th>
            <th>策略收益</th>
            <th>买入持有</th>
            <th>超额</th>
            <th>最大回撤</th>
            <th>交易</th>
            <th>胜率</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={`${row.code}-${row.strategy_label}-${idx}`}>
              <td>{row.name}({String(row.code).padStart(6, "0")})</td>
              <td>{row.strategy_label}</td>
              <td>{pct(row.total_return_pct)}</td>
              <td>{pct(row.buy_hold_return_pct)}</td>
              <td className={(row.excess_return_pct ?? 0) >= 0 ? "positive" : "negative"}>{pct(row.excess_return_pct)}</td>
              <td>{pct(row.max_drawdown_pct)}</td>
              <td>{row.trade_count}</td>
              <td>{pct(row.win_rate_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StrategyForStock({
  detail,
  job,
  activeStrategy,
  setActiveStrategy
}: {
  detail: StockStrategyDetail | null;
  job: BacktestJob | null;
  activeStrategy: string;
  setActiveStrategy: (value: TechnicalKey) => void;
}) {
  const summary = detail?.summary ?? [];
  const active = summary.find((row) => row.strategy === activeStrategy);
  return (
    <div className="strategy-detail">
      <div className="segmented">
        {technicalKeys.map((item) => (
          <button key={item} className={activeStrategy === item ? "active" : ""} onClick={() => setActiveStrategy(item)}>
            {item.toUpperCase()}
          </button>
        ))}
      </div>
      {active ? (
        <>
          {job && <div className={`job-status ${job.status}`}>{job.message}</div>}
          <div className="metric-row tight">
            <Metric label="策略收益" value={pct(active.total_return_pct)} />
            <Metric label="首买持有" value={pct(active.first_entry_hold_return_pct)} />
            <Metric label="首买超额" value={pct(active.first_entry_excess_return_pct)} />
          </div>
          <div className="metric-row tight">
            <Metric label="首次买入" value={active.first_entry_date ?? "-"} />
            <Metric label="买入价" value={formatNum(active.first_entry_price)} />
            <Metric label="区间持有" value={pct(active.buy_hold_return_pct)} />
          </div>
          <div className="metric-row tight">
            <Metric label="最大回撤" value={pct(active.max_drawdown_pct)} />
            <Metric label="交易次数" value={active.trade_count} />
            <Metric label="胜率" value={pct(active.win_rate_pct)} />
          </div>
          <TradeList detail={detail} strategy={activeStrategy} />
        </>
      ) : (
        <>
          {job && <div className={`job-status ${job.status}`}>{job.message}</div>}
          <EmptyState text={activeStrategy === "td9" ? "当前回测结果还没有 TD9 策略；重新运行单股回测后会生成。" : detail?.message ?? "当前股票暂无策略验证结果。"} />
        </>
      )}
    </div>
  );
}

function TradeList({ detail, strategy }: { detail: StockStrategyDetail | null; strategy: string }) {
  const trades = (detail?.trades ?? []).filter((trade) => strategy === "all" || trade.strategy === strategy);
  if (!trades.length) return <EmptyState text="暂无买卖明细。" />;
  return (
    <div className="trade-list">
      {trades.slice(0, 12).map((trade, idx) => (
        <div className="trade-item" key={`${trade.strategy}-${trade.entry_date}-${idx}`}>
          <div>
            <strong>{trade.strategy_label}</strong>
            <span>{trade.entry_date ?? "-"} 买入 {formatNum(trade.entry_price)} → {trade.exit_date ?? "持仓中"} 卖出 {formatNum(trade.exit_price)}</span>
          </div>
          <div className={(trade.return_pct ?? 0) >= 0 ? "positive" : "negative"}>
            {pct(trade.return_pct)}
          </div>
          <small>{trade.entry_reason ?? "-"} / {trade.exit_reason ?? trade.status} / {trade.holding_days ?? "-"} 天</small>
        </div>
      ))}
    </div>
  );
}

function MiniChart({ rows, field, color }: { rows: Array<Record<string, number | string | null>>; field: string; color: string }) {
  const values = rows.map((row) => Number(row[field])).filter((value) => Number.isFinite(value));
  if (values.length < 2) return <EmptyState text="暂无足够图表数据。" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * 100;
    const y = 56 - ((value - min) / range) * 48;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg className="mini-chart" viewBox="0 0 100 64" preserveAspectRatio="none">
      <polyline fill="none" stroke={color} strokeWidth="2" points={points} />
    </svg>
  );
}

function buildConcentrationMap(payload: ConcentrationResponse | null): Map<string, ConcentrationResponse["distribution"][number]> {
  const map = new Map<string, ConcentrationResponse["distribution"][number]>();
  for (const item of payload?.distribution ?? []) {
    map.set(item.code, item);
  }
  return map;
}

function candidateFromConcentration(row: ConcentrationResponse["top"][number], candidates: Candidate[]): Candidate {
  const existing = candidates.find((candidate) => candidate.code === row.code);
  if (existing) return existing;
  return {
    code: row.code,
    ts_code: row.ts_code,
    name: row.name,
    score: 0,
    group: "资金活跃",
    action_hint: "重点观察",
    close: row.close ?? 0,
    change_pct: row.change_pct,
    amount_yi: row.amount_yi ?? 0,
    amount_rank: row.rank,
    ret20_pct: null,
    ret60_pct: null,
    drawdown20_pct: null,
    macd_status: "待查看",
    kdj_status: "待查看",
    rsi14: null,
    reasons: [`Top250 成交额排名第 ${row.rank}`, `单日成交额 ${formatNum(row.amount_yi)} 亿`],
    risks: row.rank <= 20 ? ["资金关注度高，避免情绪化追高"] : [],
  };
}

function marketActionPlan(overview: MarketOverview | null, latest: ConcentrationRow | null) {
  const up = overview?.up ?? 0;
  const down = overview?.down ?? 0;
  const cr10 = latest?.cr10_pct ?? null;
  const cr10Change = latest?.cr10_pct_change ?? 0;
  const effectiveChange = latest?.effective_count_change ?? 0;
  const breadthGood = up > down * 1.25;
  const breadthWeak = down > up * 1.15;
  const crowded = cr10 !== null && (cr10 >= 18 || (cr10Change > 0.5 && effectiveChange < 0));
  const spreading = cr10 !== null && cr10Change <= 0.2 && (latest?.cr50_pct_change ?? 0) > 0.3;
  if (breadthWeak && crowded) {
    return {
      level: "defensive",
      title: "市场偏拥挤，先防守",
      summary: "下跌家数占优，同时资金仍集中在少数股票；新手更适合降低冲动交易，等回踩和信号确认。",
      items: [
        { label: "宽度", value: `涨 ${up} / 跌 ${down}`, hint: "市场承接偏弱" },
        { label: "集中度", value: `CR10 ${pct(cr10)}`, hint: "头部交易拥挤" },
        { label: "动作", value: "少追高", hint: "只观察策略信号明确的股票" },
      ],
    };
  }
  if (breadthGood && spreading) {
    return {
      level: "active",
      title: "热点有扩散迹象",
      summary: "上涨家数占优，Top50 扩张强于 Top10，说明资金可能从龙头向更多股票扩散。",
      items: [
        { label: "宽度", value: `涨 ${up} / 跌 ${down}`, hint: "市场参与度较好" },
        { label: "扩散", value: `CR50 ${pct(latest?.cr50_pct)}`, hint: "观察低位转强候选" },
        { label: "动作", value: "分批验证", hint: "优先看回撤小、成交连续的候选" },
      ],
    };
  }
  if (crowded) {
    return {
      level: "watch",
      title: "主线清楚但偏拥挤",
      summary: "资金集中度较高，强势股可能继续强，但追高回撤也会放大。",
      items: [
        { label: "集中度", value: `CR10 ${pct(cr10)}`, hint: "头部吸金明显" },
        { label: "有效股票数", value: formatNum(latest?.effective_count), hint: "越低越拥挤" },
        { label: "动作", value: "等回踩", hint: "结合个股策略验证" },
      ],
    };
  }
  return {
    level: "balanced",
    title: "市场环境相对均衡",
    summary: "暂未看到极端拥挤或明显退潮，新手可以按候选评分逐只验证，不急于满仓。",
    items: [
      { label: "宽度", value: `涨 ${up} / 跌 ${down}`, hint: "观察是否持续改善" },
      { label: "集中度", value: `CR10 ${pct(cr10)}`, hint: "资金分布不算极端" },
      { label: "动作", value: "逐只复盘", hint: "看 K 线、指标和回测是否一致" },
    ],
  };
}

function concentrationContext(latest: ConcentrationRow | null): string {
  if (!latest) return "等待集中度数据加载。";
  const cr10 = latest.cr10_pct ?? 0;
  const cr10Change = latest.cr10_pct_change ?? 0;
  const effectiveChange = latest.effective_count_change ?? 0;
  if (cr10 >= 18 || (cr10Change > 0.5 && effectiveChange < 0)) return "资金更抱团，强势股可能强者恒强，但追高风险上升。";
  if (cr10Change < -0.4 && effectiveChange > 0) return "资金从头部扩散，适合观察低位转强和回踩确认。";
  return "资金分布相对均衡，结合市场宽度和候选评分一起看。";
}

function concentrationLevel(latest: ConcentrationRow | null): string {
  const cr10 = latest?.cr10_pct ?? null;
  if (cr10 === null) return "暂无判断";
  if (cr10 >= 18) return "资金高度集中";
  if (cr10 >= 12) return "资金明显集中";
  if (cr10 >= 8) return "资金适度集中";
  return "资金较分散";
}

function concentrationExplain(latest: ConcentrationRow | null): string {
  const cr10 = latest?.cr10_pct ?? null;
  const effective = latest?.effective_count ?? null;
  if (cr10 === null) return "等待数据库返回更多交易日后再观察。";
  if (cr10 >= 18) return `Top10 已占 ${pct(cr10)}，说明头部股票吸走较多成交额；新手更适合等回踩或策略确认。`;
  if (cr10 >= 12) return `Top10 占 ${pct(cr10)}，主线较清楚，但要警惕高位拥挤和连续上涨后的回撤。`;
  if (effective !== null && effective > 80) return `有效股票数约 ${formatNum(effective)}，成交分布较宽，热点可能在扩散，适合多看分组而不是只盯龙头。`;
  return `Top10 占 ${pct(cr10)}，集中度不高，说明资金没有明显只抱团少数股票。`;
}

function buildReviewQueue(candidates: Candidate[], notes: Record<string, ReviewNote>) {
  return candidates
    .map((candidate) => {
      const note = notes[candidate.code];
      return {
        candidate,
        reason: reviewQueueReason(candidate),
        done: Boolean(note),
        plan: note?.plan
      };
    })
    .filter((item, index) => index < 12 || item.done || item.reason !== "常规候选")
    .sort((left, right) => {
      if (left.done !== right.done) return left.done ? 1 : -1;
      return right.candidate.score - left.candidate.score;
    })
    .slice(0, 8);
}

function reviewQueueReason(candidate: Candidate): string {
  const structure = [...candidate.reasons, ...candidate.risks].find((item) => /背离|钝化|低9|高9|TD/.test(item));
  if (candidate.action_hint === "重点观察" || candidate.score >= 85) return "高评分重点观察";
  if (candidate.action_hint === "等待回踩" || candidate.action_hint === "过热不追") return "追高风险需复盘";
  if (candidate.td_buy_setup === 9 || candidate.td_signal === "low9") return "TD低9结构观察";
  if (candidate.td_sell_setup === 9 || candidate.td_signal === "high9") return "TD高9风险复盘";
  if (structure) return structure;
  if (candidate.risks.length >= 2) return "风险标签较多";
  if (candidate.group) return candidate.group;
  return "常规候选";
}

function reviewPlanFromAction(action: string): ReviewNote["plan"] {
  if (action.includes("回踩")) return "等回踩";
  if (action.includes("风险") || action.includes("放弃")) return "放弃";
  if (action.includes("重点")) return "观察";
  return "观察";
}

function todayString(): string {
  return new Date().toISOString().slice(0, 10);
}

function latestDailyReportDate(reports: ReportItem[]): string {
  const match = reports
    .map((item) => item.id.match(/daily_review_(\d{4}-\d{2}-\d{2})/))
    .find(Boolean);
  return match?.[1] ?? new Date().toISOString().slice(0, 10);
}

function amountYiText(amountYuan: unknown, fallback: unknown): string {
  const amount = numberFromText(amountYuan);
  if (amount !== null && amount > 100000000) return formatNum(amount / 100000000);
  return reviewCell(fallback).replace("亿", "");
}

function concentrationTone(value: string): "up" | "warn" | "info" | "danger" {
  if (value.includes("单票")) return "danger";
  if (value.includes("寡头")) return "warn";
  if (value.includes("偏集中")) return "info";
  return "up";
}

function trendTone(value: string): "up" | "warn" | "info" | "danger" {
  if (value.includes("退")) return "danger";
  if (value.includes("激") || value.includes("增") || value.includes("新")) return "up";
  if (value.includes("持平")) return "info";
  return "warn";
}

function strengthTone(value: string): "up" | "warn" | "info" | "danger" {
  if (value.includes("强")) return "up";
  if (value.includes("弱")) return "danger";
  if (value.includes("待")) return "warn";
  return "info";
}

function amountChangeText(previous: unknown, current: unknown, change: unknown): string {
  const prev = numberFromText(previous);
  const cur = numberFromText(current);
  const pctValue = numberFromText(change);
  const prevText = prev && prev > 0 ? formatNum(prev) : "0";
  const curText = cur && cur > 0 ? formatNum(cur) : "0";
  if (pctValue === null) return `${prevText}→${curText}亿（新晋）`;
  return `${prevText}→${curText}亿（${signedPct(pctValue)}）`;
}

function metricWithUnit(value: unknown, unit: unknown): string {
  const numeric = numberFromText(value);
  if (numeric === null) return "-";
  return `${formatNum(numeric)}${unit ?? ""}`;
}

function liquidityTone(value: string): "up" | "warn" | "info" | "danger" {
  if (value.includes("高") || value.includes("放") || value.includes("吸金")) return "up";
  if (value.includes("缩") || value.includes("降温")) return "danger";
  if (value.includes("中")) return "info";
  return "warn";
}

function eventTone(value: string): "up" | "warn" | "info" | "danger" {
  if (value.includes("强")) return "up";
  if (value.includes("中")) return "info";
  if (value.includes("风险") || value.includes("退")) return "danger";
  return "warn";
}

function sentimentClass(value: string): string {
  if (value.includes("乐观") || value.includes("成长") || value.includes("进攻")) return "report-up";
  if (value.includes("悲观") || value.includes("谨慎")) return "report-down";
  return "report-info";
}

function adviceTone(value: string): "up" | "warn" | "info" | "danger" {
  if (value.includes("重点") || value.includes("持有")) return "up";
  if (value.includes("风险") || value.includes("防守")) return "danger";
  if (value.includes("等待") || value.includes("确认")) return "warn";
  return "info";
}

function archiveStatus(value: string | undefined): string {
  if (value === "archived") return "归档命中";
  if (value === "saved") return "已写入归档";
  if (value === "rebuilt") return "已刷新重建";
  if (value === "created") return "新建归档";
  return "未归档";
}

function stockDecision(
  candidate: Candidate,
  analysis: IndicatorResponse["analysis"] | undefined,
  activeSummary: StrategySummary | undefined,
  activeStrategy: TechnicalKey
) {
  const trend = analysis?.trend;
  const nearestFib = analysis?.fibonacci?.nearest;
  const structure = analysis?.structure ?? [];
  const trendPositive = trend?.status === "强趋势" || trend?.status === "趋势修复";
  const trendWeak = trend?.status === "趋势偏弱";
  const strategyReturn = activeSummary?.total_return_pct ?? null;
  const strategyTrades = activeSummary?.trade_count ?? 0;
  const strategyPositive = strategyReturn !== null && strategyReturn > 0;
  const topRisk = structure.some((item) => item.type.includes("top")) || candidate.risks.some((item) => item.includes("高") || item.includes("风险") || item.includes("顶"));
  const tdHot = candidate.td_signal === "high9" || candidate.td_sell_setup === 9;
  const farAboveMa20 = (trend?.distance_ma20_pct ?? 0) > 15;
  const positives = [
    ...(trendPositive ? [`趋势状态：${trend?.status}`] : []),
    ...(candidate.reasons.slice(0, 2)),
    ...(strategyPositive ? [`${activeStrategy.toUpperCase()} 回测收益为正`] : []),
    ...(structure.some((item) => item.type.includes("bottom")) ? ["近期有底部结构观察信号"] : []),
  ];
  const risks = [
    ...candidate.risks.slice(0, 2),
    ...(trendWeak ? ["趋势偏弱，左侧信号需要等待确认"] : []),
    ...(topRisk ? ["存在顶部结构或追高风险"] : []),
    ...(tdHot ? ["TD高9附近，不适合情绪化追高"] : []),
    ...(farAboveMa20 ? ["价格距离MA20偏远，回撤敏感度上升"] : []),
    ...(strategyTrades === 0 ? [`${activeStrategy.toUpperCase()} 当前没有可执行交易样本`] : []),
  ];
  const cleanPositives = positives.length ? positives : ["暂无强一致信号，先以观察为主"];
  const cleanRisks = risks.length ? Array.from(new Set(risks)) : ["暂无显著规则风险，但仍需控制仓位"];
  let action = candidate.action_hint || "继续观察";
  let tone = "balanced";
  let summary = "信号还没有形成强一致，适合继续观察而不是急于行动。";
  if (trendPositive && strategyPositive && cleanRisks.length <= 2 && !tdHot) {
    action = "重点观察";
    tone = "active";
    summary = "趋势和当前策略表现相对配合，可进入重点观察，但仍要等待实际信号和回撤位置。";
  }
  if (farAboveMa20 || tdHot || topRisk) {
    action = "等回踩";
    tone = "watch";
    summary = "关注度或涨幅偏高，当前更适合等回踩、等结构重新确认。";
  }
  if (trendWeak || candidate.risks.length >= 3) {
    action = "风险较高";
    tone = "defensive";
    summary = "趋势或风险标签不友好，新手更适合降低仓位假设，只做复盘观察。";
  }
  return {
    action,
    tone,
    summary,
    positives: cleanPositives.slice(0, 3),
    risks: cleanRisks.slice(0, 3),
    items: [
      { label: "趋势", value: trend?.status ?? "-", hint: trend?.hint ?? "等待数据" },
      { label: "位置", value: nearestFib?.label ?? "-", hint: nearestFib ? `距现价 ${pct(nearestFib.distance_pct)}` : "暂无斐波那契参考" },
      { label: "策略", value: activeSummary ? pct(activeSummary.total_return_pct) : "-", hint: activeSummary ? `${activeStrategy.toUpperCase()} / ${activeSummary.trade_count} 次交易` : "暂无当前策略回测" },
      { label: "风险", value: cleanRisks.length ? `${cleanRisks.length}项` : "低", hint: cleanRisks[0] ?? "暂无显著风险" },
    ],
  };
}

function td9Status(row: Pick<Candidate, "td_buy_setup" | "td_sell_setup" | "td_signal">): string {
  if (row.td_signal === "low9" || row.td_buy_setup === 9) return "TD低9";
  if (row.td_signal === "high9" || row.td_sell_setup === 9) return "TD高9";
  const buy = row.td_buy_setup ?? 0;
  const sell = row.td_sell_setup ?? 0;
  if (buy >= 6) return `低${buy}`;
  if (sell >= 6) return `高${sell}`;
  return "TD平稳";
}

function td9Guide(row: Pick<Candidate, "td_buy_setup" | "td_sell_setup" | "td_signal">): string {
  if (row.td_signal === "low9" || row.td_buy_setup === 9) return "近期连续走弱达到低9，只代表进入超跌观察区，需要等止跌、放量或趋势指标改善后再验证。";
  if (row.td_signal === "high9" || row.td_sell_setup === 9) return "近期连续走强达到高9，说明关注度和短线涨幅可能偏热，新手不宜只因热门追高。";
  const buy = row.td_buy_setup ?? 0;
  const sell = row.td_sell_setup ?? 0;
  if (buy >= 6) return "低位序列正在累积，先观察是否继续弱势，等出现转强证据。";
  if (sell >= 6) return "高位序列正在累积，趋势可能仍强，但要开始关注回撤风险。";
  return "当前没有明显九转序列提醒，仍以趋势、成交和回撤为主。";
}
