"""``drydock analyze`` — Blueprint analysis: ANALYSIS.md, spikes, and target artifacts.

Single LLM call producing all analyze outputs via delimited blocks. Writes deterministically;
tests inject a fake runner and never spend API credits.

Outputs: ANALYSIS.md (target root), SEA_TRIALS.md, SOUNDINGS.md, COMPASS.md (if
absent), spike-intent.json, spike-stack.json, spike-gaps-ac.json, spike-guardrails.json, and
any variable spikes the LLM discovers.
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

_SKIP_FILES = frozenset({
    "METADATA.md",
    "README.md",
    "IDEAS.md",
    "COMPASS.md",           # lives at target root; blueprint copy is always a stub
    "ACCEPTANCE_CRITERIA.md",  # not a typed spec file type
})
_SKIP_PREFIX = "BUILD_"

_FIXED_SPIKES = ("spike-intent.json", "spike-stack.json", "spike-gaps-ac.json", "spike-guardrails.json")

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_VERDICT_RE = re.compile(r"^verdict:\s*(\S+)", re.MULTILINE)
_VERDICT_REASON_RE = re.compile(r"^verdict:\s*\S+[^\n]*\n([^\n#][^\n]+)", re.MULTILINE)


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
    sea_trials_path: Path
    soundings_path: Path
    compass_path: Path | None
    spike_paths: tuple[Path, ...]
    verdict: str
    verdict_reason: str | None
    execution_id: str | None
    ok: bool
    error: str | None = None

    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _collect_blueprint_files(blueprint_dir: Path) -> list[Path]:
    """Return spec files for analysis, excluding meta/build files."""
    files = []
    for path in sorted(blueprint_dir.glob("*.md")):
        if path.name in _SKIP_FILES:
            continue
        if path.name.startswith(_SKIP_PREFIX):
            continue
        files.append(path)
    return files


def _assemble_prompt(body: str, blueprint_dir: Path, today: str, *, compass_exists: bool) -> str:
    files = _collect_blueprint_files(blueprint_dir)
    parts = [
        body,
        "",
        "## Analysis job",
        "",
        f"- BLUEPRINT_PATH: {blueprint_dir}",
        f"- DATE: {today}",
        f"- COMPASS_EXISTS: {'true' if compass_exists else 'false'}",
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


def _parse_blocks(text: str) -> dict[str, str]:
    """Return a dict of block-name → stripped content from === NAME === delimiters."""
    return {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}


def _parse_output(text: str) -> tuple[str, str, str, str | None, dict[str, dict], str, str | None]:
    """Return (analysis, sea_trials, soundings, compass_or_none, spikes_dict, verdict, verdict_reason).

    ``spikes_dict`` maps filename → parsed dict for every spike-*.json block.
    Raises ValueError on missing required blocks or invalid JSON.
    """
    blocks = _parse_blocks(text)

    for required in ("ANALYSIS.md", "SEA_TRIALS.md", "SOUNDINGS.md"):
        if required not in blocks:
            raise ValueError(f"LLM output missing === {required} === block")

    for spike_name in _FIXED_SPIKES:
        if spike_name not in blocks:
            raise ValueError(f"LLM output missing === {spike_name} === block")

    spikes: dict[str, dict] = {}
    for name, content in blocks.items():
        if name.startswith("spike-") and name.endswith(".json"):
            try:
                spikes[name] = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} block is not valid JSON: {exc}") from exc

    analysis_text = blocks["ANALYSIS.md"]
    verdict_match = _VERDICT_RE.search(analysis_text)
    verdict = verdict_match.group(1) if verdict_match else "unknown"

    reason_match = _VERDICT_REASON_RE.search(analysis_text)
    verdict_reason = reason_match.group(1).strip() if reason_match else None

    compass_content = blocks.get("COMPASS.md") or None

    return (
        analysis_text,
        blocks["SEA_TRIALS.md"],
        blocks["SOUNDINGS.md"],
        compass_content,
        spikes,
        verdict,
        verdict_reason,
    )


def analyze(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
) -> AnalyzeResult:
    """Analyze a Blueprint and write all analyze artifacts to the Target."""
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    questionnaires_dir = target_dir / "QuarterDeck" / "questionnaires"
    analysis_path = target_dir / "ANALYSIS.md"
    sea_trials_path = target_dir / "SEA_TRIALS.md"
    soundings_path = target_dir / "SOUNDINGS.md"
    compass_target = target_dir / "COMPASS.md"
    compass_exists = compass_target.is_file()

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    assembled = _assemble_prompt(prompt.body, blueprint_dir, today, compass_exists=compass_exists)

    result = run(
        assembled,
        target_dir,
        model=prompt.model,
        command_name="analyze",
        parameters={"target": target, "blueprint": str(blueprint_dir)},
        on_text=on_text,
    )

    exec_id = getattr(result, "execution_id", None)

    # Placeholder paths for failure results
    spike_placeholder: tuple[Path, ...] = ()

    def _fail(msg: str) -> AnalyzeResult:
        return AnalyzeResult(
            target_dir=target_dir,
            analysis_path=analysis_path,
            sea_trials_path=sea_trials_path,
            soundings_path=soundings_path,
            compass_path=None,
            spike_paths=spike_placeholder,
            verdict="unknown",
            verdict_reason=None,
            execution_id=exec_id,
            ok=False,
            error=msg,
        )

    if not result.ok or not result.text.strip():
        return _fail("LLM execution failed")

    try:
        analysis_text, sea_trials_text, soundings_text, compass_text, spikes, verdict, verdict_reason = (
            _parse_output(result.text)
        )
    except ValueError as exc:
        return _fail(str(exc))

    questionnaires_dir.mkdir(parents=True, exist_ok=True)

    analysis_path.write_text(analysis_text + "\n", encoding="utf-8", newline="\n")
    sea_trials_path.write_text(sea_trials_text + "\n", encoding="utf-8", newline="\n")
    soundings_path.write_text(soundings_text + "\n", encoding="utf-8", newline="\n")

    written_compass: Path | None = None
    if compass_text and not compass_exists:
        compass_target.write_text(compass_text + "\n", encoding="utf-8", newline="\n")
        written_compass = compass_target

    spike_paths: list[Path] = []
    for name, data in spikes.items():
        spike_path = questionnaires_dir / name
        spike_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        spike_paths.append(spike_path)

    return AnalyzeResult(
        target_dir=target_dir,
        analysis_path=analysis_path,
        sea_trials_path=sea_trials_path,
        soundings_path=soundings_path,
        compass_path=written_compass,
        spike_paths=tuple(sorted(spike_paths)),
        verdict=verdict,
        verdict_reason=verdict_reason,
        execution_id=exec_id,
        ok=True,
    )
