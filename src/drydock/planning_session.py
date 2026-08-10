"""``drydock plan create`` — LLM-driven authoring of the Blueprint and executable Manifest.

`plan create` implements the reviewed analysis in stages: one LLM call declares and freezes the
topology, bounded LLM batches author its typed Blueprint specifications, and Python serializes the
executable ``MANIFEST.md``. The Manifest is the single work graph: it carries build order, grouping,
and per-step prompt-assembly fields, so no separate build-ordering file is emitted. The module
parses the blocks, runs a deterministic integrity gate, and writes the files.

When a prior MANIFEST.md exists, Planning runs as an authoritative rewrite. Build provenance and
closed states survive only for specification files whose regenerated content has the recorded
sha256; changed specifications return to ``pending``. The model emits text; the module writes files.
Tests inject a fake runner and never spend API credits.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from fnmatch import fnmatch
from hashlib import sha256 as _sha256
from pathlib import Path
from typing import Protocol, cast

from drydock import technology_stack
from drydock.acceptance import PYTHON_FENCE_RE, parse_programmatic_acceptance_text
from drydock.acceptance_requirements import (
    project_plan_requirement_decisions,
    recommend_external_declarations,
)
from drydock.build_plan import (
    AppliedSpecRecord,
    BuildPlan,
    build_relevant_sha256,
    build_relevant_text_sha256,
    disambiguate_manifest_ids,
    parse_build_plan,
    set_applied_specs,
)
from drydock.config import build_dir_for
from drydock.decisions import (
    ARCHITECTURE_BLUEPRINT,
    DECISIONS_BLOCK,
    DECISIONS_FILENAME,
    load_decisions,
    parse_plan_decisions,
    questionnaire_decisions,
    reconcile_decisions,
    render_commander_guidance,
    validate_decision_blueprints,
    write_decisions,
)
from drydock.errors import (
    ErrorRecord,
    RecordedError,
    SpecificationError,
    clear_error_record,
    errors_path,
    write_error_record,
)
from drydock.exclude_files import ensure_exclude_file, load_excluded_filenames
from drydock.llm import run_prompt
from drydock.manifest_edit import batch_set_block_fields
from drydock.metadata import increment_version, set_build_state, set_sub_state, stamp_last
from drydock.override import PLAN_DECISION, WaivedGate, dedupe_waivers, stamp_override
from drydock.paths import get_prompts_root
from drydock.plan_graph import PlanComputation, PlannedStory
from drydock.plan_score import PlanScore, score_plan
from drydock.plan_shape import OutputContract, ShapeDefect, check_contract, render_defects
from drydock.plan_topology import TOPOLOGY_BLOCK, parse_topology
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_fenced_parts,
    contextual_markdown_parts,
    estimate_tokens,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompt_context import prompt_source_header
from drydock.prompt_headers import prompt_header_for_file
from drydock.prompts import load_prompt
from drydock.sea_trials import parse_sea_trials_text
from drydock.source_material import SourceMaterialFile, discover_source_material
from drydock.source_roles import parse_source_roles, promote_imported_sources
from drydock.standard_artifacts import ensure_standard_artifacts, render_console

PROMPT_NAME = "plan_create"

_BLOCK_RE = re.compile(r"=== (?!END )(.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_OPEN_BLOCK_LINE_RE = re.compile(r"^=== (?!END )(?P<name>[^\n=]+?) ===\s*$", re.MULTILINE)
_END_BLOCK_LINE_RE = re.compile(r"^=== END (?P<name>[^\n=]+?) ===\s*$", re.MULTILINE)
_WRITE_CALL_RE = re.compile(
    r'<invoke name="Write">\s*'
    r'<parameter name="file_path">(?P<path>.*?)</parameter>\s*'
    r'<parameter name="content">(?P<content>.*?)</parameter>\s*'
    r"</invoke>",
    re.DOTALL,
)
_FUNCTION_WRAPPER_RE = re.compile(r"</?function_calls>\s*")
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_PLANNING_INSTRUCTIONS_RE = re.compile(r"^## Planning Instructions\s*$", re.MULTILINE)
#: A cited source path. ``*`` and ``?`` are accepted so a citation may name a family of source files
#: (``sources/FEATURE-CATALOG-*.md``) the way an author naturally abbreviates one; the pattern is
#: expanded against the discovered source material by :func:`_expand_source_citations`.
_SOURCE_CITATION_RE = re.compile(r"(?<![A-Za-z0-9_.\-*?])(sources/[A-Za-z0-9_./\-*?]+)")
_SHAPE_RE = re.compile(r"Project type:\s*`?([A-Za-z][\w-]*)`?", re.MULTILINE)
# Block names the LLM emits that are not authored Blueprint spec files.
_RESERVED_BLOCKS = frozenset({
    "MANIFEST.md",
    TOPOLOGY_BLOCK,
    "PLAN_CREATE_BLOCKED.txt",
    "PLAN_CREATE_ERROR.txt",
    DECISIONS_BLOCK,
})
_NON_BLUEPRINT_ARTIFACTS = frozenset({"AGENTS.md"})

_CONTRACT_FILES = ("MANIFEST_CONTRACT.md", "BLUEPRINTS_CONTRACT.md")

# Stage 2 gives the planning agent a small, exact work queue.  A bounded tranche prevents a large
# topology from inducing dozens of simultaneously opened artifact envelopes near the output limit.
_PLAN_BLUEPRINT_BATCH_SIZE = 5

# Story count is not capped. The ~100-story cap was a proxy for over-decomposition, but story
# sizing is now "one build pass" (see drydock.plan_stack), which has no opinion about how many
# stories a project contains: a correct 300-story project is plausible and would have been
# refused. Scale is answered with a stronger model, not a refusal to plan. A manageable number
# well under 100 remains the ideal, as guidance rather than a gate.
_OUTSIDE_TEXT_LIMIT = 100
_OUTSIDE_SPAN_LIMIT = 3
_OUTSIDE_FORBIDDEN_MARKERS = ("===", "<invoke", "<function_calls", "```", "~~~")
# Legal `parent:` block types per block type. A story or spike groups under a
# feature; an ac gates a story, a spike, or a feature group.
_PARENT_BLOCK_TYPES = {
    "story": frozenset({"feature"}),
    "spike": frozenset({"feature"}),
    "ac": frozenset({"story", "spike", "feature"}),
}

_FEEDBACK_FILENAME = "PLAN_COMPASS.md"
_REUSE_PROMPT_NAME = "plan_reuse"
_PLAN_MODE_LABELS = {
    "reuse-manifest-first": "REUSE mode: preserving existing Blueprint specs, regenerating MANIFEST.md",
    "full-rewrite": "OVERWRITE mode: regenerating Blueprint specs and MANIFEST.md from the analysis",
    "speckit-translate": "SPEC-KIT mode: translating imported Spec Kit sources into the Blueprint",
}
_SPECKIT_PROMPT_NAME = "plan_create_speckit"
_CONFORM_PROMPT_NAME = "plan_conform"
_TERMINAL_SECTIONS = (
    "Programmatic Acceptance",
    "User Acceptance",
    "Guardrails",
)
_TYPED_HEADING_RE = re.compile(r"^#\s+(?P<kind>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?P<name>.+?)\s*$")
_HEADER_ROW_RE = re.compile(r"^\|\s*(?P<field>[^|]+?)\s*\|\s*(?P<value>.*?)\s*\|$")
_TERMINAL_SECTION_RE = re.compile(
    r"^## (?P<heading>Programmatic Acceptance|User Acceptance|Guardrails)\s*$"
    r".*?(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)

_ROOT_TYPED_SPEC_FILES = frozenset({
    "ARCHITECTURE.md",
    "DATABASE.md",
    "UI-GENERAL.md",
    "HOMEPAGE.md",
})
_IGNORE_TYPED_SPEC_FILES = frozenset({
    "AGENTS.md",
    "ARCHITECTURE_compact.md",
    "ARCHITECTURE_compact.skip.md",
    "DATABASE_compact.md",
    "DATABASE_compact.skip.md",
})


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    stderr: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class PlanCreateResult:
    plan: BuildPlan
    target_dir: Path
    quarterdeck_dir: Path
    changed: bool
    authored_files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    execution_id: str | None = None
    waiver_execution_id: str | None = None
    plan_mode: str = ""
    conformed_files: tuple[Path, ...] = ()
    waivers: tuple[WaivedGate, ...] = ()


@dataclass(frozen=True)
class PlanDeferredResult:
    """Recoverable planning handoff requiring Commander direction."""

    target_dir: Path
    error_record: ErrorRecord
    errors_path: Path
    detail: str
    initial_execution_id: str | None = None
    challenge_execution_id: str | None = None
    plan_mode: str = ""


@dataclass(frozen=True)
class ExistingSpec:
    path: Path
    filename: str
    file_type: str
    object_name: str
    header_fields: dict[str, str]
    body: str
    reusable: bool


@dataclass(frozen=True)
class OutsideTextSpan:
    """One non-whitespace span before, between, or after complete artifact blocks."""

    text: str
    previous_artifact: str | None
    next_artifact: str | None

    @property
    def normalized(self) -> str:
        return self.text.strip()

    @property
    def location(self) -> str:
        if self.previous_artifact is None:
            return f"before {self.next_artifact or 'the first artifact'}"
        if self.next_artifact is None:
            return f"after {self.previous_artifact}"
        return f"between {self.previous_artifact} and {self.next_artifact}"


class OutsideArtifactTextError(SpecificationError):
    """A structurally complete artifact batch contains text outside its blocks."""

    def __init__(
        self,
        *,
        blocks: dict[str, str],
        spans: tuple[OutsideTextSpan, ...],
        result: CompletedRun,
    ):
        self.blocks = blocks
        self.spans = spans
        details = []
        for span in spans:
            preview = json.dumps(
                span.normalized[:_OUTSIDE_TEXT_LIMIT],
                ensure_ascii=False,
            )
            remaining = len(span.normalized) - _OUTSIDE_TEXT_LIMIT
            suffix = f" … ({remaining} more characters)" if remaining > 0 else ""
            details.append(f"  {span.location}: {preview}{suffix}")
        message = (
            "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
            "  Non-whitespace text appeared outside delimited artifact blocks.\n"
            + "\n".join(details)
            + "\n  No Blueprint or Manifest artifacts were written."
        )
        super().__init__(_with_execution_evidence(message, result))


# ── Parsing ──────────────────────────────────────────────────────────────────────


def _parse_blocks(text: str) -> dict[str, str]:
    """Return block-name → stripped content from ``=== NAME ===`` delimiters."""
    return {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}


def _repair_missing_leading_delimiter(text: str) -> str | None:
    """Recover a missing first ``=== NAME ===`` when the orphan END line is unambiguous.

    Claude occasionally emits the first artifact body and closing delimiter but drops the opening
    delimiter. Recover only when the output starts with body text and the first delimiter we can
    prove is an orphan ``=== END <name> ===`` line. Any ordinary prose preamble still fails.
    """
    if not text or text.lstrip().startswith("==="):
        return None

    first_end = _END_BLOCK_LINE_RE.search(text)
    if first_end is None:
        return None

    leading = text[: first_end.start()]
    if not leading.strip():
        return None
    if "===" in leading:
        return None

    recovered_name = first_end.group("name").strip()
    remainder = text[first_end.end() :]
    if f"=== {recovered_name} ===" in remainder:
        return None

    leading_body = leading.rstrip("\n")
    repaired = f"=== {recovered_name} ===\n{leading_body}\n=== END {recovered_name} ==={remainder}"
    return repaired


def _execution_output_path(result: CompletedRun) -> str | None:
    artifacts = getattr(result, "artifacts", None)
    output_file = getattr(artifacts, "output_file", None)
    return str(output_file) if output_file else None


def _with_execution_evidence(message: str, result: CompletedRun) -> str:
    output_file = _execution_output_path(result)
    if output_file:
        return f"{message}\n  Execution output: {output_file}"
    return message


_AUTH_PHRASES = ("not logged in", "please run /login", "authentication_failed", "unauthenticated")


def _raise_llm_failure(command_name: str, detail: str, execution_id: str) -> None:
    detail_lower = detail.lower()
    if any(phrase in detail_lower for phrase in _AUTH_PHRASES):
        raise SpecificationError(
            f"Plan generation failed: claude CLI is not authenticated.\n"
            f"  Run: /login  (in the Claude Code session that will execute drydock)\n"
            f"  Then retry: drydock {command_name}\n"
            f"  Execution: {execution_id}"
        )
    msg = f"Plan generation failed: {command_name} LLM execution failed"
    if detail:
        msg += f"\n  Detail: {detail}"
    msg += f"\n  Execution: {execution_id}"
    raise SpecificationError(msg)


def _parse_strict_blocks(text: str, result: CompletedRun) -> dict[str, str]:
    """Parse the required artifact block protocol and reject malformed output."""
    repaired = _repair_missing_leading_delimiter(text)
    if repaired is not None:
        text = repaired
    blocks, spans = _parse_strict_blocks_by_line(text, result)
    _reject_unpaired_end_delimiters(text, blocks, result)
    _reject_embedded_delimiters(blocks, result)
    if spans:
        raise OutsideArtifactTextError(blocks=blocks, spans=spans, result=result)
    return blocks


def _reject_unpaired_end_delimiters(
    text: str, blocks: dict[str, str], result: CompletedRun
) -> None:
    """Fail loudly when an ``=== END X ===`` line has no matching parsed ``=== X ===`` block.

    When the model emits only opening delimiters between files (closing just the final block), the
    line parser silently absorbs every later delimiter into the first still-open block, collapsing
    the whole response into one artifact. The orphan END lines are the unambiguous signal: an END
    delimiter whose name never became a block means the files were not paired. A stray
    ``=== END X ===`` inside a body is already a contract violation, so this cannot false-positive
    on well-formed output.
    """
    for match in _END_BLOCK_LINE_RE.finditer(text):
        name = match.group("name").strip()
        if name not in blocks:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    f"  Delimiter pairing mismatch: found `=== END {name} ===` with no matching "
                    f"`=== {name} ===` block.\n"
                    "  Every file must be wrapped in a paired open/END delimiter.\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )


def _reject_embedded_delimiters(blocks: dict[str, str], result: CompletedRun) -> None:
    """Fail loudly when a parsed body contains an artifact delimiter line.

    Under the protocol a delimiter never appears inside a file. One that survives into a body means
    the recovery rules could not resolve the boundary — the model restarted an artifact or nested
    one inside another — and the block that absorbed it is not the file it claims to be.
    """
    for name, body in blocks.items():
        for line in body.splitlines():
            stripped = line.strip()
            if _OPEN_BLOCK_LINE_RE.match(stripped) or _END_BLOCK_LINE_RE.match(stripped):
                raise SpecificationError(
                    _with_execution_evidence(
                        "Plan generation failed: LLM output did not satisfy the artifact "
                        "contract.\n"
                        f"  Delimiter pairing mismatch: `{stripped}` appears inside the body of "
                        f"`{name}`.\n"
                        "  Every file must be wrapped in a paired open/END delimiter.\n"
                        "  No Blueprint or Manifest artifacts were written.",
                        result,
                    )
                )


def _parse_strict_blocks_by_line(
    text: str, result: CompletedRun
) -> tuple[dict[str, str], tuple[OutsideTextSpan, ...]]:
    blocks: dict[str, str] = {}
    current_name: str | None = None
    current_body: list[str] = []
    outside: list[str] = []
    outside_spans: list[OutsideTextSpan] = []
    previous_name: str | None = None
    saw_delimiter = False

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        open_match = _OPEN_BLOCK_LINE_RE.match(line.strip())
        end_match = _END_BLOCK_LINE_RE.match(line.strip())
        if current_name is None:
            opening_name: str | None = None
            if open_match:
                opening_name = open_match.group("name").strip()
            elif (
                end_match
                and end_match.group("name").strip() != previous_name
                and not _contains_delimiter_line(outside)
                and _is_orphan_artifact_opener(
                    lines, index=index, name=end_match.group("name").strip()
                )
            ):
                # `=== END X ===` with no open block and no later `=== X ===` can only be the
                # opening delimiter the model transposed; its later END closes the block.
                opening_name = end_match.group("name").strip()
            if opening_name is not None:
                outside_text = "".join(outside)
                if outside_text.strip():
                    outside_spans.append(
                        OutsideTextSpan(
                            text=outside_text,
                            previous_artifact=previous_name,
                            next_artifact=opening_name,
                        )
                    )
                current_name = opening_name
                current_body = []
                outside = []
                saw_delimiter = True
                continue
            outside.append(line)
            continue
        if end_match and end_match.group("name").strip() == current_name:
            _record_block(blocks, current_name, current_body, result)
            previous_name = current_name
            current_name = None
            current_body = []
            saw_delimiter = True
            continue
        if (
            end_match
            and not _contains_delimiter_line(current_body)
            and _is_transposed_artifact_boundary(
                lines,
                index=index,
                current_name=current_name,
                next_name=end_match.group("name").strip(),
            )
        ):
            _record_block(blocks, current_name, current_body, result)
            previous_name = current_name
            current_name = end_match.group("name").strip()
            current_body = []
            saw_delimiter = True
            continue
        current_body.append(line)

    if current_name is not None:
        _record_block(blocks, current_name, current_body, result)
        previous_name = current_name
        saw_delimiter = True

    outside_text = "".join(outside)
    if outside_text.strip():
        outside_spans.append(
            OutsideTextSpan(
                text=outside_text,
                previous_artifact=previous_name,
                next_artifact=None,
            )
        )
    return (blocks if saw_delimiter else {}), tuple(outside_spans)


def _record_block(
    blocks: dict[str, str],
    name: str,
    body: list[str],
    result: CompletedRun,
) -> None:
    """Store a parsed artifact body, tolerating only a byte-identical repeat of the same name.

    A model that emits the same artifact twice with identical content has lost nothing: either copy
    is the artifact. Two blocks with the same name and different content are unresolvable, so the
    whole response is rejected.
    """
    content = "".join(body).strip()
    if name in blocks:
        if blocks[name] == content:
            return
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                f"  Duplicate artifact block with conflicting content: {name}\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )
    blocks[name] = content


def _contains_delimiter_line(chunk: list[str]) -> bool:
    """Whether accumulated lines already hold a delimiter, which makes any recovery ambiguous."""
    for line in chunk:
        stripped = line.strip()
        if _OPEN_BLOCK_LINE_RE.match(stripped) or _END_BLOCK_LINE_RE.match(stripped):
            return True
    return False


def _is_orphan_artifact_opener(lines: list[str], *, index: int, name: str) -> bool:
    """Whether an ``=== END X ===`` line with no block open is really X's opening delimiter.

    Recover only when no later ``=== X ===`` opening delimiter exists. With no block open, an END
    line cannot close anything, so the model dropped the opener; the block runs to the next
    delimiter that closes it. A later opener means the model instead restarted the artifact, which
    stays ambiguous and is rejected by the pairing check.
    """
    return not _has_later_opening_delimiter(lines, index=index, name=name)


def _is_transposed_artifact_boundary(
    lines: list[str],
    *,
    index: int,
    current_name: str,
    next_name: str,
) -> bool:
    """Recognize ``END next`` used in place of ``END current`` + ``open next``.

    Recover only when no later opening delimiter for the candidate next artifact exists. Under the
    artifact protocol an END delimiter never appears inside a body, so a mismatched END is a
    boundary. A later opener for the same name means the model restarted the artifact instead:
    that stays ambiguous, remains body text, and is rejected by the pairing check.
    """
    if next_name == current_name:
        return False
    return not _has_later_opening_delimiter(lines, index=index, name=next_name)


def _has_later_opening_delimiter(lines: list[str], *, index: int, name: str) -> bool:
    for later_line in lines[index + 1 :]:
        open_match = _OPEN_BLOCK_LINE_RE.match(later_line.strip())
        if open_match and open_match.group("name").strip() == name:
            return True
    return False


def _parse_write_call_blocks(text: str, target_dir: Path, blueprint_dir: Path) -> dict[str, str]:
    """Recover artifacts from Claude's non-executed ``Write`` call transcript.

    Claude occasionally returns tool-call XML despite being invoked without tools.  The calls are
    not executed, but their content is a complete artifact set.  Accept only paths within the
    active Blueprint plus the target's two plan artifacts; ignore every other simulated write.
    """
    target_root = target_dir.resolve()
    blueprint_root = blueprint_dir.resolve()
    blocks: dict[str, str] = {}
    cursor = 0
    saw_write = False
    for match in _WRITE_CALL_RE.finditer(text):
        if _outside_text_in_write_transcript(
            text[cursor : match.start()], after_artifacts=saw_write
        ):
            raise SpecificationError("Text appeared outside simulated Write artifacts.")
        try:
            path = Path(match.group("path").strip()).expanduser().resolve()
        except OSError:
            continue
        content = match.group("content").strip()
        if path.parent == target_root and path.name in {"MANIFEST.md", TOPOLOGY_BLOCK}:
            name = path.name
        elif path.is_relative_to(blueprint_root):
            name = path.relative_to(blueprint_root).as_posix()
        else:
            continue
        if name in blocks:
            raise SpecificationError(f"Duplicate simulated Write artifact: {name}")
        blocks[name] = content
        cursor = match.end()
        saw_write = True
    if saw_write and _outside_text_in_write_transcript(text[cursor:], after_artifacts=True):
        raise SpecificationError("Text appeared outside simulated Write artifacts.")
    return blocks


def _outside_text_in_write_transcript(text: str, *, after_artifacts: bool) -> bool:
    stripped = _FUNCTION_WRAPPER_RE.sub("", text)
    return _has_substantive_outside_text(stripped, after_artifacts=after_artifacts)


def _has_substantive_outside_text(text: str, *, after_artifacts: bool) -> bool:
    del after_artifacts
    return bool(text.strip())


#: Any artifact header, anchored or not. A parsed body must never contain one: when a
#: response is cut mid-artifact and resumes by restarting that artifact, ``_BLOCK_RE``
#: spans from the first header to the first ``=== END ===``, swallowing the truncated
#: attempt and the restart into one block that still pairs 1:1.
_HEADER_ANYWHERE_RE = re.compile(r"=== (?:END )?(?P<name>[^=\n]+?) ===")


def _artifact_delimiter_defects(text: str, blocks: dict[str, str]) -> tuple[str, ...]:
    """Report artifacts silently dropped by the parser, or whose body absorbed another.

    Two structural failures survive the parser and reach the Blueprint as damage.

    An artifact opened but never closed is dropped entirely: ``_BLOCK_RE`` pairs on a
    backreference, so an opener with no ``=== END ===`` matches nothing and the whole
    specification vanishes from the response without a word.

    An artifact header inside a parsed body means the response was cut mid-artifact and
    resumed by restarting it. ``_BLOCK_RE`` then spans from the first header to the first
    ``=== END ===``, swallowing the truncated attempt and its retry into one block that
    still pairs 1:1 and still counts as present.

    Deliberately narrow: missing leading and trailing delimiters have their own recovery
    paths, orphan END lines are already rejected by ``_reject_unpaired_end_delimiters``,
    and none of this measures size.
    """
    defects: list[str] = []

    opened = [match.group("name").strip() for match in _OPEN_BLOCK_LINE_RE.finditer(text)]
    for name in sorted({name for name in opened if name not in blocks}):
        defects.append(
            f"`{name}` opens but never closes, so it was dropped from the response entirely; "
            "every artifact that opens must close"
        )

    for name, body in blocks.items():
        embedded = sorted({
            match.group("name").strip() for match in _HEADER_ANYWHERE_RE.finditer(body)
        })
        if embedded:
            defects.append(
                f"`{name}` contains an artifact header inside its body "
                f"({', '.join(f'`{found}`' for found in embedded)}); the response was cut "
                "mid-artifact and its truncated attempt was absorbed into this block"
            )
    return tuple(defects)


def _artifact_delimiters_are_complete(text: str, blocks: dict[str, str]) -> bool:
    """Whether every parsed artifact appears in exactly one paired delimiter set."""
    opens = Counter(match.group("name").strip() for match in _OPEN_BLOCK_LINE_RE.finditer(text))
    ends = Counter(match.group("name").strip() for match in _END_BLOCK_LINE_RE.finditer(text))
    expected = Counter({name: 1 for name in blocks})
    return bool(expected) and opens == ends == expected


def _outside_text_is_waiver_eligible(
    spans: tuple[OutsideTextSpan, ...],
    *,
    text: str,
    blocks: dict[str, str],
) -> bool:
    """Whether bounded outside text may be submitted for semantic waiver."""
    if not spans or len(spans) > _OUTSIDE_SPAN_LIMIT:
        return False
    if not _artifact_delimiters_are_complete(text, blocks):
        return False
    # The plan artifact is last: `TOPOLOGY.md` for a declaration, `MANIFEST.md` for the reuse and
    # Spec Kit prompts, which still emit the plan directly.
    if tuple(blocks)[-1] not in {"MANIFEST.md", TOPOLOGY_BLOCK}:
        return False
    normalized = [span.normalized for span in spans]
    if sum(len(text) for text in normalized) > _OUTSIDE_TEXT_LIMIT:
        return False
    lowered = "\n".join(normalized).lower()
    return not any(marker.lower() in lowered for marker in _OUTSIDE_FORBIDDEN_MARKERS)


def _outside_text_waiver_evidence(
    spans: tuple[OutsideTextSpan, ...],
    *,
    artifact_count: int,
) -> str:
    """Render bounded, quoted evidence for the waiver judge."""
    total = sum(len(span.normalized) for span in spans)
    lines = [
        "FAILURE_CLASS: outside-artifact-text",
        "STRUCTURE_VALID: true",
        "PLAN_VALID: true",
        f"ARTIFACT_COUNT: {artifact_count}",
        f"OUTSIDE_TEXT_TOTAL_CHARACTERS: {total}",
        f"OUTSIDE_TEXT_SPANS: {len(spans)}",
    ]
    for index, span in enumerate(spans, start=1):
        lines += [
            "",
            f"SPAN {index}:",
            f"  LOCATION: {span.location}",
            f"  TEXT_JSON: {json.dumps(span.normalized, ensure_ascii=False)}",
        ]
    return "\n".join(lines)


def _read_if(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


# ── Replan state merge ─────────────────────────────────────────────────────────


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes()).hexdigest()


def _load_prior_plan_state(
    plan_path: Path,
) -> tuple[dict[str, AppliedSpecRecord], dict[str, tuple[str, str | None]]]:
    """Parse an existing MANIFEST.md and extract preservation state.

    Returns (applied_specs, {block_id → (state, finding)}). Returns empty dicts
    only when the manifest does not exist. Invalid existing Manifests abort before
    planning mutates any Target artifact. ``finding`` is non-None
    only for spike blocks that carry a non-empty finding text.
    """
    if not plan_path.is_file():
        return {}, {}
    from drydock.manifest import DrydockManifest

    prior = DrydockManifest.load(plan_path)
    block_states: dict[str, tuple[str, str | None]] = {}
    for block in prior.blocks:
        finding: str | None = None
        if block.block_type == "spike":
            raw = block.fields.get("finding")
            if isinstance(raw, tuple):
                raw = ", ".join(str(r) for r in raw)
            finding = str(raw).strip() if raw else None
            if not finding:
                finding = None
        block_states[block.block_id] = (block.state, finding)
    blueprint_dir = plan_path.parent / "blueprint"
    applied_specs: dict[str, AppliedSpecRecord] = {}
    for name, record in prior.applied_specs.items():
        build_digest = record.build_sha256
        spec_path = blueprint_dir / name
        if not build_digest and spec_path.is_file() and _file_sha256(spec_path) == record.sha256:
            build_digest = build_relevant_sha256(spec_path)
        applied_specs[name] = AppliedSpecRecord(
            path=record.path,
            sha256=record.sha256,
            commit=record.commit,
            applied_by=record.applied_by,
            applied_at=record.applied_at,
            build_sha256=build_digest,
        )
    return applied_specs, block_states


def _spec_is_dirty(
    spec_name: str,
    blueprint_dir: Path,
    applied_specs: dict[str, AppliedSpecRecord],
) -> bool:
    """Return True if the Blueprint file has changed since it was applied.

    A file with no applied_specs entry has never been applied — not dirty.
    A deleted file that was previously applied is dirty.
    """
    record = applied_specs.get(spec_name)
    if record is None:
        return False
    spec_path = blueprint_dir / spec_name
    if not spec_path.is_file():
        return True
    if _file_sha256(spec_path) == record.sha256:
        return False
    return not (record.build_sha256 and build_relevant_sha256(spec_path) == record.build_sha256)


def _merge_prior_state(
    plan_path: Path,
    blueprint_dir: Path,
    prior_applied_specs: dict[str, AppliedSpecRecord],
    prior_block_states: dict[str, tuple[str, str | None]],
) -> None:
    """Carry forward execution state from a prior MANIFEST.md into the freshly written one.

    Rules applied in order:
    - ``applied_specs`` is restored verbatim — the graph database is never regenerated.
    - A block whose prior state is ``pending`` receives no update.
    - A block whose implements: files are all build-relevantly clean carries its prior
      state and, for spikes, its prior ``finding``.
    - A block with any dirty implements: file is left at ``pending``; the LLM will re-apply it.
    """
    if prior_applied_specs:
        set_applied_specs(plan_path, prior_applied_specs)

    if not prior_block_states:
        return

    new_plan = parse_build_plan(plan_path)
    updates: dict[str, dict[str, str | None]] = {}

    for block in new_plan.blocks:
        prior_state, prior_finding = prior_block_states.get(block.block_id, ("pending", None))

        if prior_state == "pending":
            if block.block_type == "spike" and prior_finding:
                updates[block.block_id] = {"finding": prior_finding}
            continue

        implements = block.fields.get("implements", ())
        if isinstance(implements, str):
            implements = (implements,)

        governed = tuple(str(spec) for spec in implements if spec)
        dirty = not governed or any(
            spec not in prior_applied_specs
            or _spec_is_dirty(spec, blueprint_dir, prior_applied_specs)
            for spec in governed
        )

        block_updates: dict[str, str | None] = {}
        if not dirty:
            block_updates["state"] = prior_state
        if block.block_type == "spike" and prior_finding:
            block_updates["finding"] = prior_finding

        if block_updates:
            updates[block.block_id] = block_updates

    batch_set_block_fields(plan_path, updates)


def _collect_sources(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[Path]:
    return [
        entry.path
        for entry in discover_source_material(blueprint_dir, excluded_filenames=excluded_filenames)
        if entry.text is not None
    ]


def _expand_source_citations(
    cited: set[str], available: set[str]
) -> tuple[set[str], list[str], list[str]]:
    """Resolve cited source paths against the discovered material.

    Returns ``(resolved, missing, empty_patterns)``. A citation naming a single file resolves to
    itself and is reported in ``missing`` when no such file was imported. A citation carrying a
    ``*`` or ``?`` wildcard resolves to every source file it matches, and is reported in
    ``empty_patterns`` when it matches none — a pattern that matches nothing is an unsatisfiable
    evidence reference exactly as a missing filename is, but it needs its own wording so the
    Commander sees the pattern rather than a path fragment.
    """
    resolved: set[str] = set()
    missing: list[str] = []
    empty_patterns: list[str] = []
    for citation in cited:
        if any(character in citation for character in "*?"):
            matched = {path for path in available if fnmatch(path, citation)}
            if matched:
                resolved |= matched
            else:
                empty_patterns.append(citation)
        elif citation in available:
            resolved.add(citation)
        else:
            missing.append(citation)
    return resolved, sorted(missing), sorted(empty_patterns)


def _source_evidence_bundle(
    blueprint_dir: Path,
    analysis_text: str,
    *,
    excluded_filenames: frozenset[str],
) -> list[SourceMaterialFile] | None:
    """Return every readable source; Analyze guides interpretation, not visibility."""
    del analysis_text
    return [
        entry
        for entry in discover_source_material(blueprint_dir, excluded_filenames=excluded_filenames)
        if entry.text is not None
    ]


def _collect_changes(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[Path]:
    changes_dir = blueprint_dir / "changes"
    if not changes_dir.is_dir():
        return []
    return sorted(
        p for p in changes_dir.glob("*.md") if p.is_file() and p.name not in excluded_filenames
    )


def _is_typed_blueprint_filename(name: str) -> bool:
    if name in _IGNORE_TYPED_SPEC_FILES or "_compact." in name:
        return False
    if name in _ROOT_TYPED_SPEC_FILES:
        return True
    return bool(
        name.startswith("FEATURE-")
        or name.startswith("SCREEN-")
        or name.startswith("AC-")
        or "-AC.md" in name
        or "-AC-" in name
    )


def _default_file_type(name: str) -> str | None:
    if name in _ROOT_TYPED_SPEC_FILES:
        return name.removesuffix(".md")
    if name.startswith("FEATURE-"):
        return "FEATURE"
    if name.startswith("SCREEN-"):
        return "SCREEN"
    if name.startswith("AC-") or "-AC.md" in name or "-AC-" in name:
        return "AC"
    return None


def _default_object_name(name: str) -> str:
    if name == "ARCHITECTURE.md":
        return "Architecture"
    if name == "DATABASE.md":
        return "Database"
    if name == "UI-GENERAL.md":
        return "Shared UI"
    if name == "HOMEPAGE.md":
        return "Homepage"
    stem = name.removesuffix(".md")
    for prefix in ("FEATURE-", "SCREEN-", "AC-"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    stem = stem.replace("-AC", "").replace("AC-", "")
    return stem.replace("-", " ").strip() or stem


def _split_spec_structure(text: str) -> tuple[str | None, dict[str, str], str]:
    lines = text.splitlines()
    heading: str | None = None
    start = 0
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            heading = line.strip()
            start = idx + 1
            break
    if heading is None:
        return None, {}, text.strip()

    header_fields: dict[str, str] = {}
    body_start = len(lines)
    for idx in range(start, len(lines)):
        line = lines[idx]
        if line.startswith("## "):
            body_start = idx
            break
        match = _HEADER_ROW_RE.match(line.strip())
        if match:
            header_fields[match.group("field").strip()] = match.group("value").strip()
    body = "\n".join(lines[body_start:]).strip()
    return heading, header_fields, body


def _parse_existing_spec(path: Path) -> ExistingSpec:
    text = path.read_text(encoding="utf-8")
    heading, header_fields, body = _split_spec_structure(text)
    match = _TYPED_HEADING_RE.match(heading or "")
    file_type = (
        match.group("kind") if match else (_default_file_type(path.name) or "FEATURE")
    ).strip()
    object_name = match.group("name").strip() if match else _default_object_name(path.name)
    reusable = bool(
        match
        or header_fields
        or any(f"## {section}" in text for section in _TERMINAL_SECTIONS)
        or body.startswith("## ")
        or text.strip()
    )
    return ExistingSpec(
        path=path,
        filename=path.name,
        file_type=file_type,
        object_name=object_name,
        header_fields=header_fields,
        body=body,
        reusable=reusable,
    )


def _collect_existing_typed_specs(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[ExistingSpec]:
    specs: list[ExistingSpec] = []
    for path in sorted(blueprint_dir.glob("*.md")):
        if path.name in excluded_filenames or not _is_typed_blueprint_filename(path.name):
            continue
        specs.append(_parse_existing_spec(path))
    return specs


def _discard_unbuilt_specs(
    blueprint_dir: Path,
    applied_specs: dict[str, AppliedSpecRecord],
    *,
    excluded_filenames: frozenset[str] = frozenset(),
) -> list[str]:
    """Delete every typed Blueprint spec whose story has not been built.

    A spec is *built* when ``drydock build`` recorded it in the Manifest's
    ``applied_specs`` after a block completed without failing. Delivered code depends
    on those specs, so a replan preserves them; everything else is prior plan output
    that the replan regenerates. Scope matches ``_collect_existing_typed_specs``:
    top-level typed specs only, never ``sources/`` or ``changes/``.

    Returns the deleted filenames, sorted.
    """
    discarded: list[str] = []
    for path in sorted(blueprint_dir.glob("*.md")):
        if path.name in excluded_filenames or not _is_typed_blueprint_filename(path.name):
            continue
        if path.name in applied_specs:
            continue
        path.unlink()
        discarded.append(path.name)
    return discarded


def _is_speckit_source(blueprint_dir: Path) -> bool:
    """True when blueprint/sources/ holds a Spec Kit tree from ``import --format speckit``."""
    sources_dir = blueprint_dir / "sources"
    if (sources_dir / "memory" / "constitution.md").is_file():
        return True
    return any(sources_dir.glob("specs/*/spec.md"))


def _is_reuse_candidate(specs: list[ExistingSpec]) -> bool:
    if not specs:
        return False
    reusable = sum(1 for spec in specs if spec.reusable)
    if reusable == 0:
        return False
    if any(spec.filename in {"ARCHITECTURE.md", "DATABASE.md", "UI-GENERAL.md"} for spec in specs):
        return True
    return reusable >= 2


def _normalize_version(existing: str, today: str) -> str:
    today_compact = today.replace("-", "")
    match = re.fullmatch(r"(?P<date>\d{8})\s+V(?P<rev>\d+)", existing.strip())
    if match and match.group("date") == today_compact:
        return f"{today_compact} V{int(match.group('rev')) + 1}"
    return f"{today_compact} V1"


def _normalize_description(value: str | None, object_name: str) -> str:
    text = (value or "").strip()
    if not text:
        text = f"{object_name} specification."
    if text[-1:] not in ".!?":
        text += "."
    return text


def _default_phase(spec: ExistingSpec) -> str:
    if spec.filename in {"ARCHITECTURE.md", "DATABASE.md"}:
        return "1"
    if spec.filename == "UI-GENERAL.md" or spec.file_type == "FEATURE":
        return "2"
    if spec.file_type == "SCREEN":
        return "3"
    return spec.header_fields.get("Phase", "").strip()


def _render_terminal_section(heading: str, content: str | None) -> str:
    body = (content or "").strip() or "- None."
    return f"## {heading}\n\n{body.strip()}\n"


def _extract_terminal_section(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$.*?(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return None
    lines = match.group(0).splitlines()
    return "\n".join(lines[1:]).strip()


def _strip_terminal_sections(text: str) -> str:
    return _TERMINAL_SECTION_RE.sub("", text).strip()


def _strip_retired_questions(text: str) -> str:
    """Remove legacy Blueprint Questions without touching acceptance sections."""
    return re.sub(
        r"^## Questions\s*$.*?(?=^## |\Z)",
        "",
        text,
        flags=re.MULTILINE | re.DOTALL,
    ).strip()


def _render_normalized_spec(spec: ExistingSpec, *, today: str, ui_general_exists: bool) -> str:
    fields = dict(spec.header_fields)
    fields["Version"] = _normalize_version(fields.get("Version", ""), today)
    fields["Description"] = _normalize_description(fields.get("Description"), spec.object_name)
    depends_on = fields.get("Depends On", "").strip()
    if spec.file_type == "SCREEN" and ui_general_exists and not depends_on:
        depends_on = "UI-GENERAL.md"
    fields["Depends On"] = depends_on
    fields["Provides"] = fields.get("Provides", "").strip()
    phase = fields.get("Phase", "").strip() or _default_phase(spec)
    fields["Phase"] = phase

    header_lines = [
        f"# {spec.file_type}: {spec.object_name}",
        "",
        "| Field       | Value |",
        "|-------------|-------|",
        f"| Version     | {fields['Version']} |",
        f"| Description | {fields['Description']} |",
        f"| Depends On  | {fields['Depends On']} |",
        f"| Provides    | {fields['Provides']} |",
        f"| Phase       | {fields['Phase']} |",
    ]

    if spec.file_type == "SCREEN":
        for extra in ("Route", "Parent", "Main Menu", "Sub Menu", "Tab Order", "Consumes"):
            if extra in fields:
                header_lines.append(f"| {extra:<11} | {fields[extra]} |")

    body = _strip_terminal_sections(spec.body)
    sections = {
        heading: _extract_terminal_section(spec.body, heading) for heading in _TERMINAL_SECTIONS
    }
    rendered = "\n".join(header_lines).rstrip()
    if body:
        rendered += "\n\n" + body.strip()
    for heading in _TERMINAL_SECTIONS:
        rendered += "\n\n" + _render_terminal_section(heading, sections[heading]).rstrip()
    return rendered.rstrip() + "\n"


def _normalize_existing_specs(
    specs: list[ExistingSpec],
    *,
    today: str,
    built: frozenset[str] = frozenset(),
) -> tuple[list[Path], list[Path]]:
    """Normalize reusable spec headers, leaving built specs untouched.

    Normalizing stamps today's date into ``Version``, which changes the file's sha256.
    For a built spec that would make it dirty and send its story back to ``pending``, so
    a replan would rebuild delivered work on every run. Built means untouched.
    """
    changed: list[Path] = []
    normalized_paths: list[Path] = []
    ui_general_exists = any(spec.filename == "UI-GENERAL.md" for spec in specs)
    for spec in specs:
        if not spec.reusable:
            continue
        if spec.filename in built:
            normalized_paths.append(spec.path)
            continue
        normalized = _render_normalized_spec(spec, today=today, ui_general_exists=ui_general_exists)
        normalized_paths.append(spec.path)
        if spec.path.read_text(encoding="utf-8") != normalized:
            _write_text(spec.path, normalized)
            changed.append(spec.path)
    return normalized_paths, changed


def _collect_discoveries(target_dir: Path) -> list[Path]:
    qd = target_dir / "QuarterDeck" / "questionnaires"
    if not qd.is_dir():
        return []
    return sorted(qd.glob("discovery-*.json"))


def _has_answer(question: dict) -> bool:
    """Return whether a questionnaire answer contains a persisted decision."""
    answer = question.get("answer", "")
    if isinstance(answer, str):
        return bool(answer.strip())
    if isinstance(answer, list):
        return any(str(value).strip() for value in answer)
    return bool(answer)


def _required_plan_decisions(target_dir: Path) -> list[str]:
    """Return labels for unanswered discovery decisions that explicitly gate planning."""
    unanswered: list[str] = []
    for path in _collect_discoveries(target_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("archived", False):
            continue
        for question in data.get("questions", []):
            if not question.get("required_before_plan", False) or _has_answer(question):
                continue
            label = str(question.get("label") or question.get("id") or path.stem).strip()
            unanswered.append(f"{path.name}: {label}")
    return unanswered


def _answered_discovery(path: Path) -> dict | None:
    """Return the questionnaire with only its answered questions, or ``None`` if none are answered.

    A question is answered iff it carries non-empty ``answer`` text (written by QuarterDeck).
    Only answered fields feed ``plan create``; unanswered questions are excluded, and a
    questionnaire with no answers is skipped entirely.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    answered = [q for q in data.get("questions", []) if str(q.get("answer", "")).strip()]
    if not answered:
        return None
    return {**{k: v for k, v in data.items() if k != "questions"}, "questions": answered}


