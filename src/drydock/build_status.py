"""Build-status reporting — plan vs. implementation, grouped by feature.

``drydock build status`` answers one question: how far has the build progressed
against the plan? The MANIFEST.md is the plan; each block's ``state`` is the
implementation fact. This module shapes those facts into the same feature
grouping the sprint plan and compass use, rolls up per-feature and overall
progress, and marks the buildable frontier — the steps ``drydock build`` would
run next. It reads the plan only; it writes nothing and runs no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

from drydock.build_plan import BuildPlan, PlanBlock

STEP_TYPES = ("story", "spike")


@dataclass(frozen=True)
class StepStatus:
    """One executable step with its folded acceptance criteria."""

    block: PlanBlock
    acs: tuple[PlanBlock, ...]
    buildable: bool


@dataclass(frozen=True)
class FeatureStatus:
    """A feature grouping of steps, with feature-level acs and a rollup."""

    feature: PlanBlock | None
    name: str
    feature_acs: tuple[PlanBlock, ...]
    steps: tuple[StepStatus, ...]

    @property
    def verified(self) -> int:
        return sum(1 for s in self.steps if s.block.state == "closed/verified")

    @property
    def total(self) -> int:
        return len(self.steps)


@dataclass(frozen=True)
class BuildStatus:
    """The full build-status report for one Target plan."""

    project: str
    plan_state: str
    groups: tuple[FeatureStatus, ...]
    buildable_ids: tuple[str, ...]

    def _step_count(self, state: str) -> int:
        return sum(1 for group in self.groups for step in group.steps if step.block.state == state)

    @property
    def steps_total(self) -> int:
        return sum(group.total for group in self.groups)

    @property
    def steps_verified(self) -> int:
        return self._step_count("closed/verified")

    @property
    def steps_implemented(self) -> int:
        return self._step_count("implemented")

    @property
    def steps_pending(self) -> int:
        return self._step_count("pending")

    @property
    def steps_failed(self) -> int:
        return self._step_count("closed/failed")

    def percent_complete(self) -> int:
        if not self.steps_total:
            return 0
        return round(100 * self.steps_verified / self.steps_total)


def build_status(plan: BuildPlan) -> BuildStatus:
    """Shape a parsed plan into a feature-grouped build-status report."""
    by_id = plan.by_id()
    buildable_ids = tuple(block.block_id for block in plan.buildable_steps())
    buildable = set(buildable_ids)

    acs_by_parent: dict[str, list[PlanBlock]] = {}
    for block in plan.blocks:
        if block.block_type == "ac" and block.parent:
            acs_by_parent.setdefault(block.parent, []).append(block)

    order: list[str | None] = []
    members: dict[str | None, list[StepStatus]] = {}
    for block in plan.blocks:
        if block.block_type not in STEP_TYPES:
            continue
        parent = block.parent
        key = parent if parent and parent in by_id else None
        if key not in members:
            members[key] = []
            order.append(key)
        members[key].append(
            StepStatus(
                block=block,
                acs=tuple(acs_by_parent.get(block.block_id, ())),
                buildable=block.block_id in buildable,
            )
        )

    groups: list[FeatureStatus] = []
    for key in order:
        if key is None:
            name = "Ungrouped"
            feature = None
        else:
            feature = by_id[key]
            name = feature.name
        groups.append(
            FeatureStatus(
                feature=feature,
                name=name,
                feature_acs=tuple(acs_by_parent.get(key or "", ())),
                steps=tuple(members[key]),
            )
        )

    return BuildStatus(
        project=plan.project,
        plan_state=plan.state,
        groups=tuple(groups),
        buildable_ids=buildable_ids,
    )
