from __future__ import annotations

import dataclasses
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


STRATEGY_DIR = Path(__file__).parent / "strategies"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class Strategy:
    filename: str
    title: str
    content: str
    sections: dict[str, str]

    def summary(self, max_chars: int = 360) -> dict[str, Any]:
        excerpt = self.sections.get("适用场景") or self.content
        excerpt = _compact_text(excerpt)
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars].rstrip() + "..."
        return {
            "filename": self.filename,
            "title": self.title,
            "sections": list(self.sections),
            "excerpt": excerpt,
        }


def list_strategies() -> list[dict[str, Any]]:
    return [strategy.summary(max_chars=180) for strategy in _load_strategies()]


def get_strategy(filename_or_title: str) -> dict[str, Any] | None:
    query = filename_or_title.strip()
    if not query:
        return None
    for strategy in _load_strategies():
        if query == strategy.filename or query == strategy.title or query in {strategy.filename.removesuffix(".md")}:
            return _strategy_payload(strategy, score=1.0, matched_terms=[])
    normalized = query.lower()
    for strategy in _load_strategies():
        if normalized in strategy.filename.lower() or normalized in strategy.title.lower():
            return _strategy_payload(strategy, score=0.8, matched_terms=[])
    return None


def search_strategies(query: str, top_k: int = 3) -> dict[str, Any]:
    safe_query = query.strip()
    safe_top_k = min(max(int(top_k or 3), 1), 10)
    query_terms = _terms(safe_query)
    if not safe_query or not query_terms:
        return {"query": query, "count": 0, "results": []}

    scored = []
    for strategy in _load_strategies():
        score, matched_terms = _score_strategy(strategy, safe_query, query_terms)
        if score > 0:
            scored.append((score, matched_terms, strategy))

    scored.sort(key=lambda item: (-item[0], item[2].filename))
    results = [
        _strategy_payload(strategy, score=score, matched_terms=matched_terms, include_content=False)
        for score, matched_terms, strategy in scored[:safe_top_k]
    ]
    return {"query": query, "count": len(results), "results": results}


@lru_cache(maxsize=1)
def _load_strategies() -> tuple[Strategy, ...]:
    strategies: list[Strategy] = []
    if not STRATEGY_DIR.exists():
        return tuple()
    for path in sorted(STRATEGY_DIR.glob("*.md")):
        if path.name in {"README.md", "SOURCE.md"}:
            continue
        content = path.read_text(encoding="utf-8")
        title = _title_from_content(content) or path.stem
        strategies.append(Strategy(filename=path.name, title=title, content=content, sections=_sections(content)))
    return tuple(strategies)


def _strategy_payload(
    strategy: Strategy,
    score: float,
    matched_terms: list[str],
    include_content: bool = True,
) -> dict[str, Any]:
    payload = {
        **strategy.summary(),
        "score": round(float(score), 4),
        "matched_terms": matched_terms[:12],
        "key_conditions": _section_lines(strategy.sections.get("核心条件", ""), limit=5),
        "buy_signals": _section_lines(strategy.sections.get("买入信号", ""), limit=4),
        "sell_signals": _section_lines(strategy.sections.get("卖出信号", ""), limit=4),
        "risk_notes": _section_lines(strategy.sections.get("风险提示", ""), limit=3),
    }
    if include_content:
        payload["content"] = strategy.content
    return payload


def _score_strategy(strategy: Strategy, query: str, query_terms: set[str]) -> tuple[float, list[str]]:
    haystack = f"{strategy.title}\n{strategy.filename}\n{strategy.content}".lower()
    title = strategy.title.lower()
    filename = strategy.filename.lower()
    matched_terms = sorted(term for term in query_terms if term.lower() in haystack)

    score = 0.0
    normalized_query = query.lower()
    if normalized_query in title:
        score += 8
    if normalized_query in filename:
        score += 6
    if normalized_query in haystack:
        score += 4

    for term in matched_terms:
        lowered = term.lower()
        if lowered in title:
            score += 4
        elif lowered in filename:
            score += 3
        else:
            score += 1

    scenario = strategy.sections.get("适用场景", "").lower()
    conditions = strategy.sections.get("核心条件", "").lower()
    for term in matched_terms:
        lowered = term.lower()
        if lowered in scenario:
            score += 1.5
        if lowered in conditions:
            score += 1.5

    return score, matched_terms


def _title_from_content(content: str) -> str | None:
    match = _HEADING_RE.search(content)
    return match.group(1).strip() if match else None


def _sections(content: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(content))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        sections[match.group(1).strip()] = content[start:end].strip()
    return sections


def _terms(text: str) -> set[str]:
    terms = {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}
    compact = re.sub(r"\s+", "", text.strip().lower())
    if len(compact) >= 2:
        terms.add(compact)
    return {term for term in terms if len(term) >= 2}


def _section_lines(text: str, limit: int) -> list[str]:
    lines = []
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-*").strip()
        if cleaned:
            lines.append(cleaned)
        if len(lines) >= limit:
            break
    return lines


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
