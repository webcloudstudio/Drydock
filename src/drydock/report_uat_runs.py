"""Successful UAT runs compared by Drydock work, tokens, tool calls, and LLM time.

Backs ``drydock report uat_report``. Reads each kit's ``runs/<run-id>/result.json``, the run's
preserved LLM execution records and raw transcripts, and its Manifest. Writes nothing.

Each LLM execution is counted in one category:

* **Build** — a block's first build attempt (``attempt`` 0).
* **Repair** — a build retry (``attempt`` > 0) or a diagnose pass.
* **Plan** — plan synthesis, continuation batches, conflict challenge, and lineage.
* **Plan Rep** — plan artifact, declaration, and coverage repairs, and ``plan repair``.
* **Other** — analyze, score, refit, and anything else.

Tool calls are normalized across providers: **Shell** (Claude ``Bash``, Codex
``command_execution``), **Edit** (Claude ``Edit``/``Write``/``MultiEdit``/``NotebookEdit``,
Codex ``file_change``), and **Other** (every other tool).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drydock.llm_usage import normalize_tokens, read_records, scan_activity
from drydock.manifest import DrydockManifest, ManifestError, StoryNode

_CATEGORIES = ("build", "repair", "plan", "plan_repair", "other")
_PLAN_REPAIR_PASSES = ("artifact_repair_pass", "declaration_repair_pass", "coverage_repair_pass")
_CLAUDE_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
_CODEX_TOOL_ITEMS = {
    "command_execution": "shell",
    "file_change": "edit",
    "mcp_tool_call": "other",
    "web_search": "other",
}
_MAX_TRANSCRIPT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class UatRunRow:
    project: str
    run_id: str
    model: str
    stories: int | None
    calls: Mapping[str, int]
    fresh_input_tokens: int
    cache_read_tokens: int
    output_tokens: int
    shell_calls: int
    edit_calls: int
    other_tool_calls: int
    llm_elapsed_ms: int

    @property
    def date(self) -> str:
        stamp = self.run_id.partition(".")[0]
        if len(stamp) == 8 and stamp.isdigit():
            return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        return stamp

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())

    @property
    def total_tokens(self) -> int:
        return self.fresh_input_tokens + self.cache_read_tokens + self.output_tokens


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return 0


def categorize(record: Mapping[str, Any]) -> str:
    """Return the report category of one LLM execution record."""
    job = _mapping(record.get("job"))
    command = str(job.get("command_name") or "")
    parameters = _mapping(job.get("parameters"))
    if command == "build":
        return "repair" if _int(parameters.get("attempt")) else "build"
    if command == "diagnose":
        return "repair"
    if command == "plan repair":
        return "plan_repair"
    if command == "plan":
        if any(_int(parameters.get(key)) for key in _PLAN_REPAIR_PASSES):
            return "plan_repair"
        return "plan"
    if command == "lineage_attribute":
        return "plan"
    return "other"


def _raw_transcript(record: Mapping[str, Any], run_dir: Path) -> Path | None:
    raw = _mapping(record.get("artifacts")).get("raw")
    if not isinstance(raw, str) or not raw:
        return None
    recorded = Path(raw)
    if recorded.is_file():
        return recorded
    # A kit moved after the run keeps the transcript beside the run's own workspace logs.
    relocated = run_dir / "workspace" / "logs" / recorded.name
    return relocated if relocated.is_file() else None


def tool_calls(path: Path, provider: str) -> dict[str, int]:
    """Count one raw transcript's tool calls as ``shell``, ``edit``, and ``other``."""
    counts = {"shell": 0, "edit": 0, "other": 0}
    try:
        if path.stat().st_size > _MAX_TRANSCRIPT_BYTES:
            return counts
    except OSError:
        return counts
    if provider.lower() == "gemini":
        counts["other"] = scan_activity(path, provider).tool_calls
        return counts
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "item.completed":
                    kind = _CODEX_TOOL_ITEMS.get(str(_mapping(event.get("item")).get("type")))
                    if kind:
                        counts[kind] += 1
                elif event.get("type") == "assistant":
                    content = _mapping(event.get("message")).get("content")
                    for block in content if isinstance(content, list) else ():
                        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
                            continue
                        name = str(block.get("name") or "")
                        if name == "Bash":
                            counts["shell"] += 1
                        elif name in _CLAUDE_EDIT_TOOLS:
                            counts["edit"] += 1
                        else:
                            counts["other"] += 1
    except OSError:
        pass
    return counts


def _stories(run_dir: Path) -> int | None:
    for manifest in sorted((run_dir / "workspace" / "targets").glob("*/MANIFEST.md")):
        try:
            parsed = DrydockManifest.load(manifest, compatibility=True)
        except ManifestError:
            return None
        return sum(isinstance(block, StoryNode) for block in parsed.blocks)
    return None


