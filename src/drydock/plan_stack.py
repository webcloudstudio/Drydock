"""Zone A stack resolution and block cost sizing.

`TECHNOLOGY_STACK.md` declares *which* stack is used; it is the only stack input Zone A used to
read. The Rigging stack files themselves — ``fastapi.md``, ``common.md`` — were never opened at
plan time, so a story's builder/consumer mode had no measurable basis. Resolving the stack file
set is therefore a required Zone A step: the mode assignment in :mod:`drydock.plan_graph` and the
cost target below both need the real files.

**Tokens belong to the block, not the story.** A story is sized by Agile judgement — 1 to 5 story
points, one thing done completely, releasable on its own — and has no token dimension at all. What
is measured in tokens is the block: the assembled cost of one build run. Because a block holds at
least one story, the target constrains a story only in the degenerate single-story case.

The earlier framing sized a *story* by "what one build agent can implement and verify in a single
pass". That was never a decomposition boundary: a model will accept a whole epic in one pass and
build it badly, so capacity says nothing about whether the unit of work is a story.

The target is the active model's ``prompt_target_tokens`` from ``model_config.jsonl``, which
already means *the maximum assembled prompt cost of one build step* — the same quantity measured
here at plan time. A second key would be the same number under a second name, drifting.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from drydock import model_config, technology_stack
from drydock.build import PROMPT_TARGET_TOKENS, PROMPT_WARNING_TOKENS, resolve_target_tokens
from drydock.errors import ConfigurationError
from drydock.paths import get_stack_dir, resolve_rigging_file
from drydock.prompt_assembly import estimate_tokens

#: Fallback target when ``model_config.jsonl`` is unreadable. Mirrors the build-time default so
#: plan-time and build-time sizing cannot disagree.
DEFAULT_BLOCK_TARGET_TOKENS = PROMPT_TARGET_TOKENS

#: Prior spelling, retained for callers. The old name attached the measurement to a story; tokens
#: are a property of the block a story is built in.
DEFAULT_STORY_BUDGET_TOKENS = DEFAULT_BLOCK_TARGET_TOKENS

_COMPACT_SUFFIX = "_compact.md"
_SKIP_SUFFIX = "_compact.skip.md"


def block_target_tokens() -> int:
    """Return the configured block cost target in tokens.

    Resolves the active model's ``prompt_target_tokens`` — the value ``drydock build`` uses to flag
    an over-stacked step. Sizing is a read-only costing pass, so an unusable setting downgrades to the built-in
    default rather than refusing to plan. This is a target, not a gate: over-target work is
    marked and built.
    """
    return resolve_target_tokens()


#: Share of a model's ``prompt_limit_tokens`` one planned block may reach. A block the planner
#: sizes near the limit is escalated to the row's ``escalate_model`` at build time once the
#: estimate drifts; the margin keeps every planned block on the configured model.
BLOCK_LIMIT_FRACTION = 0.9


def block_limit_tokens_for(profile: model_config.ModelProfile) -> int:
    """Return the absolute ceiling on one block's planned cost for ``profile``.

    The row's ``prompt_warning_tokens``, lowered to ``BLOCK_LIMIT_FRACTION`` of its
    ``prompt_limit_tokens`` when it sets one. Plan sizing omits the CLI's fixed build payload that
    escalation counts, so that overhead is subtracted to compare like with like.
    """
    ceiling = profile.prompt_warning_tokens
    if profile.prompt_limit_tokens is not None:
        allowed = int(BLOCK_LIMIT_FRACTION * profile.prompt_limit_tokens)
        ceiling = min(ceiling, allowed - profile.overhead(allow_tools=True))
    return ceiling


def block_limit_tokens() -> int:
    """Return the active model's absolute block ceiling, falling back to the built-in default."""
    try:
        return block_limit_tokens_for(model_config.active_profile())
    except ConfigurationError:
        return PROMPT_WARNING_TOKENS


#: Prior spelling. Tokens measure a block, never a story.
story_budget_tokens = block_target_tokens


def block_min_savings() -> int:
    """Return the configured minimum shared context, in tokens, that justifies a block merge.

    Resolves ``block_min_savings``. Blocking is a read-only optimization pass, so an unusable
    setting downgrades to the built-in default rather than refusing to plan.
    """
    from drydock.config import DEFAULT_BLOCK_MIN_SAVINGS, get_block_min_savings

    try:
        return get_block_min_savings()
    except ConfigurationError:
        return DEFAULT_BLOCK_MIN_SAVINGS


