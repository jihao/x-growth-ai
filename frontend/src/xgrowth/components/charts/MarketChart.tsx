import { useEffect, useState } from "react";
import type { TechnicalKey } from "../../appTypes";
import type { IndicatorResponse } from "../../types";
import { formatCompact, formatInt, formatNum, shortDate } from "../../utils/formatters";
import { EmptyState } from "../ui/Panel";

export function MarketChart({
  rows,
  analysis,
  indicator,
  strategy,
  signals
}: {
  rows: IndicatorResponse["rows"];
  analysis?: IndicatorResponse["analysis"];
  indicator: TechnicalKey;
  strategy: string;
  signals: Array<{ date: string; signal: string; reason: string }>;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [visibleCount, setVisibleCount] = useState(120);
  const [windowEnd, setWindowEnd] = useState(0);
  const [showFibonacci, setShowFibonacci] = useState(false);
  const fullData = rows.filter((row) => row.open && row.high && row.low && row.close);
  useEffect(() => {
    setWindowEnd(fullData.length);
  }, [fullData.length]);
  const safeVisibleCount = Math.min(visibleCount, fullData.length);
  const safeWindowEnd = Math.min(Math.max(windowEnd || fullData.length, safeVisibleCount), fullData.length);
  const windowStart = Math.max(0, safeWindowEnd - safeVisibleCount);
  const data = fullData.slice(windowStart, safeWindowEnd);
  if (data.length < 2) return <EmptyState text="暂无足够 K 线数据。" />;

  const width = 980;
  const plotWidth = 900;
  const axisX = 910;
  const height = 585;
  const candleTop = 22;
  const showIndicatorPanel = indicator !== "td9";
  const candleHeight = showIndicatorPanel ? 260 : 350;
  const volumeTop = candleTop + candleHeight + 24;
  const volumeHeight = 82;
  const indicatorTop = volumeTop + volumeHeight + 26;
  const indicatorHeight = 110;
  const chartBottom = showIndicatorPanel ? indicatorTop + indicatorHeight : volumeTop + volumeHeight;
  const timeAxisY = chartBottom + 28;
  const signalMap = new Map(signals.map((item) => [item.date, item]));
  const high = Math.max(...data.map((row) => Number(row.high)));
  const low = Math.min(...data.map((row) => Number(row.low)));
  const priceRange = high - low || 1;
  const maxVolume = Math.max(...data.map((row) => Number(row.volume ?? 0)), 1);
  const candleGap = plotWidth / data.length;
  const candleWidth = Math.max(3, Math.min(9, candleGap * 0.62));
  const priceY = (value: number) => candleTop + (high - value) / priceRange * candleHeight;
  const volumeY = (value: number) => volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;
  const indicatorLines = showIndicatorPanel ? indicatorSeries(data, indicator) : [];
  const overview = overviewLine(fullData);
  const selectedLeftPct = fullData.length ? windowStart / fullData.length * 100 : 0;
  const selectedWidthPct = fullData.length ? safeVisibleCount / fullData.length * 100 : 100;
  const hover = hoverIndex === null ? null : data[hoverIndex];
  const hoverX = hoverIndex === null ? null : hoverIndex * candleGap + candleGap / 2;
  const hoverCloseY = hover ? priceY(Number(hover.close)) : null;
  const hoverSignal = hover ? signalMap.get(hover.date) : null;
  const priceTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    ratio,
    y: candleTop + ratio * candleHeight,
    value: high - ratio * priceRange
  }));
  const fibLevels = showFibonacci ? (analysis?.fibonacci?.levels ?? []).filter((level) => level.price !== null && Number(level.price) <= high && Number(level.price) >= low) : [];
  const dateTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const index = Math.min(data.length - 1, Math.max(0, Math.round(ratio * (data.length - 1))));
    return { x: index * candleGap + candleGap / 2, label: shortDate(data[index].date) };
  });

  return (
    <div className="market-chart-wrap">
      <label className="chart-toggle" title="显示或隐藏斐波那契回调价位">
        <input type="checkbox" checked={showFibonacci} onChange={(event) => setShowFibonacci(event.currentTarget.checked)} />
        <span>斐波那契</span>
      </label>
      <svg
        className="market-chart"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const x = (event.clientX - rect.left) / rect.width * width;
          const index = Math.max(0, Math.min(data.length - 1, Math.floor(x / candleGap)));
          setHoverIndex(index);
        }}
      >
        <rect x="0" y="0" width={width} height={height} fill="#ffffff" />
        {priceTicks.map((tick) => (
          <line key={tick.ratio} x1="0" x2={plotWidth} y1={tick.y} y2={tick.y} className="grid-line" />
        ))}
        {fibLevels.map((level) => (
          <g key={level.label}>
            <line x1="0" x2={plotWidth} y1={priceY(Number(level.price))} y2={priceY(Number(level.price))} className="fib-line" />
            <text x={plotWidth - 86} y={priceY(Number(level.price)) - 4} className="fib-text">{level.label} {formatNum(level.price)}</text>
          </g>
        ))}
        {data.map((row, index) => {
          const x = index * candleGap + candleGap / 2;
          const open = Number(row.open);
          const close = Number(row.close);
          const up = close >= open;
          const yOpen = priceY(open);
          const yClose = priceY(close);
          const bodyY = Math.min(yOpen, yClose);
          const bodyHeight = Math.max(1, Math.abs(yClose - yOpen));
          const signal = signalMap.get(row.date);
          const tdBuySetup = Number(row.td_buy_setup ?? 0);
          const tdSellSetup = Number(row.td_sell_setup ?? 0);
          return (
            <g key={row.date}>
              <line x1={x} x2={x} y1={priceY(Number(row.high))} y2={priceY(Number(row.low))} className={up ? "candle-up" : "candle-down"} />
              <rect x={x - candleWidth / 2} y={bodyY} width={candleWidth} height={bodyHeight} className={up ? "candle-up-fill" : "candle-down-fill"} />
              <rect x={x - candleWidth / 2} y={volumeY(Number(row.volume ?? 0))} width={candleWidth} height={volumeTop + volumeHeight - volumeY(Number(row.volume ?? 0))} className={up ? "volume-up" : "volume-down"} />
              {tdBuySetup > 0 && (
                <text x={x - 4} y={priceY(Number(row.low)) + 28} className="td9-buy-text">
                  {tdBuySetup}
                </text>
              )}
              {tdSellSetup > 0 && (
                <text x={x - 4} y={priceY(Number(row.high)) - 18} className="td9-sell-text">
                  {tdSellSetup}
                </text>
              )}
              {signal && (
                <g className="trade-signal">
                  <circle cx={x} cy={signal.signal === "buy" ? priceY(Number(row.low)) + 14 : priceY(Number(row.high)) - 14} r="7" className={signal.signal === "buy" ? "signal-buy" : "signal-sell"} />
                  <text x={x - 3.5} y={signal.signal === "buy" ? priceY(Number(row.low)) + 18 : priceY(Number(row.high)) - 10} className="signal-text">{signal.signal === "buy" ? "B" : "S"}</text>
                </g>
              )}
            </g>
          );
        })}
        <line x1="0" x2={plotWidth} y1={volumeTop} y2={volumeTop} className="panel-line" />
        {showIndicatorPanel && <line x1="0" x2={plotWidth} y1={indicatorTop} y2={indicatorTop} className="panel-line" />}
        {indicatorLines.map((line) => (
          <polyline key={line.name} fill="none" stroke={line.color} strokeWidth="2" points={line.points} />
        ))}
        <line x1={axisX} x2={axisX} y1={candleTop} y2={chartBottom} className="axis-line" />
        {priceTicks.map((tick) => (
          <g key={`price-${tick.ratio}`}>
            <line x1={axisX - 4} x2={axisX} y1={tick.y} y2={tick.y} className="axis-line" />
            <text x={axisX + 6} y={tick.y + 4} className="axis-text">{formatNum(tick.value)}</text>
          </g>
        ))}
        <text x={axisX + 6} y={volumeTop + 12} className="axis-text">量 {formatCompact(maxVolume)}</text>
        {dateTicks.map((tick, idx) => (
          <g key={`${tick.label}-${idx}`}>
            <line x1={tick.x} x2={tick.x} y1={timeAxisY - 8} y2={timeAxisY - 2} className="axis-line" />
            <text x={tick.x - 24} y={timeAxisY + 14} className="axis-text">{tick.label}</text>
          </g>
        ))}
        {hover && hoverX !== null && hoverCloseY !== null && (
          <g className="crosshair">
            <line x1={hoverX} x2={hoverX} y1={candleTop} y2={chartBottom} />
            <line x1="0" x2={plotWidth} y1={hoverCloseY} y2={hoverCloseY} />
            <rect x={axisX + 2} y={hoverCloseY - 10} width="60" height="18" rx="3" />
            <text x={axisX + 8} y={hoverCloseY + 4}>{formatNum(hover.close)}</text>
          </g>
        )}
        <text x="10" y="18" className="chart-label">{indicator === "td9" ? "K线 / 成交量 / TD序列数字 / TD9信号" : `K线 / 成交量 / TD序列数字 / ${indicator.toUpperCase()} / ${strategy.toUpperCase()} 信号`}</text>
        {showIndicatorPanel && <text x="10" y={indicatorTop + 16} className="chart-label">{indicator.toUpperCase()}</text>}
      </svg>
      {hover && hoverX !== null && (
        <div className="chart-tooltip" style={{ left: `${Math.min(78, Math.max(2, hoverX / plotWidth * 100))}%` }}>
          <strong>{hover.date}</strong>
          <span>开 {formatNum(hover.open)} 高 {formatNum(hover.high)}</span>
          <span>低 {formatNum(hover.low)} 收 {formatNum(hover.close)}</span>
          <span>量 {formatCompact(Number(hover.volume ?? 0))}</span>
          <span>{indicator.toUpperCase()} {indicatorTooltip(hover, indicator)}</span>
          {macdStructureText(hover) && <span>{macdStructureText(hover)}</span>}
          {Number(hover.td_buy_setup ?? 0) > 0 && <span>TD下跌序列：{formatInt(hover.td_buy_setup)}，绿色数字在K线下方</span>}
          {Number(hover.td_sell_setup ?? 0) > 0 && <span>TD上涨序列：{formatInt(hover.td_sell_setup)}，红色数字在K线上方</span>}
          {hoverSignal && <span>{hoverSignal.signal === "buy" ? "买入" : "卖出"}：{hoverSignal.reason}</span>}
        </div>
      )}
      <div className="range-panel">
        <div className="range-buttons">
          {[60, 120, 240].map((count) => (
            <button
              key={count}
              className={visibleCount === count ? "active" : ""}
              onClick={() => {
                setVisibleCount(count);
                setWindowEnd(fullData.length);
                setHoverIndex(null);
              }}
            >
              {count}日
            </button>
          ))}
          <button
            className={visibleCount >= fullData.length ? "active" : ""}
            onClick={() => {
              setVisibleCount(fullData.length);
              setWindowEnd(fullData.length);
              setHoverIndex(null);
            }}
          >
            全部
          </button>
        </div>
        <div className="range-track">
          <svg viewBox="0 0 100 34" preserveAspectRatio="none">
            <polyline points={overview} fill="none" stroke="#94a3b8" strokeWidth="1.6" />
            <rect x={selectedLeftPct} y="3" width={selectedWidthPct} height="28" rx="2" className="range-selection" />
            <line x1={selectedLeftPct} x2={selectedLeftPct} y1="3" y2="31" className="range-handle-line" />
            <line x1={selectedLeftPct + selectedWidthPct} x2={selectedLeftPct + selectedWidthPct} y1="3" y2="31" className="range-handle-line" />
          </svg>
          <input
            aria-label="拖动时间窗口"
            type="range"
            min={safeVisibleCount}
            max={fullData.length}
            value={safeWindowEnd}
            disabled={safeVisibleCount >= fullData.length}
            onChange={(event) => {
              setWindowEnd(Number(event.currentTarget.value));
              setHoverIndex(null);
            }}
          />
        </div>
        <div className="range-labels">
          <span>{fullData[0]?.date ?? "-"}</span>
          <strong>{data[0]?.date ?? "-"} 至 {data[data.length - 1]?.date ?? "-"}</strong>
          <span>{fullData[fullData.length - 1]?.date ?? "-"}</span>
        </div>
      </div>
    </div>
  );
}