def _records(run_dir: Path) -> list[dict[str, Any]]:
    for candidate in (
        run_dir / "evidence" / "llm.jsonl",
        run_dir / "workspace" / "logs" / "llm.jsonl",
    ):
        if candidate.is_file():
            return read_records(candidate)[0]
    return []


def _run_row(run_dir: Path, result: Mapping[str, Any]) -> UatRunRow:
    calls = dict.fromkeys(_CATEGORIES, 0)
    fresh = cache_read = output = llm_ms = 0
    tools = {"shell": 0, "edit": 0, "other": 0}
    for record in _records(run_dir):
        calls[categorize(record)] += 1
        job = _mapping(record.get("job"))
        stats = _mapping(_mapping(record.get("result")).get("stats"))
        provider = str(job.get("llm") or "")
        total_input, cached, out = normalize_tokens(provider, stats)
        fresh += max(total_input - cached, 0)
        cache_read += cached
        output += out
        llm_ms += _int(stats.get("elapsed_ms"))
        raw = _raw_transcript(record, run_dir)
        if raw is not None:
            for kind, count in tool_calls(raw, provider).items():
                tools[kind] += count
    return UatRunRow(
        project=run_dir.parent.parent.name,
        run_id=str(result.get("run_id") or run_dir.name),
        model=str(_mapping(result.get("environment")).get("model") or "unknown"),
        stories=_stories(run_dir),
        calls=calls,
        fresh_input_tokens=fresh,
        cache_read_tokens=cache_read,
        output_tokens=output,
        shell_calls=tools["shell"],
        edit_calls=tools["edit"],
        other_tool_calls=tools["other"],
        llm_elapsed_ms=llm_ms,
    )


def successful_runs(uat_root: Path) -> list[UatRunRow]:
    """Return every passed run under ``uat_root``, newest first."""
    rows: list[UatRunRow] = []
    for result_path in uat_root.glob("*/runs/*/result.json"):
        result = _read_json(result_path)
        if result.get("status") == "passed":
            rows.append(_run_row(result_path.parent, result))
    rows.sort(key=lambda row: (row.run_id, row.project), reverse=True)
    return rows


def _tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(value)


def _minutes(milliseconds: int) -> str:
    return f"{milliseconds / 60_000:.0f}"


def _table(title: str, headers: tuple[str, ...], values: list[tuple[str, ...]]) -> list[str]:
    widths = [
        max(len(headers[i]), *(len(value[i]) for value in values)) for i in range(len(headers))
    ]

    def render(row: tuple[str, ...]) -> str:
        return "  ".join(
            value.ljust(widths[i]) if i < 3 else value.rjust(widths[i])
            for i, value in enumerate(row)
        ).rstrip()

    return ["", title, render(headers), *(render(value) for value in values)]


def render_uat_report(rows: list[UatRunRow]) -> list[str]:
    """Render the ``UAT RUN REPORT``: Drydock work, tokens, and tool calls with time."""
    lines = ["UAT RUN REPORT", "--------------"]
    if not rows:
        lines.append("No successful UAT runs.")
        return lines
    key = ("Project", "Date", "Model")
    keys = [(row.project, row.date, row.model) for row in rows]
    lines += _table(
        "DRYDOCK LLM CALLS",
        (*key, "Stories", "Build", "Repair", "Plan", "Plan Rep", "Other", "Calls"),
        [
            (
                *k,
                "—" if row.stories is None else str(row.stories),
                *(f"{row.calls[category]:,}" for category in _CATEGORIES),
                f"{row.total_calls:,}",
            )
            for k, row in zip(keys, rows, strict=True)
        ],
    )
    lines += _table(
        "TOKENS",
        (*key, "Fresh in", "Cache read", "Output", "Total"),
        [
            (
                *k,
                _tokens(row.fresh_input_tokens),
                _tokens(row.cache_read_tokens),
                _tokens(row.output_tokens),
                _tokens(row.total_tokens),
            )
            for k, row in zip(keys, rows, strict=True)
        ],
    )
    lines += _table(
        "TOOL CALLS AND TIME",
        (*key, "Shell", "Edit", "Other", "LLM min"),
        [
            (
                *k,
                f"{row.shell_calls:,}",
                f"{row.edit_calls:,}",
                f"{row.other_tool_calls:,}",
                _minutes(row.llm_elapsed_ms),
            )
            for k, row in zip(keys, rows, strict=True)
        ],
    )
    lines += [
        "",
        "Build = first attempt per block · Repair = build retries and diagnose · "
        "Plan Rep = plan repairs",
        "LLM min = every LLM call, resumes included",
    ]
    return lines
