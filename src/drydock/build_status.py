"""Build-status reporting — plan vs. implementation, grouped by block.

``drydock build status`` answers one question: how far has the build progressed
against the plan? The MANIFEST.md is the plan; each block's ``state`` is the
implementation fact. This module shapes those facts into the same feature
grouping the sprint plan and compass use, rolls up per-feature and overall
progress, and marks the buildable frontier — the steps ``drydock build`` would
run next. It reads the plan only; it writes nothing and runs no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

from drydock.build import work_kind_of
from drydock.build_plan import FINISHED_STATES, BuildPlan, PlanBlock
from drydock.build_run import SELECTABLE_STATES

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
    group_id: str
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
    def steps_questions(self) -> int:
        return self._step_count("blocked/questions")

    @property
    def steps_failed(self) -> int:
        return self._step_count("closed/failed")

    @property
    def failed_ids(self) -> tuple[str, ...]:
        """Manifest-ordered ids of failed steps — the rebuild frontier."""
        return tuple(
            step.block.block_id
            for group in self.groups
            for step in group.steps
            if step.block.state == "closed/failed"
        )

    def percent_complete(self) -> int:
        if not self.steps_total:
            return 0
        return round(100 * self.steps_verified / self.steps_total)


def build_status(plan: BuildPlan) -> BuildStatus:
    """Shape a parsed plan into a block-grouped build-status report."""
    by_id = plan.by_id()
    buildable_ids, buildable_steps = _buildable_blocks(plan)
    buildable = set(buildable_steps)

    acs_by_parent: dict[str, list[PlanBlock]] = {}
    for block in plan.blocks:
        if block.block_type == "ac" and block.parent:
            acs_by_parent.setdefault(block.parent, []).append(block)

    if plan.uses_computed_blocks:
        groups = []
        for number, block_steps in plan.computed_groups():
            groups.append(
                FeatureStatus(
                    feature=None,
                    group_id=f"block-{number}",
                    name=f"Build Block {number} · {block_steps[0].story_type.title()}",
                    feature_acs=(),
                    steps=tuple(
                        StepStatus(
                            block=block,
                            acs=tuple(acs_by_parent.get(block.block_id, ())),
                            buildable=block.block_id in buildable,
                        )
                        for block in block_steps
                    ),
                )
            )
        return BuildStatus(
            project=plan.project,
            groups=tuple(groups),
            buildable_ids=buildable_ids,
        )

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
                group_id=feature.block_id if feature is not None else "ungrouped",
                name=name,
                feature_acs=tuple(acs_by_parent.get(key or "", ())),
                steps=tuple(members[key]),
            )
        )

    return BuildStatus(
        project=plan.project,
        groups=tuple(groups),
        buildable_ids=buildable_ids,
    )


def _verified(block_id: str, by_id: dict[str, PlanBlock]) -> bool:
    dependency = by_id.get(block_id)
    return dependency is not None and dependency.state in FINISHED_STATES


def _buildable_blocks(plan: BuildPlan) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the next runnable build block id and child step ids.

    A grouped block is runnable when all dependencies outside the group are
    verified. Dependencies between stories/spikes in the same group are internal
    sequencing and do not split the build unit. The frontier is strictly
    manifest-order: later blocks are not considered ready until earlier pending
    work is verified, failed/retried, or reordered by the operator.
    """
    by_id = plan.by_id()
    if plan.uses_computed_blocks:
        for number, executable in plan.computed_groups():
            pending = tuple(block for block in executable if block.state in SELECTABLE_STATES)
            if not pending:
                continue
            available = {
                block.block_id
                for block in executable
                if block.state in SELECTABLE_STATES or block.state in FINISHED_STATES
            }
            external_deps = tuple(
                dep
                for block in pending
                for dep in block.depends
                if dep not in available and not _verified(dep, by_id)
            )
            if external_deps:
                return (), ()
            return (f"block-{number}",), tuple(block.block_id for block in pending)
        return (), ()

    grouped_children = {
        child.block_id
        for block in plan.blocks
        if block.block_type == "feature"
        for child in plan.children(block.block_id)
        if child.block_type in STEP_TYPES
    }

    for block in plan.blocks:
        if block.block_type == "feature":
            executable = tuple(
                child for child in plan.children(block.block_id) if child.block_type in STEP_TYPES
            )
            pending = tuple(child for child in executable if child.state in SELECTABLE_STATES)
            if not pending:
                continue
            first_kind = work_kind_of(pending[0])
            pending = _first_pending_work_run(pending, first_kind)
            internal_ids = {child.block_id for child in pending}
            external_deps = [
                dep
                for dep in block.depends
                if dep not in internal_ids and not _verified(dep, by_id)
            ]
            for child in pending:
                external_deps.extend(
                    dep
                    for dep in child.depends
                    if dep not in internal_ids and not _verified(dep, by_id)
                )
            if external_deps:
                return (), ()
            return (block.block_id,), tuple(child.block_id for child in pending)

        if block.block_type not in STEP_TYPES or block.block_id in grouped_children:
            continue
        if block.state not in SELECTABLE_STATES:
            continue
        if not all(_verified(dep, by_id) for dep in block.depends):
            return (), ()
        return (block.block_id,), (block.block_id,)

    return (), ()


def _first_pending_work_run(
    pending: tuple[PlanBlock, ...], first_kind: str
) -> tuple[PlanBlock, ...]:
    run: list[PlanBlock] = []
    for child in pending:
        if work_kind_of(child) != first_kind:
            break
        run.append(child)
    return tuple(run)
