"""``SCORECARD.md``: the full-rebuild release retrospective.

Every score subcommand that carries a verdict (``spec``, ``ac``, ``build``, ``release``)
regenerates this file in full after it runs. Nothing here is authored incrementally: each call
reassembles the whole document from ``PROJECT_STATUS.jsonl`` (which stamps ran, when, pass/fail)
plus each command's own evidence — ``SPECIFICATION_SCORECARD.md``, ``SOUNDINGS.md``, the build
report, ``evidence/score-release.json``, ``DECISIONS.json``. No writer ever hand-appends a
section, so no run can lose another run's section; a rebuild that finds no evidence for a command
simply reports that command as not yet run.
"""

from __future__ import annotations

from pathlib import Path

from drydock.decisions import DECISIONS_FILENAME, load_decisions
from drydock.project_status import latest_per_label, read_status
from drydock.sea_trials import SeaTrial, load_sea_trials
from drydock.standard_artifacts import (
    VERIFIED_FAIL,
    VERIFIED_PASS,
    VERIFIED_PREPASSED,
    load_soundings,
)

SCORECARD_FILENAME = "SCORECARD.md"


def _stamp(verb: str, command: str, at: str) -> list[str]:
    """A stamped approval: verb, attribution, and timestamp, as a small quoted block."""
    return [f"> **{verb.upper()}**", f"> {command} · {at}" if at else f"> {command}", ""]


def _not_yet_run(command: str) -> list[str]:
    return ["> **NOT YET RUN**", f"> {command}", ""]


def _spec_section(target: str, target_dir: Path) -> list[str]:
    lines = ["## Specification", ""]
    report_path = target_dir / "SPECIFICATION_SCORECARD.md"
    command = f"drydock score spec {target}"
    if not report_path.is_file():
        lines.extend(_not_yet_run(command))
        return lines
    at = _mtime_iso(report_path)
    lines.extend(_stamp("AUDITED", command, at))
    lines.append("See `SPECIFICATION_SCORECARD.md` for findings.")
    lines.append("")
    return lines


def _ac_section(target: str, target_dir: Path) -> list[str]:
    lines = ["## Acceptance", ""]
    command = f"drydock score ac {target}"
    status = latest_per_label(read_status(target_dir)).get("SCORE AC")
    soundings = load_soundings(target_dir / "SOUNDINGS.md")
    if status is None and not soundings:
        lines.extend(_not_yet_run(command))
        return lines
    if status is not None:
        lines.extend(
            _stamp("PASSED" if status.passed else "FAILED", status.command or command, status.at)
        )
    else:
        lines.extend(_stamp("RECORDED", command, ""))
    passed = sum(1 for row in soundings.values() if row.verified == VERIFIED_PASS)
    failed = sum(1 for row in soundings.values() if row.verified == VERIFIED_FAIL)
    prepassed = sum(1 for row in soundings.values() if row.verified == VERIFIED_PREPASSED)
    unverified = len(soundings) - passed - failed - prepassed
    lines.append(
        f"PASS {passed}   FAIL {failed}   UNVERIFIED {unverified}   PREPASSED {prepassed}"
        f"   ({len(soundings)} AC total)"
    )
    if failed:
        lines.append("")
        lines.append("Failed:")
        lines.extend(
            f"- {row.criterion_id} — {row.blueprint}"
            for row in soundings.values()
            if row.verified == VERIFIED_FAIL
        )
    lines.append("")
    return lines


def _build_section(target: str, target_dir: Path) -> list[str]:
    from drydock.build_report import build_score_report
    from drydock.config import get_workspace

    lines = ["## Build", ""]
    command = f"drydock score build {target}"
    status = latest_per_label(read_status(target_dir)).get("SCORE BUILD")
    report = build_score_report(
        target, target_dir, records_path=get_workspace() / "logs" / "llm.jsonl"
    )
    if status is None and not report.blocks:
        lines.extend(_not_yet_run(command))
        return lines
    if status is not None:
        lines.extend(
            _stamp("PASSED" if status.passed else "FAILED", status.command or command, status.at)
        )
    else:
        lines.extend(_stamp("RECORDED", command, ""))
    rate = report.cache_hit_rate
    rate_text = "-" if rate is None else f"{rate * 100:.1f}%"
    lines.append(
        f"Blocks: {len(report.blocks)}   Repaired: {len(report.repaired_blocks)}   "
        f"Failed: {len(report.failed_blocks)}"
    )
    lines.append(
        f"Tokens: {report.total_input + report.output:,} "
        f"(cached {report.cached_input:,}, output {report.output:,})   Cache hit rate: {rate_text}"
    )
    lines.append("")
    return lines


