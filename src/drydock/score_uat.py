"""Successful UAT runs compared by agent turns and total tokens, for ``drydock score uat_report``.

Reads each kit's ``runs/<run-id>/result.json`` and the run's preserved LLM execution records.
Writes nothing.

* **Turns** are the provider-reported agent turns of each execution (Claude ``num_turns``).
  A provider that reports none (Codex) is counted from its raw transcript as completed agent
  steps: messages, tool calls, and file changes.
* **Total tokens** are the run's recorded input (cache reads included) plus output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drydock.llm_usage import read_records, scan_activity


@dataclass(frozen=True)
class UatRunRow:
    project: str
    run_id: str
    model: str
    turns: int
    total_tokens: int

    @property
    def date(self) -> str:
        stamp = self.run_id.partition(".")[0]
        if len(stamp) == 8 and stamp.isdigit():
            return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        return stamp


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _raw_transcript(record: Mapping[str, Any], run_dir: Path) -> Path | None:
    raw = _mapping(record.get("artifacts")).get("raw")
    if not isinstance(raw, str) or not raw:
        return None
    recorded = Path(raw)
    if recorded.is_file():
        return recorded
    # A kit moved after the run keeps the transcript beside the run's own workspace logs.
    return run_dir / "workspace" / "logs" / recorded.name


def _record_turns(record: Mapping[str, Any], run_dir: Path) -> int:
    stats = _mapping(_mapping(record.get("result")).get("stats"))
    reported = _int(stats.get("turns"))
    if reported:
        return reported
    raw = _raw_transcript(record, run_dir)
    if raw is None:
        return 0
    provider = str(_mapping(record.get("job")).get("llm") or "")
    activity = scan_activity(raw, provider)
    return activity.messages + activity.tool_calls + activity.file_changes


def _run_turns(run_dir: Path) -> int:
    for candidate in (
        run_dir / "evidence" / "llm.jsonl",
        run_dir / "workspace" / "logs" / "llm.jsonl",
    ):
        if candidate.is_file():
            records, _invalid = read_records(candidate)
            return sum(_record_turns(record, run_dir) for record in records)
    return 0


def successful_runs(uat_root: Path) -> list[UatRunRow]:
    """Return every passed run under ``uat_root``, newest first."""
    rows: list[UatRunRow] = []
    for result_path in uat_root.glob("*/runs/*/result.json"):
        result = _read_json(result_path)
        if result.get("status") != "passed":
            continue
        run_dir = result_path.parent
        usage = _mapping(result.get("usage"))
        rows.append(
            UatRunRow(
                project=run_dir.parent.parent.name,
                run_id=str(result.get("run_id") or run_dir.name),
                model=str(_mapping(result.get("environment")).get("model") or "unknown"),
                turns=_run_turns(run_dir),
                total_tokens=_int(usage.get("input_tokens")) + _int(usage.get("output_tokens")),
            )
        )
    rows.sort(key=lambda row: (row.run_id, row.project), reverse=True)
    return rows


def render_uat_report(rows: list[UatRunRow]) -> list[str]:
    """Render the fixed-width ``UAT RUN REPORT`` table."""
    lines = ["UAT RUN REPORT", "--------------"]
    if not rows:
        lines.append("No successful UAT runs.")
        return lines
    headers = ("Project", "Date", "Model", "Turns", "Total Tokens")
    values = [
        (row.project, row.date, row.model, f"{row.turns:,}", f"{row.total_tokens:,}")
        for row in rows
    ]
    widths = [max(len(headers[i]), *(len(value[i]) for value in values)) for i in range(5)]
    numeric = frozenset({3, 4})

    def render(row: tuple[str, ...]) -> str:
        return "  ".join(
            value.rjust(widths[i]) if i in numeric else value.ljust(widths[i])
            for i, value in enumerate(row)
        ).rstrip()

    lines.append(render(headers))
    lines.extend(render(value) for value in values)
    return lines