def ensure_feedback_file(target_dir: Path) -> str:
    """Create PLAN_COMPASS.md with the default prompt if absent; never overwrite.

    A persistent, human-owned standing directive re-injected into every ``drydock plan create``
    run. Returns the file's current text.
    """
    path = target_dir / _FEEDBACK_FILENAME
    if not path.is_file():
        header = prompt_header_for_file(_FEEDBACK_FILENAME)
        path.write_text(
            (
                header.default_text
                if header and header.default_text is not None
                else "# Plan Compass\n"
            ),
            encoding="utf-8",
            newline="\n",
        )
    return path.read_text(encoding="utf-8")


_PLAN_BLOCKERS_START = "<!-- DRYDOCK PLAN BLOCKERS START -->"
_PLAN_BLOCKERS_END = "<!-- DRYDOCK PLAN BLOCKERS END -->"
_PLAN_BLOCKERS_RE = re.compile(
    rf"\n*{re.escape(_PLAN_BLOCKERS_START)}.*?{re.escape(_PLAN_BLOCKERS_END)}\n*",
    re.DOTALL,
)


def _clear_plan_compass_blockers(target_dir: Path) -> None:
    """Remove resolved generated blockers while preserving Commander-authored content."""
    path = target_dir / _FEEDBACK_FILENAME
    if not path.is_file():
        return
    current = path.read_text(encoding="utf-8")
    updated = _PLAN_BLOCKERS_RE.sub("\n\n", current).rstrip() + "\n"
    if updated != current:
        path.write_text(updated, encoding="utf-8", newline="\n")


