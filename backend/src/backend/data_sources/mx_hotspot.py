from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextSkillResult:
    ok: bool
    content: str
    source: str
    raw_path: Path | None = None
    error: str | None = None


class MxHotspotClient:
    def __init__(self, repo_root: Path) -> None:
        self.hotspot_script = repo_root / ".skills" / "mx-skills" / "stock-market-hotspot-discovery" / "scripts" / "get_data.py"
        self.search_script = repo_root / ".skills" / "mx-skills" / "mx-finance-search" / "scripts" / "get_data.py"

    def market_hotspot(self, query: str = "今日A股市场热点和热门股票") -> TextSkillResult:
        if not self.hotspot_script.exists():
            return TextSkillResult(False, "", "stock-market-hotspot-discovery", error=f"Skill script not found: {self.hotspot_script}")
        completed = subprocess.run(
            [sys.executable, str(self.hotspot_script), "--query", query],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        return _parse_text_skill_output(completed, "stock-market-hotspot-discovery")

    def finance_search(self, query: str) -> TextSkillResult:
        if not self.search_script.exists():
            return TextSkillResult(False, "", "mx-finance-search", error=f"Skill script not found: {self.search_script}")
        completed = subprocess.run(
            [sys.executable, str(self.search_script), query],
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
        return _parse_text_skill_output(completed, "mx-finance-search")


def promote_text_artifact(raw_path: Path | None, artifact_name: str) -> Path | None:
    if raw_path is None or not raw_path.exists():
        return None
    target = raw_path.with_name(f"{artifact_name}{raw_path.suffix}")
    shutil.copy2(raw_path, target)
    return target


def _parse_text_skill_output(completed: subprocess.CompletedProcess[str], source: str) -> TextSkillResult:
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode != 0:
        return TextSkillResult(False, "", source, error=output)

    raw_path = _extract_saved_path(output)
    content = _strip_saved_line(output)
    if not content:
        return TextSkillResult(False, "", source, raw_path=raw_path, error="Skill returned empty content")
    return TextSkillResult(True, content, source, raw_path=raw_path)


def _extract_saved_path(output: str) -> Path | None:
    for line in output.splitlines():
        if line.startswith("Saved:"):
            return Path(line.split(":", 1)[1].strip())
    return None


def _strip_saved_line(output: str) -> str:
    lines: list[str] = []
    for line in output.splitlines():
        if line.startswith("Saved:") or line.startswith("默认输出目录为："):
            continue
        lines.append(line)
    return "\n".join(lines).strip()
