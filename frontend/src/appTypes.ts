export type Page = "home" | "screen" | "stock" | "strategy" | "concentration" | "reports" | "learning" | "data";

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