# ── Prompt assembly ────────────────────────────────────────────────────────────────


def _fenced(label: str, body: str, *, lang: str = "markdown") -> list[str]:
    return [f"## {label}", "", f"```{lang}", body.rstrip("\n"), "```", ""]


def _fenced_if(path: Path, label: str) -> list[str]:
    text = _read_if(path)
    return _fenced(label, text) if text else []


def _render_answered_discoveries(target_dir: Path) -> list[str]:
    answered = [(p, _answered_discovery(p)) for p in _collect_discoveries(target_dir)]
    answered = [(p, data) for p, data in answered if data is not None]
    if not answered:
        return []
    parts = ["## Answered questionnaires (consume these decisions)", ""]
    for path, data in answered:
        parts += ["### " + path.name, "", "```json", json.dumps(data, indent=2), "```", ""]
    return parts


def _render_contract(name: str) -> list[str]:
    try:
        contract_path = get_prompts_root() / name
    except Exception:
        return []
    if not contract_path.is_file():
        return []
    return _fenced(name, contract_path.read_text(encoding="utf-8"))


def _render_sources(blueprint_dir: Path) -> list[str]:
    parts = ["## Imported source files", ""]
    for path in _collect_sources(blueprint_dir):
        label = path.relative_to(blueprint_dir).as_posix()
        parts += [
            f"### {prompt_source_header(label, path)}",
            "",
            "```markdown",
            path.read_text(encoding="utf-8").rstrip(),
            "```",
            "",
        ]
    return parts


def _managed_doc_parts(
    *,
    filename: str,
    content: str,
    content_role: str,
    path: Path,
) -> list:
    return list(
        contextual_markdown_parts(
            filename,
            content,
            filename=filename,
            role=content_role,
            path=path,
        )
    )


def _assemble_prompt(
    body: str,
    target_dir: Path,
    blueprint_dir: Path,
    analysis_text: str,
    today: str,
    *,
    feedback_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
    typed_spec_paths: list[Path] | None = None,
) -> str:
    return _assemble_prompt_assembly(
        body,
        target_dir,
        blueprint_dir,
        analysis_text,
        today,
        feedback_text=feedback_text,
        input_tokens=input_tokens,
        excluded_filenames=load_excluded_filenames(target_dir),
        typed_spec_paths=typed_spec_paths,
    ).rendered_text


def _assemble_prompt_assembly(
    body: str,
    target_dir: Path,
    blueprint_dir: Path,
    analysis_text: str,
    today: str,
    *,
    feedback_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
    excluded_filenames: frozenset[str] = frozenset(),
    typed_spec_paths: list[Path] | None = None,
    source_evidence: list[SourceMaterialFile] | None = None,
    built_ledger: tuple[str, ...] = (),
) -> PromptAssembly:
    if input_tokens is None:
        input_tokens = load_prompt(PROMPT_NAME).input_tokens
    shape_match = _SHAPE_RE.search(analysis_text)
    quality_match = _QUALITY_RE.search(analysis_text)
    prompt_parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Planning job",
            [
                "## Planning job",
                "",
                f"- TARGET: {target_dir.name}",
                f"- BLUEPRINT_PATH: {blueprint_dir}",
                f"- DATE: {today}",
                f"- SYSTEM_SHAPE: {shape_match.group(1) if shape_match else 'unknown'}",
                f"- ANALYSIS_QUALITY: {quality_match.group(1) if quality_match else 'unknown'}",
                "",
            ],
            kind="job",
        ),
    ]
    if built_ledger:
        prompt_parts.append(
            lines_part(
                "Built work ledger",
                [
                    "## Built Work Ledger (read-only)",
                    "",
                    "Preserve these completed story identities and governed specification owners. "
                    "Semantic dependency changes remain allowed.",
                    "",
                    *[f"- {entry}" for entry in built_ledger],
                    "",
                ],
                kind="built-ledger",
            )
        )

    def compass_parts() -> list:
        path = target_dir / "COMPASS.md"
        text = _read_if(path)
        if not text:
            return []
        return _managed_doc_parts(
            filename="COMPASS.md",
            content=text,
            content_role="compass",
            path=path,
        )

    def technology_stack_parts() -> list:
        text = technology_stack.load_text(target_dir)
        if not text.strip():
            return []
        return _managed_doc_parts(
            filename=technology_stack.FILENAME,
            content=text.strip(),
            content_role="technology stack",
            path=technology_stack.path_for(target_dir),
        )

    def plan_compass_parts() -> list:
        if not (feedback_text and feedback_text.strip()):
            return []
        return _managed_doc_parts(
            filename=_FEEDBACK_FILENAME,
            content=feedback_text.strip(),
            content_role="plan feedback",
            path=target_dir / _FEEDBACK_FILENAME,
        )

    def analysis_parts() -> list:
        return list(
            contextual_markdown_parts(
                "ANALYSIS.md",
                analysis_text,
                filename="ANALYSIS.md",
                role="planning basis",
                path=target_dir / "ANALYSIS.md",
            )
        )

    def soundings_parts() -> list:
        path = target_dir / "SOUNDINGS.md"
        text = _read_if(path)
        if not text:
            return []
        return list(
            contextual_markdown_parts(
                "SOUNDINGS.md",
                text,
                filename="SOUNDINGS.md",
                role="acceptance context",
                path=path,
            )
        )

    def sea_trials_parts() -> list:
        path = target_dir / "SEA_TRIALS.md"
        text = _read_if(path)
        if not text:
            return []
        return list(
            contextual_markdown_parts(
                "SEA_TRIALS.md",
                text,
                filename="SEA_TRIALS.md",
                role="project acceptance contract",
                path=path,
            )
        )

    def questionnaire_parts() -> list:
        answered = [(p, _answered_discovery(p)) for p in _collect_discoveries(target_dir)]
        answered = [(p, data) for p, data in answered if data is not None]
        if not answered:
            return []
        parts_list = [
            lines_part(
                "Answered questionnaire header",
                ["## Answered questionnaires (consume these decisions)", ""],
                kind="section",
            )
        ]
        for path_obj, data in answered:
            parts_list.extend(
                contextual_fenced_parts(
                    path_obj.name,
                    json.dumps(data, indent=2),
                    filename=path_obj.name,
                    fence="json",
                    role="questionnaire",
                    path=path_obj,
                )
            )
        return parts_list

    def persistent_feedback_parts() -> list:
        rendered = render_commander_guidance(questionnaire_decisions(target_dir))
        if not rendered:
            return []
        return [lines_part("Persistent Plan feedback", rendered.splitlines(), kind="feedback")]

    def typed_spec_parts() -> list:
        parts_list = [
            lines_part(
                "Imported source file header", ["## Imported source files", ""], kind="section"
            )
        ]
        if typed_spec_paths is not None:
            typed_material = [
                SourceMaterialFile(
                    path_obj,
                    path_obj.relative_to(blueprint_dir).as_posix(),
                    "markdown",
                    "analyzed",
                    "selected",
                    path_obj.read_text(encoding="utf-8"),
                    "markdown",
                )
                for path_obj in typed_spec_paths
            ]
            source_material = [*typed_material, *(source_evidence or [])]
        elif source_evidence is not None:
            source_material = source_evidence
        else:
            source_material = [
                entry
                for entry in discover_source_material(
                    blueprint_dir, excluded_filenames=excluded_filenames
                )
                if entry.text is not None
            ]
        for entry in source_material:
            path_obj = entry.path
            label = entry.relative_path
            parts_list.extend(
                contextual_fenced_parts(
                    label,
                    entry.text.rstrip() if entry.text else "",
                    filename=label,
                    fence=entry.fence,
                    role="source file",
                    path=path_obj,
                )
            )
        change_files = []
        if typed_spec_paths is None:
            change_files = _collect_changes(blueprint_dir, excluded_filenames=excluded_filenames)
        if change_files:
            parts_list.append(
                lines_part(
                    "Change ticket header",
                    [
                        "## Change tickets",
                        "",
                        "These files amend existing Blueprint specs. Each ticket declares the",
                        "parent spec in its `Amends:` header. Stories generated for a change",
                        "ticket must inherit the full `depends:` chain of the parent spec's",
                        "stories.",
                        "",
                    ],
                    kind="section",
                )
            )
            for path_obj in change_files:
                label = f"changes/{path_obj.name}"
                parts_list.extend(
                    contextual_markdown_parts(
                        label,
                        path_obj.read_text(encoding="utf-8").rstrip(),
                        filename=label,
                        role="change ticket",
                        path=path_obj,
                    )
                )
        return parts_list

    def contract_parts(name: str) -> list:
        try:
            contract_path = get_prompts_root() / name
        except Exception:
            return []
        if not contract_path.is_file():
            return []
        return list(
            contextual_markdown_parts(
                name,
                contract_path.read_text(encoding="utf-8"),
                filename=name,
                role="contract",
                path=contract_path,
            )
        )

    renderers: dict[str, Callable[[], list]] = {
        "COMPASS.md": compass_parts,
        technology_stack.FILENAME: technology_stack_parts,
        "PLAN_COMPASS.md": plan_compass_parts,
        "ANALYSIS.md": analysis_parts,
        "SEA_TRIALS.md": sea_trials_parts,
        "SOUNDINGS.md": soundings_parts,
        "QUESTIONNAIRES": questionnaire_parts,
        "TYPED_SPEC": typed_spec_parts,
    }

    def make_contract_renderer(contract: str) -> Callable[[], list]:
        def render_contract() -> list:
            return contract_parts(contract)

        return render_contract

    for contract in _CONTRACT_FILES:
        renderers[contract] = make_contract_renderer(contract)
    for token in input_tokens:
        render = renderers.get(token)
        if render is None:
            continue
        prompt_parts.extend(render())
    prompt_parts.extend(persistent_feedback_parts())
    prompt_parts.append(section_heading_part("# Agent Task"))
    prompt_parts.append(part("Prompt body", body + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(prompt_parts))


# ── Integrity gate ──────────────────────────────────────────────────────────────────


def _has_cycle(edges: dict[str, set[str]]) -> bool:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in edges}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for nxt in edges.get(node, set()):
            if nxt not in color:
                continue
            if color[nxt] == GRAY or (color[nxt] == WHITE and visit(nxt)):
                return True
        color[node] = BLACK
        return False

    return any(color[node] == WHITE and visit(node) for node in edges)


_PROVIDES_RE = re.compile(r"^\|\s*Provides\s*\|(.*)\|\s*$", re.MULTILINE)
_ROUTE_ROW_RE = re.compile(r"^\|\s*(?:Provides|Consumes)\s*\|(.*)\|\s*$", re.MULTILINE)
_ROUTE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s,|`]*)")


def _spec_provides(text: str) -> str:
    """Return the trimmed `| Provides |` header value, or '' when absent/empty."""
    match = _PROVIDES_RE.search(text)
    return match.group(1).strip() if match else ""


def _uncovered_routes(text: str) -> tuple[str, ...]:
    """Routes in `Provides`/`Consumes` whose literal path never appears in the
    spec's Programmatic Acceptance section (test-driven route coverage)."""
    routes: set[tuple[str, str]] = set()
    for row in _ROUTE_ROW_RE.finditer(text):
        routes.update(_ROUTE_RE.findall(row.group(1)))
    if not routes:
        return ()
    acceptance = _extract_terminal_section(text, "Programmatic Acceptance") or ""
    missing: list[str] = []
    for verb, path in sorted(routes):
        key = path.split("{")[0].split("<")[0]
        if key in ("", "/"):
            continue
        if key not in acceptance:
            missing.append(f"{verb} {path}")
    return tuple(missing)


def _acceptance_status(text: str) -> tuple[int, bool]:
    """Inspect a spec's Programmatic Acceptance section.

    Returns (assertion_count, justified_none): the number of concrete acceptance
    checks — the canonical ``### {check-id}`` + fenced ``python`` blocks the build
    engine actually executes — and whether an empty section carries an inline
    justification (``- None. <reason>``) rather than a bare ``- None.``.
    """
    section = _extract_terminal_section(text, "Programmatic Acceptance")
    if section is None:
        return 0, False
    count = len(PYTHON_FENCE_RE.findall(section))
    justified_none = False
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        first, _, remainder = stripped[2:].strip().partition(" ")
        if first.rstrip(".,:").lower() == "none" and remainder.strip(" .,:"):
            justified_none = True
    return count, justified_none


# Markers that indicate an acceptance check executes a script rather than merely
# referring to it. Naming the test-suite file — asserting it is staged, or importing a
# helper beside it — is not execution.
_TEST_SUITE_INVOCATION_RE = re.compile(
    r"subprocess|sys\.executable|os\.system|check_output|check_call|Popen|runpy"
    r"|\bpython[\d.]*\b|\bpytest\b",
    re.IGNORECASE,
)

# Explicit opt-in that makes a full-suite story gate deliberate rather than accidental.
# Mirrors ``acceptance._full_suite``: ``Suite:`` declares a deliberate suite-bound run, and
# both ``full`` and ``scoped`` are accepted.
_SUITE_MARKER_RE = re.compile(r"^Suite:\s*(?:full|scoped)\s*$", re.MULTILINE | re.IGNORECASE)
_SCOPED_SUITE_RE = re.compile(r"^Suite:\s*scoped\s*$", re.MULTILINE | re.IGNORECASE)
_ZERO_SKIPPED_RE = re.compile(r"(?:assert[^\n]*|\bexpect[^\n]*)[\"']0 skipped[\"']", re.IGNORECASE)


def _invokes_unbounded_test_suite(acceptance: str) -> bool:
    """Report whether the acceptance section runs the whole test suite it never declared.

    Story acceptance is bounded by default so an ordinary check cannot accidentally invoke the
    whole test suite: it may stage the suite, or select a slice with ``--pattern`` / ``--number``.
    The terminal verification story gates on the real suite by declaring ``Suite: full`` in
    the assertion's heading block, which makes the full run deliberate and reviewable.
    """
    if "--pattern" in acceptance or "--number" in acceptance:
        return False
    lines = acceptance.splitlines()
    for index, line in enumerate(lines):
        if "spec_tests.py" not in line:
            continue
        # A call may span lines, so inspect a small window around the reference. A fence
        # delimiter carries a language tag ("```python") that is not an invocation.
        window = "\n".join(
            line
            for line in lines[max(0, index - 3) : index + 4]
            if not line.lstrip().startswith("```")
        )
        if not _TEST_SUITE_INVOCATION_RE.search(window):
            continue
        # The declaration sits in the heading block above the fenced code.
        if _SUITE_MARKER_RE.search("\n".join(lines[: index + 1])):
            continue
        return True
    return False


def _scoped_suite_claims_zero_skipped(acceptance: str) -> bool:
    """Reject a whole-suite completion condition on an intentionally bounded suite run."""
    return bool(_SCOPED_SUITE_RE.search(acceptance) and _ZERO_SKIPPED_RE.search(acceptance))


# A programmatic story should carry at least this many assertions before it stops
# drawing a test-driven-acceptance warning.
_MIN_ASSERTIONS_PER_STORY = 2