function indicatorSeries(rows: IndicatorResponse["rows"], indicator: TechnicalKey) {
  const width = 900;
  const top = 414;
  const height = 110;
  const fields = indicator === "macd"
    ? [{ name: "DIF", field: "macd_dif", color: "#2563eb" }, { name: "DEA", field: "macd_dea", color: "#dc2626" }]
    : indicator === "kdj"
      ? [{ name: "K", field: "kdj_k", color: "#2563eb" }, { name: "D", field: "kdj_d", color: "#dc2626" }, { name: "J", field: "kdj_j", color: "#16a34a" }]
      : indicator === "rsi"
        ? [{ name: "RSI14", field: "rsi14", color: "#7c3aed" }]
        : [{ name: "低9计数", field: "td_buy_setup", color: "#2563eb" }, { name: "高9计数", field: "td_sell_setup", color: "#dc2626" }];
  const values = fields.flatMap((item) => rows.map((row) => Number(row[item.field as keyof typeof row])).filter(Number.isFinite));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return fields.map((item) => ({
    ...item,
    points: rows.map((row, index) => {
      const value = Number(row[item.field as keyof typeof row]);
      const x = rows.length === 1 ? 0 : (index / (rows.length - 1)) * width;
      const y = Number.isFinite(value) ? top + (max - value) / range * height : top + height;
      return `${x},${y}`;
    }).join(" ")
  }));
}

