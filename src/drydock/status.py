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