def _drives_external_suite(acceptance: str) -> bool:
    """True when a fenced acceptance check executes an imported program or test suite.

    A single check that shells out to the staged conformance harness — running
    ``spec_tests.py`` (or any suite) through subprocess/pytest — performs comprehensive,
    non-trivial verification in one block: it is the strongest test-driven acceptance a
    story can carry, not the weakest. Such a story is exempt from the several-fenced-checks
    minimum, which exists to stop a lone trivial in-process assert from standing in for real
    coverage. In-process assertions (a test client, direct function calls) do not match and
    stay subject to the minimum. Only fenced ``python`` code is inspected, so the word
    "python" in prose never trips the exemption.
    """
    code = "\n".join(match.group("code") for match in PYTHON_FENCE_RE.finditer(acceptance))
    return bool(_TEST_SUITE_INVOCATION_RE.search(code))


def _spec_is_conformant(text: str) -> bool:
    """True when a typed spec needs no conform pass.

    Conformant means the spec carries a typed ``# Kind: Name`` heading and its
    ``## Programmatic Acceptance`` is non-empty: at least one concrete assertion, or an
    explicit justified ``- None. <reason>``. A bare ``- None.`` is non-conformant.
    """
    heading, _, _ = _split_spec_structure(text)
    if heading is None or not _TYPED_HEADING_RE.match(heading):
        return False
    count, justified_none = _acceptance_status(text)
    return count >= 1 or justified_none


def _assemble_conform_prompt(
    body: str, *, spec: ExistingSpec, today: str, source_text: str
) -> PromptAssembly:
    """Assemble a single-spec conform prompt: job block + the spec verbatim + task body."""
    return PromptAssembly(
        parts=(
            system_preamble_part(),
            section_heading_part("# Input Context"),
            lines_part(
                "Conform job",
                [
                    "## Conform job",
                    "",
                    f"- SPEC_FILE: {spec.filename}",
                    f"- SPEC_TYPE: {spec.file_type}",
                    f"- OBJECT: {spec.object_name}",
                    f"- DATE: {today}",
                    "",
                ],
                kind="job",
            ),
            *contextual_markdown_parts(
                spec.filename,
                source_text,
                filename=spec.filename,
                role="imported spec to conform",
            ),
            section_heading_part("# Agent Task"),
            part("Prompt body", body + "\n\n", kind="prompt-body"),
        )
    )


def _extract_conformed_spec(text: str, filename: str) -> str | None:
    """Return the body of the ``=== <filename> ===`` artifact block, or None if absent."""
    for match in _BLOCK_RE.finditer(text):
        if match.group(1).strip() == filename:
            return match.group(2).strip()
    return None


def conform_specs(
    specs: list[ExistingSpec],
    blueprint_dir: Path,
    *,
    today: str,
    target: str = "",
    runner: RunnerFn | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
    on_text: TextCallback | None = None,
) -> tuple[list[Path], list[str]]:
    """LLM-conform each reusable spec whose Programmatic Acceptance is empty.

    Reads each non-conformant spec, keeps its substance, restructures it into the Drydock
    header plus the four terminal sections, and authors several Python-testable
    Programmatic Acceptance assertions (conforming any imported ``## Test`` prose). The
    module writes files; the model only emits text. A spec that returns empty, without its
    artifact block, or still non-conformant is left unchanged and reported as a warning.
    Returns ``(written_paths, warnings)``. Tests inject a fake runner.
    """
    run = runner if runner is not None else run_prompt
    pending = [
        spec
        for spec in specs
        if spec.reusable and not _spec_is_conformant(spec.path.read_text(encoding="utf-8"))
    ]
    if not pending:
        return [], []
    if on_text is not None:
        on_text(
            f"[plan] conforming {len(pending)} spec(s) with empty Programmatic Acceptance "
            "into Drydock format with authored assertions\n"
        )
    prompt = load_prompt(_CONFORM_PROMPT_NAME)
    written: list[Path] = []
    warnings: list[str] = []
    for spec in pending:
        source_text = spec.path.read_text(encoding="utf-8")
        prompt_assembly = _assemble_conform_prompt(
            prompt.body, spec=spec, today=today, source_text=source_text
        )
        result = run(
            prompt_assembly.rendered_text,
            blueprint_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="plan conform",
            parameters={"spec": spec.filename, "prompt": _CONFORM_PROMPT_NAME},
            log_dir=log_dir,
            target=target,
            on_text=on_text,
            prompt_assembly=prompt_assembly,
        )
        if not result.ok or not result.text.strip():
            warnings.append(
                f"conform: {spec.filename} — LLM produced no output; spec left unchanged"
            )
            continue
        conformed = _extract_conformed_spec(result.text, spec.filename)
        if conformed is None:
            warnings.append(
                f"conform: {spec.filename} — response had no `{spec.filename}` artifact block; "
                "spec left unchanged"
            )
            continue
        if not _spec_is_conformant(conformed):
            warnings.append(
                f"conform: {spec.filename} — conformed spec still lacks Programmatic Acceptance "
                "assertions; spec left unchanged"
            )
            continue
        _write_text(spec.path, conformed if conformed.endswith("\n") else conformed + "\n")
        written.append(spec.path)
    return written, warnings


def _integrity_check(
    plan: BuildPlan,
    blueprint_dir: Path,
    *,
    available_specs: frozenset[str] = frozenset(),
    emitted_files: dict[str, str] | None = None,
) -> list[str]:
    """Fatal issues raise SpecificationError; non-fatal issues return as warnings."""
    ids = {block.block_id for block in plan.blocks}
    emitted_files = emitted_files or {}
    fatal: list[str] = []
    warnings: list[str] = []

    edges: dict[str, set[str]] = {}
    position = {block.block_id: index for index, block in enumerate(plan.blocks)}
    for block in plan.blocks:
        edges[block.block_id] = set(block.depends)
        for dep in block.depends:
            if dep not in ids:
                fatal.append(f"{block.block_id}: depends on unknown id {dep!r}")
            elif position.get(dep, -1) > position[block.block_id]:
                # Consistent order: a dependency must be emitted above its dependent.
                warnings.append(
                    f"{block.block_id}: depends on {dep!r}, which is emitted later; "
                    "blocks should appear in dependency order"
                )

    if _has_cycle(edges):
        fatal.append("dependency graph contains a cycle")

    # Grouping integrity. An unresolvable `parent:` orphans the block from every
    # feature group, so the work graph silently loses its grouping; a parent of the
    # wrong block type breaks the frontier and closure rules that read the hierarchy.
    by_id = plan.by_id()
    for block in plan.blocks:
        if not block.parent:
            continue
        parent = by_id.get(block.parent)
        if parent is None:
            fatal.append(f"{block.block_id}: parent names unknown id {block.parent!r}")
            continue
        allowed = _PARENT_BLOCK_TYPES.get(block.block_type)
        if allowed is not None and parent.block_type not in allowed:
            fatal.append(
                f"{block.block_id}: parent {block.parent!r} is a {parent.block_type}; "
                f"a {block.block_type} must be parented to a {' or '.join(sorted(allowed))}"
            )

    def spec_text(name: str) -> str | None:
        if name in emitted_files:
            return emitted_files[name]
        path = blueprint_dir / name
        return path.read_text(encoding="utf-8") if path.is_file() else None

    executable_with_empty_depends = False
    spec_owners: dict[str, list[str]] = {}
    for block in plan.blocks:
        if block.block_type in ("story", "spike") and not block.depends:
            executable_with_empty_depends = True
        if block.block_type != "story":
            continue
        implements = block.fields.get("implements", ())
        targets = implements if isinstance(implements, tuple) else (implements,)
        targets = tuple(name for name in targets if name)
        if len(targets) != 1:
            fatal.append(
                f"{block.block_id}: story must implement exactly one Blueprint specification; "
                f"found {len(targets)}"
            )
        for name in targets:
            spec_owners.setdefault(str(name), []).append(block.block_id)
        for name in targets:
            if name and name not in available_specs and not (blueprint_dir / name).is_file():
                fatal.append(f"{block.block_id}: implements missing spec file {name!r}")
            text = spec_text(str(name)) if name else None
        # Test-driven acceptance is Blueprint-first. A story whose implemented
        # specs declare a programmatic surface
        # must carry several concrete Python assertions unless an inline-justified
        # `- None.` explains the absence.
        surface = False
        justified = False
        drives_suite = False
        assertions = 0
        for name in targets:
            text = spec_text(name) if name else None
            if text is None:
                continue
            if _spec_provides(text):
                surface = True
            count, none_reason = _acceptance_status(text)
            assertions += count
            justified = justified or none_reason
            section = _extract_terminal_section(text, "Programmatic Acceptance") or ""
            if _drives_external_suite(section):
                drives_suite = True
            # Test-driven route coverage. A SCREEN's assertions must literally
            # call every route it provides or consumes — hard gate. A FEATURE
            # may exercise its routes through typed helpers, so an unnamed
            # route is a warning, not fatal.
            uncovered = _uncovered_routes(text)
            if uncovered:
                detail = ", ".join(uncovered)
                if name.startswith("SCREEN-"):
                    fatal.append(
                        f"{block.block_id}: {name}: Programmatic Acceptance never calls "
                        f"route(s) {detail} — a SCREEN's assertions must call every route "
                        "it provides or consumes"
                    )
                elif name.startswith("FEATURE-"):
                    warnings.append(
                        f"{block.block_id}: {name}: Programmatic Acceptance does not name "
                        f"route(s) {detail}; exercise each provided route, naming its "
                        "literal path"
                    )
        if (
            surface
            and not justified
            and not drives_suite
            and assertions < _MIN_ASSERTIONS_PER_STORY
        ):
            fatal.append(
                f"{block.block_id}: {assertions} Programmatic Acceptance assertion(s) across "
                "its implemented spec(s), which declare a programmatic surface; author several "
                "concrete Python assertions (test-driven acceptance), drive the imported test "
                "suite, or justify `- None.` inline"
            )
        for name in targets:
            text = spec_text(name) if name else None
            # Scope to the acceptance section. A spec may name the test suite in prose
            # (a Test Strategy bullet) without any story check ever executing it.
            acceptance = (
                _extract_terminal_section(text, "Programmatic Acceptance") if text else None
            )
            if acceptance and _invokes_unbounded_test_suite(acceptance):
                fatal.append(
                    f"{block.block_id}: Programmatic Acceptance runs the whole test suite "
                    "without declaring Suite: full; a non-terminal story must bound its run "
                    "with the runner's --pattern/--number selector, or gate the full run on "
                    "the terminal Suite: full story and SEA_TRIALS.md final measurement"
                )
            if acceptance and _scoped_suite_claims_zero_skipped(acceptance):
                fatal.append(
                    f"{block.block_id}: Programmatic Acceptance declares Suite: scoped but "
                    "asserts zero skipped tests; skipped tests are expected outside the story's "
                    "selected slice, so only the terminal Suite: full story may require 0 skipped"
                )

    for name, owners in sorted(spec_owners.items()):
        if len(owners) > 1:
            fatal.append(
                f"{name}: implemented by multiple stories: {', '.join(owners)}; "
                "each governed specification has exactly one owning story"
            )

    sea_path = blueprint_dir.parent / "SEA_TRIALS.md"
    sea_text = sea_path.read_text(encoding="utf-8") if sea_path.is_file() else ""
    if re.search(r"^##\s+st-", sea_text, re.MULTILINE):
        sea_document = parse_sea_trials_text(sea_text)
        known = {trial.criterion_id for trial in sea_document.trials}
        covered: set[str] = set()
        for block in plan.blocks:
            raw_accepts = block.fields.get("accepts", ())
            refs = raw_accepts if isinstance(raw_accepts, tuple) else (raw_accepts,)
            for ref in refs:
                if ref not in known:
                    fatal.append(f"{block.block_id}: accepts unknown Sea Trial {ref!r}")
                else:
                    covered.add(ref)
        for name, text in emitted_files.items():
            if not name.endswith(".md"):
                continue
            for match in re.finditer(r"^Sea Trials:\s*(.+?)\s*$", text, re.M | re.I):
                for ref in (part.strip().lower() for part in match.group(1).split(",")):
                    if ref not in known:
                        fatal.append(f"{name}: proof references unknown Sea Trial {ref!r}")
                    else:
                        covered.add(ref)
        missing = sorted(
            trial.criterion_id
            for trial in sea_document.trials
            if trial.required
            and trial.trial_type in {"technical", "behavioral"}
            and trial.criterion_id not in covered
        )
        if missing:
            fatal.append(
                "required Sea Trials lack implementation/proof coverage: " + ", ".join(missing)
            )

    # Story count is not capped; see the module note. Reject an under-decomposed plan:
    # every analyzed story is delivered by some story. Stage 1 applied this same rule to
    # the declaration, so reaching a defect here means the plan arrived by a path that has
    # no topology to check.
    from drydock.plan_topology import coverage_defects, story_covers

    coverage_fatal, coverage_warnings = coverage_defects(
        [
            (block.block_id, story_covers(block))
            for block in plan.blocks
            if block.block_type == "story"
        ],
        analyzed_story_ids(blueprint_dir),
    )
    fatal.extend(coverage_fatal)
    warnings.extend(coverage_warnings)

    # Zone C — deterministic verification of the declared graph. The model authors judgment;
    # Python proves the result is internally consistent and refuses it otherwise. Active only
    # for the story taxonomy (`type:`); a legacy-taxonomy Manifest projects to an empty set.
    from drydock.plan_graph import verify_graph
    from drydock.plan_topology import stories_from_manifest

    declared = stories_from_manifest(plan.blocks)
    if declared:
        for defect in verify_graph(declared):
            (fatal if defect.fatal else warnings).append(defect.rendered())

    # Initial runnable frontier — a soft warning. At least one executable block must
    # start with an empty `depends:` or the build has nothing it can run first.
    has_executable = any(b.block_type in ("story", "spike") for b in plan.blocks)
    if has_executable and not executable_with_empty_depends:
        warnings.append(
            "no story or spike has an empty depends: — the initial runnable frontier is empty "
            "and the build cannot start"
        )

    if fatal:
        raise SpecificationError("Plan integrity check failed:\n  " + "\n  ".join(fatal))
    return warnings


def _parse_plan_text(text: str) -> BuildPlan:
    """Parse Manifest text before target files are mutated."""
    from drydock.manifest import DrydockManifest

    return DrydockManifest.parse(text, source="MANIFEST.md")


#: Marks a planning warning about an acceptance criterion a static analyzer believes cannot
#: pass as authored. The console promotes these above ordinary graph advisories. Nothing is
#: removed: the analyzers are authoring guidance, not a gate.
ACCEPTANCE_REMOVED_MARKER = "unsatisfiable acceptance criterion"


def _strip_unsatisfiable_acceptance(
    blocks: dict[str, str], *, sources_dir: Path | None = None
) -> tuple[str, ...]:
    """Report unsatisfiable acceptance criteria in the emitted specs, without editing them.

    This used to delete the criterion. Deletion was enforcement built on a static prediction,
    and the prediction has a false-positive rate: the analyzers behind it are an unbounded
    blacklist grown one observed failure at a time, and two of them were retracted after they
    began failing fixtures that had passed for weeks. Silently removing a legitimate criterion
    costs more than carrying a doubtful one, because a criterion that really cannot pass now
    settles as UNVERIFIED at run time and is never charged against the build.

    ``sources_dir`` points at the staged assets the emitted criteria will run against, so a
    criterion that invokes one can be checked against that asset's own declared preconditions.
    """
    from drydock.acceptance import flag_unsatisfiable_acceptance

    findings: list[str] = []
    for name in sorted(blocks):
        if name in _RESERVED_BLOCKS:
            continue
        findings.extend(
            f"{name} [{flagged.check_id}]: {ACCEPTANCE_REMOVED_MARKER} — {flagged.reason}"
            for flagged in flag_unsatisfiable_acceptance(
                blocks[name], source=name, sources_dir=sources_dir
            )
        )
    return tuple(findings)


#: The plan-create output contract, measured deterministically by :mod:`drydock.plan_shape`.
#: Shape conformance is a checker, not an instruction: the prompt no longer asks the model to
#: verify its own delimiters and block completeness, because that verification is free and
#: reliable in code. Delimiter pairing is not re-checked here — the strict parser above already
#: owns pairing together with its documented recoveries.
#: Artifact *ordering* is not part of this contract: the strict parser preserves response order
#: and the waiver path already requires a terminal ``MANIFEST.md``, so re-asserting it here would
#: reject a complete plan over a fact nothing downstream depends on.
PLAN_OUTPUT_CONTRACT = OutputContract(
    required=("MANIFEST.md",),
    require_typed_headings=False,
)

#: The same contract for the declaration path. ``plan create`` asks for a topology declaration and
#: Drydock serializes the Manifest from it; the reuse and Spec Kit prompts still emit ``MANIFEST.md``
#: directly and keep :data:`PLAN_OUTPUT_CONTRACT`.
PLAN_TOPOLOGY_CONTRACT = OutputContract(
    required=(TOPOLOGY_BLOCK,),
    require_typed_headings=False,
)

#: The advisory half of the same contract. A missing typed heading is a real defect but a
#: repairable one — ``conform_specs`` is the existing second model pass for exactly this — so it
#: is reported rather than used to refuse a complete plan.
#: ``leading`` is advisory on purpose. A complete response whose declaration arrives last is
#: still a valid plan, so refusing it would trade a working run for tidiness. Ordering only
#: pays off on a *short* response, where a leading declaration is what makes the run resumable
#: — so report the deviation and let the run stand.
PLAN_SHAPE_ADVISORY = OutputContract(
    leading=TOPOLOGY_BLOCK,
    untyped=frozenset({"MANIFEST.md", "TOPOLOGY.md", "README.md", "METADATA.md"}),
)


def check_plan_shape(
    blocks: dict[str, str],
    contract: OutputContract = PLAN_OUTPUT_CONTRACT,
) -> tuple[ShapeDefect, ...]:
    """Measure Success Mode artifacts against the fatal half of the declared output contract."""
    return check_contract("", blocks, contract)


def advisory_plan_shape(blocks: dict[str, str]) -> tuple[ShapeDefect, ...]:
    """Measure the same artifacts against the repairable half of the contract."""
    return tuple(
        defect
        for defect in check_contract("", blocks, PLAN_SHAPE_ADVISORY)
        if defect.code in {"untyped-heading", "leading-artifact"}
    )


