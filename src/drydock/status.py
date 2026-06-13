"""drydock status — compact project orientation across all three invocation forms."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


_HISTORY_FILENAME = "history.jsonl"


@dataclass
class TargetInfo:
    name: str
    target_dir: Path
    display_name: str
    phase: str          # Set Up | Arrange | Implement | Loop | Unknown
    phase_detail: str
    next_operation: str = ""
    history: list[dict] = field(default_factory=list)
    history_path: Path | None = None


@dataclass
class WorkspaceStatus:
    workspace: Path
    targets_root: Path
    targets: list[TargetInfo] = field(default_factory=list)


def _has_blueprint_content(blueprint_dir: Path) -> bool:
    """True if blueprint/ contains any authored file beyond skeleton .gitkeep entries."""
    if not blueprint_dir.is_dir():
        return False
    for f in blueprint_dir.rglob("*"):
        if f.is_file() and f.name != ".gitkeep":
            return True
    return False


def _read_history(history_path: Path, limit: int = 5) -> list[dict]:
    if not history_path.exists():
        return []
    records: list[dict] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json
            records.append(json.loads(line))
        except Exception:
            pass
    return records[-limit:]


def _analyze_target(target_dir: Path, *, debug: bool = False) -> TargetInfo:
    from drydock.metadata import get_field, parse_metadata

    def _dbg(path: Path) -> None:
        if debug:
            print(f"  Reading {path}")

    name = target_dir.name
    _dbg(target_dir / "METADATA.md")
    meta = parse_metadata(target_dir / "METADATA.md")
    display_name = get_field(meta, "display_name") or name
    blueprint = get_field(meta, "blueprint") or name

    blueprint_dir = target_dir / "blueprint"
    build_plan_path = target_dir / "BUILD_PLAN.md"
    history_path = target_dir / "logs" / _HISTORY_FILENAME

    _dbg(blueprint_dir)
    has_content = _has_blueprint_content(blueprint_dir)
    _dbg(build_plan_path)
    _dbg(history_path)
    history = _read_history(history_path)

    if not has_content:
        phase, detail = "Set Up", "Blueprint is empty — no source material imported yet"
        next_op = f"drydock import {blueprint} {name} <source> --format markdown"
    elif not build_plan_path.exists():
        phase, detail = "Arrange", "Blueprint has content — plan not yet created"
        next_op = f"drydock plan create {blueprint} {name}"
    else:
        try:
            from drydock.build_plan import parse_build_plan
            plan = parse_build_plan(build_plan_path)
        except Exception:
            phase = "Arrange"
            detail = "BUILD_PLAN.md could not be parsed — check its format"
            next_op = f"drydock plan create {blueprint} {name}"
            return TargetInfo(
                name=name, target_dir=target_dir, display_name=display_name,
                phase=phase, phase_detail=detail, next_operation=next_op,
                history=history, history_path=history_path,
            )

        if plan.state == "draft":
            phase = "Arrange"
            detail = "Draft plan created — awaiting QuarterDeck approval"
            next_op = f"drydock run quarterdeck {name}  (then approve in Planning Session)"
        else:
            counts = plan.state_counts()
            total = len(plan.blocks)
            verified = counts.get("closed/verified", 0)
            pending = counts.get("pending", 0)
            implemented = counts.get("implemented", 0)
            failed = counts.get("closed/failed", 0)

            if total > 0 and verified == total:
                phase = "Loop"
                detail = f"All {total} blocks verified — ready for Refit"
                next_op = f"drydock refit {blueprint} {name} BOTH <Scope> <Change>"
            else:
                frontier = plan.runnable_frontier()
                parts = [f"{verified}/{total} verified", f"{pending} pending"]
                if implemented:
                    parts.append(f"{implemented} implemented")
                if failed:
                    parts.append(f"{failed} FAILED")
                phase = "Implement"
                detail = "  ·  ".join(parts)
                if frontier:
                    next_op = (
                        f"drydock build {blueprint} {name}"
                        f"  (frontier: {', '.join(b.name for b in frontier[:2])})"
                    )
                else:
                    next_op = f"drydock build {blueprint} {name}"

    return TargetInfo(
        name=name, target_dir=target_dir, display_name=display_name,
        phase=phase, phase_detail=detail, next_operation=next_op,
        history=history, history_path=history_path,
    )


def status_workspace(workspace: Path, targets_root: Path, *, debug: bool = False) -> WorkspaceStatus:
    """Return status for all initialized targets in the workspace."""
    targets: list[TargetInfo] = []
    if targets_root.is_dir():
        if debug:
            print(f"  Reading {targets_root}/")
        for entry in sorted(targets_root.iterdir()):
            if entry.is_dir() and (entry / "METADATA.md").exists():
                try:
                    info = _analyze_target(entry, debug=debug)
                except Exception:
                    info = TargetInfo(
                        name=entry.name, target_dir=entry, display_name=entry.name,
                        phase="Unknown", phase_detail="Error reading target state",
                    )
                targets.append(info)
    elif debug:
        print(f"  Reading {targets_root}/  (not found)")
    return WorkspaceStatus(workspace=workspace, targets_root=targets_root, targets=targets)


@dataclass
class StatusResult:
    blueprint: str
    target: str = ""
    target_path: Path | None = None
    plan: object = None  # BuildPlan | None
    frontier: tuple = ()  # tuple[PlanBlock, ...]
    validation: object = None  # ValidationResult | None
    last_command: str = ""
    last_time: str = ""


def status_blueprint_target(
    blueprint: str,
    target: str,
    blueprint_dir: Path,
    target_dir: Path,
) -> StatusResult:
    from drydock.build_plan import load_target_plan

    plan = load_target_plan(target, target_dir)
    frontier = plan.runnable_frontier()
    return StatusResult(
        blueprint=blueprint,
        target=target,
        target_path=target_dir / target,
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
    plan_path = cwd / "BUILD_PLAN.md"

    if plan_path.exists():
        from drydock.build_plan import parse_build_plan

        plan = parse_build_plan(plan_path)
        blueprint = plan.project
        target = cwd.name
        # The CWD is the Target; validate against the Target directory.
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
