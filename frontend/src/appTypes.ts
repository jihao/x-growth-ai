export type Page = "home" | "screen" | "stock" | "strategy" | "concentration" | "reports" | "history" | "learning" | "data";

export type TechnicalKey = "macd" | "kdj" | "rsi" | "td9";

export const technicalKeys: TechnicalKey[] = ["macd", "kdj", "rsi", "td9"];

export const REVIEW_STORAGE_KEY = "x-growth-review-notes";

export type ReviewNote = {
  code: string;
  name: string;
  date: string;
  plan: "观察" | "等回踩" | "模拟买入" | "放弃";
  reason: string;
  waitFor: string;
  risk: string;
  updatedAt: string;
};

export function pageTitle(page: Page): string {
  return {
    home: "首页",
    screen: "选股看板",
    stock: "个股分析",
    strategy: "策略验证",
    concentration: "集中度趋势",
    reports: "日报区域",
    history: "历史 Markdown",
    learning: "学习区域",
    data: "数据区域"
  }[page];
}
