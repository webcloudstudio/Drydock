"""drydock status — compact project orientation across all three invocation forms."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SUMMARY_FIELD_RE = re.compile(r"^  (\w+):\s*(.+?)$", re.MULTILINE)


@dataclass(frozen=True)
class AnalysisSummary:
    quality: str = ""
    story_count: int = 0
    question_count: int = 0
    blocker_count: int = 0
    screen_count: int = 0


@dataclass(frozen=True)
class PlanSummary:
    state: str = ""
    total: int = 0
    verified: int = 0
    pending: int = 0
    implemented: int = 0
    failed: int = 0


@dataclass
class TargetInfo:
    name: str
    target_dir: Path
    display_name: str
    phase: str  # Set Up | Arrange | Implement | Loop | Unknown
    phase_detail: str
    metadata_state: str = ""
    metadata_sub_state: str = ""
    imported_sources: int = 0
    authored_blueprints: int = 0
    analysis: AnalysisSummary | None = None
    blockers_present: bool = False
    questionnaire_count: int = 0
    plan_summary: PlanSummary | None = None
    frontier: tuple = ()
    next_operation: str = ""
    history: list[dict] = field(default_factory=list)
    history_path: Path | None = None
    compact_recs: list = field(default_factory=list)


@dataclass
class WorkspaceStatus:
    workspace: Path
    targets_root: Path
    targets: list[TargetInfo] = field(default_factory=list)


@dataclass
class StatusResult:
    blueprint: str
    target: str = ""
    target_path: Path | None = None
    target_info: TargetInfo | None = None
    plan: object = None  # BuildPlan | None
    frontier: tuple = ()  # tuple[PlanBlock, ...]
    validation: object = None  # ValidationResult | None
    last_command: str = ""
    last_time: str = ""


def _has_blueprint_content(blueprint_dir: Path) -> bool:
    """True if blueprint/ contains any authored file beyond skeleton .gitkeep entries."""
    if not blueprint_dir.is_dir():
        return False
    for path in blueprint_dir.rglob("*"):
        if path.is_file() and path.name != ".gitkeep":
            return True
    return False


def _count_authored_files(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and path.name != ".gitkeep")


def _count_imported_sources(blueprint_dir: Path) -> int:
    return _count_authored_files(blueprint_dir / "sources")


def _count_authored_blueprints(blueprint_dir: Path) -> int:
    if not blueprint_dir.is_dir():
        return 0
    count = 0
    for path in blueprint_dir.rglob("*.md"):
        if "sources" in path.parts:
            continue
        count += 1
    return count


def _read_analysis_summary(target_dir: Path) -> AnalysisSummary | None:
    path = target_dir / "ANALYSIS.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    quality_match = _QUALITY_RE.search(text)
    quality = quality_match.group(1) if quality_match else ""
    fields = {key.lower(): value.strip() for key, value in _SUMMARY_FIELD_RE.findall(text)}

    def _as_int(key: str) -> int:
        try:
            return int(fields.get(key, "0"))
        except ValueError:
            return 0

    return AnalysisSummary(
        quality=quality,
        story_count=_as_int("stories"),
        question_count=_as_int("questions"),
        blocker_count=_as_int("blockers"),
        screen_count=_as_int("screens"),
    )


def _count_questionnaires(target_dir: Path) -> int:
    questionnaires_dir = target_dir / "QuarterDeck" / "questionnaires"
    if not questionnaires_dir.is_dir():
        return 0
    return sum(1 for path in questionnaires_dir.glob("*.json") if path.is_file())


def _read_workspace_history(history_path: Path, target: str, limit: int = 5) -> list[dict]:
    """Return the most-recent *limit* records for *target* from the workspace history log."""
    if not history_path.exists():
        return []
    records: list[dict] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("target", "") == target:
                records.append(rec)
        except Exception:
            pass
    return records[-limit:]


def _summarize_plan(plan) -> PlanSummary:
    counts = plan.state_counts()
    return PlanSummary(
        state=plan.state,
        total=len(plan.blocks),
        verified=counts.get("closed/verified", 0),
        pending=counts.get("pending", 0),
        implemented=counts.get("implemented", 0),
        failed=counts.get("closed/failed", 0),
    )


def _analyze_target(target_dir: Path, workspace: Path) -> TargetInfo:
    from drydock.metadata import get_build_state, get_field, parse_metadata

    name = target_dir.name
    metadata_path = target_dir / "METADATA.md"
    logger.debug("Reading %s", metadata_path)
    meta = parse_metadata(metadata_path)
    display_name = get_field(meta, "display_name") or name
    metadata_state = get_build_state(target_dir)
    metadata_sub_state = get_field(meta, "build_sub_state") or ""

    blueprint_dir = target_dir / "blueprint"
    build_plan_path = target_dir / "MANIFEST.md"
    history_path = workspace / "logs" / "history.jsonl"
    imported_sources = _count_imported_sources(blueprint_dir)
    authored_blueprints = _count_authored_blueprints(blueprint_dir)
    analysis = _read_analysis_summary(target_dir)
    blockers_present = (target_dir / "BLOCKERS.md").is_file()
    questionnaire_count = _count_questionnaires(target_dir)

    logger.debug("Reading %s", blueprint_dir)
    has_content = _has_blueprint_content(blueprint_dir)
    logger.debug("Reading %s", build_plan_path)
    logger.debug("Reading %s", history_path)
    history = _read_workspace_history(history_path, name)

    plan_summary: PlanSummary | None = None
    frontier: tuple = ()
    compact_recs: list = []

    if build_plan_path.exists():
        try:
            from drydock.build_plan import compact_recommendations, parse_build_plan

            plan = parse_build_plan(build_plan_path)
            plan_summary = _summarize_plan(plan)
            frontier = plan.runnable_frontier()
            compact_recs = compact_recommendations(plan)
        except Exception:
            phase = "Arrange"
            detail = "MANIFEST.md could not be parsed — check its format"
            next_op = f"drydock plan {name}"
            return TargetInfo(
                name=name,
                target_dir=target_dir,
                display_name=display_name,
                phase=phase,
                phase_detail=detail,
                metadata_state=metadata_state,
                metadata_sub_state=metadata_sub_state,
                imported_sources=imported_sources,
                authored_blueprints=authored_blueprints,
                analysis=analysis,
                blockers_present=blockers_present,
                questionnaire_count=questionnaire_count,
                plan_summary=plan_summary,
                frontier=frontier,
                next_operation=next_op,
                history=history,
                history_path=history_path,
                compact_recs=[],
            )

        assert plan_summary is not None
        if plan.state == "draft":
            phase = "Arrange"
            detail = "Draft plan created — review the Planning Session build tree"
            next_op = f"drydock run quarterdeck {name}"
        elif plan_summary.total > 0 and plan_summary.verified == plan_summary.total:
            phase = "Loop"
            detail = f"All {plan_summary.total} blocks verified — ready for Refit"
            next_op = f"drydock refit {name} BOTH <Scope> <Change>"
        else:
            parts = [
                f"{plan_summary.verified}/{plan_summary.total} verified",
                f"{plan_summary.pending} pending",
            ]
            if plan_summary.implemented:
                parts.append(f"{plan_summary.implemented} implemented")
            if plan_summary.failed:
                parts.append(f"{plan_summary.failed} FAILED")
            phase = "Implement"
            detail = "  ·  ".join(parts)
            if frontier:
                next_op = (
                    f"drydock build {name}"
                    f"  (frontier: {', '.join(block.name for block in frontier[:2])})"
                )
            else:
                next_op = f"drydock build {name}"
    elif imported_sources == 0 and not analysis and authored_blueprints == 0 and not has_content:
        phase, detail = "Set Up", "Target initialized — no source material imported yet"
        next_op = f"drydock import {name} <source> --format markdown"
    elif blockers_present:
        phase, detail = "Arrange", "Analysis is blocked — answer BLOCKERS.md and re-run analyze"
        next_op = f"Edit BLOCKERS.md, then run: drydock analyze {name}"
    elif analysis is None and imported_sources > 0:
        phase, detail = "Arrange", "Source material imported — analysis not yet run"
        next_op = f"drydock analyze {name}"
    elif not build_plan_path.exists():
        if analysis and analysis.quality == "Questions" and questionnaire_count > 0:
            phase = "Arrange"
            detail = "Analysis complete — open questions remain; planning can proceed"
            next_op = f"drydock run quarterdeck {name}"
        elif analysis and analysis.quality == "Ready":
            phase = "Arrange"
            detail = "Analysis ready — plan not yet created"
            next_op = f"drydock plan {name}"
        else:
            phase = "Arrange"
            detail = "Blueprint artifacts present — plan not yet created"
            next_op = f"drydock plan {name}"
    return TargetInfo(
        name=name,
        target_dir=target_dir,
        display_name=display_name,
        phase=phase,
        phase_detail=detail,
        metadata_state=metadata_state,
        metadata_sub_state=metadata_sub_state,
        imported_sources=imported_sources,
        authored_blueprints=authored_blueprints,
        analysis=analysis,
        blockers_present=blockers_present,
        questionnaire_count=questionnaire_count,
        plan_summary=plan_summary,
        frontier=frontier,
        next_operation=next_op,
        history=history,
        history_path=history_path,
        compact_recs=compact_recs,
    )


def status_workspace(
    workspace: Path, targets_root: Path, *, debug: bool = False
) -> WorkspaceStatus:
    """Return status for all initialized targets in the workspace."""
    logger.debug("status_workspace: workspace=%s targets_root=%s", workspace, targets_root)
    targets: list[TargetInfo] = []
    if targets_root.is_dir():
        logger.debug("Reading %s/", targets_root)
        for entry in sorted(targets_root.iterdir()):
            if entry.is_dir() and (entry / "METADATA.md").exists():
                try:
                    info = _analyze_target(entry, workspace)
                except Exception:
                    logger.exception("Error analyzing target %s", entry.name)
                    info = TargetInfo(
                        name=entry.name,
                        target_dir=entry,
                        display_name=entry.name,
                        phase="Unknown",
                        phase_detail="Error reading target state",
                    )
                targets.append(info)
    else:
        logger.debug("targets_root not found: %s", targets_root)
    return WorkspaceStatus(workspace=workspace, targets_root=targets_root, targets=targets)


def status_blueprint_target(
    blueprint: str,
    target: str,
    blueprint_dir: Path,
    target_dir: Path,
) -> StatusResult:
    del blueprint_dir  # The target layout is authoritative for status.

    from drydock.build_plan import load_target_plan
    from drydock.errors import SpecificationError

    target_path = target_dir / target
    if not target_path.is_dir():
        raise SpecificationError(f"Target not found: {target_path}")

    info = _analyze_target(target_path, target_dir.parent)
    plan = None
    frontier = ()
    if info.plan_summary is not None and (target_path / "MANIFEST.md").exists():
        plan = load_target_plan(target, target_dir)
        frontier = plan.runnable_frontier()

    return StatusResult(
        blueprint=blueprint,
        target=target,
        target_path=target_path,
        target_info=info,
        plan=plan,
        frontier=frontier,
    )


def status_blueprint(blueprint: str, target_dir: Path) -> StatusResult:
    from drydock.validate_specification import validate_specification

    result = validate_specification(blueprint, target_dir)
    return StatusResult(
        blueprint=blueprint,
        validation=result,
    )


def status_current(target_root: Path) -> StatusResult | None:
    """Orientation status: CWD-first, then last recorded activity.

    ``target_root`` is the ``targets/`` root; each Target's Blueprint resolves to
    ``<target>/blueprint``.
    """
    from drydock.config import get_last_activity
    from drydock.validate_specification import validate_specification

    cwd = Path.cwd()
    plan_path = cwd / "MANIFEST.md"

    if plan_path.exists():
        from drydock.build_plan import parse_build_plan

        plan = parse_build_plan(plan_path)
        blueprint = plan.project
        target = cwd.name
        validation = None
        try:
            validation = validate_specification(blueprint, cwd)
        except Exception:
            pass
        activity = get_last_activity()
        return StatusResult(
            blueprint=blueprint,
            target=target,
            target_path=cwd,
            target_info=_analyze_target(cwd, target_root.parent),
            plan=plan,
            frontier=plan.runnable_frontier(),
            validation=validation,
            last_command=activity.get("command", ""),
            last_time=activity.get("time", ""),
        )

    activity = get_last_activity()
    bp = activity.get("blueprint", "")
    if not bp:
        return None

    tgt = activity.get("target", "")
    last_command = activity.get("command", "")
    last_time = activity.get("time", "")

    if tgt:
        target_dir = target_root / tgt
        result = status_blueprint_target(bp, tgt, target_dir / "blueprint", target_root)
        try:
            result.validation = validate_specification(bp, target_dir)
        except Exception:
            pass
    else:
        result = StatusResult(blueprint=bp)

    result.last_command = last_command
    result.last_time = last_time
    return result