def _compute_schedule(
    declared: Sequence[PlannedStory],
    *,
    blueprint_dir: Path,
    emitted_files: dict[str, str],
) -> PlanComputation:
    """Verify a declared graph and compute everything positional about it.

    Sizing uses the deduplicated files assembled for a build block: Compass, governed
    specifications, context, stack, rules, and instructions. The preferred threshold guides
    grouping; the configured error threshold is an absolute gate.
    """
    from drydock.config import get_prompt_error_tokens
    from drydock.plan_graph import compute_plan
    from drydock.plan_stack import block_target_tokens, resolve_stack_set

    resolved = resolve_stack_set(name for story in declared for name in story.stack)

    def specification_tokens(name: str) -> int:
        text = emitted_files.get(name)
        if text is None:
            path = blueprint_dir / name
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return estimate_tokens(len(text.encode("utf-8")))

    compass_path = blueprint_dir.parent / "COMPASS.md"
    compass_tokens = estimate_tokens(compass_path.stat().st_size) if compass_path.is_file() else 0

    def named_file_tokens(name: str, key: str) -> int:
        names = [name]
        if name.endswith("_compact.md"):
            names.append(name.replace("_compact.md", ".md"))
        candidates = [
            root / candidate
            for candidate in names
            for root in (blueprint_dir, blueprint_dir.parent)
        ]
        if key == "rules":
            try:
                from drydock.paths import get_rigging_root

                rigging = get_rigging_root()
                candidates[0:0] = [rigging / candidate for candidate in names]
            except Exception:
                pass
        emitted = emitted_files.get(name)
        if emitted is not None:
            return estimate_tokens(len(emitted.encode()))
        for path in candidates:
            try:
                return estimate_tokens(path.stat().st_size)
            except OSError:
                continue
        return 0

    def field_names(story: PlannedStory, key: str) -> tuple[str, ...]:
        value = str(story.fields.get(key, ""))
        return tuple(part.strip() for part in value.split(",") if part.strip())

    def block_size_fn(stories: Sequence[PlannedStory]) -> int:
        total = compass_tokens
        seen_files: set[str] = set()
        stack_modes: dict[str, str] = {}
        for story in stories:
            if story.implements not in seen_files:
                seen_files.add(story.implements)
                total += specification_tokens(story.implements)
            for key in ("context", "rules"):
                names = list(field_names(story, key))
                if key == "context" and story.implements.startswith(("FEATURE-", "SCREEN-")):
                    for managed in ("ARCHITECTURE.md", "DATABASE.md"):
                        if managed in emitted_files or (blueprint_dir / managed).is_file():
                            names.append(managed.replace(".md", "_compact.md"))
                for name in names:
                    canonical = name.replace("_compact.md", ".md")
                    if canonical not in seen_files:
                        seen_files.add(canonical)
                        total += named_file_tokens(name, key)
            total += estimate_tokens(len(str(story.fields.get("instructions", "")).encode()))
            for name in story.stack:
                mode = story.stack_mode or "builder"
                if stack_modes.get(name) == "builder" or mode == "builder":
                    stack_modes[name] = "builder"
                else:
                    stack_modes[name] = "consumer"
        total += sum(
            resolved[name].tokens_for(mode)
            for name, mode in stack_modes.items()
            if name in resolved
        )
        return total

    return compute_plan(
        declared,
        target_tokens=block_target_tokens(),
        limit_tokens=get_prompt_error_tokens(),
        size_fn=lambda story: block_size_fn((story,)),
        block_size_fn=block_size_fn,
    )


def _manifest_from_declaration(
    declaration: str,
    *,
    project: str,
    blueprint_dir: Path,
    emitted_files: dict[str, str],
    result: CompletedRun,
) -> tuple[str, tuple[str, ...]]:
    """Serialize ``MANIFEST.md`` from the model's topology declaration.

    A declaration has nowhere to express a position, so the model cannot assert an order it has
    not computed even by accident. Drydock verifies the declared graph and refuses an inconsistent
    one with a precise defect rather than letting it reach disk.
    """
    from drydock.plan_topology import parse_topology, parse_topology_preamble, render_manifest

    declared, defects = parse_topology(declaration)
    if not declared:
        raise SpecificationError(
            _with_execution_evidence(
                f"Plan generation failed: {TOPOLOGY_BLOCK} declared no stories.\n  "
                + "\n  ".join(defect.rendered() for defect in defects)
                + "\n  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    computation = _compute_schedule(
        declared, blueprint_dir=blueprint_dir, emitted_files=emitted_files
    )
    if computation.fatal:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: the declared work graph is inconsistent.\n  "
                + "\n  ".join(defect.rendered() for defect in computation.fatal)
                + "\n  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    manifest_text = render_manifest(
        project,
        computation.stories,
        computation.blocks,
        updated=datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        preamble=parse_topology_preamble(declaration),
    )
    warnings = tuple(defect.rendered() for defect in defects) + tuple(
        defect.rendered() for defect in computation.warnings
    )
    return manifest_text, warnings


def _validate_plan_output(
    blocks: dict[str, str],
    blueprint_dir: Path,
    result: CompletedRun,
    source_text: str | None = None,
    *,
    project: str = "",
) -> tuple[BuildPlan, tuple[str, ...]]:
    """Validate one LLM response mode and return the parsed plan for success mode.

    ``source_text`` is the delimited response the blocks were parsed from, when there
    is one.  It is ``None`` for blocks recovered from write-tool-call syntax, which
    carry no ``=== NAME ===`` delimiters and therefore cannot be pairing-checked.

    Two success carriers are accepted, branched on explicitly: a ``TOPOLOGY.md`` declaration,
    which Drydock verifies, orders, blocks, and serializes into ``MANIFEST.md`` here, and a
    ``MANIFEST.md`` the model wrote directly, which the reuse and Spec Kit prompts still emit.
    """
    # Branch on which plan artifact the response carries, before anything else reads it.
    carrier = TOPOLOGY_BLOCK if TOPOLOGY_BLOCK in blocks else "MANIFEST.md"
    mode_blocks = {carrier, "PLAN_CREATE_BLOCKED.txt", "PLAN_CREATE_ERROR.txt"} & set(blocks)

    if "PLAN_CREATE_BLOCKED.txt" in blocks:
        if set(blocks) != {"PLAN_CREATE_BLOCKED.txt"}:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    "  BLOCKED MODE must emit only PLAN_CREATE_BLOCKED.txt.\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )
        raise SpecificationError(
            "Planning cannot proceed. No Blueprint or Manifest artifacts were written.\n  "
            + blocks["PLAN_CREATE_BLOCKED.txt"].strip()
        )

    if "PLAN_CREATE_ERROR.txt" in blocks:
        if set(blocks) != {"PLAN_CREATE_ERROR.txt"}:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    "  ERROR MODE must emit only PLAN_CREATE_ERROR.txt.\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )
        raise SpecificationError(
            "Plan generation failed: LLM reported that it could not produce a complete plan.\n"
            "  No Blueprint or Manifest artifacts were written.\n  "
            + blocks["PLAN_CREATE_ERROR.txt"].strip()
        )

    if not mode_blocks:
        raise SpecificationError(
            _with_execution_evidence(
                f"Plan generation failed: LLM output missing === {TOPOLOGY_BLOCK} === block.\n"
                "  The response must contain only delimited artifact blocks.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    if mode_blocks != {carrier}:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output mixed response modes.\n"
                "  SUCCESS MODE must not include PLAN_CREATE_BLOCKED.txt or PLAN_CREATE_ERROR.txt.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    # Success Mode is confirmed. Everything that opens must close: a header spliced onto the
    # tail of a truncated line parses as a valid block, so only the line-anchored delimiter
    # counts prove the artifact set is undamaged. Structural, never a size judgement.
    if source_text is not None:
        pairing_defects = _artifact_delimiter_defects(source_text, blocks)
        if pairing_defects:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output has damaged artifact delimiters.\n  "
                    + "\n  ".join(pairing_defects)
                    + "\n  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )

    # Measure the artifact set against the declared output contract before anything is parsed
    # or written — an absolute, deterministic guardrail in place of the prompt's former
    # self-verification tail.
    shape_defects = check_plan_shape(
        blocks,
        PLAN_TOPOLOGY_CONTRACT if carrier == TOPOLOGY_BLOCK else PLAN_OUTPUT_CONTRACT,
    )
    if shape_defects:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output did not satisfy the declared output "
                "contract.\n  "
                + render_defects(shape_defects)
                + "\n  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    declaration_warnings: tuple[str, ...] = ()
    if carrier == TOPOLOGY_BLOCK:
        # Zone C. The model declared what each story is, requires, and provides; Drydock verifies
        # the graph, orders it, packs it into blocks, and serializes the Manifest. The declaration
        # is transient and never reaches disk.
        blocks["MANIFEST.md"], declaration_warnings = _manifest_from_declaration(
            blocks.pop(TOPOLOGY_BLOCK),
            project=project,
            blueprint_dir=blueprint_dir,
            emitted_files={
                name: text for name, text in blocks.items() if name not in _RESERVED_BLOCKS
            },
            result=result,
        )

    # Guarantee unique block ids before validation: the model may reuse one slug
    # for a feature and its sole same-named story. Disambiguate in place so the
    # unique-id manifest is what gets validated and written to the target.
    blocks["MANIFEST.md"] = disambiguate_manifest_ids(blocks["MANIFEST.md"])
    plan = _parse_plan_text(blocks["MANIFEST.md"])

    emitted_specs = frozenset(name for name in blocks if name not in _RESERVED_BLOCKS)
    implemented_specs = {
        str(name)
        for block in plan.blocks
        if block.block_type == "story"
        for name in (
            block.fields.get("implements", ())
            if isinstance(block.fields.get("implements", ()), tuple)
            else (block.fields.get("implements", ""),)
        )
        if name
    }
    for name in emitted_specs:
        if (
            name in implemented_specs
            and name.lower().endswith(".md")
            and name not in _NON_BLUEPRINT_ARTIFACTS
        ):
            blocks[name] = _strip_retired_questions(blocks[name]) + "\n"
    # A criterion that no implementation can satisfy is not a specification, it is a build the
    # graph guarantees will fail. Strip it here, before the Manifest is validated or written,
    # so the emitted plan is one that can actually be built. Removals are reported, and the
    # assertion gate below still measures what each story has left.
    dropped_acceptance = _strip_unsatisfiable_acceptance(
        blocks, sources_dir=blueprint_dir / "sources"
    )
    forbidden_artifacts = sorted(name for name in emitted_specs if name in _NON_BLUEPRINT_ARTIFACTS)
    if forbidden_artifacts:
        names = ", ".join(forbidden_artifacts)
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output emitted non-Blueprint artifacts.\n"
                f"  Forbidden artifact(s): {names}\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )
    missing_from_response: list[str] = []
    for block in plan.blocks:
        if block.block_type != "story":
            continue
        implements = block.fields.get("implements", ())
        targets = implements if isinstance(implements, tuple) else (implements,)
        for name in targets:
            if name in _NON_BLUEPRINT_ARTIFACTS:
                missing_from_response.append(
                    f"{block.block_id}: implements non-Blueprint file {name!r}"
                )
                continue
            if name and name not in emitted_specs and not (blueprint_dir / name).is_file():
                missing_from_response.append(
                    f"{block.block_id}: implements missing spec file {name!r}"
                )

    if missing_from_response:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output did not satisfy the artifact contract.\n  "
                + "\n  ".join(missing_from_response)
                + "\n  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    emitted_files = {name: text for name, text in blocks.items() if name not in _RESERVED_BLOCKS}
    declared_checks = tuple(
        check
        for name, text in emitted_files.items()
        if name.lower().endswith(".md")
        for check in parse_programmatic_acceptance_text(text, source=name)
    )
    # Tooling declaration is a recommendation, never a gate. The gate it replaces asked whether
    # the model had written a ``Requires:`` line beside a check, not whether the tool was
    # installed — so a check that works perfectly on a machine where the tool has been present
    # for a decade failed planning over a missing declaration. Whether a tool is *absent* is a
    # separate question, asked by ``project_plan_requirement_decisions`` against the real
    # environment, and it is the only one that can legitimately stop anything.
    usage_recommendations = recommend_external_declarations(declared_checks)
    # Removals lead the warning list: they changed the artifact the author is about to read,
    # so they must not be buried under advisory graph notes.
    warnings = (
        dropped_acceptance
        + declaration_warnings
        + usage_recommendations
        + tuple(defect.rendered() for defect in advisory_plan_shape(emitted_files))
    ) + tuple(
        _integrity_check(
            plan,
            blueprint_dir,
            available_specs=emitted_specs,
            emitted_files=emitted_files,
        )
    )
    return plan, warnings


# ── QuarterDeck projection ──────────────────────────────────────────────────────────


def _write_quarterdeck(plan: BuildPlan, target_dir: Path) -> Path:
    quarterdeck = target_dir / "QuarterDeck"
    quarterdeck.mkdir(parents=True, exist_ok=True)
    ensure_standard_artifacts(plan.project, target_dir)
    # The QuarterDeck runtime is served from the package; only console state is written
    # into the Target (see quarterdeck_run.run_quarterdeck).
    (quarterdeck / "planning-session.md").write_text(
        f"# Planning Session: {plan.project}\n\n"
        "Review the proposed decomposition, build order, and acceptance gates on the Kanban Board. "
        "The Planning Session shows the manifest build tree for execution review.\n",
        encoding="utf-8",
    )
    (quarterdeck / "console.yaml").write_text(
        render_console(plan.project, plan_path=plan.path), encoding="utf-8"
    )
    return quarterdeck


# ── File writing ────────────────────────────────────────────────────────────────────


def _safe_blueprint_path(blueprint_dir: Path, name: str) -> Path:
    """Resolve an emitted block name under blueprint/, rejecting path traversal."""
    dest = (blueprint_dir / name).resolve()
    if blueprint_dir.resolve() not in dest.parents and dest != blueprint_dir.resolve():
        raise SpecificationError(f"Emitted file escapes the Blueprint directory: {name!r}")
    return dest


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip("\n") + "\n", encoding="utf-8", newline="\n")


def _resolve_context_name(name: str, blueprint_dir: Path) -> str | None:
    """Resolve an authored context name to a real Blueprint reference, or None to drop it.

    A ``sources/<x>`` entry is valid only when analyze promoted ``<x>`` into ``blueprint/``;
    then the prefix is stripped. A source routed to the Compass (author intent) or otherwise
    not promoted is never emitted into ``blueprint/``, so it cannot be build context and is
    dropped. ``*_compact.md`` derivatives are generated at build time, so they are kept even
    though they do not exist at plan time. Any other name is left untouched.
    """
    if name.startswith("sources/"):
        stripped = name.removeprefix("sources/")
        return stripped if (blueprint_dir / stripped).is_file() else None
    return name


def _normalize_manifest_contexts(plan_path: Path, blueprint_dir: Path) -> tuple[str, ...]:
    """Rewrite MANIFEST context fields to Drydock's deterministic compact policy.

    Returns warnings for context entries dropped because they name a source that was never
    emitted into ``blueprint/`` (only files that exist in the Blueprint may appear in the plan).
    """
    plan = parse_build_plan(plan_path)
    updates: dict[str, dict[str, str | None]] = {}
    warnings: list[str] = []
    from drydock.build import normalize_context_names

    for block in plan.blocks:
        if block.block_type not in {"story", "spike"}:
            continue
        normalized: list[str] = []
        for name in normalize_context_names(block, blueprint_dir):
            resolved = _resolve_context_name(name, blueprint_dir)
            if resolved is None:
                warnings.append(
                    f"{block.block_id}: dropped context {name!r} — not present in blueprint/ "
                    "(source routed to the Compass or never promoted); the Manifest may reference "
                    "only files that exist in the Blueprint"
                )
                continue
            normalized.append(resolved)
        normalized_tuple = tuple(normalized)
        current = block.fields.get("context", ())
        current_tuple = current if isinstance(current, tuple) else ()
        if normalized_tuple == current_tuple:
            continue
        updates[block.block_id] = {
            "context": ", ".join(normalized_tuple) if normalized_tuple else None,
        }
    batch_set_block_fields(plan_path, updates)
    return tuple(warnings)


def _prepare_manifest_in_memory(
    plan: BuildPlan,
    *,
    blueprint_dir: Path,
    emitted_files: dict[str, str],
    compass_sources: frozenset[str],
    prior_applied_specs: dict[str, AppliedSpecRecord],
    prior_block_states: dict[str, tuple[str, str | None]],
    schedule_computed: bool = False,
) -> tuple[str, ...]:
    """Merge prior state and normalize context before any target artifact write.

    ``schedule_computed`` is set when the Manifest was serialized from a topology declaration:
    the schedule was already computed from the declaration, so re-deriving it from the Manifest
    that carries it would repeat the same measurement for the same answer.
    """
    from drydock.build import is_feature_step, is_screen_step, normalize_context_names
    from drydock.build_plan import _format_applied_specs

    warnings: list[str] = []
    available = set(emitted_files)
    available.update(path.name for path in blueprint_dir.glob("*.md") if path.is_file())

    retained_applied_specs: dict[str, AppliedSpecRecord] = {}
    for name, record in prior_applied_specs.items():
        if name in emitted_files:
            digest = _sha256(emitted_files[name].encode("utf-8")).hexdigest()
            build_digest = build_relevant_text_sha256(emitted_files[name])
        else:
            path = blueprint_dir / name
            digest = _file_sha256(path) if path.is_file() else ""
            build_digest = build_relevant_sha256(path) if path.is_file() else ""
        if digest == record.sha256 or (record.build_sha256 and build_digest == record.build_sha256):
            retained_applied_specs[name] = record
    if retained_applied_specs:
        plan.set_metadata(applied_specs=_format_applied_specs(retained_applied_specs))

    for block in plan.blocks:
        updates: dict[str, str | tuple[str, ...] | None] = {}
        if block.block_type in {"story", "spike"}:
            normalized: list[str] = []
            for name in normalize_context_names(block, blueprint_dir):
                if name.startswith("sources/"):
                    promoted = name.removeprefix("sources/")
                    source_exists = (blueprint_dir / name).is_file()
                    if promoted in compass_sources or (
                        promoted not in available and not source_exists
                    ):
                        warnings.append(
                            f"{block.block_id}: dropped context {name!r} — not present in "
                            "blueprint/ (source routed to the Compass or never promoted); "
                            "the Manifest may reference only files that exist in the Blueprint"
                        )
                        continue
                    name = promoted
                normalized.append(name)
            if is_feature_step(block) or is_screen_step(block):
                for managed in ("ARCHITECTURE.md", "DATABASE.md"):
                    compact = managed.replace(".md", "_compact.md")
                    if managed in available and compact not in normalized:
                        normalized.append(compact)
            current = block.fields.get("context", ())
            current_tuple = current if isinstance(current, tuple) else ()
            if tuple(normalized) != current_tuple:
                updates["context"] = tuple(normalized) if normalized else None

        prior_state, prior_finding = prior_block_states.get(block.block_id, ("pending", None))
        if prior_state != "pending":
            implementations = block.fields.get("implements", ())
            names = implementations if isinstance(implementations, tuple) else (implementations,)
            dirty = False
            for name in (str(item) for item in names if item):
                record = prior_applied_specs.get(name)
                if record is None:
                    dirty = True
                    break
                if name in emitted_files:
                    digest = _sha256(emitted_files[name].encode("utf-8")).hexdigest()
                    build_digest = build_relevant_text_sha256(emitted_files[name])
                else:
                    path = blueprint_dir / name
                    digest = _file_sha256(path) if path.is_file() else ""
                    build_digest = build_relevant_sha256(path) if path.is_file() else ""
                if digest != record.sha256 and not (
                    record.build_sha256 and build_digest == record.build_sha256
                ):
                    dirty = True
                    break
            if not dirty:
                updates["state"] = prior_state
        if block.block_type == "spike" and prior_finding:
            updates["finding"] = prior_finding
        if updates:
            plan.set_fields(block.block_id, **updates)

    if not schedule_computed:
        warnings.extend(
            _apply_computed_schedule(plan, blueprint_dir=blueprint_dir, emitted_files=emitted_files)
        )
    plan.validate()
    return tuple(warnings)


def _apply_computed_schedule(
    plan: BuildPlan,
    *,
    blueprint_dir: Path,
    emitted_files: dict[str, str],
) -> list[str]:
    """Compute and stamp the schedule fields the model must never author.

    Block grouping, stack-mode assignment, ordering, and sizing are Python's job. The model states
    what each story requires and provides; Zone C derives everything positional from that. Deriving
    builder/consumer mode here rather than at build time makes it visible in the QuarterDeck cost
    preview, auditable before anything runs, and independent of working-tree state.

    Sizing is a **target**, not a gate: a story or block over the single-build-pass target is
    marked and planned as-is. Some specifications are irreducible, so over-target work is a fact
    the Commander reads off the Manifest, not a reason to refuse a plan.

    A Manifest still using the legacy block taxonomy carries no ``type:`` and is left untouched.
    """
    from drydock.plan_topology import computed_field_updates, stories_from_manifest

    declared = stories_from_manifest(plan.blocks)
    if not declared:
        return []

    computation = _compute_schedule(
        declared, blueprint_dir=blueprint_dir, emitted_files=emitted_files
    )
    if computation.fatal:
        return [defect.rendered() for defect in computation.fatal]
    computed_ids = {story.story_id for story in computation.stories}
    computed_nodes = {node.block_id: node for node in plan.blocks if node.block_id in computed_ids}
    ordered_nodes = [computed_nodes[story.story_id] for story in computation.stories]
    ordered = iter(ordered_nodes)
    plan.blocks[:] = [
        next(ordered) if node.block_id in computed_ids else node for node in plan.blocks
    ]
    story_number = 0
    spike_number = 0
    for node in plan.blocks:
        if node.block_type == "story":
            story_number += 1
            if node.number != story_number:
                node.number = story_number
                node.dirty = True
        elif node.block_type == "spike":
            spike_number += 1
            if node.number != spike_number:
                node.number = spike_number
                node.dirty = True
    for story_id, updates in computed_field_updates(computation.stories).items():
        plan.set_fields(story_id, **updates)
    plan.set_metadata(blocks=str(len(computation.blocks)))
    return [defect.rendered() for defect in computation.warnings]


def _record_plan_error(
    target_dir: Path,
    *,
    classification: str,
    detail: str,
    execution_id: str | None,
    log_dir: Path | None,
    recovery: str,
) -> RecordedError:
    """Persist one post-output plan failure and refresh its QuarterDeck projection."""
    record = write_error_record(
        target_dir,
        command="plan",
        phase="post-output validation",
        classification=classification,
        detail=detail,
        execution_id=execution_id,
        evidence=log_dir,
        recovery=recovery,
    )
    from drydock.quarterdeck_state import refresh_commanders_chair

    refresh_commanders_chair(target_dir)
    return RecordedError(record)


def _conflict_challenge_assembly(
    prompt_assembly: PromptAssembly,
    *,
    declaration: str,
    initial_execution_id: str | None,
) -> PromptAssembly:
    """Append one bounded challenge instruction to the complete original planning context."""
    challenge = lines_part(
        "Plan conflict challenge",
        [
            "# Plan Conflict Challenge",
            "",
            "The initial planning call declared the product conflict reproduced below. Challenge",
            "that declaration once against every authoritative input already present in this full",
            "prompt. Do not assume that project-associated runtime state is repository content.",
            "",
            "Apply these rules:",
            "- SQS, S3, databases, logs, and Marina/application-managed files are distinct from",
            "  files in a repository checkout.",
            "- “Project file” and “project-associated file” do not imply a Git checkout path.",
            "- A repository-write guardrail applies only to a destination explicitly located in",
            "  the repository.",
            "- A discovery or registration guardrail does not govern runtime processing unless",
            "  an authoritative source explicitly extends its scope.",
            "- Missing detail is not a conflict. Use a conservative reasonable interpretation.",
            "- Counts, summaries, and indexes are derived metadata. When they disagree with an",
            "  unambiguous detailed enumeration, recompute them from that enumeration and",
            "  continue. A stale derived total is not a product decision or a source correction.",
            "- Available response length is not a conflict. Emit TOPOLOGY.md first, then as many",
            "  complete declared artifacts as fit; Drydock requests the remainder in bounded",
            "  continuation passes.",
            "- A genuine conflict requires mutually exclusive authoritative requirements that",
            "  the declared precedence cannot resolve.",
            "",
            "If the declaration is unsupported, begin the Success Mode artifact batch with",
            "TOPOLOGY.md and emit as many complete declared artifacts as fit.",
            "If it is genuine, emit only PLAN_CREATE_ERROR.txt and cite the exact files, clauses,",
            "and scopes in conflict, explain why precedence cannot resolve them, and state the",
            "exact product decision or source correction required.",
            "",
            f"Initial execution ID: {initial_execution_id or '-'}",
            "",
            "Initial declaration:",
            declaration.strip(),
        ],
        kind="challenge",
    )
    return PromptAssembly(parts=(*prompt_assembly.parts, challenge))


def _topology_repair_assembly(*, declaration: str, defect: str, pass_number: int) -> PromptAssembly:
    """Build a small repair prompt for a valid artifact batch with an invalid work graph."""
    repair = lines_part(
        "Plan topology repair",
        [
            "# Plan Topology Repair",
            "",
            "Drydock accepted the Blueprint artifact batch but rejected its transient work graph.",
            "Repair only the deterministic defect reported below. Preserve every story ID,",
            "implements assignment and story fields that do not need",
            "to change. Dependencies must name exact story IDs declared in this topology.",
            "",
            "Emit exactly one fully paired TOPOLOGY.md block and no other text or artifact.",
            "",
            f"Repair pass: {pass_number}",
            "",
            "Deterministic validation defect:",
            defect.strip(),
            "",
            "Original TOPOLOGY.md body:",
            "<original-topology>",
            declaration.strip(),
            "</original-topology>",
        ],
        kind="repair",
    )
    return PromptAssembly(parts=(repair,))


def analyzed_story_ids(blueprint_dir: Path) -> tuple[str, ...]:
    """Story IDs declared by the Target's ``ANALYSIS.md``, or none when it has no Story List."""
    from drydock.quarterdeck_state import analysis_story_ids

    analysis_path = blueprint_dir.parent / "ANALYSIS.md"
    if not analysis_path.is_file():
        return ()
    return analysis_story_ids(analysis_path.read_text(encoding="utf-8"))


def _declaration_coverage_defect(declaration: str, blueprint_dir: Path) -> str:
    """The coverage defect in a topology declaration, or an empty string when it is sound."""
    from drydock.plan_topology import coverage_defects, story_covers

    declared, _ = parse_topology(declaration)
    fatal, _ = coverage_defects(
        [(story.story_id, story_covers(story)) for story in declared],
        analyzed_story_ids(blueprint_dir),
    )
    return "\n  ".join(fatal)


def _repair_declaration_coverage(
    declaration: str,
    *,
    blueprint_dir: Path,
    target: str,
    target_dir: Path,
    llm_provider: str | None,
    model: str | None,
    log_dir: Path | None,
    runner: Callable[..., object],
    on_text: Callable[[str], None] | None,
    attempts: int,
    initial_execution_id: str | None,
) -> str:
    """Correct analyzed-story coverage in the declaration before Stage 2 spends a call.

    Coverage is decidable the moment the topology exists, and a repair here costs one small
    call against the declaration alone. Returning an uncorrected declaration is not a
    failure path: the same rule runs again at final validation, which owns the refusal.
    """
    for repair_pass in range(1, attempts + 1):
        defect = _declaration_coverage_defect(declaration, blueprint_dir)
        if not defect:
            return declaration
        if on_text is not None:
            on_text(f"[plan] topology coverage repair pass {repair_pass}/{attempts} · {defect}\n")
        assembly = _topology_repair_assembly(
            declaration=declaration, defect=defect, pass_number=repair_pass
        )
        try:
            result = cast(
                CompletedRun,
                runner(
                    assembly.rendered_text,
                    target_dir,
                    llm=llm_provider,
                    model=model,
                    command_name="plan",
                    parameters={
                        "target": target,
                        "coverage_repair_pass": repair_pass,
                        "initial_execution_id": initial_execution_id or "",
                    },
                    log_dir=log_dir,
                    target=target,
                    on_text=on_text,
                    prompt_assembly=assembly,
                ),
            )
        except Exception:
            return declaration
        if not result.ok or not result.text.strip():
            return declaration
        try:
            repair_blocks = _parse_strict_blocks(result.text, result)
        except OutsideArtifactTextError:
            repair_blocks = _parse_repair_artifact_envelopes(result.text)
        except Exception:
            return declaration
        if set(repair_blocks) != {TOPOLOGY_BLOCK}:
            return declaration
        repaired = repair_blocks[TOPOLOGY_BLOCK]
        stories, defects = parse_topology(repaired)
        # A malformed or emptied re-emission is discarded whole; the accepted declaration stands.
        if defects or not stories or repaired == declaration:
            return declaration
        declaration = repaired
    return declaration


#: Plan integrity defects a topology re-emission alone can repair: each is stated entirely in a
#: field the declaration owns, so the authored Blueprint artifacts stay valid and untouched.
_TOPOLOGY_FIELD_DEFECTS = ("analyzed stories are not delivered by any Manifest story:",)


def _is_repairable_topology_defect(exc: Exception) -> bool:
    text = str(exc)
    if text.startswith("Plan generation failed: the declared work graph is inconsistent."):
        return True
    if not text.startswith("Plan integrity check failed:"):
        return False
    # Repair only when every reported defect is a declaration-field defect; a mixed report
    # needs artifact repair, which the caller reaches when this returns False.
    defects = [line.strip() for line in text.splitlines()[1:] if line.strip()]
    return bool(defects) and all(
        any(defect.startswith(marker) for marker in _TOPOLOGY_FIELD_DEFECTS) for defect in defects
    )


def _repairable_artifact_names(blocks: Mapping[str, str], defect: str) -> tuple[str, ...]:
    """Return emitted Blueprint artifacts explicitly cited by a validation defect."""
    cited = set(re.findall(r"\b[A-Z][A-Za-z0-9_-]*\.md\b", defect))
    declaration = blocks.get(TOPOLOGY_BLOCK)
    if declaration:
        stories, _ = parse_topology(declaration)
        for story in stories:
            if re.search(rf"(?m)^\s*{re.escape(story.story_id)}:", defect):
                cited.add(story.implements)
    return tuple(sorted(name for name in cited if name in blocks and name not in _RESERVED_BLOCKS))


def _artifact_repair_assembly(
    *, blocks: Mapping[str, str], names: tuple[str, ...], defect: str, pass_number: int
) -> PromptAssembly:
    """Build a small repair prompt containing only artifacts named by the validator."""
    lines = [
        "# Plan Artifact Repair",
        "",
        "Drydock accepted the Plan response shape but rejected the emitted Blueprint artifact(s)",
        "below. Repair only the deterministic defect. Preserve all unrelated content, contracts,",
        "headings, decisions, and acceptance assertions byte-for-byte where possible.",
        "Do not remove or weaken a valid assertion while adding a missing one. Every artifact with",
        "a programmatic surface retains at least two concrete Python acceptance assertions. Every",
        "DECISIONS.json is the sole decision disclosure surface; do not emit Markdown question sections.",
        "",
        "Emit exactly one fully paired artifact block for each supplied filename and no other",
        "text or artifact.",
        "",
        f"Repair pass: {pass_number}",
        "",
        "Deterministic validation defect:",
        defect.strip(),
    ]
    for name in names:
        lines.extend([
            "",
            f"Original {name} body:",
            f"<original-artifact name={json.dumps(name)}>",
            blocks[name].strip(),
            "</original-artifact>",
        ])
    return PromptAssembly(parts=(lines_part("Plan artifact repair", lines, kind="repair"),))


_REPAIR_ARTIFACT_RE = re.compile(
    r'<artifact name="(?P<name>[^"\n]+)">\s*\n(?P<body>.*?)\n?</artifact>', re.DOTALL
)


def _parse_repair_artifact_envelopes(text: str) -> dict[str, str]:
    """Parse the exact XML envelope models sometimes copy from the repair input tags."""
    blocks: dict[str, str] = {}
    cursor = 0
    for match in _REPAIR_ARTIFACT_RE.finditer(text):
        if text[cursor : match.start()].strip():
            return {}
        name = match.group("name").strip()
        if not name or name in blocks:
            return {}
        blocks[name] = match.group("body").strip()
        cursor = match.end()
    if text[cursor:].strip():
        return {}
    return blocks


def _unpaired_artifact_names(text: str, blocks: Mapping[str, str]) -> frozenset[str]:
    """Artifacts whose delimiters prove the response was cut, by name.

    Two structural signatures, both of which survive parsing. A block with no matching
    ``=== END ===`` is the tail the budget cut off — :func:`_parse_strict_blocks_by_line` records
    it anyway, so it is *present but incomplete*. A block whose body holds another artifact header
    is a cut that the model then restarted, absorbing the truncated attempt.

    Named rather than described, because the continuation loop has to drop exactly these and ask
    for them again. :func:`_artifact_delimiter_defects` renders the same two facts as prose for a
    refusal; this returns them as identifiers.
    """
    lines = text.splitlines()
    normalized = "\n".join(
        line
        for index, line in enumerate(lines)
        if index == 0
        or line.strip() != lines[index - 1].strip()
        or not _END_BLOCK_LINE_RE.match(line)
    )
    ends = Counter(match.group("name").strip() for match in _END_BLOCK_LINE_RE.finditer(normalized))
    unpaired = {name for name in blocks if ends[name] != 1}
    unpaired |= {name for name, body in blocks.items() if _HEADER_ANYWHERE_RE.search(body)}
    return frozenset(unpaired)


def _blueprint_tranche(score: PlanScore) -> tuple[str, ...]:
    """The exact Stage 2 filenames the next model call is authorized to emit."""
    return tuple(item.filename for item in score.missing[:_PLAN_BLUEPRINT_BATCH_SIZE])


def _render_ledger(score: PlanScore) -> str:
    """Render one bounded Stage 2 work queue, never the complete remaining topology."""
    tranche = frozenset(_blueprint_tranche(score))
    lines = [f"Accepted ({len(score.accepted)}) — already held, do not re-emit:"]
    lines.extend(f"  {name}" for name in sorted(score.accepted))
    if not score.accepted:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"Current batch ({len(tranche)}) — emit exactly these, in this order:")
    lines.extend(f"  {item.rendered()}" for item in score.missing if item.filename in tranche)
    if not tranche:
        lines.append("  (none)")
    deferred = len(score.missing) - len(tranche)
    lines.append("")
    lines.append(
        f"Deferred ({deferred}) — Drydock will provide later batches; do not emit them now."
    )
    invalid = tuple(item for item in score.invalid if item.filename in tranche)
    if invalid:
        lines.append("")
        lines.append(f"Defective ({len(invalid)}) — emit these again, in full, corrected:")
        lines.extend(f"  {item.rendered()}" for item in invalid)
    return "\n".join(lines)