def _trials_by_id(target_dir: Path) -> dict[str, SeaTrial]:
    sea_path = target_dir / "SEA_TRIALS.md"
    if not sea_path.is_file():
        return {}
    document = load_sea_trials(sea_path)
    return {trial.criterion_id: trial for trial in document.trials}


def _release_section(target: str, target_dir: Path) -> list[str]:
    import json

    lines = ["## Release", ""]
    command = f"drydock score release {target}"
    status = latest_per_label(read_status(target_dir)).get("SCORE RELEASE")
    evidence_path = target_dir / "evidence" / "score-release.json"
    if status is None and not evidence_path.is_file():
        lines.extend(_not_yet_run(command))
        return lines
    if status is not None:
        lines.extend(
            _stamp("RELEASED" if status.passed else "FAILED", status.command or command, status.at)
        )
    else:
        lines.extend(_stamp("RECORDED", command, ""))
    if evidence_path.is_file():
        try:
            record = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        # ``- Verdict:`` and the ``## Project acceptance`` table keep the exact markers
        # drydock.quarterdeck_state._scorecard_html parses for the Chair's verdict board.
        lines.append(f"- Verdict: {record.get('verdict', '')}")
        lines.append("")
        statement = str(record.get("statement") or record.get("verdict_line") or "").strip()
        if statement:
            lines.append(statement)
            lines.append("")
        criteria = record.get("criteria") or []
        if criteria:
            trials = _trials_by_id(target_dir)
            lines.extend([
                "## Project acceptance",
                "",
                "| ID | Type | Criterion | Verdict | Observed |",
                "|---|---|---|---|---|",
            ])
            for item in criteria:
                trial = trials.get(item.get("criterion_id", ""))
                trial_type = trial.trial_type if trial else ""
                criterion = (trial.criterion if trial else str(item.get("rationale", ""))).replace(
                    "|", "/"
                )
                observed = (
                    "; ".join(item.get("evidence") or []) or item.get("rationale", "")
                ).replace("|", "/")
                lines.append(
                    f"| {item.get('criterion_id', '')} | {trial_type} | {criterion} | "
                    f"{item.get('verdict', '')} | {observed} |"
                )
            lines.append("")
        for heading, key in (
            ("Failures", "blockers"),
            ("Manual verification required", "attestations"),
            ("Could not judge", "kit_faults"),
            ("Advisory warnings", "warnings"),
        ):
            items = record.get(key) or []
            if items:
                lines.append(f"**{heading}:**")
                lines.extend(f"- {item}" for item in items)
                lines.append("")
        improvements = record.get("improvements") or []
        if improvements:
            lines.append("**Ranked improvements:**")
            lines.extend(f"{index}. {item}" for index, item in enumerate(improvements, 1))
            lines.append("")
    lines.extend(_decisions_lines(target_dir))
    return lines


def _decisions_lines(target_dir: Path) -> list[str]:
    decisions = load_decisions(target_dir / DECISIONS_FILENAME)
    material = [item for item in decisions if item.severity in {"material", "blocking"}]
    if not material:
        return []
    lines = ["**Material decisions:**", ""]
    lines.extend(f"- {item.title} — {item.answer}" for item in material)
    lines.append("")
    return lines


def _mtime_iso(path: Path) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")


def render_scorecard(target: str, target_dir: Path) -> str:
    """Fully regenerate SCORECARD.md content from PROJECT_STATUS.jsonl and each command's evidence.

    Always a full rebuild: no section here is ever merged with what a previous run wrote, so no
    writer can clobber or lose another command's section.
    """
    lines = [f"# Scorecard: {target}", ""]
    lines.extend(_spec_section(target, target_dir))
    lines.extend(_ac_section(target, target_dir))
    lines.extend(_build_section(target, target_dir))
    lines.extend(_release_section(target, target_dir))
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def write_scorecard(target: str, target_dir: Path) -> Path:
    """Regenerate and write SCORECARD.md, returning its path."""
    path = target_dir / SCORECARD_FILENAME
    path.write_text(render_scorecard(target, target_dir), encoding="utf-8", newline="\n")
    return path
