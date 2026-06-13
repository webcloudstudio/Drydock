"""``drydock analyze`` — read-only Blueprint analysis: ANALYSIS.md + planning.json.

Evaluates typed specification files in a Blueprint, surfaces gaps and spike candidates,
and writes two Planning Session artifacts to the Target's QuarterDeck. Does not write to
the Blueprint, BUILD_CONFIGURATION.md, or MANIFEST.md.

The LLM emits text; this module writes files deterministically, so tests inject a fake
runner and never spend API credits.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.prompts import load_prompt

PROMPT_NAME = "analyze"

_SKIP_FILES = frozenset({"METADATA.md", "README.md", "IDEAS.md"})
_SKIP_PREFIX = "BUILD_"

_ANALYSIS_BLOCK = re.compile(
    r"=== ANALYSIS\.md ===\n(.*?)\n=== END ANALYSIS\.md ===",
    re.DOTALL,
)
_PLANNING_BLOCK = re.compile(
    r"=== planning\.json ===\n(.*?)\n=== END planning\.json ===",
    re.DOTALL,
)
_VERDICT_RE = re.compile(r"^verdict:\s*(\S+)", re.MULTILINE)


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class AnalyzeResult:
    target_dir: Path
    analysis_path: Path
    planning_path: Path
    verdict: str
    question_count: int
    execution_id: str | None
    ok: bool
    error: str | None = None

    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _collect_blueprint_files(blueprint_dir: Path) -> list[Path]:
    """Return spec files for analysis, excluding meta/build files and changes/."""
    files = []
    for path in sorted(blueprint_dir.glob("*.md")):
        if path.name in _SKIP_FILES:
            continue
        if path.name.startswith(_SKIP_PREFIX):
            continue
        files.append(path)
    return files


def _assemble_prompt(body: str, blueprint_dir: Path, today: str) -> str:
    files = _collect_blueprint_files(blueprint_dir)
    parts = [
        body,
        "",
        "## Analysis job",
        "",
        f"- BLUEPRINT_PATH: {blueprint_dir}",
        f"- DATE: {today}",
        "",
        "## Blueprint files",
        "",
    ]
    for path in files:
        content = path.read_text(encoding="utf-8")
        parts.append(f"### {path.name}")
        parts.append("")
        parts.append("```markdown")
        parts.append(content)
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def _parse_output(text: str) -> tuple[str, dict, str, int]:
    """Return (analysis_text, planning_data, verdict, question_count).

    Raises ValueError on missing blocks or invalid JSON.
    """
    analysis_match = _ANALYSIS_BLOCK.search(text)
    if not analysis_match:
        raise ValueError("LLM output missing === ANALYSIS.md === block")
    analysis_text = analysis_match.group(1).strip()

    planning_match = _PLANNING_BLOCK.search(text)
    if not planning_match:
        raise ValueError("LLM output missing === planning.json === block")
    planning_raw = planning_match.group(1).strip()

    try:
        planning_data = json.loads(planning_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"planning.json block is not valid JSON: {exc}") from exc

    verdict_match = _VERDICT_RE.search(analysis_text)
    verdict = verdict_match.group(1) if verdict_match else "unknown"

    question_count = len(planning_data.get("questions", []))

    return analysis_text, planning_data, verdict, question_count


def analyze(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
) -> AnalyzeResult:
    """Analyze a Blueprint and write ANALYSIS.md + planning.json to the Planning Session."""
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    planning_dir = target_dir / "QuarterDeck" / "planning"
    questionnaires_dir = target_dir / "QuarterDeck" / "questionnaires"
    analysis_path = planning_dir / "ANALYSIS.md"
    planning_path = questionnaires_dir / "planning.json"

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    assembled = _assemble_prompt(prompt.body, blueprint_dir, today)

    result = run(
        assembled,
        blueprint_dir,
        model=prompt.model,
        command_name="analyze",
        parameters={"target": target, "blueprint": str(blueprint_dir)},
        on_text=on_text,
    )

    exec_id = getattr(result, "execution_id", None)

    def _fail(msg: str) -> AnalyzeResult:
        return AnalyzeResult(
            target_dir=target_dir,
            analysis_path=analysis_path,
            planning_path=planning_path,
            verdict="unknown",
            question_count=0,
            execution_id=exec_id,
            ok=False,
            error=msg,
        )

    if not result.ok or not result.text.strip():
        return _fail("LLM execution failed")

    try:
        analysis_text, planning_data, verdict, question_count = _parse_output(result.text)
    except ValueError as exc:
        return _fail(str(exc))

    planning_dir.mkdir(parents=True, exist_ok=True)
    questionnaires_dir.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(analysis_text + "\n", encoding="utf-8", newline="\n")
    planning_path.write_text(
        json.dumps(planning_data, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    return AnalyzeResult(
        target_dir=target_dir,
        analysis_path=analysis_path,
        planning_path=planning_path,
        verdict=verdict,
        question_count=question_count,
        execution_id=result.execution_id,
        ok=True,
    )
