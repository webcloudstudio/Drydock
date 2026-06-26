"""Human review transitions for ``drydock build`` gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drydock.build_plan import PlanBlock, parse_build_plan
from drydock.errors import SpecificationError
from drydock.manifest_edit import _set_field_line, split_manifest, write_manifest

_STEP_TYPES = ("story", "spike")


@dataclass(frozen=True)
class BuildVerifyResult:
    """Result of accepting one implemented build step."""

    step_id: str
    step_name: str
    ac_ids: tuple[str, ...]


def _child_acs(blocks: tuple[PlanBlock, ...], step_id: str) -> tuple[PlanBlock, ...]:
    return tuple(block for block in blocks if block.block_type == "ac" and block.parent == step_id)


def verify_build_step(manifest_path: Path, step_id: str) -> BuildVerifyResult:
    """Mark one implemented story/spike and its child ACs ``closed/verified``.

    ``drydock build`` moves steps with acceptance checks to ``implemented``.
    This function records the human review decision that the step satisfies its
    acceptance checks and can unblock dependent work.
    """
    plan = parse_build_plan(manifest_path)
    by_id = plan.by_id()
    step = by_id.get(step_id)
    if step is None:
        raise SpecificationError(f"Build step {step_id!r} not found in {manifest_path}")
    if step.block_type not in _STEP_TYPES:
        raise SpecificationError(f"{step_id!r} is not a build step")
    if step.state != "implemented":
        raise SpecificationError(
            f"{step_id!r} is {step.state!r}; only implemented steps can be verified"
        )

    acs = _child_acs(plan.blocks, step_id)
    if not acs:
        raise SpecificationError(
            f"{step_id!r} has no acceptance checks; it should have closed during build"
        )

    doc = split_manifest(manifest_path)
    raw_by_id = doc.by_id()
    _set_field_line(raw_by_id[step_id], "state", "closed/verified")
    for ac in acs:
        _set_field_line(raw_by_id[ac.block_id], "state", "closed/verified")
    write_manifest(doc)

    return BuildVerifyResult(
        step_id=step.block_id,
        step_name=step.name,
        ac_ids=tuple(ac.block_id for ac in acs),
    )
