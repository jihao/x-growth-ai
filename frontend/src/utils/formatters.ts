import type { MarketOverview } from "../types";

export function asRows(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

export function reviewCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString("zh-CN") : value.toFixed(2);
  if (Array.isArray(value)) return value.join("、");
  return String(value);
}

export function numberFromText(value: unknown): number | null {
  if (typeof value === "number") return Number.isNaN(value) ? null : value;
  if (value === null || value === undefined) return null;
  const text = String(value).replace(/,/g, "");
  const match = text.match(/[-+]?\d*\.?\d+/);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isNaN(parsed) ? null : parsed;
}

export function formatIndexPoint(value: number | null): string {
  if (value === null) return "-";
  return `${value.toFixed(2)}点`;
}

export function signedPct(value: number | null): string {
  if (value === null) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function signedlessPct(value: number | null): string {
  if (value === null) return "-";
  return `${value.toFixed(2)}%`;
}

export function ratioText(up: number | undefined, down: number | undefined): string {
  if (!up || !down) return "-";
  return `${(up / down).toFixed(2)}:1`;
}

export function breadthLabel(overview: MarketOverview | undefined): string {
  if (!overview) return "等待数据";
  if (overview.up > overview.down * 1.3) return "上涨占优";
  if (overview.down > overview.up * 1.2) return "跌多涨少";
  return "分化均衡";
}

export function ppText(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}${Math.abs(value) < 10 ? "pp" : ""}`;
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(2)}%`;
}

export function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(2);
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Math.round(value).toLocaleString("zh-CN");
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)}万`;
  return value.toFixed(0);
}

export function shortDate(value: string): string {
  return value.length >= 10 ? value.slice(5) : value;
}
