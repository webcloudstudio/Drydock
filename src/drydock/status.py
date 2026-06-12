"""drydock status — compact project orientation across all three invocation forms."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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


def status_blueprint(blueprint: str, blueprint_dir: Path) -> StatusResult:
    from drydock.validate_specification import validate_specification

    result = validate_specification(blueprint, blueprint_dir)
    return StatusResult(
        blueprint=blueprint,
        validation=result,
    )


def status_current(blueprint_dir: Path, target_dir: Path) -> StatusResult | None:
    """Orientation status: CWD-first, then last recorded activity."""
    from drydock.config import get_last_activity

    cwd = Path.cwd()
    plan_path = cwd / "BUILD_PLAN.md"

    if plan_path.exists():
        from drydock.build_plan import parse_build_plan

        plan = parse_build_plan(plan_path)
        blueprint = plan.project
        target = cwd.name
        # Also run validation if blueprint_dir resolves
        validation = None
        try:
            from drydock.validate_specification import validate_specification

            validation = validate_specification(blueprint, blueprint_dir)
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
        result = status_blueprint_target(bp, tgt, blueprint_dir, target_dir)
        # Also run validation
        try:
            from drydock.validate_specification import validate_specification

            result.validation = validate_specification(bp, blueprint_dir)
        except Exception:
            pass
    else:
        result = status_blueprint(bp, blueprint_dir)

    result.last_command = last_command
    result.last_time = last_time
    return result