def _continuation_assembly(
    prompt_assembly: PromptAssembly,
    *,
    topology: str,
    decisions: str,
    ledger: str,
) -> PromptAssembly:
    """Append the bounded continuation instruction to the *unchanged* original context.

    The prefix must stay byte-identical: the whole economy of continuing rather than restarting
    rests on the provider's prompt cache recognising it. Appending is the only permitted edit,
    which is why this mirrors :func:`_conflict_challenge_assembly` rather than rebuilding.
    """
    body = load_prompt("plan_continue").body.strip()
    frozen = lines_part(
        "Frozen Stage 1 output",
        [
            "# Frozen Stage 1 Output",
            "",
            "The following topology and decisions are the exact accepted Stage 1 output.",
            "Author the current Blueprint batch from them; do not reconstruct or amend them.",
            "",
            "## TOPOLOGY.md",
            "",
            topology.strip(),
            "",
            "## DECISIONS.json",
            "",
            decisions.strip() or "[]",
        ],
        kind="frozen-stage",
    )
    instruction = lines_part(
        "Plan continuation",
        [body, "", "## Ledger", "", ledger],
        kind="continuation",
    )
    return PromptAssembly(parts=(*prompt_assembly.parts, frozen, instruction))


@dataclass(frozen=True)
class _Continuation:
    """What the continuation loop accumulated, and how it ended."""

    blocks: dict[str, str]
    score: PlanScore
    execution_ids: tuple[str, ...]
    passes: int


def _continue_short_plan(
    blocks: dict[str, str],
    *,
    blocks_text: str,
    prompt_assembly: PromptAssembly,
    declared: Sequence[PlannedStory],
    target: str,
    target_dir: Path,
    llm_provider: str | None,
    model: str | None,
    log_dir: Path | None,
    runner: Callable[..., object],
    on_text: Callable[[str], None] | None,
    attempts: int,
    initial_execution_id: str | None,
) -> _Continuation:
    """Resume a response that stopped short of its own declaration.

    Stage 1 has frozen the complete topology before this loop starts. Stage 2 exposes at most five
    declared artifacts per call and accepts only that tranche. ``attempts`` is the consecutive
    no-progress retry allowance; successful tranches continue until the declaration is complete.

    Nothing accepted is ever discarded. A junk pass, a rejected amendment, or a conflicting
    re-emission ends the loop with the accumulator intact rather than corrupting it.
    """
    damaged = _unpaired_artifact_names(blocks_text, blocks)
    accumulated = {name: body for name, body in blocks.items() if name not in damaged}
    current = tuple(declared)
    score = score_plan(current, accumulated)
    if on_text is not None:
        on_text(
            "[plan-score]"
            + score.progress_block(stage="STAGE 1 · TOPOLOGY", result="Topology accepted")
        )
    execution_ids = [initial_execution_id or ""]
    passes = 0
    stalled_passes = 0

    # One successful artifact per call is the slowest legitimate forward motion.  The additional
    # retry allowance bounds malformed/no-progress calls without capping a large valid topology at
    # three batches.
    max_passes = len(current) + attempts
    while attempts > 0 and passes < max_passes and not score.is_complete:
        passes += 1
        if on_text is not None:
            on_text(f"[plan] continuation pass {passes}/{attempts} · {score.progress_line()}\n")
        assembly = _continuation_assembly(
            prompt_assembly,
            topology=accumulated[TOPOLOGY_BLOCK],
            decisions=accumulated.get(DECISIONS_BLOCK, "[]"),
            ledger=_render_ledger(score),
        )
        try:
            result = cast(
                CompletedRun,
                runner(
                    assembly.rendered_text,
                    target_dir,
                    llm=llm_provider,
                    model=model,
                    command_name="plan",
                    parameters={
                        "target": target,
                        "continuation_pass": passes,
                        "initial_execution_id": initial_execution_id or "",
                    },
                    log_dir=log_dir,
                    target=target,
                    on_text=on_text,
                    prompt_assembly=assembly,
                ),
            )
        except Exception:
            break
        execution_ids.append(getattr(result, "execution_id", "") or "")
        if not result.ok or not result.text.strip():
            if on_text is not None:
                on_text(
                    "[plan-score]"
                    + score.progress_block(
                        stage=f"STAGE 2 · BLUEPRINT BATCH {passes}",
                        result="Rejected: empty or failed model response",
                    )
                )
            break

        try:
            pass_blocks = _parse_strict_blocks(result.text, result)
        except OutsideArtifactTextError as exc:
            pass_blocks = exc.blocks
        except SpecificationError:
            if on_text is not None:
                on_text(
                    "[plan-score]"
                    + score.progress_block(
                        stage=f"STAGE 2 · BLUEPRINT BATCH {passes}",
                        result="Rejected: malformed artifact response",
                    )
                )
            stalled_passes += 1
            if stalled_passes >= attempts:
                break
            continue
        if not pass_blocks:
            if on_text is not None:
                on_text(
                    "[plan-score]"
                    + score.progress_block(
                        stage=f"STAGE 2 · BLUEPRINT BATCH {passes}",
                        result="Rejected: no Blueprint artifacts",
                    )
                )
            stalled_passes += 1
            if stalled_passes >= attempts:
                break
            continue

        # Each pass is pairing-checked against its own response, before anything it produced is
        # allowed near the accumulator. The merged set spans several responses and can no longer
        # be checked as one text, so this is the only point at which that check is possible.
        pass_damaged = _unpaired_artifact_names(result.text, pass_blocks)

        tranche = frozenset(_blueprint_tranche(score))
        accepted_now = frozenset(score.accepted)
        conflicted = False
        for name, body in pass_blocks.items():
            if name in {TOPOLOGY_BLOCK, DECISIONS_BLOCK}:
                # Stage 1 artifacts are frozen. A byte-identical repeat is tolerated for provider
                # compatibility but ignored; a revision invalidates the whole Stage 2 pass.
                if accumulated.get(name) != body:
                    conflicted = True
                    break
                continue
            if name not in tranche:
                conflicted = True
                break
            if name in pass_damaged:
                continue
            if name in accepted_now:
                # An accepted artifact is frozen. A byte-identical repeat costs nothing; a
                # differing one means this pass disagrees with work already paid for, and the
                # pass is dropped whole rather than resolved by guesswork.
                if accumulated.get(name) != body:
                    conflicted = True
                    break
                continue
            accumulated[name] = body
        if conflicted:
            if on_text is not None:
                on_text(
                    "[plan-score]"
                    + score.progress_block(
                        stage=f"STAGE 2 · BLUEPRINT BATCH {passes}",
                        result="Rejected: output changed frozen or deferred work",
                    )
                )
            stalled_passes += 1
            if stalled_passes >= attempts:
                break
            continue

        advanced = score_plan(current, accumulated)
        if not advanced.improved_on(score):
            score = advanced
            if on_text is not None:
                on_text(
                    "[plan-score]"
                    + score.progress_block(
                        stage=f"STAGE 2 · BLUEPRINT BATCH {passes}",
                        result="No complete Blueprint accepted",
                    )
                )
            stalled_passes += 1
            if stalled_passes >= attempts:
                break
            continue
        accepted_count = len(advanced.accepted) - len(score.accepted)
        score = advanced
        if on_text is not None:
            on_text(
                "[plan-score]"
                + score.progress_block(
                    stage=f"STAGE 2 · BLUEPRINT BATCH {passes}",
                    result=f"Accepted {accepted_count} Blueprint(s)",
                )
            )
        stalled_passes = 0

    return _Continuation(
        blocks=accumulated,
        score=score,
        execution_ids=tuple(item for item in execution_ids if item),
        passes=passes,
    )


