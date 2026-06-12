import { REVIEW_STORAGE_KEY, type ReviewNote } from "../appTypes";

export function loadReviewNotes(): Record<string, ReviewNote> {
  try {
    const raw = window.localStorage.getItem(REVIEW_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as Record<string, ReviewNote>;
  } catch {
    return {};
  }
}
