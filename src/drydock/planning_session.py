"""``drydock plan create`` — LLM-driven authoring of the Blueprint and executable Manifest.

`plan create` implements the reviewed analysis. In one LLM call it rewrites the imported source
material into typed Blueprint specification files and the executable ``MANIFEST.md`` — all as
delimited ``=== NAME ===`` blocks. The Manifest is the single work graph: it carries build order,
grouping, and per-step prompt-assembly fields, so no separate build-ordering file is emitted.
The module parses the blocks, runs a deterministic integrity gate, and writes the files.

When a prior MANIFEST.md exists, a state-preserving merge runs after the new Manifest is written:
``applied_specs`` is restored verbatim, block states are carried forward for clean files (sha256
unchanged), dirty files (sha256 changed) are reset to ``pending``, and applied Blueprint files are
protected from overwrite. The model emits text; the module writes files. Tests inject a fake runner
and never spend API credits.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256 as _sha256
from pathlib import Path
from typing import Protocol, cast

from drydock.acceptance import PYTHON_FENCE_RE
from drydock.build_plan import (
    AppliedSpecRecord,
    BuildPlan,
    disambiguate_manifest_ids,
    parse_build_plan,
    set_applied_specs,
)
from drydock.corpus import CorpusFile, discover_corpus
from drydock.errors import RecordedError, SpecificationError, clear_error_record, write_error_record
from drydock.exclude_files import ensure_exclude_file, load_excluded_filenames
from drydock.llm import run_prompt
from drydock.manifest_edit import batch_set_block_fields
from drydock.metadata import increment_version, set_build_state, set_sub_state, stamp_last
from drydock.paths import get_prompts_root
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_fenced_parts,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompt_context import prompt_source_header
from drydock.prompt_headers import prompt_header_for_file
from drydock.prompts import load_prompt
from drydock.sea_trials import parse_sea_trials_text
from drydock.source_roles import parse_source_roles, promote_imported_sources
from drydock.standard_artifacts import ensure_standard_artifacts, render_console

PROMPT_NAME = "plan_create"

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_OPEN_BLOCK_LINE_RE = re.compile(r"^=== (?P<name>[^\n=]+?) ===\s*$", re.MULTILINE)
_END_BLOCK_LINE_RE = re.compile(r"^=== END (?P<name>[^\n=]+?) ===\s*$", re.MULTILINE)
_WRITE_CALL_RE = re.compile(
    r'<invoke name="Write">\s*'
    r'<parameter name="file_path">(?P<path>.*?)</parameter>\s*'
    r'<parameter name="content">(?P<content>.*?)</parameter>\s*'
    r"</invoke>",
    re.DOTALL,
)
_FUNCTION_WRAPPER_RE = re.compile(r"</?function_calls>\s*")
_IGNORABLE_OUTSIDE_LINE_RE = re.compile(
    r"^(?:Continuing|Next|Proceeding|Writing|Now writing)\b.*$",
    re.IGNORECASE,
)
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_PLANNING_INSTRUCTIONS_RE = re.compile(r"^## Planning Instructions\s*$", re.MULTILINE)
_SOURCE_CITATION_RE = re.compile(r"(?<![A-Za-z0-9_.-])(sources/[A-Za-z0-9_./-]+)")
_SHAPE_RE = re.compile(r"Project type:\s*`?([A-Za-z][\w-]*)`?", re.MULTILINE)
# Block names the LLM emits that are not authored Blueprint spec files.
_RESERVED_BLOCKS = frozenset({"MANIFEST.md", "PLAN_CREATE_BLOCKED.txt", "PLAN_CREATE_ERROR.txt"})
_NON_BLUEPRINT_ARTIFACTS = frozenset({"AGENTS.md"})

_CONTRACT_FILES = ("MANIFEST_CONTRACT.md", "BLUEPRINTS_CONTRACT.md")

# Hard cap on story count; plan create refuses to emit an over-decomposed plan.
_STORY_CAP = 100

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
    "Open Questions",
)
_TYPED_HEADING_RE = re.compile(r"^#\s+(?P<kind>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?P<name>.+?)\s*$")
_HEADER_ROW_RE = re.compile(r"^\|\s*(?P<field>[^|]+?)\s*\|\s*(?P<value>.*?)\s*\|$")
_TERMINAL_SECTION_RE = re.compile(
    r"^## (?P<heading>Programmatic Acceptance|User Acceptance|Guardrails|Open Questions)\s*$"
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
    plan_mode: str = ""
    conformed_files: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ExistingSpec:
    path: Path
    filename: str
    file_type: str
    object_name: str
    header_fields: dict[str, str]
    body: str
    reusable: bool


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


def _strip_leading_preamble(text: str) -> str:
    """Discard benign narration emitted before the first artifact delimiter.

    The model occasionally prefixes the artifact stream with a sentence explaining
    what it is about to emit (common in reuse mode, e.g. "Blueprint already contains
    all required specs, so I'm emitting only MANIFEST.md."). When a valid opening
    delimiter follows and nothing before it looks like a delimiter, drop the preamble
    rather than failing an otherwise-complete plan. A ``===`` anywhere in the leading
    text is left intact so the strict parser still rejects malformed or partial blocks.
    """
    first_open = _OPEN_BLOCK_LINE_RE.search(text)
    if first_open is None:
        return text
    leading = text[: first_open.start()]
    if not leading.strip() or "===" in leading:
        return text
    return text[first_open.start() :]


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
    text = _strip_leading_preamble(text)
    blocks = _parse_strict_blocks_by_line(text, result)
    _reject_unpaired_end_delimiters(text, blocks, result)
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


def _parse_strict_blocks_by_line(text: str, result: CompletedRun) -> dict[str, str]:
    blocks: dict[str, str] = {}
    current_name: str | None = None
    current_body: list[str] = []
    outside: list[str] = []
    saw_delimiter = False

    for line in text.splitlines(keepends=True):
        open_match = _OPEN_BLOCK_LINE_RE.match(line.strip())
        end_match = _END_BLOCK_LINE_RE.match(line.strip())
        if current_name is None:
            if open_match:
                if _has_substantive_outside_text("".join(outside), after_artifacts=saw_delimiter):
                    raise SpecificationError(
                        _with_execution_evidence(
                            "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                            "  Text appeared outside delimited artifact blocks.\n"
                            "  No Blueprint or Manifest artifacts were written.",
                            result,
                        )
                    )
                current_name = open_match.group("name").strip()
                current_body = []
                outside = []
                saw_delimiter = True
                continue
            outside.append(line)
            continue
        if end_match and end_match.group("name").strip() == current_name:
            if current_name in blocks:
                raise SpecificationError(
                    _with_execution_evidence(
                        "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                        f"  Duplicate artifact block: {current_name}\n"
                        "  No Blueprint or Manifest artifacts were written.",
                        result,
                    )
                )
            blocks[current_name] = "".join(current_body).strip()
            current_name = None
            current_body = []
            saw_delimiter = True
            continue
        current_body.append(line)

    if current_name is not None:
        if current_name in blocks:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    f"  Duplicate artifact block: {current_name}\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )
        blocks[current_name] = "".join(current_body).strip()
        saw_delimiter = True

    if _has_substantive_outside_text("".join(outside), after_artifacts=saw_delimiter):
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                "  Text appeared outside delimited artifact blocks.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )
    return blocks if saw_delimiter else {}


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
        if path == target_root / "MANIFEST.md":
            name = "MANIFEST.md"
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
    if not text.strip():
        return False
    if not after_artifacts:
        return True
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _IGNORABLE_OUTSIDE_LINE_RE.match(stripped):
            continue
        return True
    return False


def _read_if(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


# ── Replan state merge ─────────────────────────────────────────────────────────


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes()).hexdigest()


def _load_prior_plan_state(
    plan_path: Path,
) -> tuple[dict[str, AppliedSpecRecord], dict[str, tuple[str, str | None]]]:
    """Parse an existing MANIFEST.md and extract preservation state.

    Returns (applied_specs, {block_id → (state, finding)}).  Returns empty dicts
    when the manifest does not exist or cannot be parsed.  ``finding`` is non-None
    only for spike blocks that carry a non-empty finding text.
    """
    if not plan_path.is_file():
        return {}, {}
    try:
        prior = parse_build_plan(plan_path)
    except Exception:
        return {}, {}
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
    return dict(prior.applied_specs), block_states


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
    return _file_sha256(spec_path) != record.sha256


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
    - A block whose implements: files are all clean (sha256 unchanged) carries its prior
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

        dirty = any(
            _spec_is_dirty(str(spec), blueprint_dir, prior_applied_specs)
            for spec in implements
            if spec
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
        for entry in discover_corpus(blueprint_dir, excluded_filenames=excluded_filenames)
        if entry.text is not None
    ]


def _source_evidence_bundle(
    blueprint_dir: Path,
    analysis_text: str,
    *,
    excluded_filenames: frozenset[str],
) -> list[CorpusFile] | None:
    """Return Analyze-cited prompt evidence; ``None`` preserves legacy full-corpus plans."""
    if not _PLANNING_INSTRUCTIONS_RE.search(analysis_text):
        return None
    corpus = discover_corpus(blueprint_dir, excluded_filenames=excluded_filenames)
    if not corpus:
        return []
    cited = set(_SOURCE_CITATION_RE.findall(analysis_text))
    if not cited:
        raise SpecificationError(
            "ANALYSIS.md Planning Instructions contain no `sources/...` evidence citations. "
            "Re-run analyze or add cited source evidence before planning."
        )
    by_path = {entry.relative_path: entry for entry in corpus}
    missing = sorted(cited - set(by_path))
    if missing:
        raise SpecificationError(
            "ANALYSIS.md cites source path(s) not present in the imported corpus: "
            + ", ".join(missing)
        )
    unusable = sorted(path for path in cited if by_path[path].text is None)
    if unusable:
        raise SpecificationError(
            "ANALYSIS.md cites source path(s) that cannot be injected as readable evidence: "
            + ", ".join(unusable)
        )
    return [entry for entry in corpus if entry.relative_path in cited and entry.text is not None]


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


def _has_stack_selection(target_dir: Path) -> bool:
    """Return whether QuarterDeck has persisted a non-empty stack selection."""
    path = target_dir / "QuarterDeck" / "questionnaires" / "discovery-stack.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for question in data.get("questions", []):
        if question.get("id") != "stack_components":
            continue
        answer = question.get("answer", "")
        if isinstance(answer, str):
            return bool(answer.strip())
        if isinstance(answer, list):
            return any(str(value).strip() for value in answer)
        return bool(answer)
    return False


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
    source_evidence: list[CorpusFile] | None = None,
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

    def typed_spec_parts() -> list:
        parts_list = [
            lines_part(
                "Imported source file header", ["## Imported source files", ""], kind="section"
            )
        ]
        if source_evidence is not None:
            corpus = source_evidence
        elif typed_spec_paths is not None:
            corpus = [
                CorpusFile(
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
        else:
            corpus = [
                entry
                for entry in discover_corpus(blueprint_dir, excluded_filenames=excluded_filenames)
                if entry.text is not None
            ]
        for entry in corpus:
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
# referring to it. Naming the corpus file — asserting it is staged, or importing a
# helper beside it — is not execution.
_CORPUS_INVOCATION_RE = re.compile(
    r"subprocess|sys\.executable|os\.system|check_output|check_call|Popen|runpy"
    r"|\bpython[\d.]*\b|\bpytest\b",
    re.IGNORECASE,
)

# Explicit opt-in that makes a full-corpus story gate deliberate rather than accidental.
_CORPUS_FULL_RE = re.compile(r"^Corpus:\s*full\s*$", re.MULTILINE | re.IGNORECASE)


def _invokes_unbounded_corpus(acceptance: str) -> bool:
    """Report whether the acceptance section runs a conformance corpus it never declared.

    Story acceptance is bounded by default so an ordinary check cannot accidentally invoke a
    whole suite: it may stage the corpus, or select a slice with ``--pattern`` / ``--number``.
    The terminal verification story gates on the real corpus by declaring ``Corpus: full`` in
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
        if not _CORPUS_INVOCATION_RE.search(window):
            continue
        # The declaration sits in the heading block above the fenced code.
        if _CORPUS_FULL_RE.search("\n".join(lines[: index + 1])):
            continue
        return True
    return False


# A programmatic story should carry at least this many assertions before it stops
# drawing a test-driven-acceptance warning.
_MIN_ASSERTIONS_PER_STORY = 2


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

    def spec_text(name: str) -> str | None:
        if name in emitted_files:
            return emitted_files[name]
        path = blueprint_dir / name
        return path.read_text(encoding="utf-8") if path.is_file() else None

    story_count = 0
    executable_with_empty_depends = False
    for block in plan.blocks:
        if block.block_type in ("story", "spike") and not block.depends:
            executable_with_empty_depends = True
        if block.block_type != "story":
            continue
        story_count += 1
        implements = block.fields.get("implements", ())
        targets = implements if isinstance(implements, tuple) else (implements,)
        for name in targets:
            if name and name not in available_specs and not (blueprint_dir / name).is_file():
                fatal.append(f"{block.block_id}: implements missing spec file {name!r}")
        # Every story must carry at least one acceptance gate — hard emission gate.
        has_ac = any(b.block_type == "ac" and b.parent == block.block_id for b in plan.blocks)
        if not has_ac:
            fatal.append(f"{block.block_id}: story has no acceptance check")

        # Test-driven-acceptance coverage — a hard emission gate, like the child-ac
        # gate above. A story whose implemented specs declare a programmatic surface
        # must carry several concrete Python assertions unless an inline-justified
        # `- None.` explains the absence.
        surface = False
        justified = False
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
        if surface and not justified and assertions < _MIN_ASSERTIONS_PER_STORY:
            fatal.append(
                f"{block.block_id}: {assertions} Programmatic Acceptance assertion(s) across "
                "its implemented spec(s), which declare a programmatic surface; author several "
                "concrete Python assertions (test-driven acceptance) or justify `- None.` inline"
            )
        for name in targets:
            text = spec_text(name) if name else None
            # Scope to the acceptance section. A spec may name the corpus in prose
            # (a Test Strategy bullet) without any story check ever executing it.
            acceptance = (
                _extract_terminal_section(text, "Programmatic Acceptance") if text else None
            )
            if acceptance and _invokes_unbounded_corpus(acceptance):
                fatal.append(
                    f"{block.block_id}: Programmatic Acceptance invokes an unbounded "
                    "conformance corpus; keep it in SEA_TRIALS.md final measurement"
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

    # Reject an over-decomposed plan.
    if story_count > _STORY_CAP:
        fatal.append(f"story count {story_count} exceeds the ~{_STORY_CAP}-story cap")

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
    with tempfile.TemporaryDirectory(prefix="drydock-plan-") as tmp:
        path = Path(tmp) / "MANIFEST.md"
        _write_text(path, text)
        return parse_build_plan(path)


def _validate_plan_output(
    blocks: dict[str, str], blueprint_dir: Path, result: CompletedRun
) -> tuple[BuildPlan, tuple[str, ...]]:
    """Validate one LLM response mode and return the parsed plan for success mode."""
    mode_blocks = {"MANIFEST.md", "PLAN_CREATE_BLOCKED.txt", "PLAN_CREATE_ERROR.txt"} & set(blocks)

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
                "Plan generation failed: LLM output missing === MANIFEST.md === block.\n"
                "  The response must contain only delimited artifact blocks.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    if mode_blocks != {"MANIFEST.md"}:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output mixed response modes.\n"
                "  SUCCESS MODE must not include PLAN_CREATE_BLOCKED.txt or PLAN_CREATE_ERROR.txt.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    # Guarantee unique block ids before validation: the model may reuse one slug
    # for a feature and its sole same-named story. Disambiguate in place so the
    # unique-id manifest is what gets validated and written to the target.
    blocks["MANIFEST.md"] = disambiguate_manifest_ids(blocks["MANIFEST.md"])
    plan = _parse_plan_text(blocks["MANIFEST.md"])

    emitted_specs = frozenset(name for name in blocks if name not in _RESERVED_BLOCKS)
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
    warnings = tuple(
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


# ── Entry point ─────────────────────────────────────────────────────────────────────


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
) -> PlanCreateResult:
    """Author the Blueprint and executable Manifest from the reviewed analysis."""
    target_dir = target_directory / target
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
    if not _has_stack_selection(target_dir):
        raise SpecificationError(
            "Technology Stack questionnaire is unanswered — select applicable Rigging components "
            "in QuarterDeck before planning."
        )

    plan_path = target_dir / "MANIFEST.md"
    prior_manifest = _read_if(plan_path)
    prior_applied_specs, prior_block_states = _load_prior_plan_state(plan_path)
    # In overwrite mode nothing is protected: every regenerated spec is written so the
    # rewrite (e.g. freshly authored programmatic acceptance) actually lands on disk.
    if overwrite:
        prior_applied_specs = {}

    # Standing-directive feedback file — created if absent, never overwritten, injected when the
    # user has edited it beyond the default placeholder.
    feedback_text = ensure_feedback_file(target_dir)
    ensure_exclude_file(target_dir)
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
    # A replan preserves only what has been built; the rest is prior plan output and is
    # regenerated. Deleting first means mode selection, the reuse prompt's "emit the
    # missing files" instruction, and `typed_spec_paths` all see the built set alone.
    # `--overwrite` cleared prior_applied_specs above, so it discards every spec.
    discarded_specs = _discard_unbuilt_specs(
        blueprint_dir, prior_applied_specs, excluded_filenames=excluded_filenames
    )
    if discarded_specs and on_text is not None:
        on_text(
            f"[plan] discarding {len(discarded_specs)} unbuilt Blueprint spec(s) for "
            f"regeneration: {', '.join(discarded_specs)}\n"
        )
    existing_specs = _collect_existing_typed_specs(
        blueprint_dir, excluded_filenames=excluded_filenames
    )
    # `--overwrite` forces a full rewrite: ignore existing specs for mode selection so
    # the Blueprint is regenerated from the analysis rather than preserved.
    reuse_mode = not overwrite and _is_reuse_candidate(existing_specs)
    speckit_mode = not overwrite and not reuse_mode and _is_speckit_source(blueprint_dir)
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
            # Conformance is itself an LLM call in reuse mode. Its inputs are now
            # fully preflighted, so it follows the same current-error lifecycle.
            clear_error_record(target_dir)
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
    )

    # Preflight is complete. A retry now retires the prior current error immediately
    # before its replacement LLM call; failed preflight attempts never reach here.
    clear_error_record(target_dir)
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

    try:
        blocks = _parse_strict_blocks(result.text, result)
    except SpecificationError:
        recovered = _parse_write_call_blocks(result.text, target_dir, blueprint_dir)
        if not recovered:
            record = write_error_record(
                target_dir,
                command="plan",
                phase="post-output validation",
                classification="model artifact contract failed",
                detail="The model output did not contain a complete plan artifact.",
                execution_id=exec_id,
                evidence=log_dir,
                recovery=f"Inspect the execution evidence, correct the plan input if needed, then run: drydock plan {target}",
            )
            from drydock.quarterdeck_state import refresh_commanders_chair

            refresh_commanders_chair(target_dir)
            raise RecordedError(record)
        blocks = recovered
    try:
        plan, warnings = _validate_plan_output(blocks, blueprint_dir, result)
    except Exception as exc:
        record = write_error_record(
            target_dir,
            command="plan",
            phase="post-output validation",
            classification="plan output validation failed",
            detail=str(exc),
            execution_id=exec_id,
            evidence=log_dir,
            recovery=f"Correct the plan input or model artifact, then run: drydock plan {target}",
        )
        from drydock.quarterdeck_state import refresh_commanders_chair

        refresh_commanders_chair(target_dir)
        raise RecordedError(record) from exc

    # Applied (built) Blueprint files are protected: the LLM's regenerated version is
    # discarded so delivered code keeps the spec it was built against. A clean file also
    # keeps its sha256 stable, letting the merge confirm the story needs no re-run; a
    # file the author edited keeps the author's content, and `_merge_prior_state` returns
    # that block to `pending` so the story rebuilds against the edit.
    _protected: frozenset[str] = frozenset(prior_applied_specs)

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
    promote_imported_sources(blueprint_dir, parse_source_roles(analysis_text), target_dir)

    # 2. The executable plan. Write the LLM output, then merge prior block states and
    #    restore applied_specs so that closed/verified work and the graph database survive
    #    a replan. Dirty blocks (implements: sha256 changed) are left at pending.
    _write_text(plan_path, blocks["MANIFEST.md"])
    _merge_prior_state(plan_path, blueprint_dir, prior_applied_specs, prior_block_states)
    context_warnings = _normalize_manifest_contexts(plan_path, blueprint_dir)

    # 4. Re-read the written Manifest so result paths reflect the target artifact.
    plan = parse_build_plan(plan_path)

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

    return PlanCreateResult(
        plan=plan,
        target_dir=target_dir,
        quarterdeck_dir=quarterdeck,
        changed=changed,
        authored_files=tuple(sorted({*authored, *normalized_existing, *conformed_specs})),
        warnings=tuple([*conform_warnings, *warnings, *context_warnings]),
        execution_id=exec_id,
        plan_mode=plan_mode,
        conformed_files=tuple(conformed_specs),
    )