def _required_action_from_declaration(declaration: str) -> str:
    """Return the model's complete Required action body, without inventing a decision."""
    marker = re.search(r"(?im)^Required action:\s*$", declaration)
    if marker is None:
        return declaration.strip()
    action = declaration[marker.end() :].strip()
    return action or declaration.strip()


def _confirmed_conflict_is_source_cited(declaration: str) -> bool:
    """Require the challenge to identify sources and both decision-bearing sections."""
    has_source = bool(
        re.search(
            r"(?im)(?:sources/[A-Za-z0-9_./?*\-]+|[A-Za-z0-9_.\-]+\.md\b)",
            declaration,
        )
    )
    return (
        has_source
        and bool(re.search(r"(?im)^Reason:\s*$", declaration))
        and bool(re.search(r"(?im)^Required action:\s*$", declaration))
    )


def _record_confirmed_plan_conflict(
    target_dir: Path,
    *,
    target: str,
    declaration: str,
    initial_declaration: str,
    initial_execution_id: str | None,
    challenge_execution_id: str | None,
    log_dir: Path | None,
) -> ErrorRecord:
    """Persist a source-cited product conflict as the Target's current deferred error."""
    detail_parts = []
    if challenge_execution_id:
        detail_parts.extend([
            "Confirmed conflict:",
            declaration.strip(),
            "",
            "Initial declaration:",
            initial_declaration.strip(),
        ])
    else:
        detail_parts.extend(["Model-declared conflict:", declaration.strip()])
    action = _required_action_from_declaration(declaration)
    record = write_error_record(
        target_dir,
        command="plan",
        phase="product decision",
        classification="plan requires a product decision",
        detail="\n".join(detail_parts),
        recovery=(
            f"{action}\n\n"
            f"Review the active record: drydock run quarterdeck {target}\n"
            f"After correcting the decision or source: drydock plan {target}"
        ),
        execution_id=initial_execution_id,
        challenge_execution_id=challenge_execution_id,
        evidence=log_dir,
        state="Deferred",
        detail_limit=None,
    )
    from drydock.quarterdeck_state import refresh_commanders_chair

    refresh_commanders_chair(target_dir)
    return record


def _record_conflict_challenge_failure(
    target_dir: Path,
    *,
    target: str,
    initial_declaration: str,
    initial_execution_id: str | None,
    challenge_execution_id: str | None,
    failure: str,
    log_dir: Path | None,
) -> RecordedError:
    """Record a failed challenge without confirming the model's product declaration."""
    record = write_error_record(
        target_dir,
        command="plan",
        phase="post-output validation",
        classification="plan conflict challenge failed",
        detail=(
            "The initial product-conflict declaration was not confirmed because the required "
            "challenge pass failed.\n\n"
            f"Initial declaration:\n{initial_declaration.strip()}\n\n"
            f"Challenge failure:\n{failure.strip() or 'No diagnostic output was returned.'}"
        ),
        recovery=(
            "Inspect the initial and challenge execution evidence, correct the provider or "
            f"artifact failure, then run: drydock plan {target}\n"
            f"Review the active record: drydock run quarterdeck {target}"
        ),
        execution_id=initial_execution_id,
        challenge_execution_id=challenge_execution_id,
        evidence=log_dir,
        detail_limit=None,
    )
    from drydock.quarterdeck_state import refresh_commanders_chair

    refresh_commanders_chair(target_dir)
    return RecordedError(record)


def _approve_outside_text_candidate(
    exc: OutsideArtifactTextError,
    *,
    blueprint_dir: Path,
    target_dir: Path,
    target: str,
    result: CompletedRun,
    execution_id: str | None,
    allow_diagnostic_recovery: bool,
    llm_provider: str | None,
    model: str | None,
    log_dir: Path | None,
    runner: RunnerFn,
    on_text: TextCallback | None,
) -> tuple[BuildPlan, tuple[str, ...], str, str]:
    """Validate an outside-text candidate, then spend the shared diagnostic call on semantics."""
    if not _outside_text_is_waiver_eligible(
        exc.spans,
        text=result.text,
        blocks=exc.blocks,
    ):
        raise _record_plan_error(
            target_dir,
            classification="model artifact contract failed",
            detail=str(exc),
            execution_id=execution_id,
            log_dir=log_dir,
            recovery=(
                "Remove the reported outside text or correct the model artifact, then run: "
                f"drydock plan {target}"
            ),
        ) from exc

    try:
        validated_plan, validated_warnings = _validate_plan_output(
            exc.blocks, blueprint_dir, result, source_text=result.text, project=target
        )
    except Exception as validation_exc:
        raise _record_plan_error(
            target_dir,
            classification="plan output validation failed",
            detail=str(validation_exc),
            execution_id=execution_id,
            log_dir=log_dir,
            recovery=f"Correct the plan input or model artifact, then run: drydock plan {target}",
        ) from validation_exc

    decision = None
    if allow_diagnostic_recovery:
        if on_text is not None:
            on_text(
                "[plan] complete plan contains bounded text outside artifact blocks; "
                "requesting diagnostic approval\n"
            )
        from drydock.diagnose import request_artifact_waiver

        decision = request_artifact_waiver(
            target_dir,
            command=f"drydock plan {target}",
            target=target,
            evidence=_outside_text_waiver_evidence(
                exc.spans,
                artifact_count=len(exc.blocks),
            ),
            llm=llm_provider,
            model=model,
            log_dir=log_dir,
            runner=runner,
        )
    if decision is None or not decision.approved:
        decision_detail = (
            f"\n  Waiver rejected: {decision.reason}"
            if decision is not None
            else "\n  No diagnostic waiver approval was available."
        )
        raise _record_plan_error(
            target_dir,
            classification="model artifact contract failed",
            detail=str(exc) + decision_detail,
            execution_id=execution_id,
            log_dir=log_dir,
            recovery=(
                "Remove the reported outside text or correct the model artifact, then run: "
                f"drydock plan {target}"
            ),
        ) from exc

    removed_count = sum(len(span.normalized) for span in exc.spans)
    removed_preview = "; ".join(
        f"{span.location}: {json.dumps(span.normalized, ensure_ascii=False)}" for span in exc.spans
    )
    warning = (
        "recovered complete artifact batch after diagnostic approval removed "
        f"{removed_count} outside character(s) ({removed_preview}); decision execution "
        f"{decision.execution_id}: {decision.reason}"
    )
    if on_text is not None:
        on_text(f"[plan] {warning}\n")
    return validated_plan, validated_warnings, decision.execution_id, warning


# ── Entry point ─────────────────────────────────────────────────────────────────────


def _record_plan_lineage(
    target_dir: Path,
    blueprint_dir: Path,
    plan: object,
    *,
    runner: RunnerFn | None,
    model: str | None,
    llm_provider: str | None,
    log_dir: Path | None,
    target: str,
) -> None:
    """Record that this plan consumed the pending source versions, and which stories they became.

    Planning is the only actor that reads the whole source and decides what it decomposes into, so
    the provenance link is captured here rather than reconstructed later. Failure is never fatal:
    a Target with unlinked lineage is repairable with ``drydock refit <Target> --relineage``, but a
    plan lost to a bookkeeping error is not.
    """
    from datetime import date as _date

    from drydock.lineage import consume_after_plan
    from drydock.lineage_attribution import attribute_source
    from drydock.target_git import head_commit

    def attributor(rel_path: str, source_text: str):
        return attribute_source(
            rel_path,
            source_text,
            plan,
            working_directory=blueprint_dir,
            runner=runner,
            log_dir=log_dir,
            model=model,
            llm_provider=llm_provider,
            target=target,
        )

    try:
        _, warnings = consume_after_plan(
            target_dir,
            blueprint_dir / "sources",
            date=_date.today().isoformat(),
            commit=head_commit(target_dir),
            attributor=attributor,
        )
    except Exception as exc:  # noqa: BLE001 - lineage must never break planning
        print(f"  lineage: not recorded ({exc})")
        return
    for warning in warnings:
        print(f"  lineage: {warning}")