@dataclass(frozen=True)
class ResolvedStackFile:
    """One Rigging stack file, resolved and measured at plan time."""

    name: str
    path: Path | None
    tokens: int = 0
    compact_path: Path | None = None
    compact_tokens: int = 0

    @property
    def resolved(self) -> bool:
        return self.path is not None

    @property
    def has_compact(self) -> bool:
        return self.compact_path is not None

    def tokens_for(self, mode: str) -> int:
        """Cost of attaching this file in ``builder`` or ``consumer`` mode.

        A builder story receives the full stack file; a consumer story receives the interface
        view. This is the computable form of the compact-substitution rule, decided at plan time
        rather than tracked through an applied registry at build time.
        """
        if mode == "consumer" and self.has_compact:
            return self.compact_tokens
        return self.tokens


def _measure(path: Path) -> int:
    try:
        return estimate_tokens(path.stat().st_size)
    except OSError:
        return 0


def resolve_stack_file(name: str, stack_dir: Path | None = None) -> ResolvedStackFile:
    """Resolve one declared stack filename against the Rigging stack directory."""
    if stack_dir is None:
        try:
            stack_dir = get_stack_dir()
        except Exception:
            return ResolvedStackFile(name=name, path=None)
    path = resolve_rigging_file(name, stack_dir)
    if path is None:
        return ResolvedStackFile(name=name, path=None)
    compact = path.parent / name.replace(".md", _COMPACT_SUFFIX)
    skip = path.parent / name.replace(".md", _SKIP_SUFFIX)
    has_compact = compact.is_file() and not skip.is_file()
    return ResolvedStackFile(
        name=name,
        path=path,
        tokens=_measure(path),
        compact_path=compact if has_compact else None,
        compact_tokens=_measure(compact) if has_compact else 0,
    )


def resolve_stack_set(
    names: Iterable[str], stack_dir: Path | None = None
) -> dict[str, ResolvedStackFile]:
    """Resolve and measure every declared stack file, preserving declaration order."""
    if stack_dir is None:
        try:
            stack_dir = get_stack_dir()
        except Exception:
            stack_dir = None
    resolved: dict[str, ResolvedStackFile] = {}
    for name in names:
        cleaned = name.strip()
        if cleaned and cleaned not in resolved:
            resolved[cleaned] = resolve_stack_file(cleaned, stack_dir)
    return resolved


def resolve_target_stack(
    target_dir: Path, stack_dir: Path | None = None
) -> dict[str, ResolvedStackFile]:
    """Resolve the Target's declared technology stack into measured Rigging files.

    ``TECHNOLOGY_STACK.md`` is the sole authority on *which* stack is used. An absent or
    incomplete file means undecided, not forbidden, so an empty result is a normal Zone A
    outcome and never gates planning.
    """
    try:
        declared = technology_stack.stack_files(target_dir)
    except Exception:
        declared = []
    return resolve_stack_set(declared, stack_dir)


def unresolved_names(resolved: dict[str, ResolvedStackFile]) -> tuple[str, ...]:
    """Return declared stack names with no matching Rigging file, sorted."""
    return tuple(sorted(name for name, entry in resolved.items() if not entry.resolved))


def stack_cost(
    names: Sequence[str],
    resolved: dict[str, ResolvedStackFile],
    *,
    mode: str = "builder",
) -> int:
    """Total token cost of attaching ``names`` in the given mode."""
    return sum(resolved[name].tokens_for(mode) for name in dict.fromkeys(names) if name in resolved)


def story_pass_tokens(
    *,
    specification_tokens: int,
    stack: Sequence[str],
    resolved: dict[str, ResolvedStackFile],
    mode: str = "builder",
) -> int:
    """Estimate one story's contribution to its block's cost: its specification plus stack files.

    This is an input to block sizing, not a verdict on the story. A story that measures large is
    not thereby mis-sized — story sizing is the Agile judgement, and this number belongs to the
    block the story lands in.
    """
    return specification_tokens + stack_cost(stack, resolved, mode=mode)


def exceeds_block_target(tokens: int, *, target: int | None = None) -> bool:
    """Whether a measured block exceeds the cost target and should be marked over-target."""
    return tokens > (block_target_tokens() if target is None else target)


def exceeds_build_pass(tokens: int, *, budget: int | None = None) -> bool:
    """Prior spelling of :func:`exceeds_block_target`."""
    return exceeds_block_target(tokens, target=budget)