function overviewLine(rows: IndicatorResponse["rows"]): string {
  const values = rows.map((row) => Number(row.close)).filter(Number.isFinite);
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values.map((value, index) => {
    const x = index / (values.length - 1) * 100;
    const y = 30 - (value - min) / range * 24;
    return `${x},${y}`;
  }).join(" ");
}

function indicatorTooltip(row: IndicatorResponse["rows"][number], indicator: TechnicalKey): string {
  if (indicator === "macd") return `DIF ${formatNum(row.macd_dif)} DEA ${formatNum(row.macd_dea)}`;
  if (indicator === "kdj") return `K ${formatNum(row.kdj_k)} D ${formatNum(row.kdj_d)} J ${formatNum(row.kdj_j)}`;
  if (indicator === "rsi") return `RSI14 ${formatNum(row.rsi14)}`;
  return `低9计数 ${formatInt(row.td_buy_setup)} 高9计数 ${formatInt(row.td_sell_setup)}`;
}

function macdStructureText(row: IndicatorResponse["rows"][number]): string {
  if (row.macd_bottom_divergence) return "MACD底背离：价格创新低但DIF未同步创新低";
  if (row.macd_top_divergence) return "MACD顶背离：价格创新高但DIF未同步创新高";
  if (row.macd_bottom_passivation) return "MACD底钝化：柱线改善，等待结构确认";
  if (row.macd_top_passivation) return "MACD顶钝化：柱线走弱，警惕动能衰减";
  return "";
}