def create_plan(
    blueprint: str,
    target: str,
    target_directory: Path,
    *,
    overwrite: bool = False,
    conform: bool = True,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
    allow_diagnostic_recovery: bool = False,
    continue_attempts: int = 3,
    override: bool = False,
) -> PlanCreateResult | PlanDeferredResult:
    """Author the Blueprint and executable Manifest from the reviewed analysis."""
    target_dir = target_directory / target
    # Every planning attempt starts a new current-error lifecycle, including attempts that fail
    # preflight before reaching an LLM call.
    clear_error_record(target_dir)

    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(
            f"Blueprint directory not found: {blueprint_dir}\n  Import source material first."
        )

    analysis_path = target_dir / "ANALYSIS.md"
    analysis_text = _read_if(analysis_path)
    if not analysis_text:
        raise SpecificationError(
            f"ANALYSIS.md not found: {analysis_path}\n  Run: drydock analyze {target}"
        )
    source_roles = parse_source_roles(analysis_text)

    blockers_path = target_dir / "BLOCKERS.md"
    if blockers_path.is_file():
        raise SpecificationError(
            "BLOCKERS.md is present — planning is blocked. Answer the blockers and re-run "
            f"`drydock analyze {target}` before `drydock plan {target}`."
        )
    quality_match = _QUALITY_RE.search(analysis_text)
    if quality_match and quality_match.group(1).lower() == "blocked":
        raise SpecificationError(
            "ANALYSIS.md quality is Blocked — resolve blockers and re-run analyze before planning."
        )
    # TECHNOLOGY_STACK.md never gates planning. An absent or empty stack file means the stack is
    # undecided, which plan resolves from the sources — it is not a Commander decision to await.
    waivers: list[WaivedGate] = []
    required_decisions = _required_plan_decisions(target_dir)
    if required_decisions and not override:
        raise SpecificationError(
            "Required Analyze questionnaire decisions are unanswered — answer them in QuarterDeck "
            "before planning:\n  - " + "\n  - ".join(required_decisions)
        )
    # Waivers are reported by the caller as one summary block rather than streamed: cmd_plan's
    # progress callback deliberately suppresses raw plan chatter, and a bypassed gate must never
    # depend on --debug to be seen.
    waivers.extend(WaivedGate(kind=PLAN_DECISION, subject=label) for label in required_decisions)

    plan_path = target_dir / "MANIFEST.md"
    prior_manifest = _read_if(plan_path)
    replanning = prior_manifest is not None
    prior_applied_specs, prior_block_states = _load_prior_plan_state(plan_path)
    # Explicit overwrite also discards all prior build provenance. A normal replan retains
    # provenance only when the authoritative rewrite emits byte-identical specification content.
    if overwrite:
        prior_applied_specs = {}

    built_ledger: tuple[str, ...] = ()
    if replanning and not overwrite:
        prior_plan = parse_build_plan(plan_path)
        ledger: list[str] = []
        for block in prior_plan.blocks:
            if block.state not in {"closed/verified", "implemented"}:
                continue
            implements = block.fields.get("implements", ())
            names = implements if isinstance(implements, tuple) else (implements,)
            for name in (str(value) for value in names if value):
                record = prior_applied_specs.get(name)
                if record is None:
                    continue
                ledger.append(
                    f"story_id={block.block_id}; specification={name}; "
                    f"applied_sha256={record.sha256}; build_sha256={record.build_sha256 or '-'}"
                )
        built_ledger = tuple(ledger)

    # Capture durable answers before unbuilt Blueprint files are discarded for regeneration.
    questionnaire_decisions(target_dir)

    # Standing-directive feedback file — created if absent, never overwritten, injected when the
    # user has edited it beyond the default placeholder.
    ensure_feedback_file(target_dir)
    # Compatibility only: retire generated blocker blocks written by older Drydock releases.
    # PLAN_COMPASS.md is now strictly human-owned and is never a plan-error destination.
    _clear_plan_compass_blockers(target_dir)
    feedback_text = (target_dir / _FEEDBACK_FILENAME).read_text(encoding="utf-8")
    ensure_exclude_file(target_dir)
    # Zone A — resolve the stack file set. TECHNOLOGY_STACK.md declares *which* stack is used;
    # the Rigging files themselves must be opened and measured at plan time or builder/consumer
    # mode and the single-build-pass ceiling have no basis. An empty or unresolved result never
    # gates planning: absence means undecided.
    from drydock.plan_stack import resolve_target_stack, unresolved_names

    resolved_stack = resolve_target_stack(target_dir)
    stack_warnings = [
        f"stack: {name!r} is declared in {technology_stack.FILENAME} but no Rigging stack file "
        "resolves to it; the build agent receives no guidance for that technology"
        for name in unresolved_names(resolved_stack)
    ]
    if on_text is not None and resolved_stack:
        on_text(
            f"[plan] resolved {len(resolved_stack) - len(stack_warnings)} of "
            f"{len(resolved_stack)} declared Rigging stack file(s)\n"
        )
    default_feedback = prompt_header_for_file(_FEEDBACK_FILENAME)
    feedback_for_prompt = (
        feedback_text
        if feedback_text.strip()
        != (
            default_feedback.default_text.strip()
            if default_feedback and default_feedback.default_text
            else "# Plan Compass"
        )
        else None
    )

    run = runner if runner is not None else run_prompt
    today = datetime.now(timezone.utc).date().isoformat()  # noqa: UP017
    excluded_filenames = load_excluded_filenames(target_dir)
    # Remove unbuilt Plan output before regeneration. Built files remain as a failure-safe until
    # validated replacement artifacts are available, but they carry no overwrite protection.
    discarded_specs = (
        _discard_unbuilt_specs(
            blueprint_dir, prior_applied_specs, excluded_filenames=excluded_filenames
        )
        if replanning or overwrite
        else []
    )
    if discarded_specs and on_text is not None:
        on_text(
            f"[plan] discarding {len(discarded_specs)} unbuilt Blueprint spec(s) for "
            f"regeneration: {', '.join(discarded_specs)}\n"
        )
    existing_specs = _collect_existing_typed_specs(
        blueprint_dir, excluded_filenames=excluded_filenames
    )
    # A replan is a fresh Planning Crew review with full authority over Plan-owned outputs.
    # Existing built specs remain on disk as failure-safe context until the validated response
    # replaces them, but they never force reuse mode or block regenerated content.
    force_rewrite = overwrite or replanning
    reuse_mode = not force_rewrite and _is_reuse_candidate(existing_specs)
    speckit_mode = not force_rewrite and not reuse_mode and _is_speckit_source(blueprint_dir)
    imported_source_paths = _collect_sources(blueprint_dir, excluded_filenames=excluded_filenames)
    reusable_spec_paths: list[Path] | None = None
    normalized_existing: list[Path] = []
    if reuse_mode:
        prompt_name = _REUSE_PROMPT_NAME
        plan_mode = "reuse-manifest-first"
    elif speckit_mode:
        prompt_name = _SPECKIT_PROMPT_NAME
        plan_mode = "speckit-translate"
    else:
        prompt_name = PROMPT_NAME
        plan_mode = "full-rewrite"
    mode_label = _PLAN_MODE_LABELS.get(plan_mode, plan_mode)
    if on_text is not None:
        on_text(
            f"[plan] mode={plan_mode} prompt={prompt_name} "
            f"existing_specs={len(existing_specs)} imported_sources={len(imported_source_paths)}\n"
        )
        forced = " (forced by --overwrite)" if overwrite else ""
        on_text(f"[plan] {mode_label}{forced}\n")
    conformed_specs: list[Path] = []
    conform_warnings: list[str] = []
    if reuse_mode:
        # Conform any reusable spec whose Programmatic Acceptance is empty: keep its
        # substance, restructure into the Drydock header + four sections, and author
        # test-driven assertions. Runs before normalization so the reuse prompt and the
        # MANIFEST are built from already-conformed specs.
        if conform:
            try:
                conformed_specs, conform_warnings = conform_specs(
                    existing_specs,
                    blueprint_dir,
                    today=today,
                    target=target,
                    runner=runner,
                    model=model,
                    llm_provider=llm_provider,
                    log_dir=log_dir,
                    on_text=on_text,
                )
            except Exception as exc:
                record = write_error_record(
                    target_dir,
                    command="plan",
                    phase="LLM conformance",
                    classification="LLM conformance failed",
                    detail=str(exc),
                    evidence=log_dir,
                    recovery=f"Correct the conformance failure, then run: drydock plan {target}",
                )
                from drydock.quarterdeck_state import refresh_commanders_chair

                refresh_commanders_chair(target_dir)
                raise RecordedError(record) from exc
            if conformed_specs:
                existing_specs = _collect_existing_typed_specs(
                    blueprint_dir, excluded_filenames=excluded_filenames
                )
        reusable_spec_paths, normalized_existing = _normalize_existing_specs(
            existing_specs, today=today, built=frozenset(prior_applied_specs)
        )
        if on_text is not None:
            on_text(
                "[plan] reuse-mode: preserving existing Blueprint specs, normalizing headers, "
                "and generating MANIFEST.md plus any missing files.\n"
            )

    prompt = load_prompt(prompt_name)
    prompt_assembly = _assemble_prompt_assembly(
        prompt.body,
        target_dir,
        blueprint_dir,
        analysis_text,
        today,
        feedback_text=feedback_for_prompt,
        input_tokens=prompt.input_tokens,
        excluded_filenames=excluded_filenames,
        typed_spec_paths=reusable_spec_paths,
        source_evidence=_source_evidence_bundle(
            blueprint_dir, analysis_text, excluded_filenames=excluded_filenames
        ),
        built_ledger=built_ledger,
    )

    try:
        result = cast(
            CompletedRun,
            run(
                prompt_assembly.rendered_text,
                target_dir,
                llm=llm_provider,
                model=model or prompt.model,
                command_name="plan",
                parameters={"target": target, "blueprint": str(blueprint_dir)},
                log_dir=log_dir,
                target=target,
                on_text=on_text,
                prompt_assembly=prompt_assembly,
            ),
        )
    except Exception as exc:
        record = write_error_record(
            target_dir,
            command="plan",
            phase="LLM execution",
            classification="LLM execution failed",
            detail=str(exc),
            recovery=f"Correct the provider or execution issue, then run: drydock plan {target}",
        )
        from drydock.quarterdeck_state import refresh_commanders_chair

        refresh_commanders_chair(target_dir)
        raise RecordedError(record) from exc
    exec_id = getattr(result, "execution_id", None)
    if not result.ok or not result.text.strip():
        detail = result.text.strip() or result.stderr.strip()
        record = write_error_record(
            target_dir,
            command="plan",
            phase="LLM execution",
            classification="LLM execution failed",
            detail=detail,
            execution_id=result.execution_id,
            evidence=log_dir,
            recovery=f"Inspect the execution evidence, then run: drydock plan {target}",
        )
        from drydock.quarterdeck_state import refresh_commanders_chair

        refresh_commanders_chair(target_dir)
        raise RecordedError(record)

    validated_plan: BuildPlan | None = None
    validated_warnings: tuple[str, ...] = ()
    # Whether the plan was serialized from a topology declaration, in which case the schedule is
    # already computed and the merge path must not re-derive it.
    declared_topology = False
    latest_plan_score: PlanScore | None = None
    waiver_execution_id: str | None = None
    waiver_warning: str | None = None
    # The delimited response the blocks came from, tracked so the pairing check measures the
    # right text. Write-call recovery produces blocks with no delimiters, and clears this.
    blocks_text: str | None = result.text
    try:
        blocks = _parse_strict_blocks(result.text, result)
    except OutsideArtifactTextError as exc:
        try:
            recovered = _parse_write_call_blocks(result.text, target_dir, blueprint_dir)
        except SpecificationError as write_exc:
            raise _record_plan_error(
                target_dir,
                classification="model artifact contract failed",
                detail=str(write_exc),
                execution_id=exec_id,
                log_dir=log_dir,
                recovery=(
                    "Inspect the execution evidence, correct the plan artifact, then run: "
                    f"drydock plan {target}"
                ),
            ) from write_exc
        if recovered:
            blocks = recovered
            blocks_text = None
        else:
            blocks = exc.blocks
            declared_topology = TOPOLOGY_BLOCK in blocks
            (
                validated_plan,
                validated_warnings,
                waiver_execution_id,
                waiver_warning,
            ) = _approve_outside_text_candidate(
                exc,
                blueprint_dir=blueprint_dir,
                target_dir=target_dir,
                target=target,
                result=result,
                execution_id=exec_id,
                allow_diagnostic_recovery=allow_diagnostic_recovery,
                llm_provider=llm_provider,
                model=model,
                log_dir=log_dir,
                runner=run,
                on_text=on_text,
            )
    except SpecificationError as exc:
        reported_exc = exc
        try:
            recovered = _parse_write_call_blocks(result.text, target_dir, blueprint_dir)
        except SpecificationError as write_exc:
            reported_exc = write_exc
            recovered = {}
        if recovered:
            blocks = recovered
            blocks_text = None
        else:
            raise _record_plan_error(
                target_dir,
                classification="model artifact contract failed",
                detail=str(reported_exc),
                execution_id=exec_id,
                log_dir=log_dir,
                recovery=(
                    "Inspect the execution evidence, correct the plan input if needed, then run: "
                    f"drydock plan {target}"
                ),
            ) from reported_exc
    if validated_plan is None:
        deferred_block = blocks.get("PLAN_CREATE_ERROR.txt") or blocks.get(
            "PLAN_CREATE_BLOCKED.txt"
        )
        if deferred_block is not None and set(blocks) in (
            {"PLAN_CREATE_ERROR.txt"},
            {"PLAN_CREATE_BLOCKED.txt"},
        ):
            initial_declaration = deferred_block.strip()
            challenge_exec_id: str | None = None
            if allow_diagnostic_recovery:
                if on_text is not None:
                    on_text(
                        "[plan] model declared a product conflict; challenging its assumptions\n"
                    )
                challenge_assembly = _conflict_challenge_assembly(
                    prompt_assembly,
                    declaration=initial_declaration,
                    initial_execution_id=exec_id,
                )
                try:
                    challenge_result = cast(
                        CompletedRun,
                        run(
                            challenge_assembly.rendered_text,
                            target_dir,
                            llm=llm_provider,
                            model=model or prompt.model,
                            command_name="plan",
                            parameters={
                                "target": target,
                                "blueprint": str(blueprint_dir),
                                "conflict_challenge": True,
                                "initial_execution_id": exec_id or "",
                            },
                            log_dir=log_dir,
                            target=target,
                            on_text=on_text,
                            prompt_assembly=challenge_assembly,
                        ),
                    )
                except Exception as challenge_exc:
                    raise _record_conflict_challenge_failure(
                        target_dir,
                        target=target,
                        initial_declaration=initial_declaration,
                        initial_execution_id=exec_id,
                        challenge_execution_id=None,
                        failure=f"{type(challenge_exc).__name__}: {challenge_exc}",
                        log_dir=log_dir,
                    ) from challenge_exc
                challenge_exec_id = getattr(challenge_result, "execution_id", None)
                if not challenge_result.ok or not challenge_result.text.strip():
                    challenge_failure = (
                        challenge_result.text.strip()
                        or challenge_result.stderr.strip()
                        or "The challenge execution returned no output."
                    )
                    raise _record_conflict_challenge_failure(
                        target_dir,
                        target=target,
                        initial_declaration=initial_declaration,
                        initial_execution_id=exec_id,
                        challenge_execution_id=challenge_exec_id,
                        failure=challenge_failure,
                        log_dir=log_dir,
                    )
                try:
                    challenge_blocks = _parse_strict_blocks(challenge_result.text, challenge_result)
                except Exception as challenge_exc:
                    raise _record_conflict_challenge_failure(
                        target_dir,
                        target=target,
                        initial_declaration=initial_declaration,
                        initial_execution_id=exec_id,
                        challenge_execution_id=challenge_exec_id,
                        failure=str(challenge_exc),
                        log_dir=log_dir,
                    ) from challenge_exc
                confirmed = challenge_blocks.get("PLAN_CREATE_ERROR.txt") or challenge_blocks.get(
                    "PLAN_CREATE_BLOCKED.txt"
                )
                if confirmed is not None and set(challenge_blocks) in (
                    {"PLAN_CREATE_ERROR.txt"},
                    {"PLAN_CREATE_BLOCKED.txt"},
                ):
                    if not _confirmed_conflict_is_source_cited(confirmed):
                        raise _record_conflict_challenge_failure(
                            target_dir,
                            target=target,
                            initial_declaration=initial_declaration,
                            initial_execution_id=exec_id,
                            challenge_execution_id=challenge_exec_id,
                            failure=(
                                "The challenge repeated a conflict without the required exact "
                                "source citations, Reason section, and Required action section.\n\n"
                                f"Challenge declaration:\n{confirmed.strip()}"
                            ),
                            log_dir=log_dir,
                        )
                    deferred_block = confirmed.strip()
                else:
                    blocks = challenge_blocks
                    blocks_text = challenge_result.text
                    result = challenge_result
                    exec_id = challenge_exec_id
                    deferred_block = None
            if deferred_block is not None:
                record = _record_confirmed_plan_conflict(
                    target_dir,
                    target=target,
                    declaration=deferred_block,
                    initial_declaration=initial_declaration,
                    initial_execution_id=exec_id,
                    challenge_execution_id=challenge_exec_id,
                    log_dir=log_dir,
                )
                return PlanDeferredResult(
                    target_dir=target_dir,
                    error_record=record,
                    errors_path=errors_path(target_dir),
                    detail=record.detail,
                    initial_execution_id=record.execution_id or None,
                    challenge_execution_id=record.challenge_execution_id or None,
                    plan_mode=plan_mode,
                )
            # Stage 1 freezes the declaration. Stage 2 then authors its Blueprint files in bounded
            # batches. Only a delimited response carries the evidence needed to distinguish a cut
            # artifact from a complete one, so write-call recovery keeps the original behavior.
        if continue_attempts > 0 and blocks_text is not None and TOPOLOGY_BLOCK in blocks:
            # Coverage is checked here, against the frozen declaration, so an uncovered
            # analyzed story costs one repair call rather than the whole Stage 2 spend.
            blocks[TOPOLOGY_BLOCK] = _repair_declaration_coverage(
                blocks[TOPOLOGY_BLOCK],
                blueprint_dir=blueprint_dir,
                target=target,
                target_dir=target_dir,
                llm_provider=llm_provider,
                model=model or prompt.model,
                log_dir=log_dir,
                runner=run,
                on_text=on_text,
                attempts=continue_attempts,
                initial_execution_id=exec_id,
            )
            declared_stories, _ = parse_topology(blocks[TOPOLOGY_BLOCK])
            if declared_stories:
                continuation = _continue_short_plan(
                    blocks,
                    blocks_text=blocks_text,
                    prompt_assembly=prompt_assembly,
                    declared=declared_stories,
                    target=target,
                    target_dir=target_dir,
                    llm_provider=llm_provider,
                    model=model or prompt.model,
                    log_dir=log_dir,
                    runner=run,
                    on_text=on_text,
                    attempts=continue_attempts,
                    initial_execution_id=exec_id,
                )
                latest_plan_score = continuation.score
                if continuation.passes:
                    blocks = continuation.blocks
                    # The merged set spans several responses and can no longer be pairing-checked
                    # as one text; each contribution was already checked against its own response.
                    blocks_text = None
                    if not continuation.score.is_complete:
                        raise _record_plan_error(
                            target_dir,
                            classification="plan generation stalled",
                            detail=(
                                "Blueprint generation stalled after TOPOLOGY.md was accepted "
                                f"and frozen, after {continuation.passes} Stage 2 pass(es).\n"
                                f"{continuation.score.render()}\n"
                                "  execution ids: "
                                + ", ".join(continuation.execution_ids)
                                + "\n  No Blueprint or Manifest artifacts were written."
                            ),
                            execution_id=exec_id,
                            log_dir=log_dir,
                            recovery=(
                                f"Inspect the failed Stage 2 batch, then run: drydock plan {target}"
                            ),
                        )
        try:
            declared_topology = TOPOLOGY_BLOCK in blocks
            candidate_blocks = dict(blocks)
            plan, warnings = _validate_plan_output(
                candidate_blocks,
                blueprint_dir,
                result,
                source_text=blocks_text,
                project=target,
            )
            blocks = candidate_blocks
        except Exception as exc:
            repair_exc = exc
            repair_succeeded = False
            if (
                allow_diagnostic_recovery
                and continue_attempts > 0
                and TOPOLOGY_BLOCK in blocks
                and _is_repairable_topology_defect(exc)
            ):
                declaration = blocks[TOPOLOGY_BLOCK]
                for repair_pass in range(1, continue_attempts + 1):
                    if on_text is not None:
                        on_text(f"[plan] topology repair pass {repair_pass}/{continue_attempts}\n")
                    repair_assembly = _topology_repair_assembly(
                        declaration=declaration,
                        defect=str(repair_exc),
                        pass_number=repair_pass,
                    )
                    try:
                        repair_result = cast(
                            CompletedRun,
                            run(
                                repair_assembly.rendered_text,
                                target_dir,
                                llm=llm_provider,
                                model=model or prompt.model,
                                command_name="plan",
                                parameters={
                                    "target": target,
                                    "topology_repair_pass": repair_pass,
                                    "initial_execution_id": exec_id or "",
                                },
                                log_dir=log_dir,
                                target=target,
                                on_text=on_text,
                                prompt_assembly=repair_assembly,
                            ),
                        )
                        if not repair_result.ok or not repair_result.text.strip():
                            break
                        try:
                            repair_blocks = _parse_strict_blocks(repair_result.text, repair_result)
                        except OutsideArtifactTextError:
                            repair_blocks = _parse_repair_artifact_envelopes(repair_result.text)
                        if set(repair_blocks) != {TOPOLOGY_BLOCK}:
                            break
                        repaired_declaration = repair_blocks[TOPOLOGY_BLOCK]
                        if repaired_declaration == declaration:
                            break
                        declaration = repaired_declaration
                        repaired_blocks = dict(blocks)
                        repaired_blocks[TOPOLOGY_BLOCK] = declaration
                        candidate_blocks = dict(repaired_blocks)
                        try:
                            plan, warnings = _validate_plan_output(
                                candidate_blocks,
                                blueprint_dir,
                                repair_result,
                                source_text=None,
                                project=target,
                            )
                        except Exception as next_exc:
                            repair_exc = next_exc
                            if not _is_repairable_topology_defect(next_exc):
                                break
                            continue
                        blocks = candidate_blocks
                        result = repair_result
                        exec_id = getattr(repair_result, "execution_id", None)
                        blocks_text = None
                        repair_succeeded = True
                        break
                    except Exception as next_exc:
                        repair_exc = next_exc
                        break
            if allow_diagnostic_recovery and continue_attempts > 0 and not repair_succeeded:
                repaired_blocks = dict(blocks)
                for repair_pass in range(1, continue_attempts + 1):
                    names = _repairable_artifact_names(repaired_blocks, str(repair_exc))
                    if not names:
                        break
                    if on_text is not None:
                        on_text(
                            f"[plan] artifact repair pass {repair_pass}/{continue_attempts} · "
                            f"{', '.join(names)}\n"
                        )
                    repair_assembly = _artifact_repair_assembly(
                        blocks=repaired_blocks,
                        names=names,
                        defect=str(repair_exc),
                        pass_number=repair_pass,
                    )
                    try:
                        repair_result = cast(
                            CompletedRun,
                            run(
                                repair_assembly.rendered_text,
                                target_dir,
                                llm=llm_provider,
                                model=model or prompt.model,
                                command_name="plan",
                                parameters={
                                    "target": target,
                                    "artifact_repair_pass": repair_pass,
                                    "initial_execution_id": exec_id or "",
                                    "artifacts": ",".join(names),
                                },
                                log_dir=log_dir,
                                target=target,
                                on_text=on_text,
                                prompt_assembly=repair_assembly,
                            ),
                        )
                        if not repair_result.ok or not repair_result.text.strip():
                            break
                        try:
                            repair_blocks = _parse_strict_blocks(repair_result.text, repair_result)
                        except OutsideArtifactTextError:
                            repair_blocks = _parse_repair_artifact_envelopes(repair_result.text)
                        if set(repair_blocks) != set(names):
                            break
                        if all(repair_blocks[name] == repaired_blocks[name] for name in names):
                            break
                        repaired_blocks.update(repair_blocks)
                        candidate_blocks = dict(repaired_blocks)
                        try:
                            plan, warnings = _validate_plan_output(
                                candidate_blocks,
                                blueprint_dir,
                                repair_result,
                                source_text=None,
                                project=target,
                            )
                        except Exception as next_exc:
                            repair_exc = next_exc
                            continue
                        blocks = candidate_blocks
                        result = repair_result
                        exec_id = getattr(repair_result, "execution_id", None)
                        blocks_text = None
                        repair_succeeded = True
                        break
                    except Exception as next_exc:
                        repair_exc = next_exc
                        break
            if not repair_succeeded:
                exc = repair_exc
                record = write_error_record(
                    target_dir,
                    command="plan",
                    phase="post-output validation",
                    classification="plan output validation failed",
                    detail=f"{exc}\n  No files were changed.",
                    execution_id=exec_id,
                    evidence=log_dir,
                    recovery=f"Correct the plan input or model artifact, then run: drydock plan {target}",
                )
                from drydock.quarterdeck_state import refresh_commanders_chair

                refresh_commanders_chair(target_dir)
                raise RecordedError(record) from exc
    else:
        plan, warnings = validated_plan, validated_warnings

    if declared_topology and latest_plan_score is not None and on_text is not None:
        on_text(
            "[plan-score]"
            + replace(latest_plan_score, manifest_serialized=True).progress_block(
                stage="STAGE 3 · MANIFEST",
                result="Manifest validated and serialized",
            )
        )

    requirement_decisions = project_plan_requirement_decisions(
        blocks, target_dir=target_dir, build_dir=build_dir_for(target)
    )
    if requirement_decisions:
        warnings = (
            *warnings,
            "Acceptance tooling authorization required: "
            + ", ".join(item.id for item in requirement_decisions),
        )

    # A fresh import may preserve reusable specs. A replan has full authority over every Plan-owned
    # output, including specifications previously used by Build.
    _protected: frozenset[str] = (
        frozenset() if replanning or overwrite else frozenset(prior_applied_specs)
    )

    emitted_blueprints = {
        name: content for name, content in blocks.items() if name not in _RESERVED_BLOCKS
    }
    context_warnings = _prepare_manifest_in_memory(
        plan,
        blueprint_dir=blueprint_dir,
        emitted_files=emitted_blueprints,
        compass_sources=frozenset(
            path for path, role in source_roles.items() if role.plan_disposition == "compass"
        ),
        prior_applied_specs=prior_applied_specs,
        prior_block_states=prior_block_states,
        schedule_computed=declared_topology,
    )
    plan.path = plan_path
    blocks["MANIFEST.md"] = plan.render()

    # 1. Author the typed Blueprint spec files (everything that is not a reserved block).
    authored: list[Path] = []
    for name, content in blocks.items():
        if name in _RESERVED_BLOCKS:
            continue
        dest = _safe_blueprint_path(blueprint_dir, name)
        if name in _protected:
            authored.append(dest)
            continue
        _write_text(dest, content)
        authored.append(dest)

    # Imported sources remain immutable provenance.  Planning projects build-facing assets
    # into Blueprint paths and routes author intent into the persistent Compass.
    promote_imported_sources(blueprint_dir, source_roles, target_dir)

    # 1.5. Reconcile significant design decisions Plan disclosed against retained
    # Commander-authored answers, and persist DECISIONS.json — the sole persistence target for
    # these disclosures (see notes/notes_plan.md §Significant decisions surface as DECISIONS.json).
    fresh_decisions = (
        *parse_plan_decisions(blocks.get(DECISIONS_BLOCK, "[]")),
        *requirement_decisions,
    )
    story_for_spec = {
        str(name): block.block_id
        for block in plan.blocks
        if block.block_type == "story"
        for name in (
            block.fields.get("implements", ())
            if isinstance(block.fields.get("implements", ()), tuple)
            else (block.fields.get("implements", ""),)
        )
        if name
    }
    fresh_decisions = tuple(
        replace(item, story=story_for_spec.get(item.blueprint, item.story))
        for item in fresh_decisions
    )
    allowed_blueprints = frozenset(emitted_blueprints) | {ARCHITECTURE_BLUEPRINT}
    fresh_decisions, decision_warnings = validate_decision_blueprints(
        fresh_decisions, allowed_blueprints
    )
    decisions_path = target_dir / DECISIONS_FILENAME
    merged_decisions = reconcile_decisions(fresh_decisions, load_decisions(decisions_path))
    write_decisions(decisions_path, merged_decisions)

    # 2. Persist the already merged, normalized, fully validated executable graph once.
    plan.save(plan_path)
    _record_plan_lineage(
        target_dir,
        blueprint_dir,
        plan,
        runner=runner,
        model=model,
        llm_provider=llm_provider,
        log_dir=log_dir,
        target=target,
    )
    from drydock.question_gates import synchronize_manifest_question_gates

    plan = synchronize_manifest_question_gates(plan_path, blueprint_dir)
    _clear_plan_compass_blockers(target_dir)

    # 4. The in-memory graph now reflects the target path and persisted artifact.

    # SOUNDINGS.md is not written here. `drydock score ac` reads the Blueprint, runs the
    # assertions, and emits the board with its verdicts.
    changed = prior_manifest != (plan_path.read_text(encoding="utf-8"))
    quarterdeck = _write_quarterdeck(plan, target_dir)

    increment_version(target_dir)
    set_build_state(target_dir, "planned")
    set_sub_state(target_dir, "approved")
    stamp_last(target_dir, "planned")

    from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

    _refresh_chair(target_dir)

    unique_waivers = dedupe_waivers(waivers)
    stamp_override(target_dir, unique_waivers)

    return PlanCreateResult(
        plan=plan,
        target_dir=target_dir,
        quarterdeck_dir=quarterdeck,
        changed=changed,
        authored_files=tuple(sorted({*authored, *normalized_existing, *conformed_specs})),
        warnings=tuple([
            *([waiver_warning] if waiver_warning else []),
            *stack_warnings,
            *conform_warnings,
            *warnings,
            *context_warnings,
            *decision_warnings,
        ]),
        execution_id=exec_id,
        waiver_execution_id=waiver_execution_id,
        plan_mode=plan_mode,
        conformed_files=tuple(conformed_specs),
        waivers=unique_waivers,
    )
