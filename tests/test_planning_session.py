"""Tests for the LLM-driven ``drydock plan create`` (planning_session.create_plan).

A fake runner supplies canned delimited-block output; no API credits are spent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock import artifact_blocks, technology_stack
from drydock import planning_session as ps
from drydock.acceptance import (
    parse_programmatic_acceptance,
    parse_programmatic_acceptance_text,
    unresolved_globals,
)
from drydock.build_plan import AppliedSpecRecord, parse_build_plan
from drydock.errors import RecordedError, SpecificationError
from drydock.plan_graph import PlannedStory
from drydock.plan_score import artifact_defect, score_plan
from drydock.planning_session import (
    PLAN_TOPOLOGY_CONTRACT,
    PlanDeferredResult,
    _answered_discovery,
    _artifact_delimiter_defects,
    _assemble_prompt,
    _assemble_prompt_assembly,
    _load_prior_plan_state,
    _normalize_existing_specs,
    _parse_blocks,
    _parse_strict_blocks,
    _render_ledger,
    _repair_missing_leading_delimiter,
    _repairable_artifact_names,
    _spec_is_conformant,
    _spec_is_dirty,
    advisory_plan_shape,
    check_plan_shape,
    create_plan,
    ensure_feedback_file,
)


def _pa(*intents: str) -> str:
    """Render a canonical Programmatic Acceptance body.

    Each intent becomes one ``### check-N`` heading plus a fenced ``python``
    assertion block — the format the build engine executes and the plan gate
    counts. One intent yields one counted check.
    """
    blocks = []
    for index, intent in enumerate(intents, start=1):
        blocks.append(f"### check-{index}\n{intent}\n\n```python\nassert True\n```")
    return "\n\n".join(blocks)


def _pa_code(*snippets: str) -> str:
    """Like ``_pa`` but each fenced block holds a caller-supplied assertion line,
    so route paths appear inside the section for test-driven route coverage.

    The binding line matters: every check runs as its own script, so a snippet that read an
    unbound ``client`` would be unsatisfiable by construction and the plan would strip it
    before these route assertions could be measured.
    """
    blocks = []
    for index, code in enumerate(snippets, start=1):
        body = f"from app import client\n{code}"
        blocks.append(f"### check-{index}\nRoute acceptance {index}.\n\n```python\n{body}\n```")
    return "\n\n".join(blocks)


#: A minimal ``## Access Patterns`` section that ``parse_database_contract`` accepts. Plan gates
#: the operation surface because Build reads it through ``database_operation_fingerprints``.
_ACCESS_PATTERNS = (
    "## Access Patterns\n\n"
    "### FEATURE-X-001 — Read setting\n\n"
    "| Field | Value |\n|---|---|\n"
    "| Owner | FEATURE-Example.md |\n"
    "| Access | read |\n"
    "| Repository operation | `settings.get` |\n"
    "| Compatibility | rebuild |\n\n"
    "Input: GetSetting\n\n"
    "| Field | Type | Required |\n|---|---|---|\n| key | str | yes |\n\n"
    "Output: Setting\n\n"
    "| Field | Type |\n|---|---|\n| key | str |\n\n"
)


def test_default_feedback_heading_is_plan_compass(tmp_path):
    assert ensure_feedback_file(tmp_path) == "# Plan Compass\n"


def test_a_private_in_memory_database_criterion_is_a_store_defect():
    """The defect the deleted DATABASE.md normalizer guarded against is now refused directly."""
    from drydock.acceptance_store import store_setup_defects

    code = (
        "import sqlite3\n"
        'conn = sqlite3.connect(":memory:")\n'
        'assert conn.execute("SELECT name FROM sqlite_master").fetchall()\n'
    )

    assert any("in-memory database" in reason for reason in store_setup_defects(code))
    assert store_setup_defects("import sqlite3\nsqlite3.connect('data/app.db')\n") == ()


def test_plan_prompt_declares_strict_artifact_contract():
    prompt = (Path(__file__).parents[1] / "prompts" / "plan_create.md").read_text(encoding="utf-8")

    assert "Emit exactly one response mode" in prompt
    assert "### Success Mode" in prompt
    assert "=== BEGIN ARTIFACT PLAN_CREATE_ERROR.txt ===" in prompt
    assert "=== END ARTIFACT ===" in prompt
    assert "Never emit `TOPOLOGY.md` in Error Mode or Blocked Mode" in prompt
    assert "Never emit `MANIFEST.md`; Drydock serializes it from `TOPOLOGY.md`." in prompt
    assert "Every `implements:` filename in `TOPOLOGY.md` must name exactly one" in prompt
    assert "Do not emit any Blueprint specification in this response" in prompt
    assert "Never emit `AGENTS.md`." in prompt
    assert "The response is processed by a deterministic parser." in prompt
    assert "Now the Manifest." in prompt
    # Shape conformance is a checker, not an instruction: the prompt no longer asks the model to
    # audit its own delimiters, block completeness, or topological consistency. Drydock measures
    # all of it against the declared output contract after the response.
    assert "Do not audit your own output for delimiter balance" in prompt
    assert "Before responding, verify:" not in prompt


def test_stage_one_prompt_includes_read_only_built_work_ledger(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)

    assembly = _assemble_prompt_assembly(
        "Plan.",
        target,
        blueprint,
        "System Shape: service\nQuality: Ready\n",
        "2026-08-02",
        input_tokens=(),
        built_ledger=(
            "story_id=core; specification=FEATURE-CORE.md; applied_sha256=abc; build_sha256=def",
        ),
    )

    text = assembly.rendered_text
    assert "## Built Work Ledger (read-only)" in text
    assert "story_id=core; specification=FEATURE-CORE.md" in text


def test_plan_continue_prompt_requires_closed_sequential_blueprints():
    prompt = (Path(__file__).parents[1] / "prompts" / "plan_continue.md").read_text(
        encoding="utf-8"
    )

    assert "Stage 1 is complete" in prompt
    assert "Do not emit or amend `TOPOLOGY.md`" in prompt
    assert re.search(r"Only after the closing delimiter is\s+written", prompt)
    assert "Never pre-emit opening delimiters" in prompt


def test_stage_two_ledger_exposes_only_one_bounded_blueprint_batch():
    stories = tuple(
        PlannedStory(
            story_id=f"story-{index}",
            name=f"Story {index}",
            story_type="feature",
            phase=1,
            delivery_kind="capability",
            acceptance_contract=True,
            implements=f"FEATURE-{index}.md",
        )
        for index in range(1, 8)
    )

    ledger = _render_ledger(score_plan(stories, {"TOPOLOGY.md": "complete"}))

    assert "Current batch (5)" in ledger
    assert "Deferred (2)" in ledger
    assert "FEATURE-5.md" in ledger
    assert "FEATURE-6.md" not in ledger
    assert "FEATURE-7.md" not in ledger


def test_plan_prompt_separates_final_sea_trial_traceability_from_story_execution():
    prompt = (Path(__file__).parents[1] / "prompts" / "plan_create.md").read_text(encoding="utf-8")

    assert "`accepts:` is human-readable traceability, not a child acceptance command" in prompt
    # Sea Trials flow into planning and nothing points back: no proof tag, no coverage audit.
    assert "Sea Trials:" not in prompt
    assert "traceability audit" not in prompt


def test_all_plan_prompts_scope_repository_guardrails_and_require_source_cited_conflicts():
    prompts = Path(__file__).parents[1] / "prompts"

    for name in ("plan_create.md", "plan_reuse.md", "plan_create_speckit.md"):
        text = (prompts / name).read_text(encoding="utf-8")
        assert "Marina/application-managed files are distinct from repository" in text
        assert "do not imply a file inside a Git checkout" in text
        assert "repository-write guardrail applies only" in text
        assert "scoped to discovery or registration does not govern runtime" in text
        assert "Missing detail is not a conflict" in text
        assert "exact files, clauses, and scopes" in text


def test_validate_plan_output_rejects_agents_artifact(tmp_path):
    from drydock.planning_session import _validate_plan_output

    manifest = _manifest(implements="AGENTS.md")
    blocks = {
        "MANIFEST.md": manifest,
        "AGENTS.md": "# AGENTS\n",
    }

    with pytest.raises(SpecificationError, match="Forbidden artifact\\(s\\): AGENTS.md"):
        _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))


_ANALYSIS = """# Blueprint Analysis: Example
generated: 2026-06-16
blueprint: bp

Quality: Questions
  stories: 2
  stack: python

## Story List

Project type: `cli`

| ID | Story | File |
|---|---|---|
| arch | Architecture | ARCHITECTURE.md |
| status | Status command | FEATURE-Status.md |
"""

# The canonical Programmatic Acceptance body for the shared spec fixture: two
# ``### check-N`` + fenced ``python`` blocks — the format the build engine runs
# and the plan gate counts. Named so tests can swap it for `- None.` variants.
_SPEC_HEADER_PA_BODY = (
    "### check-1\n"
    "The {name} route responds with HTTP 200.\n\n"
    "```python\nassert True\n```\n\n"
    "### check-2\n"
    "The {name} handler returns the documented payload keys.\n\n"
    "```python\nassert True\n```"
)

_SPEC_HEADER = (
    """# {ftype}: {name}

| Field       | Value |
|-------------|-------|
| Version     | 20260616 V1 |
| Description | {name} contract. |
| Depends On  | |
| Provides    | drydock status |
| Phase       | 1 |

## Programmatic Acceptance

"""
    + _SPEC_HEADER_PA_BODY
    + """

## User Acceptance

- {ac}

## Guardrails

- None.
"""
)


def _select_sqlite(target_dir: Path) -> None:
    """Approve Python with SQLite, so DATABASE.md criteria may import ``persistence``."""
    from drydock.technology_stack import StackEntry, write

    write(
        target_dir,
        [StackEntry("Python", "python.md"), StackEntry("SQLite", "sqlite.md")],
        approved="2026-10-19",
    )


def _operation_criteria(text: str, *verbs: str) -> str:
    """Replace a DATABASE.md fixture's criteria with one calling each ``settings`` operation."""
    body = "".join(
        f"### settings-{verb}\n"
        f"The settings {verb} operation answers.\n\n"
        "```python\n"
        "from persistence.testing import db_session\n\n"
        "with db_session() as db:\n"
        f"    result = db.settings.{verb}(key='k')\n"
        "    print(result)\n"
        "```\n\n"
        for verb in verbs
    )
    head, tail = text.split("## Programmatic Acceptance\n\n", 1)
    return (
        head
        + "## Programmatic Acceptance\n\n"
        + body
        + "## User Acceptance"
        + (tail.split("## User Acceptance", 1)[1])
    )


def _manifest(story_state: str = "pending", implements: str = "FEATURE-Status.md") -> str:
    return f"""# MANIFEST: Example
updated: 2026-06-16
plan_hash: test
state: draft

## feature 1: Status
id: feature-status
summary: Deliver the status command.
state: pending

## story 1: Deliver Status
id: story-status
parent: feature-status
summary: Build the status command.
implements: {implements}
scope: both
state: {story_state}

## ac 1: Status command exits successfully
id: ac-status-exits
parent: story-status
kind: assertion
state: pending
"""


def _llm_output(manifest: str | None = None) -> str:
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    )
    return (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{manifest or _manifest()}\n=== END MANIFEST.md ===\n"
    )


# ── Conform-pass fixtures ─────────────────────────────────────────────────────
# A conformant ARCHITECTURE.md (carries assertions) plus a non-conformant FEATURE
# whose Programmatic Acceptance is a bare ``- None.`` and which still carries an
# imported ``## Test`` prose section. Reuse mode selects because ARCHITECTURE.md exists.

_ARCH_CONFORMANT = (
    "# ARCHITECTURE: Example\n\n"
    "| Field       | Value |\n|-------------|-------|\n"
    "| Version     | 20260630 V1 |\n| Description | Existing architecture |\n"
    "| Depends On  | |\n| Provides    | |\n| Phase       | 1 |\n\n"
    "## Modules\n\n- Architecture body.\n\n"
    "## Programmatic Acceptance\n\n"
    + _pa("The architecture package imports cleanly.")
    + "\n\n## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n"
)

_FEATURE_EMPTY_ACCEPTANCE = (
    "# FEATURE: Status\n\n"
    "| Field       | Value |\n|-------------|-------|\n"
    "| Version     | 20260528 V1 |\n| Description | Status feature. |\n"
    "| Depends On  | ARCHITECTURE.md |\n| Provides    | drydock status |\n| Phase       | 2 |\n\n"
    "## Trigger\n\n- User runs drydock status.\n\n"
    "## Test\n\n- Verify status prints the build state.\n\n"
    "## Programmatic Acceptance\n\n- None.\n\n"
    "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n"
)

_FEATURE_CONFORMED_BODY = (
    "# FEATURE: Status\n\n"
    "| Field       | Value |\n|-------------|-------|\n"
    "| Version     | 20260706 V1 |\n| Description | Status feature. |\n"
    "| Depends On  | ARCHITECTURE.md |\n| Provides    | drydock status |\n| Phase       | 2 |\n\n"
    "## Trigger\n\n- User runs drydock status.\n\n"
    "## Programmatic Acceptance\n\n"
    + _pa(
        "The status command exits with code 0.",
        "The status output names the current build state.",
    )
    + "\n\n## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n"
)

_REUSE_TWO_STORY_MANIFEST = (
    "# MANIFEST: Example\n"
    "updated: 2026-06-16\n"
    "plan_hash: test\n"
    "state: draft\n\n"
    "## feature 1: Status\n"
    "id: feature-status\n"
    "summary: Deliver the status command.\n"
    "state: pending\n\n"
    "## story 1: Architecture Foundation\n"
    "id: foundation\n"
    "parent: feature-status\n"
    "summary: Keep the architecture specification as the foundation.\n"
    "implements: ARCHITECTURE.md\n"
    "scope: both\n"
    "state: pending\n\n"
    "## ac 1: Architecture foundation exists\n"
    "id: ac-foundation\n"
    "parent: foundation\n"
    "kind: assertion\n"
    "state: pending\n\n"
    "## story 2: Deliver Status\n"
    "id: story-status\n"
    "parent: feature-status\n"
    "summary: Build the status command.\n"
    "implements: FEATURE-Status.md\n"
    "scope: both\n"
    "depends: foundation\n"
    "state: pending\n\n"
    "## ac 2: Status command exits successfully\n"
    "id: ac-status-exits\n"
    "parent: story-status\n"
    "kind: assertion\n"
    "state: pending\n"
)


def _seed_conform_target(tmp_path: Path, *, feature_text: str) -> tuple[Path, Path]:
    """Create a reuse-mode target with a conformant ARCHITECTURE and the given FEATURE."""
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    (blueprint_dir / "ARCHITECTURE.md").write_text(_ARCH_CONFORMANT, encoding="utf-8")
    feature = blueprint_dir / "FEATURE-Status.md"
    feature.write_text(feature_text, encoding="utf-8")
    return target_dir, feature


def _conform_runner(conform_text: str, *, seen: list[str] | None = None):
    """Fake runner: return ``conform_text`` for a conform call, else the reuse manifest."""

    def runner(prompt_text, *a, **k):
        if "## Conform job" in prompt_text:
            if seen is not None:
                seen.append(prompt_text)
            return FakeRun(text=conform_text)
        return FakeRun(
            text=f"=== MANIFEST.md ===\n{_REUSE_TWO_STORY_MANIFEST}\n=== END MANIFEST.md ===\n"
        )

    return runner


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    stderr: str = ""
    execution_id: str = "exec-fake"


def _assert_recorded_error(
    excinfo: pytest.ExceptionInfo[RecordedError],
    target_dir: Path,
    *,
    classification: str,
    detail: str,
) -> None:
    record = excinfo.value.record
    assert record.command == "plan"
    assert record.phase in {"LLM execution", "post-output validation"}
    assert record.classification == classification
    assert detail in record.detail
    error_text = (target_dir / "ERRORS.md").read_text(encoding="utf-8")
    assert classification in error_text
    assert detail in error_text


@pytest.fixture(autouse=True)
def fake_compactor(monkeypatch):
    from drydock.diagnose import reset_diagnosis_guard

    reset_diagnosis_guard()

    def fake(prompt, working_directory, **kwargs):
        return FakeRun(text="# Compact\n\nBody\n", execution_id="compact-fake")

    monkeypatch.setattr("drydock.rigging_compact.run_prompt", fake)
    yield
    reset_diagnosis_guard()


def _fake(text: str):
    return lambda *a, **k: FakeRun(text=text)


# Delimiter pairing contract: every emitted file must be wrapped in a matching open/END pair.
# Regression for the commonmark plan failure where the model emitted open-only delimiters between
# files plus a single trailing `=== END MANIFEST.md ===`, silently collapsing the whole response
# into the first block so MANIFEST.md never parsed.

_OPEN_ONLY_OUTPUT = (
    "=== ARCHITECTURE.md ===\n"
    "# ARCHITECTURE\n"
    "=== FEATURE-Filter-Contract.md ===\n"
    "# FEATURE: Filter Contract\n"
    "=== MANIFEST.md ===\n"
    "# MANIFEST\n"
    "=== END MANIFEST.md ===\n"
)

_PAIRED_OUTPUT = (
    "=== ARCHITECTURE.md ===\n"
    "# ARCHITECTURE\n"
    "=== END ARCHITECTURE.md ===\n"
    "=== FEATURE-Filter-Contract.md ===\n"
    "# FEATURE: Filter Contract\n"
    "=== END FEATURE-Filter-Contract.md ===\n"
    "=== MANIFEST.md ===\n"
    "# MANIFEST\n"
    "=== END MANIFEST.md ===\n"
)


def test_strict_blocks_reject_open_only_delimiters():
    # Open-only delimiters collapse every file into the first still-open block, so the block the
    # parser judged is ARCHITECTURE.md and nothing survives it. The report names the artifact that
    # absorbed the stray delimiter and the delimiter itself, which is what an operator can act on.
    with pytest.raises(SpecificationError) as excinfo:
        _parse_strict_blocks(_OPEN_ONLY_OUTPUT, FakeRun(text=_OPEN_ONLY_OUTPUT))
    message = str(excinfo.value)
    assert "Delimiter pairing mismatch" in message
    assert "ARCHITECTURE.md" in message
    assert "=== FEATURE-Filter-Contract.md ===" in message


def test_strict_blocks_parse_paired_delimiters():
    blocks = _parse_strict_blocks(_PAIRED_OUTPUT, FakeRun(text=_PAIRED_OUTPUT))
    assert set(blocks) == {
        "ARCHITECTURE.md",
        "FEATURE-Filter-Contract.md",
        "MANIFEST.md",
    }


def test_strict_blocks_end_names_match_block_keys():
    from drydock.planning_session import _END_BLOCK_LINE_RE

    blocks = _parse_strict_blocks(_PAIRED_OUTPUT, FakeRun(text=_PAIRED_OUTPUT))
    end_names = {m.group("name").strip() for m in _END_BLOCK_LINE_RE.finditer(_PAIRED_OUTPUT)}
    assert end_names == set(blocks)


def test_strict_blocks_recover_transposed_artifact_boundary():
    output = (
        "=== FEATURE-Autolinks.md ===\n"
        "# FEATURE: Autolinks\n"
        "=== END FEATURE-Raw-HTML-Inline.md ===\n"
        "# FEATURE: Raw HTML Inline\n"
        "=== END FEATURE-Raw-HTML-Inline.md ===\n"
        "=== MANIFEST.md ===\n"
        "# MANIFEST\n"
        "=== END MANIFEST.md ===\n"
    )

    blocks = _parse_strict_blocks(output, FakeRun(text=output))

    assert blocks == {
        "FEATURE-Autolinks.md": "# FEATURE: Autolinks",
        "FEATURE-Raw-HTML-Inline.md": "# FEATURE: Raw HTML Inline",
        "MANIFEST.md": "# MANIFEST",
    }


def test_strict_blocks_recover_end_delimiter_used_as_opener():
    """Regression: the model wrapped every file in `END X` … `END X`, dropping every opener.

    The open-delimiter pattern used to match `=== END X ===` too, so each such file parsed under
    the corrupt name `END X` and the artifacts between the recovered boundaries were swallowed.
    """
    output = (
        "=== TOPOLOGY.md ===\n"
        "# TOPOLOGY\n"
        "=== END TOPOLOGY.md ===\n"
        "=== END FEATURE-Alpha.md ===\n"
        "# FEATURE: Alpha\n"
        "=== END FEATURE-Alpha.md ===\n"
        "=== END FEATURE-Beta.md ===\n"
        "# FEATURE: Beta\n"
        "=== END FEATURE-Beta.md ===\n"
    )

    blocks = _parse_strict_blocks(output, FakeRun(text=output))

    assert blocks == {
        "TOPOLOGY.md": "# TOPOLOGY",
        "FEATURE-Alpha.md": "# FEATURE: Alpha",
        "FEATURE-Beta.md": "# FEATURE: Beta",
    }


def test_strict_blocks_never_key_a_block_on_an_end_delimiter():
    output = (
        "=== END FEATURE-Alpha.md ===\n# FEATURE: Alpha\n=== END FEATURE-Alpha.md ===\n"
        "=== END MANIFEST.md ===\n# MANIFEST\n=== END MANIFEST.md ===\n"
    )

    blocks = _parse_strict_blocks(output, FakeRun(text=output))

    assert not [name for name in blocks if name.startswith("END ")]
    assert set(blocks) == {"FEATURE-Alpha.md", "MANIFEST.md"}


def test_strict_blocks_reject_delimiter_inside_a_parsed_body():
    output = (
        "=== FEATURE-Alpha.md ===\n"
        "# FEATURE: Alpha\n"
        "=== FEATURE-Beta.md ===\n"
        "# FEATURE: Beta\n"
        "=== END FEATURE-Alpha.md ===\n"
    )

    with pytest.raises(SpecificationError, match="Delimiter pairing mismatch"):
        _parse_strict_blocks(output, FakeRun(text=output))


def test_strict_blocks_reject_ambiguous_mismatched_end_delimiter():
    output = (
        "=== FEATURE-Autolinks.md ===\n"
        "# FEATURE: Autolinks\n"
        "=== END FEATURE-Raw-HTML-Inline.md ===\n"
        "# FEATURE: Raw HTML Inline\n"
        "=== FEATURE-Raw-HTML-Inline.md ===\n"
        "# FEATURE: Raw HTML Inline, second attempt\n"
        "=== END FEATURE-Raw-HTML-Inline.md ===\n"
    )

    with pytest.raises(SpecificationError, match="Delimiter pairing mismatch"):
        _parse_strict_blocks(output, FakeRun(text=output))


def test_strict_blocks_close_a_misnamed_close_by_position():
    # §30.2 — `=== END COMPASS ===` closing `=== COMPASS.md ===`. The close is recognised by
    # position; no block named after the marker is invented.
    output = (
        "=== ARCHITECTURE.md ===\n# ARCHITECTURE\n=== END ARCHITECTURE ===\n"
        "=== MANIFEST.md ===\n# MANIFEST\n=== END MANIFEST.md ===\n"
    )

    blocks = _parse_strict_blocks(output, FakeRun(text=output))

    assert blocks == {"ARCHITECTURE.md": "# ARCHITECTURE", "MANIFEST.md": "# MANIFEST"}


def test_strict_blocks_keep_the_artifacts_a_defect_did_not_touch():
    # §30.3 / P-3 — one unresolvable block costs itself, not the batch. The original parser
    # discarded all three, which is D-008.
    output = (
        "=== FEATURE-Alpha.md ===\n# FEATURE: Alpha\n=== END FEATURE-Alpha.md ===\n"
        "=== FEATURE-Beta.md ===\n# FEATURE: Beta\n"
        "=== FEATURE-Gamma.md ===\n# FEATURE: Gamma\n=== END FEATURE-Beta.md ===\n"
        "=== MANIFEST.md ===\n# MANIFEST\n=== END MANIFEST.md ===\n"
    )
    defects: list[str] = []

    blocks = _parse_strict_blocks(output, FakeRun(text=output), on_defect=defects.append)

    assert set(blocks) == {"FEATURE-Alpha.md", "MANIFEST.md"}
    assert [defect.split(":")[0] for defect in defects] == ["FEATURE-Beta.md"]


def test_strict_blocks_parse_the_invariant_boundary_form():
    # §30.4 — the name is typed once, at the open; the close is a constant token.
    output = (
        "=== BEGIN ARTIFACT ARCHITECTURE.md ===\n# ARCHITECTURE\n=== END ARTIFACT ===\n"
        "=== BEGIN ARTIFACT MANIFEST.md ===\n# MANIFEST\n=== END ARTIFACT ===\n"
    )

    blocks = _parse_strict_blocks(output, FakeRun(text=output))

    assert blocks == {"ARCHITECTURE.md": "# ARCHITECTURE", "MANIFEST.md": "# MANIFEST"}


def test_strict_blocks_keep_ac_containers_inside_their_blueprint():
    output = (
        "=== BEGIN ARTIFACT STORY-Login.md ===\n"
        "# STORY: Login\n"
        "=== AC login-1 ===\nassert True\n=== END AC login-1 ===\n"
        "=== END ARTIFACT ===\n"
    )

    blocks = _parse_strict_blocks(output, FakeRun(text=output))

    assert set(blocks) == {"STORY-Login.md"}
    assert "=== AC login-1 ===" in blocks["STORY-Login.md"]


def _make_target(tmp_path: Path, *, analysis: str | None = _ANALYSIS) -> Path:
    target_dir = tmp_path / "Example"
    sources = target_dir / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / "request.md").write_text("# Request\n\nBuild a status command.\n", encoding="utf-8")
    if analysis is not None:
        (target_dir / "ANALYSIS.md").write_text(analysis, encoding="utf-8")
    questionnaires = target_dir / "QuarterDeck" / "questionnaires"
    questionnaires.mkdir(parents=True, exist_ok=True)
    (questionnaires / "discovery-stack.json").write_text(
        json.dumps({
            "id": "discovery-stack",
            "questions": [{"id": "stack_components", "answer": "python.md"}],
        }),
        encoding="utf-8",
    )
    from drydock.technology_stack import StackEntry, write

    write(target_dir, [StackEntry("Python", "python.md")], approved="2026-10-19")
    return target_dir


def _mark_built(target_dir: Path, *spec_names: str, manifest: str | None = None) -> None:
    """Record specs in MANIFEST.md ``applied_specs``, as ``drydock build`` does on success."""
    import hashlib

    blueprint_dir = target_dir / "blueprint"
    body = manifest if manifest is not None else _manifest()
    lines = body.splitlines()
    header_at = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    records = ["applied_specs: |"]
    for name in sorted(spec_names):
        digest = hashlib.sha256((blueprint_dir / name).read_bytes()).hexdigest()
        records.append(
            f"  {name} sha256={digest} commit=- applied_by=story-status "
            "applied_at=2026-06-16T00:00:00"
        )
    lines[header_at:header_at] = [*records, ""]
    (target_dir / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_authors_specs_compass_and_manifest(tmp_path):
    target_dir = _make_target(tmp_path)
    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    bp = target_dir / "blueprint"
    assert (bp / "ARCHITECTURE.md").is_file()
    assert (bp / "FEATURE-Status.md").is_file()
    assert not (target_dir / "BUILD_COMPASS.md").exists()
    assert (target_dir / "MANIFEST.md").is_file()
    # SOUNDINGS.md belongs to `drydock score ac`, which reads the Blueprint, runs the
    # assertions, and emits the board with its verdicts. Plan does not write it.
    assert not (target_dir / "SOUNDINGS.md").exists()
    assert result.plan.state == "draft"
    assert {p.name for p in result.authored_files} == {"ARCHITECTURE.md", "FEATURE-Status.md"}
    assert result.warnings == ()
    # QuarterDeck projection written.
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()
    assert (target_dir / "QuarterDeck" / "console.yaml").is_file()
    planning = (target_dir / "QuarterDeck" / "planning-session.md").read_text(encoding="utf-8")
    assert "manifest build tree" in planning
    assert "Approve the complete plan" not in planning


def test_plan_uses_the_lineage_model_only_for_source_attribution(tmp_path):
    target_dir = _make_target(tmp_path)
    from drydock.lineage import record_initial_snapshot

    record_initial_snapshot(target_dir, target_dir / "blueprint" / "sources", date="2026-09-14")
    calls: list[dict[str, object]] = []

    def runner(*_args, **kwargs):
        calls.append(kwargs)
        if kwargs["command_name"] == "lineage_attribute":
            return FakeRun(text='<unattached story="story-status"/>')
        return FakeRun(text=_llm_output())

    create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        model="sonnet",
        lineage_model="haiku",
        llm_provider="claude",
    )

    plan_calls = [call for call in calls if call["command_name"] == "plan"]
    lineage_calls = [call for call in calls if call["command_name"] == "lineage_attribute"]
    assert plan_calls and lineage_calls
    assert {call["model"] for call in plan_calls} == {"sonnet"}
    assert {call["model"] for call in lineage_calls} == {"haiku"}
    assert {call["llm"] for call in calls} == {"claude"}


_DECISION_BLOCK = json.dumps([
    {
        "id": "Q-001",
        "type": "choice",
        "severity": "material",
        "blueprint": "ARCHITECTURE.md",
        "story": None,
        "title": "Pick a queue backend",
        "description": "The Blueprint is silent on which queue technology to use.",
        "options": [{"value": "sqs", "label": "AWS SQS"}, {"value": "redis", "label": "Redis"}],
        "system_choice": "sqs",
    }
])


def test_plan_writes_decisions_json_from_llm_disclosure(tmp_path):
    target_dir = _make_target(tmp_path)
    text = (
        _llm_output() + f"=== DECISIONS.json ===\n{_DECISION_BLOCK}\n=== END DECISIONS.json ===\n"
    )
    result = create_plan("Example", "Example", tmp_path, runner=_fake(text))

    decisions_path = target_dir / "DECISIONS.json"
    assert decisions_path.is_file()
    written = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert [d["id"] for d in written] == ["Q-001"]
    assert written[0]["origin"] == "plan"
    assert written[0]["status"] == "recommended"
    # DECISIONS.json is not a Blueprint spec file.
    assert {p.name for p in result.authored_files} == {"ARCHITECTURE.md", "FEATURE-Status.md"}
    assert not (target_dir / "blueprint" / "DECISIONS.json").exists()


def test_plan_emits_no_decisions_json_content_when_llm_discloses_none(tmp_path):
    target_dir = _make_target(tmp_path)
    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))
    assert json.loads((target_dir / "DECISIONS.json").read_text(encoding="utf-8")) == []


def test_replan_retains_only_commander_directed_decision(tmp_path):
    target_dir = _make_target(tmp_path)
    decisions_path = target_dir / "DECISIONS.json"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    decisions_path.write_text(
        json.dumps([
            {
                "id": "Q-001",
                "type": "choice",
                "severity": "material",
                "origin": "plan",
                "blueprint": "ARCHITECTURE.md",
                "story": None,
                "status": "answered",
                "archived": False,
                "title": "Pick a queue backend",
                "description": "stale",
                "options": [
                    {"value": "sqs", "label": "AWS SQS"},
                    {"value": "redis", "label": "Redis"},
                ],
                "system_choice": "sqs",
                "commander_direction": "redis",
            },
            {
                "id": "Q-999",
                "type": "text",
                "severity": "low",
                "origin": "plan",
                "blueprint": "ARCHITECTURE.md",
                "story": None,
                "status": "recommended",
                "archived": False,
                "title": "Never touched by a Commander",
                "description": "stale",
                "options": [],
                "system_choice": "stale",
            },
        ]),
        encoding="utf-8",
    )
    text = _llm_output() + "=== DECISIONS.json ===\n[]\n=== END DECISIONS.json ===\n"
    create_plan("Example", "Example", tmp_path, runner=_fake(text))

    written = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert [d["id"] for d in written] == ["Q-001"]
    assert written[0]["commander_direction"] == "redis"


def test_reuse_mode_preserves_existing_spec_bodies_and_plans_from_them(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    feature = blueprint_dir / "FEATURE-Status.md"
    architecture.write_text(
        "# ARCHITECTURE: Example\n\n"
        "| Field       | Value |\n"
        "|-------------|-------|\n"
        "| Version     | 20260630 V1 |\n"
        "| Description | Existing architecture |\n"
        "| Depends On  | |\n"
        "| Provides    | |\n"
        "| Phase       | 1 |\n\n"
        "## Modules\n\n"
        "- Preserve this architecture body.\n\n"
        "## Programmatic Acceptance\n\n" + _pa("The architecture package imports cleanly.") + "\n",
        encoding="utf-8",
    )
    feature.write_text(
        "# FEATURE: Status\n\n"
        "| Field       | Value |\n"
        "|-------------|-------|\n"
        "| Version     | 20260630 V1 |\n"
        "| Description | Existing status feature |\n"
        "| Depends On  | ARCHITECTURE.md |\n"
        "| Provides    | drydock status |\n"
        "| Phase       | 2 |\n\n"
        "## Trigger\n\n"
        "- Preserve this feature body.\n\n"
        "## Programmatic Acceptance\n\n"
        + _pa(
            "The status route responds with HTTP 200.",
            "The status payload names the current build state.",
        )
        + "\n",
        encoding="utf-8",
    )
    prompt_texts: list[str] = []
    progress: list[str] = []
    manifest = _manifest(implements="ARCHITECTURE.md").replace(
        "## story 1: Deliver Status\n"
        "id: story-status\n"
        "parent: feature-status\n"
        "summary: Build the status command.\n"
        "implements: ARCHITECTURE.md\n"
        "scope: both\n"
        "state: pending\n",
        "## story 1: Architecture Foundation\n"
        "id: foundation\n"
        "parent: feature-status\n"
        "summary: Keep the architecture specification as the foundation.\n"
        "implements: ARCHITECTURE.md\n"
        "scope: both\n"
        "state: pending\n"
        "\n"
        "## ac 1: Architecture foundation exists\n"
        "id: ac-foundation\n"
        "parent: foundation\n"
        "kind: assertion\n"
        "state: pending\n"
        "\n"
        "## story 2: Deliver Status\n"
        "id: story-status\n"
        "parent: feature-status\n"
        "summary: Build the status command.\n"
        "implements: FEATURE-Status.md\n"
        "scope: both\n"
        "depends: foundation\n"
        "state: pending\n",
    )

    def runner(prompt_text, *a, **k):
        prompt_texts.append(prompt_text)
        return FakeRun(text=f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n")

    result = create_plan("Example", "Example", tmp_path, runner=runner, on_text=progress.append)

    assert result.plan.state == "draft"
    assert next(line for line in progress if line.startswith("[plan] mode=")).startswith(
        "[plan] mode=reuse-manifest-first prompt=plan_reuse existing_specs=2 imported_sources=1"
    )
    assert "reuse-mode: preserving existing Blueprint specs" in "".join(progress)
    assert "# Request" in prompt_texts[0]
    assert "Preserve this architecture body." in prompt_texts[0]
    assert "Preserve this feature body." in prompt_texts[0]
    assert "Do not emit any existing conformant Blueprint file again." in prompt_texts[0]
    assert "## Programmatic Acceptance" in architecture.read_text(encoding="utf-8")
    # Initial imported specs keep their substance while Plan normalizes the governed envelope.
    assert "Preserve this architecture body." in architecture.read_text(encoding="utf-8")
    assert "Preserve this feature body." in feature.read_text(encoding="utf-8")


def test_overwrite_forces_full_rewrite_over_existing_specs(tmp_path):
    # Existing conformant specs would normally select reuse mode; --overwrite must
    # force a full rewrite and regenerate them from the analysis instead.
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    (blueprint_dir / "ARCHITECTURE.md").write_text(
        "# ARCHITECTURE: Example\n\n"
        "| Field       | Value |\n|-------------|-------|\n"
        "| Version     | 20260630 V1 |\n| Description | Existing architecture |\n"
        "| Depends On  | |\n| Provides    | |\n| Phase       | 1 |\n\n"
        "## Modules\n\n- Old architecture body.\n",
        encoding="utf-8",
    )
    (blueprint_dir / "FEATURE-Status.md").write_text(
        "# FEATURE: Status\n\n"
        "| Field       | Value |\n|-------------|-------|\n"
        "| Version     | 20260630 V1 |\n| Description | Existing status feature |\n"
        "| Depends On  | ARCHITECTURE.md |\n| Provides    | drydock status |\n| Phase       | 2 |\n\n"
        "## Trigger\n\n- Old feature body.\n",
        encoding="utf-8",
    )
    progress: list[str] = []
    prompt_texts: list[str] = []

    def runner(prompt_text, *a, **k):
        prompt_texts.append(prompt_text)
        return FakeRun(text=_llm_output())

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        overwrite=True,
        runner=runner,
        on_text=progress.append,
    )

    assert result.plan_mode == "full-rewrite"
    assert any("OVERWRITE mode" in line for line in progress)
    # The full-rewrite prompt (not plan_reuse) ran, and the regenerated body replaced the old one.
    assert "Do not emit any existing conformant Blueprint file again." not in "".join(prompt_texts)
    assert "Old feature body." not in (blueprint_dir / "FEATURE-Status.md").read_text(
        encoding="utf-8"
    )


def test_spec_is_conformant_predicate():
    # Real assertion → conformant.
    assert _spec_is_conformant(_ARCH_CONFORMANT)
    # Bare ``- None.`` acceptance → non-conformant.
    assert not _spec_is_conformant(_FEATURE_EMPTY_ACCEPTANCE)
    # Justified ``- None. <reason>`` → conformant.
    justified = _FEATURE_EMPTY_ACCEPTANCE.replace(
        "## Programmatic Acceptance\n\n- None.\n",
        "## Programmatic Acceptance\n\n- None. Pure manual visual check.\n",
    )
    assert _spec_is_conformant(justified)
    # No typed heading → non-conformant regardless of acceptance.
    assert not _spec_is_conformant("Just prose, no heading.\n")


def test_conform_authors_acceptance_for_empty_imported_spec(tmp_path):
    target_dir, feature = _seed_conform_target(tmp_path, feature_text=_FEATURE_EMPTY_ACCEPTANCE)
    conform_block = (
        f"=== FEATURE-Status.md ===\n{_FEATURE_CONFORMED_BODY}\n=== END FEATURE-Status.md ===\n"
    )
    seen: list[str] = []
    progress: list[str] = []

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=_conform_runner(conform_block, seen=seen),
        on_text=progress.append,
    )

    assert result.plan_mode == "reuse-manifest-first"
    # Only the non-conformant FEATURE was conformed; the conformant ARCHITECTURE was skipped.
    assert len(seen) == 1
    assert "FEATURE-Status.md" in seen[0]
    assert result.conformed_files == (feature,)
    assert result.warnings == ()
    assert "conforming 1 spec(s)" in "".join(progress)

    feature_text = feature.read_text(encoding="utf-8")
    assert "The status command exits with code 0." in feature_text
    assert "User runs drydock status." in feature_text  # imported substance preserved
    assert "## Test" not in feature_text  # imported test prose folded into acceptance


def test_conform_skips_already_conformant_spec(tmp_path):
    conformant_feature = _FEATURE_EMPTY_ACCEPTANCE.replace(
        "## Programmatic Acceptance\n\n- None.\n",
        "## Programmatic Acceptance\n\n"
        + _pa(
            "The status route responds with HTTP 200.",
            "The status payload names the current build state.",
        )
        + "\n",
    )
    _seed_conform_target(tmp_path, feature_text=conformant_feature)
    seen: list[str] = []

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=_conform_runner("unused", seen=seen),
    )

    assert seen == []  # no conform call issued
    assert result.conformed_files == ()


def test_conform_still_nonconformant_response_warns_and_preserves(tmp_path):
    target_dir, feature = _seed_conform_target(tmp_path, feature_text=_FEATURE_EMPTY_ACCEPTANCE)
    # The model returns the spec but leaves Programmatic Acceptance empty.
    still_empty = _FEATURE_CONFORMED_BODY.replace(
        "## Programmatic Acceptance\n\n"
        + _pa(
            "The status command exits with code 0.",
            "The status output names the current build state.",
        ),
        "## Programmatic Acceptance\n\n- None.",
    )
    block = f"=== FEATURE-Status.md ===\n{still_empty}\n=== END FEATURE-Status.md ===\n"

    # A story whose spec still carries no criterion after a failed conform pass fails the plan.
    del target_dir
    with pytest.raises(RecordedError, match="plan output validation failed"):
        create_plan(
            "Example",
            "Example",
            tmp_path,
            runner=_conform_runner(block),
        )

    # Original imported content is left intact when conform fails to author acceptance.
    assert "Verify status prints the build state." in feature.read_text(encoding="utf-8")


def test_no_conform_flag_skips_conform_pass(tmp_path):
    target_dir, feature = _seed_conform_target(tmp_path, feature_text=_FEATURE_EMPTY_ACCEPTANCE)
    seen: list[str] = []

    # Conform is suppressed, so the surface-declaring spec keeps its bare `- None.` acceptance,
    # and the story it implements has no criterion: the plan fails.
    del target_dir
    with pytest.raises(RecordedError, match="plan output validation failed"):
        create_plan(
            "Example",
            "Example",
            tmp_path,
            conform=False,
            runner=_conform_runner("unused", seen=seen),
        )

    assert seen == []  # conform pass suppressed
    # No conform pass ran, so no assertions were authored into the spec.
    assert "assert the status command" not in feature.read_text(encoding="utf-8")


def test_normalize_existing_specs_repairs_unbuilt_and_skips_built(tmp_path):
    """Header normalization repairs a malformed spec but never touches a built one.

    Restamping `Version` changes the file sha256, which would mark a built spec dirty
    and rebuild delivered work on every replan.
    """
    from drydock.planning_session import _collect_existing_typed_specs

    blueprint_dir = tmp_path / "blueprint"
    blueprint_dir.mkdir(parents=True)
    architecture = blueprint_dir / "ARCHITECTURE.md"
    architecture.write_text("Architecture overview only.\n", encoding="utf-8")
    feature = blueprint_dir / "FEATURE-Status.md"
    feature.write_text(
        "# FEATURE: Status\n\n## Trigger\n\n- Existing feature content.\n",
        encoding="utf-8",
    )
    built_before = feature.read_text(encoding="utf-8")

    specs = _collect_existing_typed_specs(blueprint_dir)
    _normalize_existing_specs(specs, today="2026-06-16", built=frozenset({"FEATURE-Status.md"}))

    arch_text = architecture.read_text(encoding="utf-8")
    assert arch_text.startswith("# ARCHITECTURE: Architecture")
    assert re.search(r"\| Version\s+\|\s+\d{8} V1 \|", arch_text)
    assert "## Programmatic Acceptance" in arch_text
    # The built spec keeps its malformed header rather than being restamped.
    assert feature.read_text(encoding="utf-8") == built_before


def test_cli_overrides_are_passed_to_runner(tmp_path):
    _make_target(tmp_path)
    calls = []

    def runner(*a, **k):
        calls.append(k)
        return FakeRun(text=_llm_output())

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        model="gpt-5.4",
        llm_provider="codex",
    )

    assert result.plan.state == "draft"
    assert calls[0]["model"] == "gpt-5.4"
    assert calls[0]["llm"] == "codex"


def test_full_rewrite_mode_reports_prompt_and_inventory(tmp_path):
    _make_target(tmp_path)
    progress: list[str] = []

    create_plan(
        "Example", "Example", tmp_path, runner=_fake(_llm_output()), on_text=progress.append
    )

    assert next(line for line in progress if line.startswith("[plan] mode=")).startswith(
        "[plan] mode=full-rewrite prompt=plan_create existing_specs=0 imported_sources=1"
    )


def test_speckit_source_selects_speckit_prompt(tmp_path):
    target_dir = _make_target(tmp_path)
    sources = target_dir / "blueprint" / "sources"
    (sources / "memory").mkdir(parents=True)
    (sources / "memory" / "constitution.md").write_text(
        "# Constitution\n\nBuild reliable software.\n", encoding="utf-8"
    )
    (sources / "specs" / "status").mkdir(parents=True)
    (sources / "specs" / "status" / "spec.md").write_text(
        "# Feature: Status\n\nUsers can check status.\n", encoding="utf-8"
    )

    progress: list[str] = []
    conversion_report = "# Conversion Report: Example\n\n## Mapped\n\n- None.\n"
    manifest = _manifest()
    text = (
        f"=== ARCHITECTURE.md ===\n"
        f"{_SPEC_HEADER.format(ftype='ARCHITECTURE', name='Example', ac='None.')}\n"
        f"=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n"
        f"{_SPEC_HEADER.format(ftype='FEATURE', name='Status', ac='None.')}\n"
        f"=== END FEATURE-Status.md ===\n"
        f"=== CONVERSION_REPORT.md ===\n{conversion_report}\n=== END CONVERSION_REPORT.md ===\n"
        f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"
    )

    result = create_plan(
        "Example", "Example", tmp_path, runner=_fake(text), on_text=progress.append
    )

    assert next(line for line in progress if line.startswith("[plan] mode=")).startswith(
        "[plan] mode=speckit-translate prompt=plan_create_speckit "
        "existing_specs=0 imported_sources=3"
    )
    assert (target_dir / "blueprint" / "CONVERSION_REPORT.md").read_text(
        encoding="utf-8"
    ) == conversion_report
    assert result.plan.project == "Example"


def _manifest_with_applied(story_state: str, spec_name: str, sha256: str, story_id: str) -> str:
    """Build a prior MANIFEST.md with applied_specs in the preamble."""
    return (
        f"# MANIFEST: Example\n"
        f"updated: 2026-06-16\n"
        f"plan_hash: test\n"
        f"state: draft\n"
        f"applied_specs: |\n"
        f"  {spec_name} sha256={sha256} commit=abc123 applied_by={story_id} applied_at=2026-06-01T00:00:00Z\n"
        f"\n"
        f"## feature 1: Status\n"
        f"id: feature-status\n"
        f"summary: Deliver the status command.\n"
        f"state: pending\n"
        f"\n"
        f"## story 1: Deliver Status\n"
        f"id: story-status\n"
        f"parent: feature-status\n"
        f"summary: Build the status command.\n"
        f"implements: {spec_name}\n"
        f"scope: both\n"
        f"state: {story_state}\n"
        f"\n"
        f"## ac 1: Status command exits successfully\n"
        f"id: ac-status-exits\n"
        f"parent: story-status\n"
        f"kind: assertion\n"
        f"state: pending\n"
    )


def _spec_sha256(path: Path) -> str:
    from hashlib import sha256 as _sha256

    return _sha256(path.read_bytes()).hexdigest()


def test_replan_resets_closed_block_when_authoritative_spec_changes(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    spec_file = blueprint_dir / "FEATURE-Status.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Feature\n", encoding="utf-8")

    prior = _manifest_with_applied(
        "closed/verified", "FEATURE-Status.md", _spec_sha256(spec_file), "story-status"
    )
    (target_dir / "MANIFEST.md").write_text(prior, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "state: closed/verified" not in text
    assert "state: pending" in text


def test_replan_resets_dirty_block_to_pending(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    spec_file = blueprint_dir / "FEATURE-Status.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Feature\n", encoding="utf-8")

    # Record a stale sha256 so the file appears dirty.
    prior = _manifest_with_applied(
        "closed/verified", "FEATURE-Status.md", "000000000000", "story-status"
    )
    (target_dir / "MANIFEST.md").write_text(prior, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "state: closed/verified" not in text
    assert "state: pending" in text


def test_replan_prunes_applied_spec_when_authoritative_spec_changes(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    spec_file = blueprint_dir / "FEATURE-Status.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Feature\n", encoding="utf-8")

    prior = _manifest_with_applied(
        "closed/verified", "FEATURE-Status.md", _spec_sha256(spec_file), "story-status"
    )
    (target_dir / "MANIFEST.md").write_text(prior, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    plan = parse_build_plan(target_dir / "MANIFEST.md")
    assert "FEATURE-Status.md" not in plan.applied_specs


def test_plan_references_build_time_compacts_without_generating_them(tmp_path):
    target_dir = _make_target(tmp_path)
    _select_sqlite(target_dir)
    # A persistence Blueprint declares its tables; an empty one fails the plan integrity check.
    db = _SPEC_HEADER.format(ftype="DATABASE", name="Example Data", ac="None.").replace(
        "## Programmatic Acceptance",
        _ACCESS_PATTERNS.replace("FEATURE-Example.md", "FEATURE-Status.md")
        + "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n\n"
        "## Programmatic Acceptance",
        1,
    )
    db = _operation_criteria(db, "get")
    # The declaration names FEATURE-Status.md as the owner of FEATURE-X-001, so it cites it.
    status = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    ).replace(
        "## Programmatic Acceptance",
        "## Database Interface\n\n"
        "- `FEATURE-X-001` — read: read a setting - supplies: `key` - returns: `key`\n\n"
        "## Programmatic Acceptance",
        1,
    )
    manifest = _manifest().replace(
        "scope: both\nstate: pending",
        "scope: both\ncontext: README.md, ARCHITECTURE.md\nstate: pending",
    )
    out = (
        f"=== ARCHITECTURE.md ===\n{_SPEC_HEADER.format(ftype='ARCHITECTURE', name='Example', ac='None.')}\n=== END ARCHITECTURE.md ===\n"
        f"=== DATABASE.md ===\n{db}\n=== END DATABASE.md ===\n"
        f"=== FEATURE-Status.md ===\n{status}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"
    )

    create_plan("Example", "Example", tmp_path, runner=_fake(out))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "context: README.md, ARCHITECTURE_compact.md, DATABASE_compact.md" in text
    assert not (target_dir / "blueprint" / "ARCHITECTURE_compact.md").exists()
    assert not (target_dir / "blueprint" / "DATABASE_compact.md").exists()


def test_compass_routed_source_is_dropped_from_manifest_context(tmp_path):
    """A sources/ context ref to a compass-routed (non-promoted) file is dropped, not rewritten.

    ED_INSTRUCTIONS.md is author intent: Analyze has synthesized it into COMPASS.md, so Plan
    neither appends it nor emits it into blueprint/. The LLM still references it as build
    context. The written Manifest must not carry a phantom ``ED_INSTRUCTIONS.md`` context that
    points at nothing in blueprint/.
    """
    analysis = _ANALYSIS + (
        "\n## Source Roles\n\n"
        "| path | role | plan | build |\n"
        "|---|---|---|---|\n"
        "| sources/ED_INSTRUCTIONS.md | instruction | compass | none |\n"
    )
    target_dir = _make_target(tmp_path, analysis=analysis)
    compass = target_dir / "COMPASS.md"
    compass.write_text("# COMPASS\n\n## Compass\nShort orientation.\n", encoding="utf-8")
    (target_dir / "blueprint" / "sources" / "ED_INSTRUCTIONS.md").write_text(
        "# Author Intent\n\nBuild it exactly this way.\n", encoding="utf-8"
    )
    manifest = _manifest().replace(
        "scope: both\nstate: pending",
        "scope: both\ncontext: sources/ED_INSTRUCTIONS.md\nstate: pending",
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "ED_INSTRUCTIONS.md" not in text
    assert "sources/" not in text
    assert compass.read_text(encoding="utf-8") == "# COMPASS\n\n## Compass\nShort orientation.\n"
    assert not (target_dir / "blueprint" / "ED_INSTRUCTIONS.md").exists()
    assert any("ED_INSTRUCTIONS.md" in w for w in result.warnings)


def test_promoted_source_context_keeps_stripped_blueprint_path(tmp_path):
    """A sources/ context ref that WAS promoted into blueprint/ keeps its stripped path."""
    analysis = _ANALYSIS + (
        "\n## Source Roles\n\n"
        "| path | role | plan | build |\n"
        "|---|---|---|---|\n"
        "| sources/examples.json | dataset | promote | stage |\n"
    )
    target_dir = _make_target(tmp_path, analysis=analysis)
    (target_dir / "blueprint" / "sources" / "examples.json").write_text("[]\n", encoding="utf-8")
    manifest = _manifest().replace(
        "scope: both\nstate: pending",
        "scope: both\ncontext: sources/examples.json\nstate: pending",
    )

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "context: examples.json" in text
    assert (target_dir / "blueprint" / "examples.json").is_file()


def test_replan_preserves_spike_finding(tmp_path):
    spike_manifest = """# MANIFEST: Example
updated: 2026-06-16
plan_hash: test
state: draft

## spike 1: Choose parser
id: spike-parser
summary: Pick the best parser.
state: closed/verified
finding: Use the stdlib csv module.

## story 1: Deliver Status
id: story-status
summary: Build the status command.
implements: FEATURE-Status.md
scope: both
state: pending

## ac 1: Status exits
id: ac-status-exits
parent: story-status
kind: assertion
state: pending
"""
    target_dir = _make_target(tmp_path)
    (target_dir / "MANIFEST.md").write_text(spike_manifest, encoding="utf-8")

    spike_llm = (
        "=== ARCHITECTURE.md ===\n"
        + _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
        + "\n=== END ARCHITECTURE.md ===\n"
        "=== FEATURE-Status.md ===\n"
        + _SPEC_HEADER.format(ftype="FEATURE", name="Status", ac="Status exits.")
        + "\n=== END FEATURE-Status.md ===\n"
        "=== MANIFEST.md ===\n"
        + spike_manifest.replace("finding: Use the stdlib csv module.", "finding:")
        + "\n=== END MANIFEST.md ===\n"
    )
    create_plan("Example", "Example", tmp_path, runner=_fake(spike_llm))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "Use the stdlib csv module" in text


def test_load_prior_plan_state_returns_empty_when_no_manifest(tmp_path):
    specs, states = _load_prior_plan_state(tmp_path / "MANIFEST.md")
    assert specs == {}
    assert states == {}


def test_invalid_existing_manifest_aborts_before_any_target_mutation(tmp_path):
    target_dir = _make_target(tmp_path)
    manifest_path = target_dir / "MANIFEST.md"
    manifest_path.write_text(
        "# MANIFEST: Example\n\n## story 1: Broken\nstate: pending\n",
        encoding="utf-8",
    )
    before = {
        path.relative_to(target_dir): path.read_bytes()
        for path in target_dir.rglob("*")
        if path.is_file()
    }

    def runner(*_args, **_kwargs):
        raise AssertionError("invalid deterministic input must not invoke the LLM")

    with pytest.raises(SpecificationError, match="missing required `id`"):
        create_plan("Example", "Example", tmp_path, runner=runner)

    after = {
        path.relative_to(target_dir): path.read_bytes()
        for path in target_dir.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_spec_is_dirty_false_when_no_applied_record(tmp_path):
    assert not _spec_is_dirty("FEATURE.md", tmp_path, {})


def test_spec_is_dirty_true_when_hash_changed(tmp_path):
    spec = tmp_path / "FEATURE.md"
    spec.write_text("changed content", encoding="utf-8")
    record = AppliedSpecRecord(
        path="FEATURE.md",
        sha256="000000000000",
        commit="-",
        applied_by="story-x",
        applied_at="2026-06-01T00:00:00Z",
    )
    assert _spec_is_dirty("FEATURE.md", tmp_path, {"FEATURE.md": record})


def test_spec_is_dirty_false_when_hash_matches(tmp_path):
    from hashlib import sha256

    spec = tmp_path / "FEATURE.md"
    spec.write_text("content", encoding="utf-8")
    digest = sha256(spec.read_bytes()).hexdigest()
    record = AppliedSpecRecord(
        path="FEATURE.md",
        sha256=digest,
        commit="-",
        applied_by="story-x",
        applied_at="2026-06-01T00:00:00Z",
    )
    assert not _spec_is_dirty("FEATURE.md", tmp_path, {"FEATURE.md": record})


def test_replan_preserves_closed_story_when_only_relationship_metadata_changes(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    output = _llm_output(_manifest(story_state="pending"))
    regenerated = _parse_blocks(output)["FEATURE-Status.md"]
    prior = regenerated.replace("| Depends On  | |", "| Depends On  | ARCHITECTURE.md |")
    assert prior != regenerated
    (blueprint_dir / "FEATURE-Status.md").write_text(prior, encoding="utf-8")
    _mark_built(
        target_dir,
        "FEATURE-Status.md",
        manifest=_manifest(story_state="closed/verified"),
    )

    create_plan("Example", "Example", tmp_path, runner=_fake(output))

    plan = parse_build_plan(target_dir / "MANIFEST.md")
    assert plan.by_id()["story-status"].state == "closed/verified"
    assert len(plan.applied_specs["FEATURE-Status.md"].build_sha256) == 64


def test_blocked_quality_refuses_before_llm(tmp_path):
    blocked = _ANALYSIS.replace("Quality: Questions", "Quality: Blocked")
    _make_target(tmp_path, analysis=blocked)

    def _boom(*a, **k):  # must never be called
        raise AssertionError("LLM runner called despite Blocked analysis")

    with pytest.raises(SpecificationError, match="Blocked"):
        create_plan("Example", "Example", tmp_path, runner=_boom)


def test_blockers_file_present_refuses(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "BLOCKERS.md").write_text("# Blockers\n\n- Q?\n", encoding="utf-8")
    with pytest.raises(SpecificationError, match="BLOCKERS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


def test_blockers_file_requires_reanalysis_even_when_stack_is_selected(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "BLOCKERS.md").write_text(
        "# Blockers\n\n## blocker-001: Technology stack selection\nSelect a stack.\n",
        encoding="utf-8",
    )
    questionnaires = target_dir / "QuarterDeck" / "questionnaires"
    questionnaires.mkdir(parents=True, exist_ok=True)
    (questionnaires / "discovery-stack.json").write_text(
        json.dumps({
            "id": "discovery-stack",
            "questions": [
                {"id": "stack_components", "input": "checkbox_grid", "answer": "python.md"}
            ],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="BLOCKERS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


def test_blockers_file_precedes_stack_questionnaire_gate(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "BLOCKERS.md").write_text(
        "# Blockers\n\n## blocker-stack-selection: Confirm technology stack\nSelect a stack.\n",
        encoding="utf-8",
    )
    questionnaires = target_dir / "QuarterDeck" / "questionnaires"
    questionnaires.mkdir(parents=True, exist_ok=True)
    (questionnaires / "discovery-stack.json").write_text(
        json.dumps({
            "id": "discovery-stack",
            "questions": [{"id": "stack_components", "input": "checkbox_grid", "answer": ""}],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="BLOCKERS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


@pytest.mark.parametrize("entries", [None, [], [technology_stack.StackEntry("Go", "go.md")]])
def test_missing_invalid_or_unapproved_stack_blocks_before_runner(tmp_path, entries):
    target_dir = _make_target(tmp_path)
    if entries is None:
        (target_dir / technology_stack.FILENAME).unlink()
    else:
        technology_stack.write(target_dir, entries)

    def runner(*args, **kwargs):
        pytest.fail("Invalid or unapproved stack reached LLM")

    with pytest.raises(SpecificationError, match="language|approval"):
        create_plan("Example", "Example", tmp_path, runner=runner)


def test_technology_stack_is_injected_into_the_plan_prompt(tmp_path):
    target_dir = _make_target(tmp_path)
    technology_stack.write(
        target_dir,
        [
            technology_stack.StackEntry("Python", "python.md"),
            technology_stack.StackEntry("FastAPI", "fastapi.md"),
            technology_stack.StackEntry("marina-library", None, "Internal."),
        ],
    )
    technology_stack.approve(target_dir)
    captured = {}

    def runner(*args, **kwargs):
        captured["assembly"] = kwargs.get("prompt_assembly")
        return FakeRun(text=_llm_output())

    create_plan("Example", "Example", tmp_path, runner=runner)
    prompt = captured["assembly"].rendered_text
    assert technology_stack.FILENAME in prompt
    assert "fastapi.md" in prompt
    assert "marina-library" in prompt
    # The selected web server's contract travels with the stack, so the author writes the
    # package it names instead of inventing one.
    assert "## Foundation Contract" in prompt
    assert "- package: app_server" in prompt


def test_unanswered_required_analyze_decision_blocks_before_llm(tmp_path):
    target_dir = _make_target(tmp_path)
    questionnaire = (
        target_dir / "QuarterDeck" / "questionnaires" / "discovery-default-workflow.json"
    )
    questionnaire.write_text(
        json.dumps({
            "id": "discovery-default-workflow",
            "questions": [
                {
                    "id": "default_workflow",
                    "label": "Default Workflow",
                    "required_before_plan": True,
                    "answer": "",
                }
            ],
        }),
        encoding="utf-8",
    )

    def _boom(*a, **k):
        raise AssertionError("LLM runner called before required Analyze decision was answered")

    with pytest.raises(
        SpecificationError, match="discovery-default-workflow.json.*Default Workflow"
    ):
        create_plan("Example", "Example", tmp_path, runner=_boom)


def test_answered_required_analyze_decision_allows_planning(tmp_path):
    target_dir = _make_target(tmp_path)
    questionnaire = (
        target_dir / "QuarterDeck" / "questionnaires" / "discovery-default-workflow.json"
    )
    questionnaire.write_text(
        json.dumps({
            "id": "discovery-default-workflow",
            "questions": [
                {
                    "id": "default_workflow",
                    "label": "Default Workflow",
                    "required_before_plan": True,
                    "answer": "Use the service workflow.",
                }
            ],
        }),
        encoding="utf-8",
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert result.target_dir == target_dir
    assert (target_dir / "MANIFEST.md").is_file()


def test_unanswered_nonrequired_discovery_does_not_gate_planning(tmp_path):
    target_dir = _make_target(tmp_path)
    questionnaire = target_dir / "QuarterDeck" / "questionnaires" / "discovery-copy.json"
    questionnaire.write_text(
        json.dumps({
            "id": "discovery-copy",
            "questions": [
                {
                    "id": "empty_state_copy",
                    "label": "Empty-state Copy",
                    "required_before_plan": False,
                    "answer": "",
                }
            ],
        }),
        encoding="utf-8",
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert result.target_dir == target_dir
    assert (target_dir / "MANIFEST.md").is_file()


def test_confirmed_stack_selection_does_not_clear_other_blockers(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "BLOCKERS.md").write_text(
        "# Blockers\n\n## blocker-stack-selection: Confirm technology stack\nSelect a stack.\n\n"
        "## blocker-intent: Confirm product intent\nClarify the product.\n",
        encoding="utf-8",
    )
    questionnaires = target_dir / "QuarterDeck" / "questionnaires"
    questionnaires.mkdir(parents=True, exist_ok=True)
    (questionnaires / "discovery-stack.json").write_text(
        json.dumps({
            "id": "discovery-stack",
            "questions": [{"id": "stack_components", "answer": "python.md"}],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="BLOCKERS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


def test_missing_analysis_refuses(tmp_path):
    target_dir = _make_target(tmp_path, analysis=None)
    errors_path = target_dir / "ERRORS.md"
    errors_path.write_text("# BIG ERRORS — action required\n", encoding="utf-8")

    with pytest.raises(SpecificationError, match="ANALYSIS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert not errors_path.exists()


def test_plan_create_blocked_block_without_diagnosis_defers_to_errors(tmp_path):
    target_dir = _make_target(tmp_path)
    out = "=== PLAN_CREATE_BLOCKED.txt ===\nBlocked.\n=== END PLAN_CREATE_BLOCKED.txt ===\n"
    calls = 0

    def runner(*args, **kwargs):
        nonlocal calls
        calls += 1
        return FakeRun(text=out)

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert isinstance(result, PlanDeferredResult)
    assert calls == 1
    assert result.errors_path == target_dir / "ERRORS.md"
    assert result.error_record.state == "Deferred"
    assert result.error_record.classification == "plan requires a product decision"
    assert "Blocked." in result.errors_path.read_text(encoding="utf-8")
    assert (target_dir / "PLAN_COMPASS.md").read_text(encoding="utf-8") == "# Plan Compass\n"


def test_plan_create_error_without_diagnosis_defers_without_partial_writes(tmp_path):
    target_dir = _make_target(tmp_path)
    out = (
        "=== PLAN_CREATE_ERROR.txt ===\n"
        "Planning output was not produced.\n"
        "Error type: insufficient-specification\n"
        "Reason:\n"
        "- Missing route ownership.\n"
        "Required action:\n"
        "- Clarify route ownership.\n"
        "=== END PLAN_CREATE_ERROR.txt ===\n"
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert isinstance(result, PlanDeferredResult)
    errors = result.errors_path.read_text(encoding="utf-8")
    assert "Missing route ownership." in errors
    assert "Clarify route ownership." in errors
    assert "- State: Deferred" in errors
    assert (target_dir / "PLAN_COMPASS.md").read_text(encoding="utf-8") == "# Plan Compass\n"
    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


def test_false_conflict_challenge_recovers_complete_plan(tmp_path):
    target_dir = _make_target(tmp_path)
    compass = target_dir / "PLAN_COMPASS.md"
    compass.write_text("# Plan Compass\n\n## Commander Direction\n\nKeep runtime state external.\n")
    initial = (
        "=== PLAN_CREATE_ERROR.txt ===\n"
        "Reason:\n- Runtime file conflicts with repository read-only policy.\n"
        "Required action:\n- Choose repository writes or voice capture.\n"
        "=== END PLAN_CREATE_ERROR.txt ===\n"
    )
    calls = []

    def runner(prompt, *args, **kwargs):
        calls.append((prompt, kwargs))
        if len(calls) == 1:
            return FakeRun(text=initial, execution_id="initial-exec")
        return FakeRun(text=_llm_output(), execution_id="challenge-exec")

    before = compass.read_text(encoding="utf-8")
    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
    )

    assert not isinstance(result, PlanDeferredResult)
    assert result.execution_id == "challenge-exec"
    assert len(calls) == 2
    assert "Plan Conflict Challenge" in calls[1][0]
    assert "Initial execution ID: initial-exec" in calls[1][0]
    assert "repository-write guardrail applies only" in calls[1][0]
    assert "stale derived total is not a product decision" in calls[1][0]
    assert "Available response length is not a conflict" in calls[1][0]
    assert not (target_dir / "ERRORS.md").exists()
    assert compass.read_text(encoding="utf-8") == before


_PROSE_WRAPPED_ERROR = (
    "I cannot produce the plan because the sources state no status code.\n\n"
    "=== PLAN_CREATE_ERROR.txt ===\n"
    "Planning output was not produced.\n"
    "Error type: conflict\n"
    "Reason:\n- No status code is stated for removing a missing book.\n"
    "Required action:\n- State the removal status code.\n"
    "=== END PLAN_CREATE_ERROR.txt ===\n\n"
    "**Why I stopped:** picking a status code would be a guess.\n"
)


def test_prose_wrapped_plan_create_error_defers_as_error_mode(tmp_path):
    target_dir = _make_target(tmp_path)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_PROSE_WRAPPED_ERROR))

    assert isinstance(result, PlanDeferredResult)
    errors = result.errors_path.read_text(encoding="utf-8")
    assert "State the removal status code." in errors
    assert "outside delimited artifact blocks" not in errors
    assert not (target_dir / "MANIFEST.md").exists()


def test_prose_wrapped_plan_create_error_is_challenged_unattended(tmp_path, monkeypatch):
    target_dir = _make_target(tmp_path)
    monkeypatch.setenv("DRYDOCK_UAT", "1")
    calls = []

    def runner(prompt, *args, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return FakeRun(text=_PROSE_WRAPPED_ERROR, execution_id="initial-exec")
        return FakeRun(text=_llm_output(), execution_id="challenge-exec")

    result = create_plan(
        "Example", "Example", tmp_path, runner=runner, allow_diagnostic_recovery=True
    )

    assert not isinstance(result, PlanDeferredResult)
    assert result.execution_id == "challenge-exec"
    assert (
        "An unstated response contract (status code, exit status, error channel) is never Error Mode"
        in calls[0]
    )
    assert "Plan Conflict Challenge" in calls[1]
    assert not (target_dir / "ERRORS.md").exists()


def test_confirmed_conflict_challenge_writes_errors_and_no_plan_artifacts(tmp_path):
    target_dir = _make_target(tmp_path)
    initial = (
        "=== PLAN_CREATE_ERROR.txt ===\n"
        "Reason:\n- Sources disagree about retention.\n"
        "Required action:\n- Choose retention behavior.\n"
        "=== END PLAN_CREATE_ERROR.txt ===\n"
    )
    confirmed = (
        "=== PLAN_CREATE_ERROR.txt ===\n"
        "Reason:\n"
        "- sources/request.md clause `retain forever` governs runtime retention, while "
        "COMPASS.md clause `delete immediately` governs the same runtime scope. The clauses "
        "are mutually exclusive and precedence does not identify a winner.\n"
        "Required action:\n"
        "- Correct one cited clause or choose the runtime retention rule.\n"
        "=== END PLAN_CREATE_ERROR.txt ===\n"
    )

    calls = 0

    def runner(*args, **kwargs):
        nonlocal calls
        calls += 1
        return FakeRun(
            text=initial if calls == 1 else confirmed,
            execution_id="initial-exec" if calls == 1 else "challenge-exec",
        )

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
    )

    assert isinstance(result, PlanDeferredResult)
    assert result.initial_execution_id == "initial-exec"
    assert result.challenge_execution_id == "challenge-exec"
    errors = result.errors_path.read_text(encoding="utf-8")
    assert "sources/request.md clause `retain forever`" in errors
    assert "Correct one cited clause" in errors
    assert "- State: Deferred" in errors
    assert "- Execution ID: initial-exec" in errors
    assert "- Challenge Execution ID: challenge-exec" in errors
    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()
    assert (target_dir / "PLAN_COMPASS.md").read_text(encoding="utf-8") == "# Plan Compass\n"
    chair = (target_dir / "QuarterDeck" / "commanders_chair.html").read_text(encoding="utf-8")
    assert "big-error-panel" in chair
    assert "Deferred: plan requires a product decision" in chair


def test_conflict_challenge_failure_records_original_and_exits_as_error(tmp_path):
    target_dir = _make_target(tmp_path)
    initial = (
        "=== PLAN_CREATE_ERROR.txt ===\n"
        "Reason:\n- Apparent conflict.\n"
        "Required action:\n- Resolve it.\n"
        "=== END PLAN_CREATE_ERROR.txt ===\n"
    )
    calls = 0

    def runner(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeRun(text=initial, execution_id="initial-exec")
        return FakeRun(
            ok=False,
            stderr="provider unavailable during challenge",
            execution_id="challenge-exec",
        )

    with pytest.raises(RecordedError) as excinfo:
        create_plan(
            "Example",
            "Example",
            tmp_path,
            runner=runner,
            allow_diagnostic_recovery=True,
        )

    assert excinfo.value.record.classification == "plan conflict challenge failed"
    assert "Apparent conflict." in excinfo.value.record.detail
    assert "provider unavailable during challenge" in excinfo.value.record.detail
    assert excinfo.value.record.execution_id == "initial-exec"
    assert excinfo.value.record.challenge_execution_id == "challenge-exec"
    assert not (target_dir / "MANIFEST.md").exists()


def test_legacy_plan_compass_block_is_cleaned_before_failed_plan(tmp_path):
    target_dir = _make_target(tmp_path)
    compass = target_dir / "PLAN_COMPASS.md"
    compass.write_text(
        "# Plan Compass\n\n"
        "<!-- DRYDOCK PLAN BLOCKERS START -->\n"
        "## Unresolved Plan Blockers\n\nGenerated conflict.\n"
        "<!-- DRYDOCK PLAN BLOCKERS END -->\n\n"
        "## Commander Direction\n\nUse workflow A.\n",
        encoding="utf-8",
    )
    deferred = (
        "=== PLAN_CREATE_ERROR.txt ===\n"
        "Reason:\n- New conflict.\n"
        "Required action:\n- Correct the source.\n"
        "=== END PLAN_CREATE_ERROR.txt ===\n"
    )

    create_plan("Example", "Example", tmp_path, runner=_fake(deferred))

    text = compass.read_text(encoding="utf-8")
    assert "DRYDOCK PLAN BLOCKERS" not in text
    assert "Generated conflict." not in text
    assert "Use workflow A." in text
    assert "New conflict." not in text


def test_integrity_missing_implements_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    out = _llm_output(_manifest(implements="GHOST.md"))
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="implements missing spec file",
    )
    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


def test_integrity_unknown_dependency_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    manifest = _manifest().replace(
        "scope: both\nstate: pending", "scope: both\ndepends: ghost-id\nstate: pending"
    )
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="unknown id",
    )


# Grouping integrity. A story whose `parent:` names a feature the model never emitted
# is orphaned from every group: the Manifest silently loses its grouping and the
# QuarterDeck shows one ungrouped block. Regression for the commonmark plan that
# emitted `parent: parser-capability` with no such feature block.


def test_integrity_unknown_parent_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    manifest = _manifest().replace("parent: feature-status", "parent: parser-capability")
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="parent names unknown id 'parser-capability'",
    )
    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "FEATURE-Status.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


def test_integrity_story_parented_to_non_feature_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    # Parent the story to its own acceptance check: a real id, the wrong block type.
    manifest = _manifest().replace(
        "parent: feature-status\nsummary: Build the status command.",
        "parent: ac-status-exits\nsummary: Build the status command.",
    )
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="must be parented to a feature",
    )


def test_integrity_story_must_implement_exactly_one_spec(tmp_path):
    target_dir = _make_target(tmp_path)
    manifest = _manifest().replace(
        "implements: FEATURE-Status.md",
        "implements: FEATURE-Status.md, ARCHITECTURE.md",
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="must implement exactly one Blueprint specification",
    )


def test_integrity_spec_has_exactly_one_owning_story(tmp_path):
    target_dir = _make_target(tmp_path)
    manifest = _manifest() + (
        "\n## story 2: Duplicate owner\n"
        "id: duplicate-owner\n"
        "parent: feature-status\n"
        "summary: Duplicate ownership.\n"
        "implements: FEATURE-Status.md\n"
        "instructions: Do it again.\n"
        "state: pending\n"
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="duplicate implementation ownership",
    )


# Decomposition coverage. `_STORY_CAP` rejects an over-decomposed plan; these gates
# reject the opposite failure, where analyzed stories are silently collapsed away.

_ANALYSIS_WITH_IDS = _ANALYSIS.replace(
    "| arch | Architecture | ARCHITECTURE.md |\n| status | Status command | FEATURE-Status.md |",
    "| ARCH-001 | Architecture | ARCHITECTURE.md |\n"
    "| STATUS-001 | Status command | FEATURE-Status.md |",
)


def test_uncovered_analyzed_story_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    manifest = _manifest().replace(
        "implements: FEATURE-Status.md", "implements: FEATURE-Status.md\ncovers: STATUS-001"
    )
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="analyzed stories are not delivered by any Manifest story: ARCH-001",
    )


def test_uncovered_analyzed_story_is_a_repairable_topology_defect():
    # Coverage is declared in `covers:`, a field the topology owns, so a topology
    # re-emission repairs it without touching the authored Blueprint artifacts.
    from drydock.planning_session import _is_repairable_topology_defect

    assert _is_repairable_topology_defect(
        SpecificationError(
            "Plan integrity check failed:\n  analyzed stories are not delivered by any "
            "Manifest story: ARCH-001 — name each analyzed Story ID in the covers: field "
            "of the story that delivers it"
        )
    )


def test_unmatched_commander_story_guidance_is_a_repairable_topology_defect():
    """Story ids live in the declaration, so the guidance mismatch is repairable there too."""
    from drydock.planning_session import _is_repairable_topology_defect

    assert _is_repairable_topology_defect(
        SpecificationError(
            "Plan integrity check failed:\n  Commander story guidance is not matched by any "
            "Manifest story: parser-strings — preserve each guidance story id as a story id "
            "or stable covers: selector"
        )
    )


def test_mixed_integrity_defects_are_not_topology_repairable():
    # A defect stated in Blueprint prose needs artifact repair; mixing one in disqualifies
    # the whole report from the topology path.
    from drydock.planning_session import _is_repairable_topology_defect

    assert not _is_repairable_topology_defect(
        SpecificationError(
            "Plan integrity check failed:\n  analyzed stories are not delivered by any "
            "Manifest story: ARCH-001\n  FEATURE-Status.md: missing acceptance assertions"
        )
    )


def test_unrelated_integrity_defect_is_not_topology_repairable():
    from drydock.planning_session import _is_repairable_topology_defect

    assert not _is_repairable_topology_defect(
        SpecificationError("Plan integrity check failed:\n  duplicate implementation ownership")
    )


def test_covered_analyzed_stories_pass_without_warning(tmp_path):
    _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    manifest = _manifest().replace(
        "implements: FEATURE-Status.md",
        "implements: FEATURE-Status.md\ncovers: ARCH-001, STATUS-001",
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    # One story covering two analyzed stories is the declared collapse: it writes,
    # and the collapse is surfaced as a warning rather than hidden.
    assert any("covers 2 analyzed stories" in w for w in result.warnings)
    assert (tmp_path / "Example" / "MANIFEST.md").exists()


def test_governed_stage_without_a_story_is_a_repairable_topology_defect(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "STORY_GUIDANCE.json").write_text(
        '{"stories":[{"id":"parser-strings","provenance":"commander",'
        '"gate":["sh","sources/stage_test.sh","valid/string/**"]}]}\n',
        encoding="utf-8",
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail=("Commander story guidance is not matched by any Manifest story: parser-strings"),
    )


def test_governed_stage_matching_a_story_id_passes_plan_integrity(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "STORY_GUIDANCE.json").write_text(
        '{"stories":[{"id":"story-status","provenance":"commander",'
        '"gate":["sh","sources/stage_test.sh","status"]}]}\n',
        encoding="utf-8",
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert result.plan.by_id()["story-status"].block_id == "story-status"


def test_analyzed_story_claimed_twice_warns(tmp_path):
    # Two stories owning one analyzed story destroys failure attribution. The plan
    # still writes — the work graph is sound — but the shared ownership is surfaced.
    _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    manifest = _manifest().replace(
        "implements: FEATURE-Status.md",
        "implements: FEATURE-Status.md\ncovers: ARCH-001, STATUS-001",
    ) + (
        "\n## story 2: Also status\n"
        "id: story-status-two\n"
        "parent: feature-status\n"
        "summary: Duplicate owner.\n"
        "implements: ARCHITECTURE.md\n"
        "covers: STATUS-001\n"
        "state: pending\n"
        "\n## ac 2: Also exits\n"
        "id: ac-status-two\n"
        "parent: story-status-two\n"
        "kind: assertion\n"
        "state: pending\n"
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert any(
        "analyzed story STATUS-001 is claimed by 2 Manifest stories" in w for w in result.warnings
    )


def test_coverage_gate_inactive_without_analysis_story_list(tmp_path):
    _make_target(tmp_path, analysis="# Blueprint Analysis: Example\n\nQuality: Questions\n")

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert not any("analyzed stories" in w for w in result.warnings)
    assert (tmp_path / "Example" / "MANIFEST.md").exists()


def test_analysis_story_ids_reads_story_list_rows():
    from drydock.quarterdeck_state import analysis_story_ids

    assert analysis_story_ids(_ANALYSIS_WITH_IDS) == ("ARCH-001", "STATUS-001")
    # No Story List, or none with IDs, leaves the coverage gate inactive.
    assert analysis_story_ids("") == ()
    assert analysis_story_ids("## Story List\n\nProject type: `cli`\n") == ()


def test_suite_named_in_prose_outside_acceptance_is_not_fatal(tmp_path):
    """A spec may name the conformance test suite in prose. Only a Programmatic Acceptance
    check that actually runs it unbounded violates the gate."""
    _make_target(tmp_path)
    prose = (
        "## Test Strategy\n\n"
        "- The imported `spec_tests.py` test suite is staged for final measurement and "
        "limited story-scoped checks, not for per-story full-suite execution.\n\n"
    )
    header = "## Programmatic Acceptance"
    out = _llm_output().replace(header, prose + header)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert "story-status" in result.plan.by_id()


def test_suite_staged_but_not_run_inside_acceptance_is_not_fatal(tmp_path):
    """Asserting the test-suite file is staged is not running it. Only execution counts."""
    _make_target(tmp_path)
    staged = (
        "### check-suite-staged\nThe supplied verification assets are present.\n\n"
        "```python\n"
        "from pathlib import Path\n"
        "import importlib.util\n\n"
        'assert Path("sources/spec_tests.py").is_file()\n'
        'assert Path("sources/normalize.py").is_file()\n'
        'spec = importlib.util.spec_from_file_location("normalize", "sources/normalize.py")\n'
        "```\n\n"
    )
    out = _llm_output().replace(
        "## Programmatic Acceptance\n\n", "## Programmatic Acceptance\n\n" + staged
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert "story-status" in result.plan.by_id()


def test_suite_staged_directly_below_python_fence_is_not_fatal(tmp_path):
    """The fence language tag is not an invocation: a python fence opened directly above a
    staged-file assertion must not read as running the test suite."""
    _make_target(tmp_path)
    staged = (
        "### check-suite-staged\nThe supplied verification assets are present.\n\n"
        "```python\n"
        "from pathlib import Path\n\n"
        'assert Path("sources/spec_tests.py").is_file()\n'
        'assert Path("sources/normalize.py").is_file()\n'
        "```\n\n"
    )
    out = _llm_output().replace(
        "## Programmatic Acceptance\n\n", "## Programmatic Acceptance\n\n" + staged
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert "story-status" in result.plan.by_id()


def test_unbuilt_specs_are_discarded_and_regenerated(tmp_path):
    """Nothing built: every prior spec is prior plan output, so the replan rewrites it."""
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    (blueprint_dir / "ARCHITECTURE.md").write_text("STALE ARCHITECTURE\n", encoding="utf-8")
    (blueprint_dir / "FEATURE-Status.md").write_text("STALE FEATURE\n", encoding="utf-8")
    (blueprint_dir / "FEATURE-Ghost.md").write_text("ORPHAN SPEC\n", encoding="utf-8")
    (target_dir / "MANIFEST.md").write_text(_manifest(), encoding="utf-8")
    progress: list[str] = []

    result = create_plan(
        "Example", "Example", tmp_path, runner=_fake(_llm_output()), on_text=progress.append
    )

    assert result.plan_mode == "full-rewrite"
    assert "STALE" not in (blueprint_dir / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "STALE" not in (blueprint_dir / "FEATURE-Status.md").read_text(encoding="utf-8")
    # An unbuilt spec the replan does not re-author is removed, not left stale.
    assert not (blueprint_dir / "FEATURE-Ghost.md").exists()
    assert "discarding 3 unbuilt Blueprint spec(s)" in "".join(progress)


def test_replan_overwrites_built_spec_and_unbuilt_sibling(tmp_path):
    """Planning Crew authority includes specifications used by an earlier build."""
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    architecture.write_text(_ARCH_CONFORMANT, encoding="utf-8")
    (blueprint_dir / "FEATURE-Status.md").write_text("STALE FEATURE\n", encoding="utf-8")
    _mark_built(target_dir, "ARCHITECTURE.md")
    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert architecture.read_text(encoding="utf-8") != _ARCH_CONFORMANT
    assert "STALE" not in (blueprint_dir / "FEATURE-Status.md").read_text(encoding="utf-8")


def test_replan_overwrites_author_edited_built_spec(tmp_path):
    """Commander redirection is input; prior Plan output is not protected from replanning."""
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    architecture.write_text(_ARCH_CONFORMANT, encoding="utf-8")
    _mark_built(target_dir, "ARCHITECTURE.md")
    # Author edits after the build: the applied_specs sha256 no longer matches.
    edited = _ARCH_CONFORMANT.replace("Architecture body.", "AUTHOR EDIT — keep this.")
    architecture.write_text(edited, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert architecture.read_text(encoding="utf-8") != edited


def test_overwrite_discards_even_built_specs(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    architecture.write_text(_ARCH_CONFORMANT, encoding="utf-8")
    _mark_built(target_dir, "ARCHITECTURE.md")

    result = create_plan(
        "Example", "Example", tmp_path, runner=_fake(_llm_output()), overwrite=True
    )

    assert result.plan_mode == "full-rewrite"
    assert "Architecture body." not in architecture.read_text(encoding="utf-8")


def test_a_required_sea_trial_needs_no_plan_time_coverage(tmp_path):
    """Sea Trials are referenced by nothing.

    Plan integrity used to refuse a plan whose required trials were not named by an ``accepts:``
    field or a ``Sea Trials:`` proof tag. That checked that a *reference exists*, not that a
    capability was built, and the release gate — counting proof tags only — then refused five
    criteria a plan satisfying the check had covered. Whether the project meets its criteria is
    settled at score, against what exists.
    """
    target_dir = _make_target(tmp_path)
    (target_dir / "SEA_TRIALS.md").write_text(
        """# Sea Trials: Example

## st-status: Status behavior
Type: behavioral
Required: yes
Criterion: The status command shall report current state.
Verification: proof
Pattern: ubiquitous
""",
        encoding="utf-8",
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert "story-status" in result.plan.by_id()


def test_an_unknown_accepts_reference_no_longer_rejects_a_plan(tmp_path):
    """``accepts:`` is human-readable traceability that gates nothing, so a stale id in it is not
    a reason to discard a whole plan."""
    _make_target(tmp_path)
    manifest = _manifest().replace("scope: both\n", "scope: both\naccepts: st-does-not-exist\n")

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert result.plan.by_id()["story-status"].fields["accepts"] == ("st-does-not-exist",)


def test_manifest_accepts_provides_required_sea_trial_traceability(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "SEA_TRIALS.md").write_text(
        """# Sea Trials: Example

## st-status: Status behavior
Type: behavioral
Required: yes
Criterion: The status command shall report current state.
Verification: proof
Pattern: ubiquitous
""",
        encoding="utf-8",
    )
    manifest = _manifest().replace("scope: both\n", "scope: both\naccepts: st-status\n")

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert result.plan.by_id()["story-status"].fields["accepts"] == ("st-status",)


def test_integrity_accepts_whitespace_separated_dependencies(tmp_path):
    _make_target(tmp_path)
    manifest = (
        _manifest()
        + """
## story 2: Follow-up
id: story-follow-up
parent: feature-status
summary: Extend the status command.
implements: ARCHITECTURE.md
scope: both
depends: story-status story-spike
state: pending

## spike 2: Research
id: story-spike
summary: Investigate a dependency.
state: closed/verified

## ac 2: Follow-up exits successfully
id: ac-follow-up-exits
parent: story-follow-up
kind: assertion
state: pending
"""
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert result.plan.by_id()["story-follow-up"].depends == ("story-status", "story-spike")


def test_story_without_manifest_acceptance_uses_blueprint_acceptance(tmp_path):
    _make_target(tmp_path)
    # Routine story acceptance stays in Blueprint Programmatic Acceptance.
    manifest = _manifest().split("## ac 1:")[0].rstrip() + "\n"
    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert not [block for block in result.plan.blocks if block.block_type == "ac"]


@pytest.mark.parametrize(
    "none_line",
    ["- None.", "- None. Visual-only surface; behavior covered by its backing feature."],
)
def test_a_story_whose_blueprint_carries_no_criterion_is_refused(tmp_path, none_line):
    """Every story closes on its own evidence, so a story with no criterion fails the plan.

    Quantity is still not a gate; presence is. A justified ``- None.`` is no exemption.
    """
    _make_target(tmp_path)
    bare = _SPEC_HEADER.replace(_SPEC_HEADER_PA_BODY, none_line)
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = bare.format(ftype="FEATURE", name="Status", ac="Status command exits successfully.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )

    with pytest.raises(RecordedError) as raised:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert "story `story-status` implements FEATURE-Status.md, which declares no" in (
        raised.value.record.detail
    )


def test_single_suite_driving_check_satisfies_surface_gate(tmp_path):
    # A conformance test suite supplied to the Blueprint is verified by one check that
    # shells out to the staged harness — the strongest test-driven acceptance a story can
    # carry. That single fenced check must clear the several-assertions minimum instead of
    # tripping it; requiring a second fabricated assertion is the bug this guards against.
    _make_target(tmp_path)
    suite_check = (
        "### harness-smoke\n"
        "The staged conformance harness runs one selected example.\n\n"
        "```python\n"
        "import subprocess, sys\n"
        "result = subprocess.run(\n"
        '    [sys.executable, "sources/spec_tests.py", "--number", "1"],\n'
        "    capture_output=True,\n"
        "    text=True,\n"
        ")\n"
        "assert result.returncode == 0\n"
        "```"
    )
    spec = _SPEC_HEADER.replace(_SPEC_HEADER_PA_BODY, suite_check)
    arch = spec.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = spec.format(ftype="FEATURE", name="Status", ac="Status command exits successfully.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert "story-status" in result.plan.by_id()
    assert not any("Programmatic Acceptance criteria" in w for w in result.warnings)


def test_fenced_python_acceptance_counts_toward_surface_gate(tmp_path):
    # Regression: the plan gate must count canonical ``### check-id`` + fenced
    # ``python`` blocks — the format the build engine executes and the model
    # emits — not legacy ``- assert`` bullets. Two fenced checks clear the gate.
    target_dir = _make_target(tmp_path)
    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))
    assert not any("Programmatic Acceptance criteria" in w for w in result.warnings)
    arch_text = (target_dir / "blueprint" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "```python" in arch_text


def test_acceptance_status_counts_criteria_in_both_grammars_but_never_bullets():
    from drydock.planning_session import _acceptance_status

    delimited = (
        "## Programmatic Acceptance\n\n"
        "=== AC first ===\n"
        "Intent: First check.\n\n"
        "assert True\n"
        "=== END AC first ===\n"
        "=== AC second ===\n"
        "Intent: Second check.\n\n"
        "assert True\n"
        "=== END AC second ===\n\n"
        "## User Acceptance\n\n- None.\n"
    )
    assert _acceptance_status(delimited) == (2, False)
    # A proof body may legitimately contain a Markdown fence — markup targets make that ordinary.
    # Counting fences rather than criteria mistakes the payload for the container.
    fenced_body = (
        "## Programmatic Acceptance\n\n"
        "=== AC renders-fence ===\n"
        "Intent: A fenced block round-trips.\n\n"
        'assert render("```python\\nx\\n```") == "<pre><code>x</code></pre>"\n'
        "=== END AC renders-fence ===\n"
    )
    assert _acceptance_status(fenced_body) == (1, False)

    fenced = (
        "## Programmatic Acceptance\n\n"
        + _pa("First check.", "Second check.")
        + "\n\n## User Acceptance\n\n- None.\n"
    )
    assert _acceptance_status(fenced) == (2, False)
    # Legacy bullets are not runnable acceptance and must count as zero.
    bullets = "## Programmatic Acceptance\n\n- assert x == 1\n- assert y == 2\n"
    assert _acceptance_status(bullets) == (0, False)
    # Justified bare-None is still recognized.
    assert _acceptance_status("## Programmatic Acceptance\n\n- None. Manual only.\n") == (0, True)


def _screen_output(pa_lines: str, *, provides: str = "GET /welcome", consumes: str = "") -> str:
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    screen = (
        "# SCREEN: Welcome\n\n"
        "| Field       | Value |\n|-------------|-------|\n"
        "| Version     | 20260714 V1 |\n| Description | Welcome screen. |\n"
        "| Depends On  | |\n"
        f"| Provides    | {provides} |\n"
        f"| Consumes    | {consumes} |\n"
        "| Phase       | 1 |\n\n"
        "## Layout\n\n- Welcome body.\n\n"
        f"## Programmatic Acceptance\n\n{pa_lines}\n\n"
        "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n\n"
    )
    manifest = _manifest(implements="SCREEN-Welcome.md")
    return (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== SCREEN-Welcome.md ===\n{screen}\n=== END SCREEN-Welcome.md ===\n"
        f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"
    )


def test_screen_route_not_called_in_acceptance_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    out = _screen_output(
        _pa_code(
            "assert client.get('/other').status_code == 200",
            "assert 'Welcome' in client.get('/other').text",
        ),
    )
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="never calls route",
    )


def test_screen_consumed_route_not_called_in_acceptance_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    out = _screen_output(
        _pa_code(
            "assert client.get('/welcome').status_code == 200",
            "assert 'Welcome' in client.get('/welcome').text",
        ),
        consumes="GET /api/welcome-summary",
    )
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="never calls route",
    )


def test_screen_routes_called_in_acceptance_passes(tmp_path):
    _make_target(tmp_path)
    out = _screen_output(
        _pa_code(
            "assert client.get('/welcome').status_code == 200",
            "assert client.get('/api/welcome-summary').status_code == 200",
        ),
        consumes="GET /api/welcome-summary",
    )
    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))
    assert not any("route" in w for w in result.warnings)


def test_feature_route_not_named_in_acceptance_warns(tmp_path):
    _make_target(tmp_path)
    feature = _SPEC_HEADER.replace(
        "| Provides    | drydock status |", "| Provides    | POST /catalog |"
    )
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = feature.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    )
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )
    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))
    assert any("does not name route" in w and "POST /catalog" in w for w in result.warnings)


def test_dependency_on_feature_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    # Dependency edges name executable story/spike nodes, never feature groups.
    manifest = _manifest().replace(
        "implements: FEATURE-Status.md\nscope: both\nstate: pending",
        "implements: FEATURE-Status.md\nscope: both\ndepends: feature-status\nstate: pending",
    )
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="illegal dependency target",
    )


def test_forward_dependency_order_warns(tmp_path):
    _make_target(tmp_path)
    # story-status depends on a follow-up story emitted below it — out of dependency order.
    manifest = _manifest().replace(
        "implements: FEATURE-Status.md\nscope: both\nstate: pending",
        "implements: FEATURE-Status.md\nscope: both\ndepends: story-later\nstate: pending",
    )
    manifest += (
        "\n## story 2: Later\n"
        "id: story-later\n"
        "parent: feature-status\n"
        "summary: Emitted after the block that depends on it.\n"
        "implements: ARCHITECTURE.md\n"
        "scope: both\n"
        "state: pending\n"
        "\n## ac 2: Later exits\n"
        "id: ac-later\n"
        "parent: story-later\n"
        "kind: assertion\n"
        "state: pending\n"
    )
    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert any("emitted later" in w for w in result.warnings)


def test_missing_manifest_block_refuses(tmp_path):
    target_dir = _make_target(tmp_path)
    out = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: X\n=== END ARCHITECTURE.md ===\n"
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="missing === TOPOLOGY.md",
    )
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()


def test_missing_required_block_explains_required_response_contract(tmp_path):
    target_dir = _make_target(tmp_path)
    out = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: X\n=== END ARCHITECTURE.md ===\n"

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="only delimited artifact blocks",
    )


def test_leading_preamble_is_discarded_and_reported(tmp_path):
    target_dir = _make_target(tmp_path)
    out = "Blueprint already contains all required specs, so I'm emitting MANIFEST.md.\n\n"
    out += _llm_output()
    progress = []

    create_plan("Example", "Example", tmp_path, runner=_fake(out), on_text=progress.append)

    assert (target_dir / "MANIFEST.md").exists()
    assert (
        "[plan] stray text before ARCHITECTURE.md discarded: "
        '"Blueprint already contains all required specs, so I\'m emitting MANIFEST.md."\n'
    ) in progress


def test_stray_text_beside_an_unclosed_artifact_still_raises():
    from drydock.planning_session import OutsideArtifactTextError, _parse_strict_blocks

    with pytest.raises(OutsideArtifactTextError):
        _parse_strict_blocks(
            "Here is the plan.\n=== A.md ===\nalpha\n", FakeRun(text="", execution_id="x")
        )


def test_preamble_containing_delimiter_fragment_still_refuses(tmp_path):
    # Protection preserved: a stray `===` in the leading text signals a malformed or
    # partial block, so the strict parser must still reject it without writing.
    target_dir = _make_target(tmp_path)
    out = "Note: I use === delimiters below.\n\n" + _llm_output()

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail='before ARCHITECTURE.md: "Note: I use === delimiters below.',
    )

    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "FEATURE-Status.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


def test_missing_first_delimiter_is_recovered(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output()
    repaired = output.replace("=== ARCHITECTURE.md ===\n", "", 1)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(repaired))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()
    assert (target_dir / "blueprint" / "ARCHITECTURE.md").exists()


def test_missing_final_delimiter_is_recovered(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace("\n=== END MANIFEST.md ===\n", "\n", 1)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(output))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()


def test_repair_missing_leading_delimiter_refuses_ordinary_preamble():
    assert _repair_missing_leading_delimiter("Here is the plan.\n" + _llm_output()) is None


def test_truncated_artifact_restarted_mid_body_is_rejected(tmp_path):
    """A response cut mid-artifact that resumes by restarting it must not be written.

    Reproduces the Marina failure: the provider cut the response inside
    `FEATURE-Reconciliation.md` and the continuation spliced that artifact's header onto
    the broken line. `_BLOCK_RE` then spanned from the first header to the first END,
    absorbing the truncated attempt and its retry into one block that pairs 1:1.
    """
    target_dir = _make_target(tmp_path)
    feature = _SPEC_HEADER.format(ftype="FEATURE", name="Status", ac="Status command exits.")
    output = _llm_output().replace(
        "=== FEATURE-Status.md ===\n",
        f"=== FEATURE-Status.md ===\n{feature[:80]}=== FEATURE-Status.md ===\n",
        1,
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(output))

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="contains an artifact header inside its body",
    )
    assert not (target_dir / "MANIFEST.md").exists()


def test_artifact_that_opens_without_closing_is_reported():
    """An opener with no END is dropped by `_BLOCK_RE`'s backreference — a silent loss.

    Observed in a real run where `FEATURE-Autolinks.md` opened, never closed, and vanished
    from a 26-artifact response without any error. Parsing is the backstop after the
    contract guards, so the branch is measured directly.
    """
    text = _llm_output().replace("\n=== END FEATURE-Status.md ===\n", "\n", 1)
    blocks = _parse_blocks(text)

    assert "FEATURE-Status.md" not in blocks
    defects = _artifact_delimiter_defects(text, blocks)
    assert any(
        "FEATURE-Status.md" in defect and "opens but never closes" in defect for defect in defects
    )


def test_delimiter_check_ignores_artifact_size():
    """The check is structural. A large body is not a defect."""
    text = _llm_output()
    blocks = _parse_blocks(text)
    blocks["ARCHITECTURE.md"] = blocks["ARCHITECTURE.md"] + "\nfiller line" * 50_000

    assert _artifact_delimiter_defects(text, blocks) == ()


def test_well_formed_output_passes_the_delimiter_check(tmp_path):
    """The check is structural: undamaged output is never rejected, at any size."""
    target_dir = _make_target(tmp_path)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()


def test_transition_text_between_blocks_is_discarded_and_reported(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace(
        "=== MANIFEST.md ===\n",
        "Continuing with the remaining files next.\n=== MANIFEST.md ===\n",
        1,
    )
    progress = []

    create_plan("Example", "Example", tmp_path, runner=_fake(output), on_text=progress.append)

    assert (target_dir / "MANIFEST.md").exists()
    assert any(
        "stray text between FEATURE-Status.md and MANIFEST.md discarded: "
        '"Continuing with the remaining files next."' in line
        for line in progress
    )


def _artifact_waiver_runner(plan_output: str, decision_output: str):
    calls = []

    def runner(prompt, working_directory, **kwargs):
        calls.append((prompt, kwargs))
        if kwargs["command_name"] == "plan":
            return FakeRun(text=plan_output, execution_id="plan-exec")
        assert kwargs["command_name"] == "diagnose"
        return FakeRun(text=decision_output, execution_id="waiver-exec")

    runner.calls = calls
    return runner


def test_trivial_outside_text_is_written_only_after_diagnostic_approval(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace(
        "=== MANIFEST.md ===\n",
        "- Now the Manifest.\n\n=== MANIFEST.md ===\n",
        1,
    )
    runner = _artifact_waiver_runner(
        output,
        "DECISION: APPROVE_TRIVIAL_OUTSIDE_TEXT\n"
        "REASON: This is only a transition sentence between complete artifacts.\n",
    )
    progress = []

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
        on_text=progress.append,
    )

    assert (target_dir / "MANIFEST.md").exists()
    assert result.waiver_execution_id == "waiver-exec"
    assert any("diagnostic approval removed 19 outside character(s)" in w for w in result.warnings)
    assert any(
        'between FEATURE-Status.md and MANIFEST.md: "- Now the Manifest."' in w
        for w in result.warnings
    )
    assert any("requesting diagnostic approval" in line for line in progress)
    assert len(runner.calls) == 2
    waiver_prompt, waiver_kwargs = runner.calls[1]
    assert 'TEXT_JSON: "- Now the Manifest."' in waiver_prompt
    assert "STRUCTURE_VALID: true" in waiver_prompt
    assert "PLAN_VALID: true" in waiver_prompt
    assert waiver_kwargs["parameters"]["decision"] == "artifact-waiver"


def test_rejected_outside_text_writes_no_artifacts_and_spends_one_diagnostic(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace(
        "=== MANIFEST.md ===\n",
        "- The Manifest omits two unresolved stories.\n=== MANIFEST.md ===\n",
        1,
    )
    runner = _artifact_waiver_runner(
        output,
        "DECISION: REJECT_OUTSIDE_TEXT\nREASON: The text reports a material omission.\n",
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan(
            "Example",
            "Example",
            tmp_path,
            runner=runner,
            allow_diagnostic_recovery=True,
        )

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail="Waiver rejected: The text reports a material omission.",
    )
    assert len(runner.calls) == 2
    assert not (target_dir / "MANIFEST.md").exists()


def test_outside_text_over_100_characters_is_not_submitted_for_waiver(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace(
        "=== MANIFEST.md ===\n",
        "- " + ("x" * 99) + "\n=== MANIFEST.md ===\n",
        1,
    )
    calls = []

    def runner(prompt, working_directory, **kwargs):
        calls.append(kwargs)
        return FakeRun(text=output, execution_id="plan-exec")

    with pytest.raises(RecordedError) as excinfo:
        create_plan(
            "Example",
            "Example",
            tmp_path,
            runner=runner,
            allow_diagnostic_recovery=True,
        )

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail="… (1 more characters)",
    )
    assert len(calls) == 1
    assert not (target_dir / "MANIFEST.md").exists()


_PROSE_REPLY = (
    "I can't produce the Stage 1 planning output as requested, because the stack contract "
    "conflicts with itself. Tell me which reading to take, or say to proceed."
)


def test_a_prose_only_reply_is_asked_once_more_and_the_retry_is_planned(tmp_path):
    """ReadingList 20261014.014000: the model answered the planning prompt with questions and no
    artifacts, and the run stopped. One corrective call recovers it."""
    target_dir = _make_target(tmp_path)
    replies = [_PROSE_REPLY, _llm_output()]
    calls = []

    def runner(prompt, working_directory, **kwargs):
        calls.append((prompt, kwargs))
        return FakeRun(text=replies.pop(0), execution_id=f"plan-exec-{len(calls)}")

    progress = []
    create_plan("Example", "Example", tmp_path, runner=runner, on_text=progress.append)

    assert (target_dir / "MANIFEST.md").exists()
    assert len(calls) == 2
    retry_prompt, retry_kwargs = calls[1]
    assert retry_kwargs["sub_command"] == "topology retry"
    assert retry_kwargs["parameters"]["initial_execution_id"] == "plan-exec-1"
    assert "# Plan Stage 1 Retry" in retry_prompt
    assert "conflicts with itself" in retry_prompt
    assert any("carried no artifact blocks" in line for line in progress)


def test_claude_stage_one_retry_still_resumes_the_original_session(tmp_path):
    _make_target(tmp_path)
    calls: list[dict[str, object]] = []

    def runner(prompt, working_directory, **kwargs):
        calls.append(kwargs)
        response = _PROSE_REPLY if len(calls) == 1 else _llm_output()
        return FakeRun(text=response, execution_id=f"plan-exec-{len(calls)}")

    create_plan("Example", "Example", tmp_path, runner=runner, llm_provider="claude")

    assert len(calls) == 2
    assert calls[1]["sub_command"] == "topology retry"
    assert calls[1]["claude_resume_session_id"] == calls[0]["claude_session_id"]


def test_a_second_prose_reply_is_recorded_with_the_objection_shown(tmp_path):
    target_dir = _make_target(tmp_path)
    calls = []

    def runner(prompt, working_directory, **kwargs):
        calls.append(kwargs)
        return FakeRun(text=_PROSE_REPLY, execution_id="plan-exec")

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail="The reply contained no artifact blocks; the model answered in prose.",
    )
    record = excinfo.value.record
    assert "Tell me which reading to take" in record.detail
    assert "Remove the reported outside text" not in record.recovery
    assert len(calls) == 2
    assert not (target_dir / "MANIFEST.md").exists()


def test_a_reply_with_artifacts_is_never_retried_for_prose():
    from drydock.planning_session import _carries_no_artifact

    assert _carries_no_artifact(_PROSE_REPLY)
    assert not _carries_no_artifact("Preface.\n" + _llm_output())
    assert not _carries_no_artifact("=== BEGIN ARTIFACT X.md ===\nbody\n=== END ARTIFACT ===\n")


def test_invalid_candidate_plan_never_reaches_artifact_waiver(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output(_manifest(implements="GHOST.md")).replace(
        "=== MANIFEST.md ===\n",
        "Now the Manifest.\n=== MANIFEST.md ===\n",
        1,
    )
    calls = []

    def runner(prompt, working_directory, **kwargs):
        calls.append(kwargs)
        return FakeRun(text=output, execution_id="plan-exec")

    with pytest.raises(RecordedError) as excinfo:
        create_plan(
            "Example",
            "Example",
            tmp_path,
            runner=runner,
            allow_diagnostic_recovery=True,
        )

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="implements missing spec file",
    )
    assert len(calls) == 1
    assert not (target_dir / "MANIFEST.md").exists()


def test_transition_text_between_write_calls_is_rejected(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    output = _llm_output()
    calls = []
    for index, (name, content) in enumerate(_parse_blocks(output).items()):
        path = target_dir / name if name == "MANIFEST.md" else blueprint_dir / name
        calls.append(
            '<invoke name="Write">\n'
            f'<parameter name="file_path">{path}</parameter>\n'
            f'<parameter name="content">{content}</parameter>\n'
            "</invoke>"
        )
        if index == 0:
            calls.append("Continuing with the remaining files next.")

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake("\n".join(calls)))

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail="Text appeared outside simulated Write artifacts.",
    )
    assert not (target_dir / "MANIFEST.md").exists()


def test_conflicting_duplicate_artifact_block_refuses_without_writes(tmp_path):
    target_dir = _make_target(tmp_path)
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    other = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="Something else.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== ARCHITECTURE.md ===\n{other}\n=== END ARCHITECTURE.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest(implements='ARCHITECTURE.md')}\n=== END MANIFEST.md ===\n"
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail="Duplicate artifact block with conflicting content: ARCHITECTURE.md",
    )

    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()


def test_identical_duplicate_artifact_block_is_accepted(tmp_path):
    """A verbatim repeat of an artifact is unambiguous: either copy is the file."""
    target_dir = _make_target(tmp_path)
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest(implements='ARCHITECTURE.md')}\n=== END MANIFEST.md ===\n"
    )

    create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert (target_dir / "MANIFEST.md").exists()
    written = (target_dir / "blueprint" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert written.lstrip().startswith("# ARCHITECTURE")


def test_simulated_write_calls_are_recovered(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    output = _llm_output()
    calls = []
    for name, content in _parse_blocks(output).items():
        path = target_dir / name if name == "MANIFEST.md" else blueprint_dir / name
        calls.append(
            '<invoke name="Write">\n'
            f'<parameter name="file_path">{path}</parameter>\n'
            f'<parameter name="content">{content}</parameter>\n'
            "</invoke>"
        )

    result = create_plan("Example", "Example", tmp_path, runner=_fake("\n".join(calls)))

    assert result.plan.by_id()["story-status"].fields.get("implements") == ("FEATURE-Status.md",)
    assert (target_dir / "MANIFEST.md").exists()
    assert (blueprint_dir / "FEATURE-Status.md").exists()


def test_failed_run_refuses(tmp_path):
    target_dir = _make_target(tmp_path)
    with pytest.raises(RecordedError) as excinfo:
        create_plan(
            "Example", "Example", tmp_path, runner=lambda *a, **k: FakeRun(ok=False, text="")
        )
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="LLM execution failed",
        detail="No additional safe diagnostic was available.",
    )


def _write_discovery(path: Path, questions: list[dict]) -> Path:
    path.write_text(
        json.dumps({"id": path.stem, "title": "Discovery", "questions": questions}),
        encoding="utf-8",
    )
    return path


def test_answered_discovery_keeps_only_answered_questions(tmp_path):
    discovery = _write_discovery(
        tmp_path / "discovery-x.json",
        [
            {"id": "a", "prompt": "?", "answer": "yes"},
            {"id": "b", "prompt": "?"},
            {"id": "c", "prompt": "?", "answer": "   "},
        ],
    )
    result = _answered_discovery(discovery)
    assert [q["id"] for q in result["questions"]] == ["a"]


def test_answered_discovery_returns_none_when_unanswered(tmp_path):
    discovery = _write_discovery(
        tmp_path / "discovery-y.json",
        [{"id": "a", "prompt": "?"}, {"id": "b", "prompt": "?", "answer": ""}],
    )
    assert _answered_discovery(discovery) is None


def test_assemble_prompt_orders_sections_by_input_tokens(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "COMPASS.md").write_text("# Compass\n\nDirection.\n", encoding="utf-8")
    (target_dir / "SOUNDINGS.md").write_text("# Soundings\n\n- AC.\n", encoding="utf-8")
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "PROMPT BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        feedback_text="Decompose by module.",
        input_tokens=(
            "COMPASS.md",
            "PLAN_COMPASS.md",
            "ANALYSIS.md",
            "SOUNDINGS.md",
            "BLOCKERS.md",
            "TYPED_SPEC",
        ),
    )

    # COMPASS leads the file sections; the standing directive reads next; sources land last.
    order = [
        result.index('filename="COMPASS.md"'),
        result.index('filename="PLAN_COMPASS.md"'),
        result.index('filename="ANALYSIS.md"'),
        result.index('filename="SOUNDINGS.md"'),
        result.index("Imported source files"),
    ]
    assert order == sorted(order)
    # BLOCKERS.md is the plan-create gate: listed, but never injected as a content section.
    assert 'filename="BLOCKERS.md"' not in result


def test_assemble_prompt_reorders_when_tokens_reordered(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "COMPASS.md").write_text("# Compass\n\nDirection.\n", encoding="utf-8")
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        input_tokens=("ANALYSIS.md", "COMPASS.md"),
    )
    assert result.index('filename="ANALYSIS.md"') < result.index('filename="COMPASS.md"')


def test_assemble_prompt_includes_commander_owned_acceptance_contract(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "ACCEPTANCE.json").write_text(
        '{"full":["sh","sources/full_test.sh"]}\n', encoding="utf-8"
    )

    result = _assemble_prompt(
        "BODY",
        target_dir,
        target_dir / "blueprint",
        _ANALYSIS,
        "2026-08-14",
        input_tokens=("ACCEPTANCE.json",),
    )

    assert 'filename="ACCEPTANCE.json"' in result
    assert 'role="governed acceptance contract"' in result
    assert '"sources/full_test.sh"' in result


def test_assemble_prompt_includes_commander_owned_story_guidance(tmp_path):
    """The story list a Commander declared is injected, and its argv stays out of model hands."""
    target_dir = _make_target(tmp_path)
    (target_dir / "STORY_GUIDANCE.json").write_text(
        '{"stories":[{"id":"parser-strings","provenance":"commander",'
        '"gate":["sh","sources/stage_test.sh","valid/string/**"]}]}\n',
        encoding="utf-8",
    )

    result = _assemble_prompt(
        "BODY",
        target_dir,
        target_dir / "blueprint",
        _ANALYSIS,
        "2026-08-14",
        input_tokens=("STORY_GUIDANCE.json",),
    )

    assert 'filename="STORY_GUIDANCE.json"' in result
    assert 'role="governed story guidance"' in result
    assert '"parser-strings"' in result


def test_assemble_prompt_injects_resolved_blocker_history(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    analysis = _ANALYSIS + (
        "\n## Resolved Blockers\n\n"
        "### blocker-intent: Confirm intent\n\n"
        "#### Commander Resolution\n\n"
        "The CLI converts CommonMark documents to HTML.\n"
    )

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        analysis,
        "2026-06-17",
        input_tokens=("ANALYSIS.md",),
    )

    assert "Resolved Blockers" in result
    assert "The CLI converts CommonMark documents to HTML." in result


def test_assemble_prompt_injects_plan_compass_instruction_block(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        feedback_text="Decompose by module.",
        input_tokens=("PLAN_COMPASS.md",),
    )

    assert 'filename="PLAN_COMPASS.md"' in result
    assert "user steering" in result


def test_assemble_prompt_labels_source_files_with_fixed_roles(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        input_tokens=("TYPED_SPEC",),
    )

    assert 'filename="sources/request.md"' in result


def test_assemble_prompt_excludes_listed_source_filenames(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    (blueprint_dir / "sources" / "BUILD_PLAN.md").write_text("ignore me", encoding="utf-8")
    (target_dir / "EXCLUDE_FILES.md").write_text(
        "# Exclude Files\n\n## Excluded files\n- BUILD_PLAN.md\n",
        encoding="utf-8",
    )

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-17",
        input_tokens=("TYPED_SPEC",),
    )

    assert 'filename="sources/request.md"' in result
    assert 'filename="sources/BUILD_PLAN.md"' not in result


def test_assemble_prompt_includes_change_tickets_in_typed_spec(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    changes_dir = blueprint_dir / "changes"
    changes_dir.mkdir(parents=True)
    (changes_dir / "TICKET-001-AddCopy.md").write_text(
        "# Change Ticket: Add Copy\n\nAmends: FEATURE-Status.md\n",
        encoding="utf-8",
    )

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-30",
        input_tokens=("TYPED_SPEC",),
    )

    assert 'filename="changes/TICKET-001-AddCopy.md"' in result
    assert "Change tickets" in result
    assert "Amends:" in result


def test_assemble_prompt_omits_change_ticket_section_when_no_changes(tmp_path):
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"

    result = _assemble_prompt(
        "BODY",
        target_dir,
        blueprint_dir,
        _ANALYSIS,
        "2026-06-30",
        input_tokens=("TYPED_SPEC",),
    )

    assert "Change tickets" not in result
    assert "ignore me" not in result


def test_suite_bound_acceptance_accepts_canonical_suite_marker(tmp_path):
    """The current prompt emits the canonical ``Suite: full`` marker; the plan gate must
    exempt it exactly as the executor's ``acceptance._full_suite`` does."""
    _make_target(tmp_path)
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    ).replace(
        "## Programmatic Acceptance\n\n",
        "## Programmatic Acceptance\n\n"
        "### conformance-full\nSuite: full\nThe full conformance suite passes.\n\n"
        "```python\n"
        "import subprocess, sys\n"
        'subprocess.run([sys.executable, "sources/spec_tests.py"], check=True)\n'
        "```\n\n",
    )
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert "story-status" in result.plan.by_id()


# --- Unsatisfiable acceptance never reaches the build graph -------------------
#
# The Manifest is the build graph. A criterion that cannot pass by construction makes its
# block unbuildable, and the build may not rewrite it — staged acceptance assets are restored
# before grading. Plan must not emit one.

_MALFORMED_CRITERION = (
    "### scoped-number\n"
    "The supplied harness supports example selection.\n\n"
    "```python\n"
    "import subprocess\n\n"
    "result = subprocess.run(\n"
    "    ['PYTHONPATH=sources', 'python3', 'spec_tests.py', '--number', '1'],\n"
    "    shell=True,\n"
    "    capture_output=True,\n"
    "    text=True,\n"
    ")\n"
    "print(result.stdout)\n"
    "assert '1 passed' in result.stdout\n"
    "```"
)


def _spec_with(acceptance: str) -> str:
    return (
        "# FEATURE: Status\n\n"
        "| Field    | Value |\n"
        "|----------|-------|\n"
        "| Provides | status command |\n\n"
        "## Programmatic Acceptance\n\n"
        f"{acceptance}\n\n"
        "## User Acceptance\n\n- None.\n\n"
        "## Guardrails\n\n- None.\n"
    )


# ── Plan restructure: deterministic Zone A and Zone C wiring ─────────────────────────


_STORY_TAXONOMY_MANIFEST = """# MANIFEST: Example
updated: 2026-08-01
plan_hash: test
state: draft

## story 1: Serve Status
id: story-status
summary: Build the status command.
type: service
kind: capability
phase: 2
implements: FEATURE-Status.md
stack: fastapi.md
depends: story-foundation
acceptance: yes
state: pending

## story 2: Application Factory
id: story-foundation
summary: Stand up the application factory.
type: foundational
kind: capability
phase: 1
implements: ARCHITECTURE.md
stack: fastapi.md
acceptance: yes
state: pending
"""


def _story_taxonomy_output() -> str:
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    )
    return (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_STORY_TAXONOMY_MANIFEST}\n=== END MANIFEST.md ===\n"
    )


def test_zone_c_stamps_the_computed_schedule_onto_the_story_taxonomy(tmp_path):
    """Block grouping and stack mode are computed, never authored."""
    target_dir = _make_target(tmp_path)
    runner = _fake(_story_taxonomy_output())

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    manifest = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    foundation = result.plan.by_id()["story-foundation"]
    status = result.plan.by_id()["story-status"]
    assert foundation.stack_mode == "builder"
    assert status.stack_mode == "consumer"
    # Different phases never share a block.
    assert foundation.block != status.block
    assert "stack_mode:" in manifest


def test_zone_c_refuses_a_phase_inverted_plan(tmp_path):
    """The two topologies must agree: a phase-2 story cannot depend on a phase-3 story."""
    target_dir = _make_target(tmp_path)
    inverted = _STORY_TAXONOMY_MANIFEST.replace("phase: 1", "phase: 3")
    runner = _fake(_story_taxonomy_output().replace(_STORY_TAXONOMY_MANIFEST, inverted))

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner)
    assert not (target_dir / "MANIFEST.md").is_file()


def test_zone_c_refuses_two_stories_owning_one_specification(tmp_path):
    _make_target(tmp_path)
    shared = _STORY_TAXONOMY_MANIFEST.replace(
        "implements: ARCHITECTURE.md", "implements: FEATURE-Status.md"
    )
    runner = _fake(_story_taxonomy_output().replace(_STORY_TAXONOMY_MANIFEST, shared))

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner)


def test_legacy_taxonomy_manifest_is_left_alone(tmp_path):
    """A Manifest with no ``type:`` predates the restructure and skips Zone C entirely."""
    target_dir = _make_target(tmp_path)
    runner = _fake(_llm_output())

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert "stack_mode:" not in (target_dir / "MANIFEST.md").read_text(encoding="utf-8")


def test_story_count_is_not_capped(tmp_path):
    """The ~100-story cap is removed; scale is answered with a stronger model."""
    _make_target(tmp_path)
    header = "# MANIFEST: Example\nupdated: 2026-08-01\nplan_hash: test\nstate: draft\n"
    specs = []
    blocks = []
    for index in range(120):
        name = f"FEATURE-Item{index}.md"
        specs.append(
            f"=== {name} ===\n"
            + _SPEC_HEADER.format(ftype="FEATURE", name=f"Item{index}", ac="None.")
            + f"\n=== END {name} ===\n"
        )
        blocks.append(
            f"## story {index + 1}: Item {index}\n"
            f"id: story-item-{index}\n"
            f"summary: Build item {index}.\n"
            f"implements: {name}\n"
            "state: pending\n"
        )
    manifest = header + "\n" + "\n".join(blocks)
    runner = _fake("".join(specs) + f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n")

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(result.plan.blocks) == 120
    assert not any("cap" in warning for warning in result.warnings)


def test_zone_a_reports_an_unresolvable_declared_stack_file(tmp_path):
    """TECHNOLOGY_STACK.md declares which stack is used; Zone A opens the Rigging files."""
    target_dir = _make_target(tmp_path)
    technology_stack.write(
        target_dir,
        [
            technology_stack.StackEntry("Python", "python.md"),
            technology_stack.StackEntry("Ghost", "ghost.md", "Technologies"),
        ],
        approved="2026-10-19",
    )
    runner = _fake(_llm_output())

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert any("ghost.md" in warning for warning in result.warnings)


def test_advisory_shape_reports_an_untyped_specification_without_refusing_the_plan():
    blocks = {"NOTE.md": "plain prose", "MANIFEST.md": "# MANIFEST: Example"}
    assert check_plan_shape(blocks) == ()
    assert [defect.code for defect in advisory_plan_shape(blocks)] == ["untyped-heading"]


def test_fatal_shape_check_requires_the_manifest_artifact():
    assert [defect.code for defect in check_plan_shape({"ARCHITECTURE.md": "x"})] == [
        "missing-artifact"
    ]


# ── Zone B topology declaration cutover ──────────────────────────────────────────────


_TOPOLOGY_DECLARATION = """planning_feedback: |
  decision-0123456789abcdef applied FEATURE-Status.md

## story story-status
summary:      Build the status command.
type:         service
kind:         capability
phase:        2
implements:   FEATURE-Status.md
stack:        fastapi.md
depends:      story-foundation
acceptance:   yes
instructions: |
  Implement the status command against the application factory.

  Exit non-zero when the service is unreachable.

## story story-foundation
summary:      Stand up the application factory.
type:         foundational
kind:         capability
phase:        1
implements:   ARCHITECTURE.md
stack:        fastapi.md
acceptance:   yes
"""


def _topology_output(declaration: str = _TOPOLOGY_DECLARATION) -> str:
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    )
    return (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== TOPOLOGY.md ===\n{declaration}\n=== END TOPOLOGY.md ===\n"
    )


def test_declaration_is_serialized_into_the_manifest(tmp_path):
    """The model declares; Drydock verifies, orders, blocks, and serializes."""
    target_dir = _make_target(tmp_path)
    runner = _fake(_topology_output())

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    manifest = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert manifest.startswith("# MANIFEST: Example")
    ordered = [block.block_id for block in result.plan.blocks]
    # Declared status-first; phase 1 is serialized first because Drydock computed the order.
    assert ordered == ["story-foundation", "story-status"]
    foundation = result.plan.by_id()["story-foundation"]
    status = result.plan.by_id()["story-status"]
    assert foundation.stack_mode == "builder"
    assert status.stack_mode == "consumer"
    assert foundation.block != status.block
    # Multi-paragraph instructions survive the declaration round trip.
    instructions = status.fields["instructions"]
    assert "Exit non-zero when the service is unreachable." in instructions


def test_declaration_never_reaches_disk(tmp_path):
    """``TOPOLOGY.md`` is transient: part of the response, never a Blueprint file."""
    target_dir = _make_target(tmp_path)
    runner = _fake(_topology_output())

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert not (target_dir / "blueprint" / "TOPOLOGY.md").exists()
    assert not (target_dir / "TOPOLOGY.md").exists()


def test_declaration_carries_planning_feedback_into_the_manifest_preamble(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _fake(_topology_output())

    create_plan("Example", "Example", tmp_path, runner=runner)

    manifest = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "decision-0123456789abcdef applied FEATURE-Status.md" in manifest


def test_a_phase_inverted_declaration_is_refused_before_any_write(tmp_path):
    target_dir = _make_target(tmp_path)
    inverted = _TOPOLOGY_DECLARATION.replace("phase:        1", "phase:        3")
    runner = _fake(_topology_output(inverted))

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner)
    assert not (target_dir / "MANIFEST.md").is_file()


def test_a_declaration_with_an_unknown_edge_is_refused(tmp_path):
    target_dir = _make_target(tmp_path)
    dangling = _TOPOLOGY_DECLARATION.replace(
        "depends:      story-foundation", "depends:      ghost"
    )
    runner = _fake(_topology_output(dangling))

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner)
    assert not (target_dir / "MANIFEST.md").is_file()


def test_uncovered_analyzed_story_is_repaired_at_stage_1(tmp_path):
    # Coverage is decidable as soon as the declaration exists, so it is corrected there —
    # before Stage 2 authors anything against a topology that would be refused later.
    target_dir = _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    uncovered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    )
    repaired = uncovered.replace("covers:       STATUS-001", "covers:       STATUS-001, ARCH-001")
    runner = _sequence_runner(_topology_output(uncovered), _declaration_block(repaired))

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    assert "Plan Topology Repair" in runner.calls[1]
    assert "not delivered by any Manifest story: ARCH-001" in runner.calls[1]
    assert (target_dir / "MANIFEST.md").is_file()
    assert result.plan.by_id()["story-status"].fields["covers"] == ("STATUS-001", "ARCH-001")


# Regression shape from Marina_Haiku 20260913.042433: one story lists two files, and the second
# is also a file another story implements.
_MULTI_FILE_DECLARATION = _TOPOLOGY_DECLARATION.replace(
    "implements:   ARCHITECTURE.md", "implements:   ARCHITECTURE.md, FEATURE-Status.md"
)


def test_a_multi_file_implements_is_split_by_repair_before_stage_two(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(_topology_output(_MULTI_FILE_DECLARATION), _declaration_block())

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    repair = runner.calls[1]
    assert "Plan Topology Repair" in repair
    assert "implements lists 2 specifications (ARCHITECTURE.md, FEATURE-Status.md)" in repair
    assert "FEATURE-Status.md is implemented by 2 stories" in repair
    assert "One story per specification:" in repair
    assert (target_dir / "MANIFEST.md").is_file()


def test_an_unrepaired_multi_file_implements_stops_before_stage_two(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(
        _declaration_block(_MULTI_FILE_DECLARATION) + _arch_block(),
        _declaration_block(_MULTI_FILE_DECLARATION),
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    # The Stage 1 call and one repair; no Stage 2 batch is spent on an unbuildable topology.
    assert len(runner.calls) == 2
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan topology rejected",
        detail="implements lists 2 specifications (ARCHITECTURE.md, FEATURE-Status.md)",
    )
    assert not (target_dir / "MANIFEST.md").is_file()


# Regression shape from ReadingList Haiku 20261013.235724: the foundation story implemented the
# Target's TECHNOLOGY_STACK.md, so Stage 2 authored a Blueprint under that name in blueprint/
# and no story delivered ARCHITECTURE.md.
_STACK_IMPLEMENTS_DECLARATION = _TOPOLOGY_DECLARATION.replace(
    "implements:   ARCHITECTURE.md", "implements:   TECHNOLOGY_STACK.md"
)


def test_a_story_implementing_a_target_input_is_repaired_before_stage_two(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(_topology_output(_STACK_IMPLEMENTS_DECLARATION), _declaration_block())

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    assert "Plan Topology Repair" in runner.calls[1]
    assert "implements 'TECHNOLOGY_STACK.md', a Target input" in runner.calls[1]
    assert not (target_dir / "blueprint" / "TECHNOLOGY_STACK.md").exists()
    assert (target_dir / "MANIFEST.md").is_file()


def test_an_unrepaired_target_input_implements_stops_before_stage_two(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(
        _declaration_block(_STACK_IMPLEMENTS_DECLARATION) + _arch_block(),
        _declaration_block(_STACK_IMPLEMENTS_DECLARATION),
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan topology rejected",
        detail="implements 'TECHNOLOGY_STACK.md', a Target input",
    )
    assert not (target_dir / "blueprint" / "TECHNOLOGY_STACK.md").exists()
    assert not (target_dir / "MANIFEST.md").is_file()


def test_a_coverage_only_repair_carries_no_split_rules(tmp_path):
    _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    uncovered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    )
    repaired = uncovered.replace("covers:       STATUS-001", "covers:       STATUS-001, ARCH-001")
    runner = _sequence_runner(_topology_output(uncovered), _declaration_block(repaired))

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert "One story per specification:" not in runner.calls[1]


def test_a_rejected_stage_two_pass_leaves_none_of_its_artifacts_behind(tmp_path):
    # The batch carries a valid FEATURE-Status.md, then an undeclared file. The pass is dropped
    # whole, so a later pass that adds nothing cannot complete the plan with its leftovers.
    target_dir = _make_target(tmp_path)
    ghost = _SPEC_HEADER.format(ftype="FEATURE", name="Ghost", ac="Ghost exits successfully.")
    runner = _sequence_runner(
        _short_output(),
        _feature_block() + f"=== FEATURE-Ghost.md ===\n{ghost}\n=== END FEATURE-Ghost.md ===\n",
        _declaration_block(),
    )
    progress: list[str] = []

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner, on_text=progress.append)

    assert "specs:     1 / 2  accepted" in excinfo.value.record.detail
    assert "FEATURE-Ghost.md is not declared by the frozen topology" in "".join(progress)
    assert not (target_dir / "MANIFEST.md").is_file()


def test_stage_1_coverage_repair_is_skipped_when_the_declaration_covers_every_story(tmp_path):
    _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    covered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    ).replace("covers:       STATUS-001", "covers:       STATUS-001, ARCH-001")
    runner = _sequence_runner(_topology_output(covered))

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 1


def test_an_unrepaired_coverage_defect_still_refuses_the_plan(tmp_path):
    # The Stage 1 repair is an opportunity, not the authority: a model that will not
    # correct its declaration still meets the same rule at final validation.
    target_dir = _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    uncovered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    )
    runner = _sequence_runner(_topology_output(uncovered))

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="analyzed stories are not delivered by any Manifest story: ARCH-001",
    )
    assert not (target_dir / "MANIFEST.md").is_file()


def test_an_unknown_topology_edge_is_repaired_without_regenerating_specs(tmp_path):
    target_dir = _make_target(tmp_path)
    dangling = _TOPOLOGY_DECLARATION.replace(
        "depends:      story-foundation", "depends:      foundation"
    )
    repaired = _TOPOLOGY_DECLARATION
    runner = _sequence_runner(_topology_output(dangling), _declaration_block(repaired))

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
    )

    assert len(runner.calls) == 2
    assert "Plan Topology Repair" in runner.calls[1]
    assert "depends on unknown id 'foundation'" in runner.calls[1]
    assert "Original TOPOLOGY.md, in the same form your reply must use" in runner.calls[1]
    assert sorted(result.plan.by_id()) == ["story-foundation", "story-status"]
    assert (target_dir / "blueprint" / "FEATURE-Status.md").is_file()


def test_a_topology_fix_survives_a_later_unrelated_repair(tmp_path):
    """Regression: a corrected declaration must not be discarded when the same candidate

    still fails a second, unrelated defect. Previously the topology fix was applied only to a
    local ``candidate_blocks`` and never copied back to ``blocks`` unless validation fully
    passed on that pass; a later, non-topology defect (here a staged-asset environment defect)
    caused the artifact-repair fallback to start over from the original, still phase-inverted
    declaration, which then re-reported the same phase-inversion forever.
    """
    target_dir = _make_target(tmp_path)
    sources = target_dir / "blueprint" / "sources"
    (sources / "run_suite.py").write_text(
        '"""Runner.\n\nEnvironment:\n'
        "    RUNNER     command that runs the candidate. Required -- no default.\n"
        '"""\n',
        encoding="utf-8",
    )
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    broken_spec = (
        "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
        "=== AC status-suite ===\nIntent: The suite passes.\n\n"
        "import subprocess\n"
        'result = subprocess.run(["python3", "sources/run_suite.py"], capture_output=True)\n'
        "assert result.returncode == 0\n"
        "=== END AC status-suite ===\n\n"
        "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n"
    )
    fixed_spec = broken_spec.replace(
        'result = subprocess.run(["python3", "sources/run_suite.py"], capture_output=True)',
        'result = subprocess.run(["python3", "sources/run_suite.py"], capture_output=True, '
        'env={**__import__("os").environ, "RUNNER": "./status"})',
    )
    inverted = _TOPOLOGY_DECLARATION.replace("phase:        1", "phase:        3")
    first = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{broken_spec}\n=== END FEATURE-Status.md ===\n"
        f"=== TOPOLOGY.md ===\n{inverted}\n=== END TOPOLOGY.md ===\n"
    )
    runner = _sequence_runner(
        first,
        _declaration_block(_TOPOLOGY_DECLARATION),
        f"=== FEATURE-Status.md ===\n{fixed_spec}\n=== END FEATURE-Status.md ===\n",
    )

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
    )

    assert len(runner.calls) == 3
    assert "Plan Topology Repair" in runner.calls[1]
    assert "Plan Artifact Repair" in runner.calls[2]
    # The artifact-repair pass targets the real, still-open defect — not a re-report of the
    # already-fixed phase-inversion, which proves the corrected declaration was carried forward.
    assert "without RUNNER" in runner.calls[2]
    assert (
        "phase"
        not in runner.calls[2].split("Deterministic validation defect:")[1].split("\n\n")[0].lower()
    )
    ordered = [block.block_id for block in result.plan.blocks]
    assert ordered == ["story-foundation", "story-status"]


def test_a_cited_blueprint_validation_defect_repairs_only_that_artifact(tmp_path):
    _make_target(tmp_path)
    invalid = _screen_output(
        _pa_code(
            "assert client.get('/welcome').status_code == 200",
            "assert 'Welcome' in client.get('/welcome').text",
        ),
        consumes="GET /api/welcome-summary",
    )
    valid = _screen_output(
        _pa_code(
            "assert client.get('/welcome').status_code == 200",
            "assert client.get('/api/welcome-summary').status_code == 200",
        ),
        consumes="GET /api/welcome-summary",
    )
    repaired_screen = _parse_blocks(valid)["SCREEN-Welcome.md"]
    runner = _sequence_runner(
        invalid,
        f'<artifact name="SCREEN-Welcome.md">\n{repaired_screen}\n</artifact>\n',
    )

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
    )

    assert len(runner.calls) == 2
    assert "Plan Artifact Repair" in runner.calls[1]
    assert "SCREEN-Welcome.md" in runner.calls[1]
    assert "ARCHITECTURE.md body" not in runner.calls[1]
    assert result.plan.by_id()["story-status"].fields["implements"] == ("SCREEN-Welcome.md",)


def test_undeclared_external_acceptance_usage_costs_no_repair_pass(tmp_path):
    """Undeclared tooling is a recommendation, so planning neither fails nor buys a repair.

    The retired gate asked whether the model wrote a ``Requires:`` line, not whether httpx was
    installed. Failing on that spent a whole extra LLM pass to add a line that changed nothing
    about whether the check runs.
    """
    _make_target(tmp_path)
    runner = _sequence_runner(
        _screen_output(
            _pa_code(
                "import httpx\nassert httpx.get('http://localhost/welcome')",
                "assert client.get('/api/welcome-summary').status_code == 200",
            ),
            consumes="GET /api/welcome-summary",
        )
    )

    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
    )

    assert len(runner.calls) == 1
    assert any("undeclared python-package=httpx" in warning for warning in result.warnings)
    check = parse_programmatic_acceptance(result.target_dir / "blueprint" / "SCREEN-Welcome.md")[0]
    assert check.requirements == ()


def test_artifact_repair_maps_story_cited_defect_to_its_implemented_spec():
    blocks = _parse_blocks(_topology_output())
    names = _repairable_artifact_names(
        blocks,
        "story-status: 1 Programmatic Acceptance assertion; author several concrete assertions",
    )

    assert names == ("FEATURE-Status.md",)


def test_an_empty_declaration_is_refused(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _fake(_topology_output("planning_feedback: |\n  nothing declared\n"))

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner)
    assert not (target_dir / "MANIFEST.md").is_file()


def test_the_manifest_carrier_still_works_for_the_reuse_and_speckit_prompts(tmp_path):
    """The legacy branch is explicit, not incidental: a declared Manifest still plans."""
    _make_target(tmp_path)
    runner = _fake(_story_taxonomy_output())

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert result.plan.by_id()["story-foundation"].stack_mode == "builder"


def test_fatal_shape_check_requires_the_topology_artifact():
    assert [
        defect.code for defect in check_plan_shape({"ARCHITECTURE.md": "x"}, PLAN_TOPOLOGY_CONTRACT)
    ] == ["missing-artifact"]


# ── continuation: a short response is resumed, never discarded ───────────────────────
#
# The provider caps output tokens, and that cap includes reasoning. A planning response that runs
# out mid-emission used to discard every valid artifact it had already produced. `TOPOLOGY.md` is
# emitted first precisely so the count of what should exist survives the cut; these tests cover the
# loop that spends that ruler.


def _arch_block() -> str:
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    return f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"


def _feature_block() -> str:
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    )
    return f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"


def _declaration_block(declaration: str = _TOPOLOGY_DECLARATION) -> str:
    return f"=== TOPOLOGY.md ===\n{declaration}\n=== END TOPOLOGY.md ===\n"


def _short_output() -> str:
    """Declaration plus one of its two declared specs: the polite short stop."""
    return _declaration_block() + _arch_block()


def _truncated_output() -> str:
    """The hard cut: the final artifact opens and the response ends mid-body."""
    return _short_output() + "=== FEATURE-Status.md ===\n# FEATURE: Sta"


def _sequence_runner(*responses: str):
    """Fake runner returning each response in turn, repeating the last one thereafter."""
    calls: list[str] = []

    def runner(prompt_text, *a, **k):
        calls.append(prompt_text)
        index = min(len(calls) - 1, len(responses) - 1)
        return FakeRun(text=responses[index], execution_id=f"exec-{len(calls)}")

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def test_a_short_response_is_continued_and_completes(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(_short_output(), _feature_block())

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    assert (target_dir / "MANIFEST.md").is_file()
    assert sorted(block.block_id for block in result.plan.blocks) == [
        "story-foundation",
        "story-status",
    ]
    assert (target_dir / "blueprint" / "FEATURE-Status.md").is_file()


def test_topology_stage_completes_before_blueprint_authoring_starts(tmp_path):
    target_dir = _make_target(tmp_path)
    progress: list[str] = []
    stage_one = _declaration_block() + ("=== DECISIONS.json ===\n[]\n=== END DECISIONS.json ===\n")
    runner = _sequence_runner(stage_one, _arch_block() + _feature_block())

    create_plan("Example", "Example", tmp_path, runner=runner, on_text=progress.append)

    assert len(runner.calls) == 2
    assert "Stage 1 is complete" in runner.calls[1]
    assert (target_dir / "blueprint" / "ARCHITECTURE.md").is_file()
    assert (target_dir / "blueprint" / "FEATURE-Status.md").is_file()
    visible_scores = "".join(item for item in progress if item.startswith("[plan-score]"))
    assert "STAGE 1 · TOPOLOGY" in visible_scores
    assert "Blueprints Created: 0 / 2" in visible_scores
    assert "STAGE 2 · BLUEPRINT BATCH 1" in visible_scores
    assert "Blueprints Created: 2 / 2" in visible_scores
    assert "STAGE 3 · MANIFEST" in visible_scores
    assert "Manifest Created:  True" in visible_scores


def test_a_truncated_trailing_artifact_is_replaced_rather_than_frozen(tmp_path):
    """A cut artifact parses as present. Accepting it would freeze the damage onto disk."""
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(_truncated_output(), _feature_block())

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    feature = (target_dir / "blueprint" / "FEATURE-Status.md").read_text(encoding="utf-8")
    assert "# FEATURE: Sta\n" not in feature
    assert "Status command exits successfully." in feature


def test_a_malformed_stage_two_batch_retries_the_same_blueprint_tranche(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(
        _short_output(),
        "=== FEATURE-Status.md ===\n# FEATURE: truncated",
        _feature_block(),
    )

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 3
    second_ledger = runner.calls[1][len(runner.calls[0]) :]
    third_ledger = runner.calls[2][len(runner.calls[0]) :]
    assert "story-status -> FEATURE-Status.md" in second_ledger
    assert "story-status -> FEATURE-Status.md" in third_ledger
    assert (target_dir / "blueprint" / "FEATURE-Status.md").is_file()


def test_a_redundant_final_end_delimiter_preserves_completed_continuation_artifacts(tmp_path):
    target_dir = _make_target(tmp_path)
    redundant_end = _feature_block() + "=== END FEATURE-Status.md ===\n"
    runner = _sequence_runner(_short_output(), redundant_end)

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    feature = (target_dir / "blueprint" / "FEATURE-Status.md").read_text(encoding="utf-8")
    assert "Status command exits successfully." in feature


def test_nonclaude_continuation_reuses_the_original_prefix_and_carries_the_ledger(tmp_path):
    """Byte-identical prefix or the cached input is re-billed; the appended block is the gap."""
    _make_target(tmp_path)
    runner = _sequence_runner(_short_output(), _feature_block())

    create_plan("Example", "Example", tmp_path, runner=runner, llm_provider="codex")

    first, second = runner.calls
    assert second.startswith(first)
    appended = second[len(first) :]
    assert "story-status -> FEATURE-Status.md" in appended
    assert "ARCHITECTURE.md" in appended
    assert "do not re-emit" in appended
    assert "# Frozen Stage 1 Output" in appended
    assert "## story story-status" in appended


def test_each_plan_call_names_its_stage_for_console_progress(tmp_path):
    _make_target(tmp_path)
    stages: list[object] = []

    def runner(prompt_text, *_args, **kwargs):
        stages.append(kwargs.get("sub_command"))
        text = _short_output() if len(stages) == 1 else _feature_block()
        return FakeRun(text=text, execution_id=f"exec-{len(stages)}")

    create_plan("Example", "Example", tmp_path, runner=runner, llm_provider="codex")

    assert stages[:2] == ["topology", "blueprint batch 1"]


def test_claude_blueprint_batch_starts_a_fresh_session_with_frozen_context(tmp_path):
    _make_target(tmp_path)
    calls: list[tuple[str, dict[str, object]]] = []

    def runner(prompt_text, *_args, **kwargs):
        calls.append((prompt_text, kwargs))
        text = _short_output() if len(calls) == 1 else _feature_block()
        return FakeRun(text=text, execution_id=f"exec-{len(calls)}")

    create_plan("Example", "Example", tmp_path, runner=runner, llm_provider="claude")

    initial_prompt, initial_kwargs = calls[0]
    continuation_prompt, continuation_kwargs = calls[1]
    session_id = initial_kwargs["claude_session_id"]
    assert isinstance(session_id, str)
    assert continuation_kwargs["claude_session_id"] != session_id
    assert "claude_resume_session_id" not in continuation_kwargs
    assert "# Input Context" in initial_prompt
    assert continuation_prompt.startswith(initial_prompt)
    assert "# Frozen Stage 1 Output" in continuation_prompt
    assert "This batch starts a new session" in continuation_prompt
    assert "story-status -> FEATURE-Status.md" in continuation_prompt


def test_claude_blueprint_batches_do_not_carry_prior_batch_outputs():
    from drydock.llm import ClaudePromptSession
    from drydock.prompt_assembly import PromptAssembly

    declared = tuple(
        PlannedStory(story_id=f"story-{n}", implements=f"FEATURE-{n}.md") for n in range(1, 7)
    )
    topology = "Six frozen stories."
    blocks = {"TOPOLOGY.md": topology}
    initial_text = f"=== TOPOLOGY.md ===\n{topology}\n=== END TOPOLOGY.md ===\n"
    prior_body = "# FEATURE: One\nPRIOR_BATCH_OUTPUT_MARKER"
    calls: list[tuple[str, dict[str, object]]] = []

    def runner(prompt_text, *_args, **kwargs):
        calls.append((prompt_text, kwargs))
        numbers = range(1, 6) if len(calls) == 1 else range(6, 7)
        response = "".join(
            f"=== BEGIN ARTIFACT FEATURE-{n}.md ===\n"
            f"{prior_body if n == 1 else f'# FEATURE: {n}'}\n"
            "=== END ARTIFACT ===\n"
            for n in numbers
        )
        return FakeRun(text=response, execution_id=f"exec-{len(calls)}")

    result = ps._continue_short_plan(
        blocks,
        blocks_text=initial_text,
        prompt_assembly=PromptAssembly.single_prompt("ORIGINAL_CONTEXT_MARKER\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="claude",
        model="sonnet",
        log_dir=None,
        runner=runner,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
        claude_session=ClaudePromptSession(session_id="topology-session"),
    )

    assert result.score.is_complete
    assert len(calls) == 2
    first_prompt, first_kwargs = calls[0]
    second_prompt, second_kwargs = calls[1]
    assert first_kwargs["claude_session_id"] != "topology-session"
    assert second_kwargs["claude_session_id"] != first_kwargs["claude_session_id"]
    assert all("claude_resume_session_id" not in kwargs for _, kwargs in calls)
    assert "ORIGINAL_CONTEXT_MARKER" in first_prompt and "ORIGINAL_CONTEXT_MARKER" in second_prompt
    assert "# Frozen Stage 1 Output" in second_prompt
    assert "PRIOR_BATCH_OUTPUT_MARKER" not in second_prompt
    assert "Accepted (5)" in second_prompt
    assert abs(len(second_prompt) - len(first_prompt)) < 1_000


def test_a_batch_that_writes_access_patterns_as_one_table_is_refused_at_that_batch():
    """LayersTesting ``20261021.034029``: batch 1 wrote ``## Access Patterns`` as one table of
    operations and was accepted. The defect surfaced only after every later batch, and three
    repairs from the bare defect text never restored the section shape. The batch that writes an
    unparseable declaration is refused whole, since its Features cite what the declaration failed
    to hold, and is asked again with the reason."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="database", implements="DATABASE.md"),
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
        PlannedStory(story_id="story-2", implements="FEATURE-2.md"),
    )
    flat = (
        "# DATABASE: X\n\n## Access Patterns\n\n"
        "| Pattern | Owner | Access | Repository operation | Compatibility |\n"
        "|---|---|---|---|---|\n"
        "| `FEATURE-X-001` | FEATURE-1.md | read | `settings.get` | unchanged |\n\n"
        "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n"
    )
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        if len(prompts) == 1:
            emitted = {"DATABASE.md": flat}
        elif len(prompts) == 2:
            emitted = {"DATABASE.md": _DATABASE}
        else:
            emitted = {"FEATURE-1.md": "# FEATURE: 1", "FEATURE-2.md": "# FEATURE: 2"}
        response = "".join(
            f"=== BEGIN ARTIFACT {name} ===\n{body}\n=== END ARTIFACT ===\n"
            for name, body in emitted.items()
        )
        return FakeRun(text=response, execution_id=f"exec-{len(prompts)}")

    progress: list[str] = []
    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Three frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nThree frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="codex",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=progress.append,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert len(prompts) == 3
    assert "Accepted (0)" in prompts[1]
    defective = prompts[1].split("Defective (1)")[1]
    assert "database -> DATABASE.md" in defective
    assert "### <FEATURE-DOMAIN-NNN> — <Operation>" in defective
    assert any(
        line.startswith("[plan-score]") and "Retrying (2 left): DATABASE.md does not parse" in line
        for line in progress
    )
    assert result.score.is_complete
    assert result.blocks["DATABASE.md"] == _DATABASE.strip()


def test_a_rejected_declaration_is_returned_to_the_retry_for_correction():
    """FxRates ``20261024.140521``: each retry got only the defect text, re-authored DATABASE.md
    from scratch, and traded one contract fault for another until the attempts ran out."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="database", implements="DATABASE.md"),
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
    )
    rejected = (
        "# DATABASE: X\n\n## Access Patterns\n\n"
        "### FEATURE-X-001 — Read a setting\n\n| Field | Value |\n|---|---|\n"
        "| Owner | FEATURE-1.md |\n| Access | read |\n"
        "| Repository operation | `settings.get` |\n| Compatibility | unchanged |\n\n"
        "## Schemas\n\n## `settings`\n\n| Field | Type |\n|---|---|\n"
        "| key | TEXT PK |\n| sentinel_column | TEXT |\n"
    )
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        emitted = (
            {"DATABASE.md": rejected}
            if len(prompts) == 1
            else {"DATABASE.md": _DATABASE}
            if len(prompts) == 2
            else {"FEATURE-1.md": _OWNER}
        )
        response = "".join(
            f"=== BEGIN ARTIFACT {name} ===\n{body}\n=== END ARTIFACT ===\n"
            for name, body in emitted.items()
        )
        return FakeRun(text=response, execution_id=f"exec-{len(prompts)}")

    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Two frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nTwo frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="codex",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert len(prompts) == 3
    assert "sentinel_column" not in prompts[0]
    assert "sentinel_column" in prompts[1]
    assert "your rejected draft" in prompts[1]
    assert "Your rejected DATABASE.md is attached" in prompts[1].split("## Ledger")[-1]
    assert "sentinel_column" not in prompts[2]
    assert result.score.is_complete


def test_a_schema_fault_is_rejected_with_the_draft_s_other_defects():
    """FxRates ``20261024.143213``: the seed merge raised on the composite PK alone, hiding the
    synonym the same draft held until a later pass."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="database", implements="DATABASE.md"),
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
    )

    def pattern(ident: str, operation: str, kind: str = "") -> str:
        kind_row = f"| Kind | {kind} |\n" if kind else ""
        return (
            f"### {ident} — Read\n\n| Field | Value |\n|---|---|\n"
            "| Owner | FEATURE-1.md |\n| Access | read |\n"
            f"| Repository operation | `{operation}` |\n{kind_row}| Compatibility | unchanged |\n\n"
            "Input: In\n\n| Field | Type | Required |\n|---|---|---|\n| key | str | yes |\n\n"
            "Output: Row\n\n| Field | Type |\n|---|---|\n| key | str |\n| value | str |\n\n"
        )

    rejected = (
        "# DATABASE: X\n\n## Access Patterns\n\n"
        + pattern("FEATURE-X-001", "settings.list")
        + pattern("FEATURE-X-002", "settings.by_key", kind="list")
        + "## Schemas\n\n## `settings`\n\n| Field | Type |\n|---|---|\n"
        "| key | TEXT PK |\n| value | TEXT PK |\n"
    )
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        body = rejected if len(prompts) == 1 else _DATABASE
        if len(prompts) > 2:
            return FakeRun(
                text=f"=== BEGIN ARTIFACT FEATURE-1.md ===\n{_OWNER}\n=== END ARTIFACT ===\n",
                execution_id=f"exec-{len(prompts)}",
            )
        return FakeRun(
            text=f"=== BEGIN ARTIFACT DATABASE.md ===\n{body}\n=== END ARTIFACT ===\n",
            execution_id=f"exec-{len(prompts)}",
        )

    ps._continue_short_plan(
        {"TOPOLOGY.md": "Two frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nTwo frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="codex",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    ledger = prompts[1].split("## Ledger")[-1]
    defective = ledger.split("Defective (")[1].split("Previous attempt rejected")[0]
    assert defective.count("settings declares 2 PK columns") == 1
    assert "FEATURE-X-002 `settings.by_key` runs exactly what FEATURE-X-001 runs" in defective


def test_a_stall_detail_names_its_rejection_before_what_is_missing():
    assert ps._rejection_lines(
        "DATABASE.md does not parse: DATABASE.md: a; b — keep; DATABASE.md: c"
    ) == ("DATABASE.md does not parse: DATABASE.md: a; b — keep", "DATABASE.md: c")
    assert ps._rejection_lines("") == ()


def test_a_refused_seeded_declaration_is_retried_alone_and_holds_back_its_features():
    """LayersTesting ``20261021.213934``: batch 4 wrote access patterns without their heading or
    any table, and the ledger dropped the defect because the seed was never in a tranche. The
    declaration is now its own batch, so its defect is listed and no Feature is authored before
    it parses."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="database", implements="DATABASE.md"),
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
    )
    seed = "# DATABASE: X\n\n## Access Patterns\n\n## Schemas\n"
    headingless = (
        "### FEATURE-X-001 — Read a setting\n\n| Field | Value |\n|---|---|\n"
        "| Owner | FEATURE-1.md |\n| Access | read |\n"
        "| Repository operation | `settings.get` |\n| Compatibility | unchanged |\n"
    )
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        emitted = (
            {"DATABASE.md": headingless}
            if len(prompts) == 1
            else {"DATABASE.md": _DATABASE}
            if len(prompts) == 2
            else {"FEATURE-1.md": _OWNER}
        )
        response = "".join(
            f"=== BEGIN ARTIFACT {name} ===\n{body}\n=== END ARTIFACT ===\n"
            for name, body in emitted.items()
        )
        return FakeRun(text=response, execution_id=f"exec-{len(prompts)}")

    progress: list[str] = []
    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Two frozen stories.", "DATABASE.md": seed},
        blocks_text="=== TOPOLOGY.md ===\nTwo frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="codex",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=progress.append,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert len(prompts) == 3
    assert 'filename="DATABASE.md"' in prompts[0]
    ledger = prompts[1].split("## Ledger")[-1]
    assert "Accepted (0)" in ledger
    current = ledger.split("Current batch (1)")[1].split("Deferred")[0]
    assert "database -> DATABASE.md" in current
    assert "story-1" not in current
    assert "database -> DATABASE.md" in ledger.split("Defective (1)")[1]
    assert "Previous attempt rejected — DATABASE.md does not parse" in ledger
    assert any("[plan-score]" in line and "DATABASE.md does not parse" in line for line in progress)
    assert result.score.is_complete
    assert "FEATURE-X-001" in result.blocks["DATABASE.md"]


def test_a_batch_answered_with_questions_is_retried_with_the_reason():
    """LayersTesting ``20261021.173113``: Haiku answered three Stage 2 batches with questions and
    no artifacts. Each retry was byte-identical to the call that failed, drew the same answer, and
    plan stalled at 16 / 31 Blueprints. The retry now names the refusal and shows it on the
    console; an accepted batch clears it."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
        PlannedStory(story_id="story-2", implements="FEATURE-2.md"),
    )
    prompts: list[str] = []
    replies = [
        "Tell me whether the checks should use cli_runner or a subprocess.",
        "=== BEGIN ARTIFACT FEATURE-1.md ===\n# FEATURE: 1\n=== END ARTIFACT ===\n",
        "=== BEGIN ARTIFACT FEATURE-2.md ===\n# FEATURE: 2\n=== END ARTIFACT ===\n",
    ]

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        return FakeRun(text=replies[len(prompts) - 1], execution_id=f"exec-{len(prompts)}")

    progress: list[str] = []
    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Two frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nTwo frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="claude",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=progress.append,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert result.score.is_complete
    assert len(prompts) == 3
    assert "Previous attempt rejected" not in prompts[0]
    assert "Previous attempt rejected — the response held no artifact blocks" in prompts[1]
    assert "cli_runner or a subprocess" in prompts[1]
    assert "## Questions" in prompts[1].split("## Ledger")[-1]
    assert "Previous attempt rejected" not in prompts[2]
    assert any(
        line.startswith('[plan-score][plan] response without artifacts: "Tell me whether')
        for line in progress
    )


def test_a_batch_answered_without_artifacts_is_retried_as_one_blueprint():
    """LayersTesting ``20261021.183753``: the retry named the refusal but asked for the same five
    Blueprints, and Haiku refused three times more. The retry now asks for one Blueprint, says so,
    and the batch returns to five once a batch is accepted."""
    from drydock.prompt_assembly import PromptAssembly

    declared = tuple(
        PlannedStory(story_id=f"story-{n}", implements=f"FEATURE-{n}.md") for n in range(1, 8)
    )
    prompts: list[str] = []

    def emit(*numbers: int) -> str:
        return "".join(
            f"=== BEGIN ARTIFACT FEATURE-{n}.md ===\n# FEATURE: {n}\n=== END ARTIFACT ===\n"
            for n in numbers
        )

    replies = [
        "I can't produce this batch. If you want me to proceed, reply.",
        emit(1),
        emit(2, 3, 4, 5, 6),
        emit(7),
    ]

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        return FakeRun(text=replies[len(prompts) - 1], execution_id=f"exec-{len(prompts)}")

    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Seven frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nSeven frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="claude",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert result.score.is_complete
    assert len(prompts) == 4
    assert "Current batch (5)" in prompts[0]
    assert "Current batch (1)" in prompts[1]
    assert "The Current batch is now one Blueprint." in prompts[1]
    assert "Current batch (5)" in prompts[2]
    assert "Previous attempt rejected" not in prompts[2]


def _blocked_block(blueprint: str, error_type: str, cited: str) -> str:
    return (
        "=== BEGIN ARTIFACT BLUEPRINT_BLOCKED.txt ===\n"
        f"Blueprint: {blueprint}\nError type: {error_type}\nCited input: {cited}\n"
        "Details:\n- The cited input does not settle it.\n"
        "Required action:\n- Decide it.\n=== END ARTIFACT ===\n"
    )


def test_a_refuted_block_is_answered_in_the_next_batch_and_the_rest_is_kept():
    """LayersTesting ``20261022.121722``: batch 27 said the sources were absent; they were in
    the prompt. A reported block is checked against the batch's own context, the authored
    Blueprints beside it are accepted, and the next batch reads the refutation."""
    from drydock.prompt_assembly import PromptAssembly, PromptPart

    declared = (
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
        PlannedStory(story_id="story-2", implements="FEATURE-2.md"),
    )
    context = PromptAssembly(
        parts=(
            PromptPart(
                "sources/INSTRUCTIONS.md",
                "CONTEXT\n",
                kind="file",
                path=Path("/t/blueprint/sources/INSTRUCTIONS.md"),
            ),
        )
    )
    replies = [
        "=== BEGIN ARTIFACT FEATURE-1.md ===\n# FEATURE: 1\n=== END ARTIFACT ===\n"
        + _blocked_block("FEATURE-2.md", "missing-input", "sources/INSTRUCTIONS.md"),
        "=== BEGIN ARTIFACT FEATURE-2.md ===\n# FEATURE: 2\n=== END ARTIFACT ===\n",
    ]
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        return FakeRun(text=replies[len(prompts) - 1], execution_id=f"exec-{len(prompts)}")

    progress: list[str] = []
    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Two frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nTwo frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=context,
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="claude",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=progress.append,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert result.score.is_complete
    assert result.blocked == ()
    ledger = prompts[1].split("## Ledger")[-1]
    assert "Prior run error type: missing-input" in ledger
    assert "Drydock check: refuted — `sources/INSTRUCTIONS.md` is in this context" in ledger
    assert "Previous attempt rejected" not in ledger
    assert any(
        line.startswith("[plan-score][plan] blocked: FEATURE-2.md · missing-input")
        and "refuted" in line
        for line in progress
    )


def test_a_standing_block_is_retried_with_its_details_and_reported_when_retries_run_out():
    """A block is not a stop: each retry carries the prior error, without shrinking the batch.
    Only when the allowance runs out does the standing block leave the loop for the caller."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
        PlannedStory(story_id="story-2", implements="FEATURE-2.md"),
    )
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        return FakeRun(
            text=_blocked_block("FEATURE-1.md", "conflict", "COMPASS.md"),
            execution_id=f"exec-{len(prompts)}",
        )

    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Two frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nTwo frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="claude",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert len(prompts) == 3
    assert "Current batch (2)" in prompts[1]
    assert "Prior run error type: conflict" in prompts[1]
    assert "- FEATURE-1.md · conflict · cited COMPASS.md" in prompts[1]
    assert "The cited input does not settle it." in prompts[1]
    assert [entry.blueprint for entry in result.blocked] == ["FEATURE-1.md"]
    assert "blocked 1 Current batch Blueprint(s)" in result.last_rejection


def test_a_prose_refusal_is_fed_back_as_an_unstructured_refusal():
    from drydock.prompt_assembly import PromptAssembly

    declared = (PlannedStory(story_id="story-1", implements="FEATURE-1.md"),)
    replies = [
        "I can't emit this. Say the word and I'll emit it.",
        "=== BEGIN ARTIFACT FEATURE-1.md ===\n# FEATURE: 1\n=== END ARTIFACT ===\n",
    ]
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        return FakeRun(text=replies[len(prompts) - 1], execution_id=f"exec-{len(prompts)}")

    ps._continue_short_plan(
        {"TOPOLOGY.md": "One frozen story."},
        blocks_text="=== TOPOLOGY.md ===\nOne frozen story.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="claude",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    ledger = prompts[1].split("## Ledger")[-1]
    assert "Prior run error type: unstructured-refusal" in ledger
    assert "Your prose reply: \"I can't emit this. Say the word" in ledger
    assert "`BLUEPRINT_BLOCKED.txt`" in ledger


def test_plan_continue_prompt_defines_the_blocked_blueprint_report():
    from drydock.prompts import load_prompt

    prompt = load_prompt("plan_continue").body

    assert "=== BEGIN ARTIFACT BLUEPRINT_BLOCKED.txt ===" in prompt
    assert "Error type: {missing-input|conflict|insufficient-specification|other}" in prompt
    assert "Prior run error type" in prompt


def test_plan_continue_prompt_routes_questions_into_the_blueprint():
    from drydock.prompts import load_prompt

    prompt = load_prompt("plan_continue").body

    assert "nobody answers questions during planning" in prompt
    assert "`## Questions`" in prompt


def test_the_seeded_persistence_declaration_survives_into_the_first_blueprint_batch():
    """LayersTesting ``20261021.034029``: the seed was judged against the Stage 1 response, which
    never opened it, read as a truncated artifact, and dropped. Batch 1 then wrote the declaration
    from scratch, so a source-declared table would have been paraphrased or lost."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="database", implements="DATABASE.md"),
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
    )
    seed = "# DATABASE: X\n\n## `seeded_table`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n"
    authored = (
        _DATABASE
        + "\n"
        + _ACCESS_PATTERNS
        .replace("## Access Patterns\n\n", "")
        .replace("FEATURE-X-001", "FEATURE-X-002")
        .replace("`settings.get`", "`seeded_table.get`")
    )
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        name, body = ("DATABASE.md", authored) if len(prompts) == 1 else ("FEATURE-1.md", "# F: 1")
        return FakeRun(
            text=f"=== BEGIN ARTIFACT {name} ===\n{body}\n=== END ARTIFACT ===\n",
            execution_id=f"exec-{len(prompts)}",
        )

    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Two frozen stories.", "DATABASE.md": seed},
        blocks_text="=== TOPOLOGY.md ===\nTwo frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="codex",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    assert "## `seeded_table`" in prompts[0]
    assert "## `seeded_table`" in result.blocks["DATABASE.md"]
    assert "## `settings`" in result.blocks["DATABASE.md"]
    assert result.score.is_complete


def test_the_persistence_declaration_is_one_batch_and_later_batches_cite_its_compact_form():
    """LayersTesting ``20261021.231950``: the seeded declaration sat outside every Current batch
    as a conditional aside, under an instruction to emit "nothing else". No batch added the
    update and delete operations its Features needed, and Haiku refused ``FEATURE-TxnAmend.md``
    three times rather than cite an undeclared operation. ``DATABASE.md`` is now authored alone,
    in one step, frozen, and supplied to later batches as ``DATABASE_compact.md``."""
    from drydock.prompt_assembly import PromptAssembly

    declared = (
        PlannedStory(story_id="story-1", implements="FEATURE-1.md"),
        PlannedStory(story_id="database", implements="DATABASE.md"),
        PlannedStory(story_id="story-2", implements="FEATURE-2.md"),
        PlannedStory(story_id="story-3", implements="FEATURE-3.md"),
    )
    seed = "# DATABASE: X\n\n<!-- SEED_GUIDANCE_MARKER -->\n\n## Access Patterns\n\n## Schemas\n"
    authored = _DATABASE.replace("## Access Patterns\n\n", "## Access Patterns\n\n<!-- note -->\n")
    responses = {
        1: {"DATABASE.md": authored},
        2: {"DATABASE.md": authored + "\n## `extra`\n", "FEATURE-1.md": "# FEATURE: 1"},
        3: {f"FEATURE-{n}.md": f"# FEATURE: {n}" for n in range(1, 4)},
    }
    prompts: list[str] = []

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        response = "".join(
            f"=== BEGIN ARTIFACT {name} ===\n{body}\n=== END ARTIFACT ===\n"
            for name, body in responses[len(prompts)].items()
        )
        return FakeRun(text=response, execution_id=f"exec-{len(prompts)}")

    progress: list[str] = []
    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Four frozen stories.", "DATABASE.md": seed},
        blocks_text="=== TOPOLOGY.md ===\nFour frozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=declared,
        target="Example",
        target_dir=Path("Example"),
        llm_provider="codex",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=progress.append,
        attempts=3,
        initial_execution_id="exec-topology",
    )

    def current(prompt: str) -> str:
        return prompt.split("## Ledger")[-1].split("Current batch")[1].split("Deferred")[0]

    assert len(prompts) == 3
    assert "database -> DATABASE.md" in current(prompts[0])
    assert "FEATURE-1.md" not in current(prompts[0])
    assert "SEED_GUIDANCE_MARKER" in prompts[0]
    assert "story-1 -> FEATURE-1.md" in current(prompts[1])
    assert "DATABASE.md" not in current(prompts[1])
    assert "SEED_GUIDANCE_MARKER" not in prompts[1]
    assert 'filename="DATABASE_compact.md"' in prompts[2]
    assert "<!-- note -->" not in prompts[2]
    assert "### FEATURE-X-001" in prompts[2]
    assert any(
        "DATABASE.md is already accepted and this pass changed it" in line for line in progress
    )
    assert result.score.is_complete
    assert result.blocks["DATABASE.md"] == authored.strip()


def test_a_block_the_response_never_opened_is_not_called_truncated():
    text = (
        "=== BEGIN ARTIFACT A.md ===\nbody\n=== END ARTIFACT ===\n=== BEGIN ARTIFACT B.md ===\ncut"
    )

    damaged = ps._unpaired_artifact_names(text, {"A.md": "body", "B.md": "cut", "SEED.md": "x"})

    assert damaged == frozenset({"B.md"})


def test_continuation_stops_when_no_progress_and_reports_the_score(tmp_path):
    target_dir = _make_target(tmp_path)
    # Every continuation pass returns the same already-accepted artifact: no progress, ever.
    runner = _sequence_runner(_short_output(), _arch_block())

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    record = excinfo.value.record
    assert record.classification == "plan generation stalled"
    assert "specs:     1 / 2  accepted" in record.detail
    assert "story-status -> FEATURE-Status.md" in record.detail
    assert "exec-1" in record.detail and "exec-2" in record.detail
    # All-or-nothing survives: a stall writes nothing.
    assert not (target_dir / "MANIFEST.md").is_file()
    assert not (target_dir / "blueprint" / "FEATURE-Status.md").is_file()


def test_a_product_block_standing_after_retries_defers_to_the_commander(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(
        _short_output(),
        "=== BEGIN ARTIFACT BLUEPRINT_BLOCKED.txt ===\n"
        "Blueprint: FEATURE-Status.md\nError type: conflict\nCited input: COMPASS.md\n"
        "Details:\n- COMPASS.md requires exit 1 where the source requires exit 2.\n"
        "Required action:\n- Choose the exit status.\n=== END ARTIFACT ===\n",
    )

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert isinstance(result, PlanDeferredResult)
    assert "Blueprint: FEATURE-Status.md" in result.detail
    assert "Choose the exit status." in result.error_record.recovery
    assert not (target_dir / "MANIFEST.md").is_file()


def test_a_standing_missing_input_block_is_named_in_the_stall_record(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(
        _short_output(),
        "=== BEGIN ARTIFACT BLUEPRINT_BLOCKED.txt ===\n"
        "Blueprint: FEATURE-Status.md\nError type: missing-input\n"
        "Cited input: sources/GRADER.md\nDetails:\n- The grader is not supplied.\n"
        "=== END ARTIFACT ===\n",
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    detail = excinfo.value.record.detail
    assert excinfo.value.record.classification == "plan generation stalled"
    assert "last rejection: the response blocked 1 Current batch Blueprint(s)" in detail
    assert "- FEATURE-Status.md · missing-input · cited sources/GRADER.md" in detail
    # FxRates 20261024.140521: the capped detail cut the rejection after the missing list.
    assert detail.index("last rejection:") < detail.index("blocked:") < detail.index("topology:")
    assert not (target_dir / "MANIFEST.md").is_file()


def test_continuation_stops_at_the_attempt_cap(tmp_path):
    """The retry allowance bounds consecutive Stage 2 calls that make no progress."""
    _make_target(tmp_path)
    runner = _sequence_runner(_short_output(), _arch_block())

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner, continue_attempts=2)

    assert len(runner.calls) == 3


def test_a_junk_continuation_pass_does_not_corrupt_accepted_artifacts(tmp_path):
    target_dir = _make_target(tmp_path)
    runner = _sequence_runner(_short_output(), "no delimiters here at all")

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    assert "specs:     1 / 2  accepted" in excinfo.value.record.detail
    assert not (target_dir / "MANIFEST.md").is_file()


def test_continuation_never_fires_on_a_complete_response(tmp_path):
    _make_target(tmp_path)
    runner = _sequence_runner(_declaration_block() + _arch_block() + _feature_block())

    create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 1


def test_zero_attempts_disables_continuation(tmp_path):
    _make_target(tmp_path)
    runner = _sequence_runner(_short_output(), _feature_block())

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner, continue_attempts=0)

    assert len(runner.calls) == 1


def test_stage_two_cannot_amend_the_frozen_topology(tmp_path):
    target_dir = _make_target(tmp_path)
    split_declaration = _TOPOLOGY_DECLARATION.replace(
        "## story story-status\n", "## story story-status-api\n"
    ).replace("implements:   FEATURE-Status.md", "implements:   FEATURE-Status-Api.md")
    api = _SPEC_HEADER.format(ftype="FEATURE", name="Status Api", ac="API exits successfully.")
    runner = _sequence_runner(
        _short_output(),
        _declaration_block(split_declaration)
        + f"=== FEATURE-Status-Api.md ===\n{api}\n=== END FEATURE-Status-Api.md ===\n",
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    assert "Blueprint generation stalled after TOPOLOGY.md was accepted and frozen" in str(
        excinfo.value.record.detail
    )
    assert not (target_dir / "MANIFEST.md").is_file()


def test_an_amendment_that_touches_an_accepted_story_is_rejected(tmp_path):
    target_dir = _make_target(tmp_path)
    tampered = _TOPOLOGY_DECLARATION.replace(
        "implements:   ARCHITECTURE.md", "implements:   ARCHITECTURE-Renamed.md"
    )
    runner = _sequence_runner(_short_output(), _declaration_block(tampered) + _feature_block())

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=runner)

    assert "specs:     1 / 2  accepted" in excinfo.value.record.detail
    assert not (target_dir / "MANIFEST.md").is_file()


def _gate_plan_on_a_question(target_dir) -> None:
    """Write an unanswered discovery decision that declares itself required before planning."""
    questionnaires = target_dir / "QuarterDeck" / "questionnaires"
    questionnaires.mkdir(parents=True, exist_ok=True)
    (questionnaires / "discovery-stack.json").write_text(
        json.dumps({
            "archived": False,
            "questions": [
                {
                    "id": "S-1",
                    "label": "Which web framework?",
                    "required_before_plan": True,
                    "answer": "",
                }
            ],
        }),
        encoding="utf-8",
    )


def test_unanswered_required_decision_blocks_planning(tmp_path):
    target_dir = _make_target(tmp_path)
    _gate_plan_on_a_question(target_dir)

    with pytest.raises(SpecificationError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert "Which web framework?" in str(excinfo.value)


def test_override_waives_the_required_decision_and_reports_it(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "METADATA.md").write_text("# METADATA\n\nname: Example\n", encoding="utf-8")
    _gate_plan_on_a_question(target_dir)

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()), override=True)

    assert (target_dir / "MANIFEST.md").is_file()
    assert [w.kind for w in result.waivers] == ["plan-decision"]
    assert "Which web framework?" in result.waivers[0].subject
    assert "override: true" in (target_dir / "METADATA.md").read_text(encoding="utf-8")


def test_override_does_not_waive_a_blocked_analysis(tmp_path):
    """A blockers file is a verdict about the sources, not a question awaiting an answer."""
    target_dir = _make_target(tmp_path)
    (target_dir / "BLOCKERS.md").write_text("- The sources contradict each other.\n", "utf-8")

    with pytest.raises(SpecificationError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()), override=True)

    assert "BLOCKERS.md" in str(excinfo.value)


def test_override_does_not_waive_blocked_analysis_quality(tmp_path):
    target_dir = _make_target(tmp_path)
    analysis = target_dir / "ANALYSIS.md"
    analysis.write_text(
        analysis.read_text(encoding="utf-8").replace("Quality: Questions", "Quality: Blocked"),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()), override=True)

    assert "Blocked" in str(excinfo.value)


def test_a_clean_plan_records_no_waivers(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "METADATA.md").write_text("# METADATA\n\nname: Example\n", encoding="utf-8")

    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert result.waivers == ()
    assert "override:" not in (target_dir / "METADATA.md").read_text(encoding="utf-8")


# The staged-asset contract at plan time. A criterion that calls a staged harness without the
# environment that harness enforces is unbuildable, and the build may not repair it — the asset
# is restored before grading. Catching it here is the difference between a warning now and a
# failed build forty minutes later.

_STAGED_HARNESS_SCRIPT = """#!/bin/sh
set -u

if [ -z "${DECODER:-}" ]; then
    echo "error: DECODER is not set; give the command that runs your decoder." >&2
    exit 2
fi

exec toml-test -decoder "${DECODER}" "$@"
"""

_STAGED_CRITERION = """### key-conformance
The implementation passes the key conformance slice.

```python
import subprocess

result = subprocess.run(
    ["sh", "sources/run_conformance.sh", "-run", "valid/key*"],
    capture_output=True,
    text=True,
)
print(result.stdout)
assert result.returncode == 0
```"""


def _authoring_contract_blueprint_example() -> str:
    """Return the worked Blueprint example from the packaged authoring contract.

    Read from ``paths.get_prompts_root()`` rather than the repository so the assertion covers the
    packaged copy the wheel actually ships, not just the source tree.
    """
    from drydock.paths import get_prompts_root

    contract = (get_prompts_root() / "BLUEPRINTS_CONTRACT.md").read_text(encoding="utf-8")
    fences = re.findall(r"^```(?:markdown)?\n(.*?)^```", contract, re.MULTILINE | re.DOTALL)
    examples = [fence for fence in fences if "=== AC " in fence]
    assert examples, "the authoring contract no longer carries a worked === AC === example"
    return max(examples, key=len)


def test_the_authoring_contract_example_parses_as_one_artifact():
    """The format the prompt mandates must be the format the envelope parser accepts.

    Two protocols share the ``=== NAME ===`` grammar: the envelope (one artifact per block) and
    the nested proof block (``=== AC <id> ===`` inside an artifact body). When the envelope parser
    read a proof delimiter as an artifact boundary, every Blueprint carrying a criterion orphaned
    its END markers and ``drydock plan`` rejected the whole batch as malformed — for every project,
    deterministically. Nothing caught it because no test compared the two contracts.
    """
    example = _authoring_contract_blueprint_example()
    text = f"=== FEATURE-Example.md ===\n{example}\n=== END FEATURE-Example.md ===\n"

    blocks = _parse_strict_blocks(text, FakeRun(text=text))

    assert sorted(blocks) == ["FEATURE-Example.md"], (
        "a nested === AC === proof block was read as an artifact boundary"
    )
    # Parsing is only the first gate. The continuation loop then drops any artifact whose body
    # looks like it absorbed another one, and ``_HEADER_ANYWHERE_RE`` matched the nested proof
    # delimiters — so a Blueprint parsed cleanly and was discarded as damaged anyway, which is
    # how the first fix for this looked correct while `drydock plan` still failed.
    assert ps._unpaired_artifact_names(text, blocks) == frozenset(), (
        "a nested === AC === proof block was counted as an absorbed artifact"
    )
    assert artifact_defect("FEATURE-Example.md", blocks["FEATURE-Example.md"]) is None
    checks = parse_programmatic_acceptance_text(
        blocks["FEATURE-Example.md"], source="FEATURE-Example.md"
    )
    assert [check.check_id for check in checks] == ["health-check", "suite-conformance"]
    for check in checks:
        compile(check.code, check.check_id, "exec")


def test_the_plan_reader_and_the_build_engine_read_one_grammar():
    """Plan-time inspection must read the format the prompt mandates, not a superseded one.

    ``_acceptance_status`` once read Markdown ``python`` fences, so when the authored form became
    ``=== AC <id> ===`` every Blueprint scored zero however many criteria it carried. The gate
    that consumed that count is gone — quantity is never a gate — but the count still decides
    whether a conformed spec is accepted, so plan-time reading and build-time execution must
    still agree on what a criterion *is*. Asserted against the shipped contract example directly.
    """
    from drydock.planning_session import _acceptance_checks, _acceptance_status

    example = _authoring_contract_blueprint_example()
    count, justified = _acceptance_status(example)

    assert count > 0, "the plan reader finds no criteria in the authoring contract's own example"
    assert not justified
    checks = _acceptance_checks(example, source="FEATURE-Example.md")
    assert count == len(checks), "the counter and the acceptance parser disagree"


# ── a malformed criterion must never stop the pipeline ────────────────────────
# Bad stories and bad Sea Trials are outside Drydock's control. A bad acceptance criterion is
# not: Drydock's own command generates it against Drydock's own contract, so a pipeline that
# cannot process one cleanly is a pipeline defect. The criterion is surfaced, never fatal.


def _spec_with_criterion(code: str) -> str:
    return (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        f"=== AC broken-check ===\nIntent: Demonstrate the criterion.\n\n{code}\n"
        "=== END AC broken-check ===\n"
    )


def test_a_criterion_that_does_not_compile_is_reported_not_fatal():
    from drydock.planning_session import _malformed_acceptance_defects

    defects = _malformed_acceptance_defects({
        "FEATURE-Example.md": _spec_with_criterion("assert 1=2")
    })

    assert [defect.check_id for defect in defects] == ["broken-check"]
    assert "not valid Python" in defects[0].reason


def test_an_unpaired_container_is_reported_against_its_file():
    from drydock.planning_session import _malformed_acceptance_defects

    defects = _malformed_acceptance_defects({
        "FEATURE-Example.md": "=== AC one ===\nIntent: x.\n\nassert True\n"
    })

    assert len(defects) == 1
    assert defects[0].source == "FEATURE-Example.md"


def test_a_compiling_criterion_reports_nothing():
    from drydock.planning_session import _malformed_acceptance_defects

    assert (
        _malformed_acceptance_defects({"FEATURE-Example.md": _spec_with_criterion("assert 1 == 1")})
        == ()
    )


def test_plan_normalizes_subprocess_import_inside_each_standalone_ac():
    from drydock.planning_session import _normalize_standalone_imports

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC first ===\nIntent: First.\n\n"
            "import subprocess\n\nsubprocess.run(['true'], check=True)\n"
            "=== END AC first ===\n\n"
            "=== AC second ===\nIntent: Second.\n\n"
            "result = subprocess.run(['false'])\nassert result.returncode != 0\n"
            "=== END AC second ===\n"
        )
    }

    warnings = _normalize_standalone_imports(blocks)

    assert blocks["FEATURE-Example.md"].count("import subprocess") == 2
    assert warnings == (
        "FEATURE-Example.md [second]: added the required standalone import subprocess",
    )


def test_plan_takes_an_omitted_import_from_its_sibling_criteria():
    """Marina_Luna: ``create_app()`` read in one AC, imported only in its neighbours."""
    from drydock.planning_session import _normalize_standalone_imports

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC first ===\nIntent: First.\n\n"
            "from app import create_app\n\nassert create_app()\n"
            "=== END AC first ===\n\n"
            "=== AC second ===\nIntent: Second.\n\n"
            "client = create_app().test_client()\nassert helper(client)\n"
            "=== END AC second ===\n"
        )
    }

    warnings = _normalize_standalone_imports(blocks)

    checks = parse_programmatic_acceptance_text(
        blocks["FEATURE-Example.md"], source="FEATURE-Example.md"
    )
    assert checks[1].code.startswith("from app import create_app\n\nclient =")
    assert "helper" in checks[1].code  # no sibling binds it: left for verify to report
    assert warnings == (
        "FEATURE-Example.md [second]: added the standalone import from app import create_app "
        "its sibling criteria use",
    )


def test_plan_does_not_guess_an_import_its_siblings_disagree_on():
    from drydock.planning_session import _normalize_standalone_imports

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC a ===\nIntent: A.\n\nfrom app import create_app\nassert create_app()\n"
        "=== END AC a ===\n\n"
        "=== AC b ===\nIntent: B.\n\nfrom web import create_app\nassert create_app()\n"
        "=== END AC b ===\n\n"
        "=== AC c ===\nIntent: C.\n\nassert create_app()\n=== END AC c ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_standalone_imports(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_plan_binds_the_module_name_a_criterion_imports_its_factory_from():
    """Marina_Luna: ``from app import create_app`` then ``app.test_client()``."""
    from drydock.planning_session import _normalize_factory_bindings

    blocks = {
        "SCREEN-Example.md": (
            "# SCREEN: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC first ===\nIntent: First.\n\n"
            "from marina_app.factory import create_app\n\n"
            "client = marina_app.test_client()\nassert client.get('/').status_code == 200\n"
            "=== END AC first ===\n"
        )
    }

    warnings = _normalize_factory_bindings(blocks)

    checks = parse_programmatic_acceptance_text(blocks["SCREEN-Example.md"], source="x")
    assert checks[0].code == (
        "from marina_app.factory import create_app\n"
        "marina_app = create_app()\n\n"
        "client = marina_app.test_client()\nassert client.get('/').status_code == 200"
    )
    assert unresolved_globals(checks[0].code) == ()
    assert warnings == (
        "SCREEN-Example.md [first]: bound the name its import left undefined with "
        "marina_app = create_app()",
    )


def test_plan_leaves_an_unbound_name_that_means_the_module_it_imports_from():
    """``marina.db`` after ``from marina.db import Session`` means the module, not a session."""
    from drydock.planning_session import _normalize_factory_bindings

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\n"
        "from marina.db import Session\n\nassert marina.db.engine is not None\n"
        "=== END AC first ===\n\n"
        "=== AC second ===\nIntent: Second.\n\n"
        "from app import create_app, seed\n\nclient = app.test_client()\nassert client\n"
        "=== END AC second ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_factory_bindings(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_plan_does_not_call_a_standard_library_module_it_imports_a_name_from():
    from drydock.planning_session import _normalize_factory_bindings

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\n"
        "from pathlib import Path\n\nassert pathlib.Path('.').exists()\n"
        "=== END AC first ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_factory_bindings(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_plan_imports_the_entry_callable_from_the_selected_foundation():
    """Marina_Luna: 153 criteria imported ``create_app`` from ``app`` or ``marina_app``."""
    from drydock.planning_session import _normalize_foundation_imports

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC first ===\nIntent: First.\n\n"
            "from marina_app import create_app\n\nassert create_app()\n"
            "=== END AC first ===\n\n"
            "=== AC second ===\nIntent: Second.\n\n"
            "from app import create_app as factory\n\nassert factory()\n"
            "=== END AC second ===\n"
        )
    }

    warnings = _normalize_foundation_imports(blocks, ["python.md", "fastapi.md"])

    checks = parse_programmatic_acceptance_text(blocks["FEATURE-Example.md"], source="x")
    assert [check.code for check in checks] == [
        "from app_server.main import create_app\n\nassert create_app()",
        "from app_server.main import create_app as factory\n\nassert factory()",
    ]
    assert warnings == (
        "FEATURE-Example.md [first]: imported `create_app` from `app_server.main`, where the "
        "web-server foundation publishes it, instead of `marina_app`",
        "FEATURE-Example.md [second]: imported `create_app` from `app_server.main`, where the "
        "web-server foundation publishes it, instead of `app`",
    )


def test_plan_follows_the_rewrite_to_the_module_each_foundation_publishes():
    from drydock.planning_session import _normalize_foundation_imports

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC first ===\nIntent: First.\n\n"
            "from app import create_app\n\nassert create_app()\n"
            "=== END AC first ===\n"
        )
    }

    _normalize_foundation_imports(blocks, ["flask.md"])

    checks = parse_programmatic_acceptance_text(blocks["FEATURE-Example.md"], source="x")
    assert checks[0].code.startswith("from app_server import create_app\n")


def test_plan_leaves_foundation_imports_it_cannot_rewrite_whole():
    """A sibling name from the invented package would be dropped; ``plan verify`` reports it."""
    from drydock.planning_session import _normalize_foundation_imports

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\n"
        "from marina_app import create_app, Settings\n\nassert create_app(Settings())\n"
        "=== END AC first ===\n\n"
        "=== AC second ===\nIntent: Second.\n\n"
        "from app_server.main import create_app\n\nassert create_app()\n"
        "=== END AC second ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_foundation_imports(blocks, ["fastapi.md"]) == ()
    assert _normalize_foundation_imports(blocks, ["python.md"]) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_plan_replaces_a_hand_built_client_with_the_published_one():
    """Marina_Luna wrote ``client = create_app().test_client()`` 96 times on FastAPI."""
    from drydock.planning_session import (
        _normalize_foundation_imports,
        _normalize_published_clients,
    )

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC first ===\nIntent: First.\n\n"
            "import json\nfrom marina_app import create_app\n\n"
            "client = create_app().test_client()\nassert client.get('/').status_code == 200\n"
            "=== END AC first ===\n\n"
            "=== AC second ===\nIntent: Second.\n\n"
            "from app_server.main import create_app\n\n"
            "assert create_app()\nclient = create_app().test_client()\nassert client\n"
            "=== END AC second ===\n"
        )
    }

    _normalize_foundation_imports(blocks, ["fastapi.md"])
    warnings = _normalize_published_clients(blocks, ["fastapi.md"])

    checks = parse_programmatic_acceptance_text(blocks["FEATURE-Example.md"], source="x")
    assert checks[0].code == (
        "import json\nfrom app_server.testing import web_client\n\n"
        "client = web_client()\nassert client.get('/').status_code == 200"
    )
    # The entry is still read, so its import stays and the published one joins it.
    assert checks[1].code == (
        "from app_server.main import create_app\nfrom app_server.testing import web_client\n\n"
        "assert create_app()\nclient = web_client()\nassert client"
    )
    assert warnings == (
        "FEATURE-Example.md [first]: replaced `create_app().test_client()` with the published "
        "`web_client()`",
        "FEATURE-Example.md [second]: replaced `create_app().test_client()` with the published "
        "`web_client()`",
    )


def test_plan_leaves_clients_alone_without_a_selected_web_server():
    from drydock.planning_session import _normalize_published_clients

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\n"
        "from app import create_app\n\nclient = create_app().test_client()\nassert client\n"
        "=== END AC first ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_published_clients(blocks, ["python.md"]) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_plan_closes_acceptance_blocks_whose_terminator_the_model_dropped():
    """The habit this exists for cost a real jq run ten LLM calls and wrote nothing."""
    from drydock.planning_session import _normalize_unterminated_acceptance_blocks

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC first ===\nIntent: First.\n\nassert 1 == 1\n\n"
            "=== AC second ===\nIntent: Second.\n\nassert 2 == 2\n"
        )
    }

    warnings = _normalize_unterminated_acceptance_blocks(blocks)

    checks = parse_programmatic_acceptance_text(
        blocks["FEATURE-Example.md"], source="FEATURE-Example.md"
    )
    assert [check.check_id for check in checks] == ["first", "second"]
    assert [check.code for check in checks] == ["assert 1 == 1", "assert 2 == 2"]
    assert len(warnings) == 2
    assert "missing '=== END AC first ===' inserted" in warnings[0]


def test_normalizing_terminators_is_a_no_op_on_a_correctly_paired_block():
    """The property that makes this safe: output that validates today is not touched."""
    from drydock.planning_session import _normalize_unterminated_acceptance_blocks

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\nassert 1 == 1\n=== END AC first ===\n\n"
        "=== AC second ===\nIntent: Second.\n\nassert 2 == 2\n=== END AC second ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_unterminated_acceptance_blocks(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_a_marker_inside_a_string_literal_is_not_treated_as_a_boundary():
    """A target that processes Drydock's own markup embeds these lines in its proofs. Cutting
    there would split a criterion silently; the hard error must survive instead."""
    from drydock.planning_session import _normalize_unterminated_acceptance_blocks

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\n"
        'sample = """\n'
        "=== AC not-a-real-marker ===\n"
        '"""\nassert sample\n=== END AC first ===\n'
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_unterminated_acceptance_blocks(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text
    with pytest.raises(ValueError):
        parse_programmatic_acceptance_text(text, source="FEATURE-Example.md")


def test_an_unrepairable_acceptance_container_is_routed_to_repair(tmp_path):
    """A container no normalizer can close is raised into the artifact repair loop.

    Its body does not tokenize, so no boundary is inferable. It was previously written as a
    warning plus a blocking decision and the plan reported success; the criterion gated nothing
    and Build stopped on it later. Validation now refuses it, and the repair-exhausted pass
    (``enforce_criteria=False``) still returns the graph so the paid-for plan can be written for
    the terminal buildability gate to fail.
    """
    import pytest

    from drydock.planning_session import CriteriaDefect, _validate_plan_output

    broken = (
        "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
        "=== AC status-compiles ===\nIntent: First.\n\n"
        'sample = """\n'
        "=== AC status-runs ===\nIntent: Second.\n\nassert 2 == 2\n=== END AC status-runs ===\n"
    )
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": broken,
        "MANIFEST.md": manifest,
    }

    with pytest.raises(CriteriaDefect) as raised:
        _validate_plan_output(dict(blocks), tmp_path, FakeRun(text=_llm_output(manifest)))
    assert [(kind, item.source) for kind, item in raised.value.defects] == [
        ("acceptance-malformed", "FEATURE-Status.md")
    ]

    plan, warnings = _validate_plan_output(
        blocks, tmp_path, FakeRun(text=_llm_output(manifest)), enforce_criteria=False
    )
    assert plan.blocks
    assert any("acceptance block is never closed" in warning for warning in warnings)


def test_unreadable_acceptance_declares_no_tooling_instead_of_raising(tmp_path):
    """The second unguarded reader on the plan path, reached after validation succeeds."""
    from drydock.acceptance_requirements import project_plan_requirement_decisions

    blocks = {
        "FEATURE-Status.md": (
            "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
            "=== AC status-compiles ===\nIntent: First.\n\nassert 1 == 1\n"
            "=== AC status-runs ===\nIntent: Second.\n\nassert 2 == 2\n"
        )
    }

    assert (
        project_plan_requirement_decisions(
            blocks, target_dir=tmp_path, build_dir=tmp_path / "build"
        )
        == ()
    )


def test_an_ambiguous_terminator_defect_is_left_to_the_hard_error():
    """A mismatched end id has no single right answer, so nothing is inserted."""
    from drydock.planning_session import _normalize_unterminated_acceptance_blocks

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\nassert 1 == 1\n=== END AC second ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_unterminated_acceptance_blocks(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_plan_splits_a_fused_acceptance_boundary_the_model_forgot_to_open():
    """The live jq defect: one opener, a closer naming the *next* criterion, duplicated at the
    real end. Every one of 4 malformed Blueprint files in a real run showed exactly this shape,
    and the LLM-based ``plan repair`` container path failed to fix it on every attempt."""
    from drydock.planning_session import _normalize_fused_acceptance_boundaries

    blocks = {
        "FEATURE-Date-and-Time.md": (
            "# FEATURE: Date and Time\n\n## Programmatic Acceptance\n\n"
            "=== AC date-conformance ===\nIntent: First.\n\nassert 1 == 1\n"
            "=== END AC date-utc-and-errors ===\n"
            "Intent: Second.\n\nassert 2 == 2\n"
            "=== END AC date-utc-and-errors ===\n"
        )
    }

    warnings = _normalize_fused_acceptance_boundaries(blocks)

    checks = parse_programmatic_acceptance_text(
        blocks["FEATURE-Date-and-Time.md"], source="FEATURE-Date-and-Time.md"
    )
    assert [check.check_id for check in checks] == ["date-conformance", "date-utc-and-errors"]
    assert [check.code for check in checks] == ["assert 1 == 1", "assert 2 == 2"]
    assert len(warnings) == 1
    assert "closed the wrong criterion" in warnings[0]
    assert warnings[0].startswith("FEATURE-Date-and-Time.md [date-conformance]")


def test_plan_splits_a_chain_of_fused_acceptance_boundaries():
    """The live Marina_Luna defect: three criteria fused, each closer naming the *next* one, so
    every wrong id appears exactly once as a closer. The earlier single-fusion rule declined the
    whole chain and shipped an unparseable Blueprint to Build."""
    from drydock.planning_session import _normalize_fused_acceptance_boundaries

    blocks = {
        "SCREEN-Workflow.md": (
            "# SCREEN: Workflow\n\n## Programmatic Acceptance\n\n"
            "=== AC workflow-columns ===\nIntent: First.\n\nassert 1 == 1\n"
            "=== END AC workflow-production-terminal ===\n"
            "Intent: Second.\n\nassert 2 == 2\n"
            "=== END AC workflow-catalog-boundary ===\n"
            "Intent: Third.\n\nassert 3 == 3\n"
            "=== END AC workflow-catalog-boundary ===\n"
        )
    }

    warnings = _normalize_fused_acceptance_boundaries(blocks)

    checks = parse_programmatic_acceptance_text(
        blocks["SCREEN-Workflow.md"], source="SCREEN-Workflow.md"
    )
    assert [check.check_id for check in checks] == [
        "workflow-columns",
        "workflow-production-terminal",
        "workflow-catalog-boundary",
    ]
    assert [check.code for check in checks] == ["assert 1 == 1", "assert 2 == 2", "assert 3 == 3"]
    assert len(warnings) == 2


def test_a_speculative_boundary_repair_that_does_not_alternate_is_discarded_whole():
    """The wrong-id closer opens a synthetic block that nothing ever closes, so the repaired text
    does not alternate and every insertion is dropped rather than handing Build a broken file."""
    from drydock.planning_session import _normalize_fused_acceptance_boundaries

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\nassert 1 == 1\n=== END AC second ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_fused_acceptance_boundaries(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_a_fused_boundary_whose_id_opens_elsewhere_is_a_real_criterion_not_touched():
    """The mismatched id already has its own real opener elsewhere — a genuine, differently
    ordered criterion, not two fused under one opener — so nothing is inserted."""
    from drydock.planning_session import _normalize_fused_acceptance_boundaries

    text = (
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
        "=== AC first ===\nIntent: First.\n\nassert 1 == 1\n=== END AC second ===\n\n"
        "=== AC second ===\nIntent: Second.\n\nassert 2 == 2\n=== END AC second ===\n"
    )
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_fused_acceptance_boundaries(blocks) == ()
    assert blocks["FEATURE-Example.md"] == text


def test_grouped_artifact_repair_chunks_by_kind_at_the_batch_size():
    """Ed's refinement: group by which bug a file has, then chunk each group at
    ``_PLAN_BLUEPRINT_BATCH_SIZE`` — three bugs cost at most three repair calls, not one call per
    five-file slice of an undifferentiated pile."""
    from drydock.acceptance import MalformedAcceptance
    from drydock.planning_session import (
        _PLAN_BLUEPRINT_BATCH_SIZE,
        _next_repair_chunk,
        _repair_pass_budget,
    )

    kind_a_files = [f"FEATURE-A{i}.md" for i in range(12)]
    kind_b_files = [f"FEATURE-B{i}.md" for i in range(3)]
    defects = tuple(
        ("kind-a", MalformedAcceptance(check_id="c", source=name, reason="bug a"))
        for name in kind_a_files
    ) + tuple(
        ("kind-b", MalformedAcceptance(check_id="c", source=name, reason="bug b"))
        for name in kind_b_files
    )

    class FakeCriteriaDefect(Exception):
        def __init__(self, defects):
            super().__init__("fake")
            self.defects = defects

    exc = FakeCriteriaDefect(defects)
    blocks = {name: "" for name in kind_a_files + kind_b_files}

    assert (
        _repair_pass_budget(exc, _PLAN_BLUEPRINT_BATCH_SIZE, floor=3) == 4
    )  # ceil(12/5)+ceil(3/5)

    seen_chunks: list[tuple[str, tuple[str, ...]]] = []
    remaining = dict(blocks)
    current_exc: Exception = exc
    for _ in range(4):
        chunk = _next_repair_chunk(current_exc, remaining, _PLAN_BLUEPRINT_BATCH_SIZE)
        assert chunk is not None
        kind, names, _text = chunk
        assert len(names) <= _PLAN_BLUEPRINT_BATCH_SIZE
        seen_chunks.append((kind, names))
        # Simulate this chunk being fixed: its files no longer carry that kind's defect.
        current_exc = FakeCriteriaDefect(
            tuple((k, d) for k, d in current_exc.defects if d.source not in names)
        )

    assert _next_repair_chunk(current_exc, remaining, _PLAN_BLUEPRINT_BATCH_SIZE) is None
    kinds_seen = [kind for kind, _ in seen_chunks]
    assert kinds_seen.count("kind-a") == 3
    assert kinds_seen.count("kind-b") == 1
    all_named = {name for _, names in seen_chunks for name in names}
    assert all_named == set(kind_a_files) | set(kind_b_files)


def test_a_single_kind_within_the_batch_size_makes_one_chunk():
    """Regression: the common case (one bug, few files) still resolves in one call."""
    from drydock.acceptance import MalformedAcceptance
    from drydock.planning_session import _PLAN_BLUEPRINT_BATCH_SIZE, _next_repair_chunk

    class FakeCriteriaDefect(Exception):
        defects: tuple

    exc = FakeCriteriaDefect()
    exc.defects = (
        ("kind-a", MalformedAcceptance(check_id="c", source="FEATURE-A.md", reason="bug")),
    )
    blocks = {"FEATURE-A.md": ""}

    chunk = _next_repair_chunk(exc, blocks, _PLAN_BLUEPRINT_BATCH_SIZE)

    assert chunk == ("kind-a", ("FEATURE-A.md",), chunk[2])


def test_a_bare_backslash_escape_is_reported_against_its_criterion():
    """`'"value=\\(.)"'` is what a jq interpolation proof looks like. It runs, so it is not
    gated; it is not the escape the author wrote, so it is not silent either."""
    from drydock.planning_session import _acceptance_escape_warnings

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC interpolation ===\nIntent: Interpolation.\n\n"
            "program = '\"value=\\(.)\"'\nassert program\n"
            "=== END AC interpolation ===\n"
        )
    }

    warnings = _acceptance_escape_warnings(blocks)

    assert len(warnings) == 1
    assert "FEATURE-Example.md [interpolation]" in warnings[0]
    assert "invalid escape sequence" in warnings[0]
    assert 'r"..."' in warnings[0]


def test_a_correctly_escaped_criterion_reports_nothing():
    from drydock.planning_session import _acceptance_escape_warnings

    blocks = {
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC interpolation ===\nIntent: Interpolation.\n\n"
            "program = r'\"value=\\(.)\"'\nassert program\n"
            "=== END AC interpolation ===\n"
        )
    }

    assert _acceptance_escape_warnings(blocks) == ()


def test_a_malformed_criterion_becomes_a_blocking_decision():
    """Interactively this asks before the story builds; under --override it survives for review."""
    from drydock.planning_session import (
        _malformed_acceptance_defects,
        malformed_acceptance_decisions,
    )

    defects = _malformed_acceptance_defects({
        "FEATURE-Example.md": _spec_with_criterion("assert 1=2")
    })
    decisions = malformed_acceptance_decisions(defects)

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.severity == "blocking"
    assert decision.origin == "plan"
    assert decision.blueprint == "FEATURE-Example.md"
    assert decision.status == "open"
    assert "broken-check" in decision.title
    assert "not valid Python" in decision.description


def test_unattended_malformed_criterion_becomes_a_recommended_system_decision():
    from drydock.planning_session import (
        _malformed_acceptance_defects,
        malformed_acceptance_decisions,
    )

    defects = _malformed_acceptance_defects({
        "FEATURE-Example.md": _spec_with_criterion("assert 1=2")
    })
    decision = malformed_acceptance_decisions(defects, unattended=True)[0]

    assert decision.severity == "material"
    assert decision.status == "recommended"
    assert decision.system_choice == "Repair the criterion automatically before build."


# ── Invariant boundary form, end to end through the plan checks ──────────────────
#
# Toml run 20260813.231738 died `KeyError: 'TOPOLOGY.md'` in the continuation loop. The prompts
# had moved to `=== BEGIN ARTIFACT <name> === / === END ARTIFACT ===` and the parser had followed,
# but the checks that ask a structural question of the raw response still counted named closes.
# The invariant close carries no name, so every artifact of an undamaged response read as unpaired,
# the accumulator emptied, and the loop indexed a topology it had just discarded.

_INVARIANT_STAGE_ONE = (
    "=== BEGIN ARTIFACT TOPOLOGY.md ===\n"
    "# TOPOLOGY: Demo\n"
    "## story alpha\n"
    "=== END ARTIFACT ===\n"
    "=== BEGIN ARTIFACT DECISIONS.json ===\n"
    "[]\n"
    "=== END ARTIFACT ===\n"
)


def test_invariant_form_response_has_no_unpaired_artifacts():
    blocks = _parse_strict_blocks(_INVARIANT_STAGE_ONE, FakeRun(text=_INVARIANT_STAGE_ONE))

    assert sorted(blocks) == ["DECISIONS.json", "TOPOLOGY.md"]
    assert ps._unpaired_artifact_names(_INVARIANT_STAGE_ONE, blocks) == frozenset(), (
        "an invariant close was not counted, so the continuation accumulator emptied"
    )


def test_invariant_form_response_reports_no_delimiter_defect():
    blocks = _parse_strict_blocks(_INVARIANT_STAGE_ONE, FakeRun(text=_INVARIANT_STAGE_ONE))

    assert _artifact_delimiter_defects(_INVARIANT_STAGE_ONE, blocks) == ()
    assert ps._artifact_delimiters_are_complete(_INVARIANT_STAGE_ONE, blocks)


def test_invariant_form_artifact_that_opens_without_closing_is_still_reported():
    """Recognising the invariant close must not blind the check to a genuine truncation."""
    text = _INVARIANT_STAGE_ONE + "=== BEGIN ARTIFACT FEATURE-Cut.md ===\n# FEATURE: Cut\n"
    blocks = _parse_strict_blocks(text, FakeRun(text=text))

    assert "FEATURE-Cut.md" in ps._unpaired_artifact_names(text, blocks)


def test_embedded_invariant_header_is_reported_under_the_artifact_name():
    """A cut-and-restart leaves the opener inside the body; the name must be the artifact's."""
    text = (
        "=== BEGIN ARTIFACT TOPOLOGY.md ===\n"
        "# TOPOLOGY: Demo\n"
        "=== BEGIN ARTIFACT TOPOLOGY.md ===\n"
        "# TOPOLOGY: Demo\n"
        "=== END ARTIFACT ===\n"
    )
    blocks = {"TOPOLOGY.md": "# TOPOLOGY: Demo\n=== BEGIN ARTIFACT TOPOLOGY.md ===\n# TOPOLOGY"}

    defects = _artifact_delimiter_defects(text, blocks)

    assert any("`TOPOLOGY.md`" in defect for defect in defects)
    assert not any("BEGIN ARTIFACT" in defect for defect in defects)
    assert "TOPOLOGY.md" in ps._unpaired_artifact_names(text, blocks)


def test_conformed_spec_is_extracted_from_the_invariant_form():
    """`plan_conform` emits the invariant boundary; a backreference regex matched nothing."""
    text = "=== BEGIN ARTIFACT FEATURE-Login.md ===\n# FEATURE: Login\n=== END ARTIFACT ===\n"

    assert ps._extract_conformed_spec(text, "FEATURE-Login.md") == "# FEATURE: Login"


def test_conformed_spec_extraction_survives_an_unusable_response():
    """The caller degrades to `spec left unchanged`; conformance never fails a plan."""
    assert ps._extract_conformed_spec("prose with no artifact block", "FEATURE-Login.md") is None


# ── Repair transport: the reply must be readable, and a discard must be visible ──────


def test_a_coverage_repair_wrapped_in_an_xml_envelope_is_still_read(tmp_path):
    """The recorded regression: the model corrected the topology and Drydock discarded it.

    Toml `20260813.234757`. The repair prompt supplied its input inside
    `<original-topology>` tags and never stated the artifact grammar, so the model mirrored
    the tags it was shown. The reply was correct; only its envelope was not. Stage 2 then
    spent two batch passes on the uncorrected declaration and the run died on exactly the
    defect the repair had fixed.
    """
    target_dir = _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    uncovered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    )
    repaired = uncovered.replace("covers:       STATUS-001", "covers:       STATUS-001, ARCH-001")
    envelope = f"<TOPOLOGY.md>\n{repaired}\n</TOPOLOGY.md>\n"
    runner = _sequence_runner(_topology_output(uncovered), envelope)

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert (target_dir / "MANIFEST.md").is_file()
    assert result.plan.by_id()["story-status"].fields["covers"] == ("STATUS-001", "ARCH-001")


def test_a_coverage_repair_prefaced_by_prose_is_still_read(tmp_path):
    """A valid delimited repair is not discarded for harmless model narration."""
    target_dir = _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    uncovered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    )
    repaired = uncovered.replace("covers:       STATUS-001", "covers:       STATUS-001, ARCH-001")
    reply = "I corrected the missing coverage.\n\n" + _declaration_block(repaired)
    runner = _sequence_runner(_topology_output(uncovered), reply)

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert (target_dir / "MANIFEST.md").is_file()
    assert result.plan.by_id()["story-status"].fields["covers"] == ("STATUS-001", "ARCH-001")


def test_the_repair_prompt_states_the_grammar_and_demonstrates_no_other(tmp_path):
    """A prompt must never show a boundary syntax it does not want back."""
    assembly = ps._topology_repair_assembly(
        declaration=_TOPOLOGY_DECLARATION, defect="a defect", pass_number=1
    )
    text = assembly.rendered_text

    assert artifact_blocks.ARTIFACT_OPEN_TEMPLATE.format(name="TOPOLOGY.md") in text
    assert artifact_blocks.ARTIFACT_CLOSE_TOKEN in text
    assert "<original-topology>" not in text


def test_the_artifact_repair_prompt_states_the_same_grammar():
    assembly = ps._artifact_repair_assembly(
        blocks={"FEATURE-Status.md": "# FEATURE: Status"},
        names=("FEATURE-Status.md",),
        defect="a defect",
        pass_number=1,
    )
    text = assembly.rendered_text

    assert artifact_blocks.ARTIFACT_OPEN_TEMPLATE.format(name="FEATURE-Status.md") in text
    assert artifact_blocks.ARTIFACT_CLOSE_TOKEN in text
    assert "<original-artifact" not in text


def test_the_artifact_repair_prompt_carries_the_normative_compass(tmp_path):
    """A repair pass told to add an assertion is shown the rules that bind assertions.

    The observed failure: a repair pass with no Compass added a criterion that invoked a
    staged harness without the environment variable the Compass requires of every invocation,
    making the criterion false under every implementation and parking the story.
    """
    (tmp_path / "COMPASS.md").write_text(
        "# COMPASS: Example\n\n## Compass\n\nnarrative prose\n\n"
        "## Verification Protocol\n\n"
        'Every invocation supplies `env={**os.environ, "JQ": ...}`.\n',
        encoding="utf-8",
    )

    assembly = ps._artifact_repair_assembly(
        blocks={"FEATURE-Status.md": "# FEATURE: Status"},
        names=("FEATURE-Status.md",),
        defect="a defect",
        pass_number=1,
        target_dir=tmp_path,
    )
    text = assembly.rendered_text

    assert "## Verification Protocol" in text
    assert "os.environ" in text
    assert "narrative prose" not in text


def test_the_artifact_repair_prompt_omits_the_compass_block_when_there_is_none(tmp_path):
    """A prompt gains a Compass heading only when there is Compass to carry."""
    assembly = ps._artifact_repair_assembly(
        blocks={"FEATURE-Status.md": "# FEATURE: Status"},
        names=("FEATURE-Status.md",),
        defect="a defect",
        pass_number=1,
        target_dir=tmp_path,
    )

    assert "Normative Compass sections" not in assembly.rendered_text


def test_an_unreadable_repair_reply_is_reported_rather_than_swallowed(tmp_path):
    """Proceeding is correct; proceeding silently is what cost the run."""
    _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    uncovered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    )
    runner = _sequence_runner(_topology_output(uncovered), "I have corrected the topology.")
    lines: list[str] = []

    with pytest.raises(RecordedError):
        create_plan("Example", "Example", tmp_path, runner=runner, on_text=lines.append)

    assert any("repair discarded" in line for line in lines)
    assert any("no recognised artifact delimiters" in line for line in lines)


def test_a_repair_reply_mixing_envelope_forms_is_refused():
    """An envelope is recovery for a known behaviour, not a third supported grammar."""
    text = '<artifact name="TOPOLOGY.md">\n# one\n</artifact>\n<FEATURE-Status.md>\n# two\n</FEATURE-Status.md>\n'

    assert ps._parse_repair_artifact_envelopes(text) == {}


def test_prose_in_angle_brackets_is_not_an_artifact_envelope():
    assert ps._parse_repair_artifact_envelopes("<note>\nnot a file\n</note>\n") == {}


def test_a_criterion_missing_a_staged_assets_variable_is_rejected_for_repair(tmp_path):
    """The jq run: criteria called the conformance runner without the JQ it declares.

    The criterion compiles and runs, so no existing pass sees it, and the runner exits on its
    own usage code — the assertion is false at every level of implementation quality. Validation
    now refuses it, which routes the owning specification into the artifact repair loop instead
    of emitting the defect and asking a human about it afterwards.
    """
    import pytest

    from drydock.planning_session import (
        CriteriaDefect,
        _staged_asset_env_defects,
        _validate_plan_output,
        staged_asset_env_decisions,
    )

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "run_suite.py").write_text(
        '"""Runner.\n\nEnvironment:\n'
        "    RUNNER     command that runs the candidate. Required -- no default.\n"
        '"""\n',
        encoding="utf-8",
    )
    spec = (
        "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
        "=== AC status-suite ===\nIntent: The suite passes.\n\n"
        "import subprocess\n"
        'result = subprocess.run(["python3", "sources/run_suite.py"], capture_output=True)\n'
        "assert result.returncode == 0\n"
        "=== END AC status-suite ===\n\n"
        "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n"
    )
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": spec,
        "MANIFEST.md": manifest,
    }

    with pytest.raises(CriteriaDefect, match="sources/run_suite.py without RUNNER"):
        _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))

    # The repair budget is finite. When it is spent the plan is still written, and the criterion
    # falls back to the blocking decision that parks its story.
    plan, warnings = _validate_plan_output(
        blocks,
        tmp_path,
        FakeRun(text=_llm_output(manifest)),
        enforce_criteria=False,
    )
    assert plan.blocks
    assert any("sources/run_suite.py without RUNNER" in warning for warning in warnings)
    decisions = staged_asset_env_decisions(_staged_asset_env_defects(blocks, tmp_path))
    assert [item.id for item in decisions] == [
        "acceptance-FEATURE-Status.md-status-suite-staged-env"
    ]
    assert decisions[0].severity == "blocking"


_TWO_STORY_MANIFEST = """# MANIFEST: Example
updated: 2026-06-16
plan_hash: test
state: draft

## feature 1: Status
id: feature-status
summary: Deliver the status command.
state: pending

## story 1: Deliver Status
id: story-status
parent: feature-status
summary: Build the status command.
implements: FEATURE-Status.md
scope: both
state: pending

## story 2: Run the whole suite
id: story-verify
parent: feature-status
summary: Run the complete suite.
implements: FEATURE-Verify.md
depends: story-status
scope: both
state: pending
"""


def _runner_kit(tmp_path):
    """A staged suite runner offering a list mode, as the jq conformance harness does."""
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "run_suite.py").write_text(
        '"""Runner.\n\nUsage:\n'
        "    python3 sources/run_suite.py            # whole corpus\n"
        "    python3 sources/run_suite.py --list     # print cases, run nothing\n"
        '"""\n',
        encoding="utf-8",
    )


def _spec_running(code: str) -> str:
    return (
        "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
        "=== AC status-suite ===\nIntent: The suite passes.\n\n"
        "import subprocess\n"
        f"{code}\n"
        "assert result.returncode == 0\n"
        "=== END AC status-suite ===\n\n"
        "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n"
    )


def test_a_non_terminal_story_running_the_authoritative_runner_is_rejected(tmp_path):
    """jq block-9: a phase-1 staging story ran the whole corpus and the step was abandoned.

    A partial capability fails most of an authoritative corpus by construction, and its
    unimplemented cases exhaust the runner's per-case timeout rather than returning.
    """
    import pytest

    from drydock.planning_session import CriteriaDefect, _validate_plan_output

    _runner_kit(tmp_path)
    manifest = _TWO_STORY_MANIFEST
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": _spec_running(
            'result = subprocess.run(["python3", "sources/run_suite.py"], capture_output=True)'
        ),
        "FEATURE-Verify.md": _SPEC_HEADER.format(
            ftype="FEATURE", name="Verify", ac="The suite passes."
        ),
        "MANIFEST.md": manifest,
    }

    with pytest.raises(CriteriaDefect, match="is not the terminal story"):
        _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))


def test_a_non_terminal_story_may_invoke_the_runner_in_list_mode(tmp_path):
    """List mode enumerates the suite without executing a case.

    It is the staging story's one legal criterion: the corpus parses and the harness starts,
    while nothing is asked of the code under test.
    """
    from drydock.planning_session import _validate_plan_output

    _runner_kit(tmp_path)
    manifest = _TWO_STORY_MANIFEST
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": _spec_running(
            "result = subprocess.run("
            '["python3", "sources/run_suite.py", "--list"], capture_output=True)'
        ),
        "FEATURE-Verify.md": _SPEC_HEADER.format(
            ftype="FEATURE", name="Verify", ac="The suite passes."
        ),
        "MANIFEST.md": manifest,
    }

    plan, _ = _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))

    assert plan.blocks


def test_a_criterion_supplying_the_variable_raises_no_defect(tmp_path):
    from drydock.planning_session import _staged_asset_env_defects, _validate_plan_output

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "run_suite.py").write_text(
        '"""Runner.\n\nEnvironment:\n'
        "    RUNNER     command that runs the candidate. Required -- no default.\n"
        '"""\n',
        encoding="utf-8",
    )
    spec = (
        "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
        "=== AC status-suite ===\nIntent: The suite passes.\n\n"
        "import os\nimport subprocess\n"
        "result = subprocess.run(\n"
        '    ["python3", "sources/run_suite.py"],\n'
        "    capture_output=True,\n"
        '    env={**os.environ, "RUNNER": "./status"},\n'
        ")\n"
        "assert result.returncode == 0\n"
        "=== END AC status-suite ===\n\n"
        "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n"
    )
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": spec,
        "MANIFEST.md": manifest,
    }

    _, warnings = _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))

    assert not any("without RUNNER" in warning for warning in warnings)
    assert _staged_asset_env_defects(blocks, tmp_path) == ()


def test_the_authoring_contract_example_supplies_the_variables_it_documents():
    """The exemplar is the defect's origin, so the exemplar is what the lint must clear.

    Ten jq criteria omitted the runner's required variable because the contract's worked example
    called a suite runner with no ``env=`` at all. Prose forty lines below it said otherwise and
    lost. This asserts the example and the rule agree.
    """
    from drydock.acceptance import parse_programmatic_acceptance_text
    from drydock.acceptance_env import staged_asset_env_defects

    example = _authoring_contract_blueprint_example()
    asset = (
        '"""Suite runner.\n\nEnvironment:\n'
        "    RUNNER     command that runs the candidate. Required -- no default.\n"
        '"""\n'
    )
    checks = parse_programmatic_acceptance_text(
        "# FEATURE: Example\n\n## Programmatic Acceptance\n\n" + example,
        source="FEATURE-Example.md",
    )
    suite_checks = tuple(check for check in checks if "run_suite.py" in check.code)
    assert suite_checks, "the contract example no longer runs a staged suite runner"

    assert staged_asset_env_defects(suite_checks, {"tests/run_suite.py": asset}) == ()


def test_stage_two_ledger_names_the_persistence_declaration_as_its_own_batch():
    # Every other Blueprint is frozen once accepted. This one is not: a Feature authored in a
    # later batch may need a table, or a column on a table declared batches ago.
    stories = (
        PlannedStory(
            story_id="story-1",
            name="Persistence",
            story_type="feature",
            phase=1,
            delivery_kind="capability",
            acceptance_contract=True,
            implements="DATABASE.md",
        ),
        PlannedStory(
            story_id="story-2",
            name="Items",
            story_type="feature",
            phase=1,
            delivery_kind="capability",
            acceptance_contract=True,
            implements="FEATURE-ITEMS.md",
        ),
    )
    due = ps._render_ledger(score_plan(stories, {"TOPOLOGY.md": "complete"}))

    current = due.split("Current batch (1)")[1].split("Deferred")[0]
    assert "story-1 -> DATABASE.md" in current
    assert "authored once, complete, and then frozen" in current
    assert "FEATURE-ITEMS.md" not in current

    held = ps._render_ledger(
        score_plan(stories, {"TOPOLOGY.md": "complete", "DATABASE.md": "# DATABASE: X\n"})
    )
    assert "DATABASE.md" in held.split("Accepted (1)")[1].split("Current batch")[0]
    assert "story-2 -> FEATURE-ITEMS.md" in held.split("Current batch (1)")[1]
    assert "Open (" not in held


def test_the_persistence_declaration_is_seeded_from_the_template_and_the_imported_source(tmp_path):
    blueprint_dir = tmp_path / "blueprint"
    (blueprint_dir / "sources").mkdir(parents=True)
    (blueprint_dir / "sources" / "DATABASE.md").write_text(
        "# Database: Registry\n\n"
        "## `settings`\n\n"
        "| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n",
        encoding="utf-8",
    )
    stories = (
        PlannedStory(
            story_id="story-1",
            name="Persistence",
            story_type="feature",
            phase=1,
            delivery_kind="capability",
            acceptance_contract=True,
            implements="DATABASE.md",
        ),
    )
    blocks: dict[str, str] = {}

    ps._seed_database_blueprint(blocks, declared=stories, blueprint_dir=blueprint_dir)

    seeded = blocks["DATABASE.md"]
    assert "## `settings`" in seeded
    assert "| key | TEXT PK | |" in seeded
    assert "## Access Patterns" in seeded
    assert "FEATURE-EXAMPLE-001" not in seeded


def test_no_persistence_story_leaves_the_declaration_unseeded(tmp_path):
    stories = (
        PlannedStory(
            story_id="story-1",
            name="Items",
            story_type="feature",
            phase=1,
            delivery_kind="capability",
            acceptance_contract=True,
            implements="FEATURE-ITEMS.md",
        ),
    )
    blocks: dict[str, str] = {}

    ps._seed_database_blueprint(blocks, declared=stories, blueprint_dir=tmp_path / "blueprint")

    assert blocks == {}


def _empty_plan(tmp_path) -> object:
    from drydock.manifest import DrydockManifest, ManifestMetadata

    return DrydockManifest(
        path=tmp_path / "MANIFEST.md",
        metadata=ManifestMetadata(project="X"),
        blocks=[],
        preamble=[],
    )


def test_a_persistence_declaration_with_no_tables_fails_the_plan(tmp_path):
    # A project without persistence has no DATABASE.md at all. One that exists and declares
    # nothing is an empty contract, and Build fills that vacuum by inventing its own schema.
    with pytest.raises(SpecificationError) as excinfo:
        ps._integrity_check(
            _empty_plan(tmp_path),
            tmp_path,
            emitted_files={"DATABASE.md": "# DATABASE: X\n\n## Guardrails\n\n- None.\n"},
        )

    assert "DATABASE.md: declares no tables" in str(excinfo.value)


def test_a_persistence_declaration_with_tables_passes_the_plan(tmp_path):
    warnings = ps._integrity_check(
        _empty_plan(tmp_path),
        tmp_path,
        emitted_files={
            "DATABASE.md": (
                "# DATABASE: X\n\n" + _ACCESS_PATTERNS + "## `settings`\n\n"
                "| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n"
            )
        },
    )

    assert any("1 declared table(s)" in warning for warning in warnings)


def test_a_persistence_declaration_build_cannot_parse_is_a_database_defect():
    """The live Marina_Luna defect: the model wrote ``## Access Patterns`` as one flat table of
    operations instead of a named section each. Build generates the persistence layer from that
    surface, so it is repaired like every other persistence defect — recording it as a decision
    also silenced the coverage and citation checks and let the plan report success."""
    blocks = {
        "DATABASE.md": (
            "# DATABASE: X\n\n## Access Patterns\n\n"
            "| ID | Owner | Access | Repository method | Compatibility |\n"
            "|---|---|---|---|---|\n"
            "| FEATURE-X-001 | S | read | `S.get` | unchanged |\n\n"
            "## `settings`\n\n"
            "| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n"
        )
    }

    defects = ps._database_contract_defects(blocks)

    assert [kind for kind, _ in defects] == ["database-contract-invalid"]
    assert defects[0][1].source == "DATABASE.md"
    assert "## Access Patterns has no named operation" in defects[0][1].reason
    assert "### <FEATURE-DOMAIN-NNN> — <Operation>" in defects[0][1].reason


def test_every_incomplete_access_pattern_is_reported_in_one_pass():
    """Marina_Luna: a repair pass added thirteen patterns without Input/Output tables. The parser
    stops at the first; the repair loop must see all thirteen, and the owners they name."""
    incomplete = (
        "### FEATURE-Y-00{n} — Store thing\n\n| Field | Value |\n|-------|-------|\n"
        "| Owner | FEATURE-INVENTED.md |\n| Access | read-write |\n"
        "| Repository operation | `settings.update` |\n| Compatibility | data |\n\n"
    )
    database = (
        "# DATABASE: X\n\n"
        + _ACCESS_PATTERNS.rstrip("\n")
        + "\n\n"
        + incomplete.format(n=1)
        + incomplete.format(n=2)
        + "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n"
    )
    blocks = {"DATABASE.md": database, "FEATURE-Example.md": "# FEATURE: Example\n"}

    contract = ps._database_contract_defects(blocks)
    owners = ps._database_interface_defects(blocks)

    assert [item.reason.split(" requires")[0] for _, item in contract] == [
        "DATABASE.md: FEATURE-Y-001",
        "DATABASE.md: FEATURE-Y-002",
    ]
    assert "`Input: <DtoName>`" in contract[0][1].reason
    assert [(kind, "FEATURE-INVENTED.md" in item.reason) for kind, item in owners] == [
        ("database-owner-unknown", True)
    ]


def test_a_combined_access_spelling_is_read_as_read_write():
    """One cell reading ``read-write`` discarded a whole plan. A combined surface keeps both
    levels rather than collapsing: once a Blueprint must cite the pattern it uses, a collapsed
    level would reject the read-only consumer that cites it honestly."""
    blocks = {
        "DATABASE.md": _ACCESS_PATTERNS.replace("| Access | read |", "| Access | read/write |")
    }

    warnings = ps._normalize_database_access_values(blocks)

    assert "| Access | read-write |" in blocks["DATABASE.md"]
    assert len(warnings) == 1
    assert "read as 'read-write'" in warnings[0]
    assert ps._database_contract_defects(blocks) == ()


def test_a_single_sided_access_synonym_keeps_its_side():
    """``append`` writes and ``select`` reads; neither becomes the combined level."""
    for written, settled in (("append", "write"), ("select", "read")):
        blocks = {
            "DATABASE.md": _ACCESS_PATTERNS.replace("| Access | read |", f"| Access | {written} |")
        }
        ps._normalize_database_access_values(blocks)
        assert f"| Access | {settled} |" in blocks["DATABASE.md"]


def test_an_access_value_drydock_cannot_read_is_left_for_the_contract_parser():
    """An unrecognized spelling is never reinterpreted by guesswork; it reaches the parser and is
    raised for repair there."""
    blocks = {
        "DATABASE.md": _ACCESS_PATTERNS.replace("| Access | read |", "| Access | telepathy |")
    }

    assert ps._normalize_database_access_values(blocks) == ()
    assert "invalid Access: telepathy" in ps._database_contract_defects(blocks)[0][1].reason


def _criterion(code: str, *, check_id: str = "c1") -> str:
    return (
        f"# FEATURE: Example\n\n## Programmatic Acceptance\n\n=== AC {check_id} ===\n"
        f"Intent: Example.\n\n{code}\n=== END AC {check_id} ===\n"
    )


def test_a_criterion_admitting_not_found_beside_success_proves_nothing():
    """The live shape: 37 criteria, 22% of a plan's gates, each satisfied by an application with
    no routes at all. 404 means the endpoint is absent, so admitting it beside any other status
    makes the criterion true of an implementation that does nothing."""
    blocks = {"FEATURE-Example.md": _criterion("assert response.status_code in {200, 404}")}

    defects = ps._weak_acceptance_defects(blocks)

    assert len(defects) == 1
    assert "404 means the endpoint is absent" in defects[0].reason
    assert ps.weak_acceptance_decisions(defects)[0].severity == "material"


def test_a_stub_that_pins_the_status_it_answers_with_is_a_real_test():
    """Specifying a stub is legitimate, and a stub that answers is a real contract. The criterion
    is not the defect; one that declines to say what the stub answers is."""
    blocks = {"FEATURE-Example.md": _criterion("assert response.status_code == 200")}

    assert ps._weak_acceptance_defects(blocks) == ()


def test_a_not_found_probe_asserted_alone_is_one_of_the_strongest_checks():
    blocks = {"FEATURE-Example.md": _criterion("assert response.status_code == 404")}

    assert ps._weak_acceptance_defects(blocks) == ()


def test_a_criterion_admitting_success_and_server_failure_proves_nothing():
    blocks = {"FEATURE-Example.md": _criterion("assert response.status_code in (200, 503)")}

    defects = ps._weak_acceptance_defects(blocks)

    assert len(defects) == 1
    assert "success and server failure" in defects[0].reason


def test_a_determinate_pair_of_outcomes_is_not_weak():
    """``created or already exists`` is one expectation stated over two codes; neither admits an
    application that implements nothing, so it is left alone."""
    blocks = {"FEATURE-Example.md": _criterion("assert response.status_code in [201, 409]")}

    assert ps._weak_acceptance_defects(blocks) == ()


_DATABASE = (
    "# DATABASE: X\n\n"
    + _ACCESS_PATTERNS
    + "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n"
)
#: The owner of ``FEATURE-X-001`` citing it correctly. Present in a case that is about some
#: other Blueprint, so the declaration is coherent and only the Blueprint under test is at issue.
_OWNER = (
    "# FEATURE: Example\n\n## Database Interface\n\n"
    "- `FEATURE-X-001` — read: read a setting - supplies: `key` - returns: `key`\n"
)


def test_a_blueprint_named_as_owner_that_cites_nothing_fails_the_plan():
    """The boundary this section exists to enforce: the declaration says this Blueprint reaches
    the repository and the Blueprint names no operation, so its storage access is unchecked.
    Recording it as a decision left 17 of a live plan's Blueprints in exactly that state."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": "# FEATURE: Example\n\n## Guardrails\n\n- None.\n",
    }

    defects = ps._database_interface_defects(blocks)

    assert [kind for kind, _ in defects] == ["database-interface-missing"]
    # The repair loop chunks by source, so the defect names the Blueprint to re-emit — not
    # DATABASE.md, which is correct as written.
    assert defects[0][1].source == "FEATURE-Example.md"
    assert "FEATURE-X-001" in defects[0][1].reason


def test_a_blueprint_that_reaches_no_repository_declares_none_and_passes():
    """A Screen that delegates persistence writes the heading because the claim is true of it.
    With no declared form for the empty claim it had to write prose, and prose parsed as a
    malformed citation — five repair passes that no message told how to repair."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": _OWNER,
        "SCREEN-Example.md": (
            "# SCREEN: Example\n\n## Database Interface\n\n"
            "- None — persistence is owned by FEATURE-Example.md.\n"
        ),
    }

    assert ps._database_interface_defects(blocks) == ()


def test_an_owner_cannot_escape_the_gate_by_declaring_none():
    """``- None`` is the empty claim, available only to a Blueprint the declaration names
    nowhere. An owner saying it contradicts the pattern that names it."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Database Interface\n\n- None — nothing is stored.\n"
        ),
    }

    defects = ps._database_interface_defects(blocks)

    assert [kind for kind, _ in defects] == ["database-interface-missing"]


def test_ownership_is_read_from_the_declaration_not_from_the_story_stack():
    """A stack selection says which technology the story is built with, not whether it reaches a
    repository. Every Python story carries sqlalchemy.md and alembic.md, so the application shell
    that only runs the startup migration was told to cite an operation it does not own — and a Go
    or C++ Target was never gated at all."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": _OWNER,
        "FEATURE-Shell.md": (
            "# FEATURE: Shell\n\n## Database Interface\n\n"
            "- None — the shell runs the migration; FEATURE-Example.md owns the data.\n"
        ),
    }

    assert ps._database_interface_defects(blocks) == ()


def test_an_owner_that_names_no_blueprint_is_the_declarations_defect():
    """Marina_Luna declared every Owner as a service name — `Workflow service` — and the check
    compares it to a file name. Caught per citation it is one unrepairable defect in the first
    Blueprint to notice, which is where four repair passes went. Caught here it is one message
    against the one file that is wrong."""
    blocks = {
        "DATABASE.md": _DATABASE.replace(
            "| Owner | FEATURE-Example.md |", "| Owner | Settings service |"
        ),
        "FEATURE-Example.md": _OWNER,
    }

    defects = ps._database_interface_defects(blocks)

    assert "database-owner-unknown" in {kind for kind, _ in defects}
    unknown = next(defect for kind, defect in defects if kind == "database-owner-unknown")
    assert unknown.source == "DATABASE.md"
    assert "Settings service" in unknown.reason


def test_a_citation_conflict_repairs_both_sides():
    """A citation conflict is a disagreement between two files. The repair loop re-emits exactly
    the sources it is given, so a pass handed only the Blueprint has no legal move when the
    declaration is the wrong side — four passes returning the same defect was the observed cost."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Database Interface\n\n"
            "- `FEATURE-X-001` — write: write a setting - supplies: `key` - returns: `key`\n"
        ),
    }

    defects = ps._database_interface_defects(blocks)

    assert {kind for kind, _ in defects} == {"database-citation-conflict"}
    assert sorted(defect.source for _, defect in defects) == [
        "DATABASE.md",
        "FEATURE-Example.md",
    ]


def test_prose_under_the_interface_heading_names_the_line_and_the_accepted_form():
    """The repair prompt carries the defect message and nothing else, so the message is the
    only place the grammar can reach the model that has to satisfy it."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Database Interface\n\n"
            "- **Settings** — Read and write through the repository declared by DATABASE.md.\n"
        ),
    }

    defects = ps._database_interface_defects(blocks)

    assert [kind for kind, _ in defects] == ["database-interface-invalid"]
    assert "**Settings**" in defects[0][1].reason
    assert "supplies:" in defects[0][1].reason


def test_a_citation_that_contradicts_the_declaration_fails_the_plan():
    """The Blueprint names an operation the declaration does not grant it, so Build would
    implement the disagreement."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": (
            "# FEATURE: Example\n\n## Database Interface\n\n"
            "- `FEATURE-NOPE-001` — read: invented - supplies: `key` - returns: `key`\n"
        ),
    }

    defects = ps._database_interface_defects(blocks)

    assert {kind for kind, _ in defects} == {"database-citation-conflict"}
    assert "unknown database operation" in defects[0][1].reason


def test_one_bad_citation_does_not_hide_another_blueprint():
    """The validator raises on the first defect it finds. Calling it once per Blueprint is what
    lets the repair loop see every file that needs re-emitting instead of one per pass."""
    interface = (
        "# FEATURE: {name}\n\n## Database Interface\n\n"
        "- `FEATURE-NOPE-001` — read: invented - supplies: `key` - returns: `key`\n"
    )
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": interface.format(name="Example"),
        "FEATURE-Other.md": interface.format(name="Other"),
    }

    defects = ps._database_interface_defects(blocks)

    assert sorted({defect.source for _, defect in defects}) == [
        "DATABASE.md",
        "FEATURE-Example.md",
        "FEATURE-Other.md",
    ]


def test_a_declared_table_no_pattern_reaches_fails_the_plan():
    """Four tables and three access patterns shipped in a live plan with nothing looking at the
    fourth. The table is storage the declaration describes and no story can use."""
    blocks = {
        "DATABASE.md": "# DATABASE: X\n\n" + _ACCESS_PATTERNS + "## `settings`\n\n"
        "| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n\n"
        "## `activity_events`\n\n"
        "| Field | Type | Notes |\n|---|---|---|\n| id | INTEGER PK | |\n",
    }

    defects = ps._database_table_defects(blocks)

    assert [kind for kind, _ in defects] == ["database-table-uncited"]
    assert defects[0][1].check_id == "activity_events"
    assert defects[0][1].source == "DATABASE.md"


def test_an_operation_on_an_undeclared_table_fails_the_plan():
    """The same disagreement from the other side: Build would write a repository against a table
    that will not exist."""
    blocks = {
        "DATABASE.md": "# DATABASE: X\n\n"
        + _ACCESS_PATTERNS.replace("`settings.get`", "`audit.get`")
        + "## `settings`\n\n"
        "| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n",
    }

    defects = ps._database_table_defects(blocks)

    assert sorted(kind for kind, _ in defects) == [
        "database-table-uncited",
        "database-table-undeclared",
    ]


def test_a_persistence_defect_is_not_forgiven_when_repair_is_exhausted():
    """A criterion that cannot be repaired is recorded as a decision and the plan is kept. A
    persistence defect is not: the amnesty at the end of the repair loop tests for CriteriaDefect,
    and DatabaseDefect is deliberately a sibling rather than a subclass."""
    defect = ps.DatabaseDefect("boom", defects=())

    assert isinstance(defect, ps.SpecificationError)
    assert not isinstance(defect, ps.CriteriaDefect)


def test_a_blueprint_the_declaration_names_nowhere_needs_no_citation():
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": _OWNER,
        "SCREEN-Other.md": "# SCREEN: Other\n\n## Guardrails\n\n- None.\n",
    }

    assert ps._database_interface_defects(blocks) == ()


@pytest.mark.parametrize(
    "section",
    [
        # The three shapes a live Marina_Luna repair loop alternated between for three passes.
        "| Direction | Fields |\n|---|---|\n| Supplies | settings |\n",
        "",
        "- Access pattern: Reads and writes Marina-owned SQLite runtime state.\n",
    ],
)
def test_an_owners_invalid_interface_is_rewritten_from_the_declaration(section):
    """An owner may cite only what it owns, so its section is derivable from ``DATABASE.md``
    and no LLM pass is spent on it."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": (
            f"# FEATURE: Example\n\n## Database Interface\n\n{section}\n## Guardrails\n\n- None.\n"
        ),
    }

    warnings = ps._normalize_database_interfaces(blocks)

    assert len(warnings) == 1 and "FEATURE-Example.md" in warnings[0]
    assert ps._database_interface_defects(blocks) == ()
    assert "- `FEATURE-X-001` — " in blocks["FEATURE-Example.md"]
    assert blocks["FEATURE-Example.md"].endswith("## Guardrails\n\n- None.\n")


def test_an_owner_no_feature_answers_to_becomes_the_declarations_own():
    """Marina_Luna's activity log: six Features append to it, none owns it, and a repair pass
    invented `FEATURE-ACTIVITY-EVENTS.md` for the gap. The plan resolves it without an LLM."""
    blocks = {
        "DATABASE.md": _DATABASE.replace(
            "| Owner | FEATURE-Example.md |", "| Owner | FEATURE-Activity-Events.md |", 1
        ),
        "FEATURE-Example.md": "# FEATURE: Example\n",
        "SCREEN-Other.md": "# SCREEN: Other\n",
    }

    warnings = ps._normalize_database_owners(blocks)

    assert len(warnings) == 1 and "FEATURE-Activity-Events.md" in warnings[0]
    assert "| Owner | DATABASE.md |" in blocks["DATABASE.md"]
    assert ps._database_interface_defects(blocks) == ()
    # Shared, so no Blueprint is required to cite it and none is rewritten for it.
    assert ps._normalize_database_interfaces(blocks) == ()


def test_a_screen_may_not_own_a_table():
    blocks = {
        "DATABASE.md": _DATABASE.replace(
            "| Owner | FEATURE-Example.md |", "| Owner | SCREEN-Example.md |", 1
        ),
        "SCREEN-Example.md": "# SCREEN: Example\n",
    }

    assert ps._normalize_database_owners(blocks)
    assert "| Owner | DATABASE.md |" in blocks["DATABASE.md"]


def test_an_unknown_owner_elsewhere_does_not_stop_a_real_owners_rewrite():
    """Marina_Luna: one invented owner made this function bail on all of them, so four sections
    it derives exactly were handed to the model instead, and the repair budget died on them."""
    invented = _DATABASE.replace(
        "### FEATURE-X-001",
        "### FEATURE-Y-001 — Read setting\n\n| Field | Value |\n|---|---|\n"
        "| Owner | FEATURE-Absent.md |\n| Access | read |\n"
        "| Repository operation | `settings.get` |\n| Compatibility | rebuild |\n\n"
        "Input: GetSetting\n\n| Field | Type | Required |\n|---|---|---|\n| key | str | yes |\n\n"
        "Output: Setting\n\n| Field | Type |\n|---|---|\n| key | str |\n\n### FEATURE-X-001",
        1,
    )
    blocks = {
        "DATABASE.md": invented,
        "FEATURE-Example.md": "# FEATURE: Example\n",
        "SCREEN-Other.md": "# SCREEN: Other\n\n## Guardrails\n\n- None.\n",
    }

    warnings = ps._normalize_database_interfaces(blocks)

    # The owner's own section is a function of the patterns that name it, so it is written.
    assert [w.split(":")[0] for w in warnings] == ["FEATURE-Example.md"]
    assert "- `FEATURE-X-001` — " in blocks["FEATURE-Example.md"]
    # The Blueprint that owns nothing is left alone: the invented owner may be its name
    # misspelled, and `- None` would overwrite the citations it is owed.
    assert "## Database Interface" not in blocks["SCREEN-Other.md"]
    # Only the declaration's own defect survives, for one repair pass that can fix it.
    assert [kind for kind, _ in ps._database_interface_defects(blocks)] == [
        "database-owner-unknown"
    ]


def test_a_database_repair_prompt_lists_the_blueprints_that_may_own_a_pattern():
    """The invented owner came from a pass that was never told which Blueprints exist."""
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": _OWNER,
        "MANIFEST.md": "",
        "DECISIONS.json": "[]",
    }

    rendered = ps._artifact_repair_assembly(
        blocks=blocks, names=("DATABASE.md",), defect="d", pass_number=1
    ).rendered_text

    assert "- FEATURE-Example.md" in rendered
    assert "- MANIFEST.md" not in rendered and "- DECISIONS.json" not in rendered
    assert "- DATABASE.md" not in rendered
    assert "`DATABASE.md` for a pattern no single Feature owns" in rendered


def test_a_blueprint_only_repair_prompt_carries_no_owner_list():
    rendered = ps._artifact_repair_assembly(
        blocks={"DATABASE.md": _DATABASE, "FEATURE-Example.md": _OWNER},
        names=("FEATURE-Example.md",),
        defect="d",
        pass_number=1,
    ).rendered_text

    assert "may own" not in rendered and "- FEATURE-Example.md" not in rendered


def test_one_repair_pass_carries_every_defect_its_files_have():
    """Three passes on one DATABASE.md, each shown one defect and failing on the next, is how a
    live run spent its budget without ever validating."""
    from drydock.acceptance import MalformedAcceptance
    from drydock.planning_session import _PLAN_BLUEPRINT_BATCH_SIZE, _next_repair_chunk

    class FakeCriteriaDefect(Exception):
        defects: tuple

    exc = FakeCriteriaDefect()
    exc.defects = (
        ("owner-unknown", MalformedAcceptance(check_id="a", source="DATABASE.md", reason="one")),
        ("too-many-ops", MalformedAcceptance(check_id="b", source="DATABASE.md", reason="two")),
        ("other", MalformedAcceptance(check_id="c", source="FEATURE-Other.md", reason="three")),
    )

    kind, names, text = _next_repair_chunk(
        exc, {"DATABASE.md": "", "FEATURE-Other.md": ""}, _PLAN_BLUEPRINT_BATCH_SIZE
    )

    assert names == ("DATABASE.md",)
    assert "one" in text and "two" in text
    assert "three" not in text  # a file this pass does not re-emit is not its business


def test_an_owner_missing_the_section_gains_it():
    blocks = {"DATABASE.md": _DATABASE, "FEATURE-Example.md": "# FEATURE: Example\n"}

    assert ps._normalize_database_interfaces(blocks)
    assert ps._database_interface_defects(blocks) == ()


def test_a_non_owners_prose_interface_becomes_none():
    blocks = {
        "DATABASE.md": _DATABASE,
        "FEATURE-Example.md": _OWNER,
        "SCREEN-Example.md": "# SCREEN\n\n## Database Interface\n\nDelegates to the feature.\n",
    }

    ps._normalize_database_interfaces(blocks)

    assert "- None — persistence is owned by FEATURE-Example.md." in blocks["SCREEN-Example.md"]
    assert ps._database_interface_defects(blocks) == ()


def test_a_valid_narrowed_citation_is_left_alone():
    blocks = {"DATABASE.md": _DATABASE, "FEATURE-Example.md": _OWNER}

    assert ps._normalize_database_interfaces(blocks) == ()
    assert blocks["FEATURE-Example.md"] == _OWNER


def test_an_unknown_owner_is_left_to_the_repair_loop():
    blocks = {
        "DATABASE.md": _DATABASE.replace(
            "| Owner | FEATURE-Example.md |", "| Owner | Settings service |"
        ),
        "FEATURE-Example.md": "# FEATURE: Example\n\n## Database Interface\n\nprose\n",
    }

    assert ps._normalize_database_interfaces(blocks) == ()


def test_a_plan_build_cannot_execute_is_written_as_draft_and_reported(tmp_path):
    """The Marina_Luna false positive: a plan with criteria that cannot run reported
    ``approved``. The terminal check keeps the paid-for artifacts for ``drydock plan repair``,
    leaves the Manifest draft so Build refuses it, and returns the report rather than failing,
    so ``drydock plan verify <T> || drydock plan repair <T>`` follows (FxRates
    ``20261024.015228`` halted on the failure before its own repair stage)."""
    from drydock.build_plan import parse_build_plan
    from drydock.metadata import get_sub_state

    target_dir = _make_target(tmp_path)
    (target_dir / "METADATA.md").write_text("name: Example\nbuild_sub_state: \n", encoding="utf-8")
    broken = _llm_output().replace(
        "### check-1\nThe Status route responds with HTTP 200.\n\n```python\nassert True\n```",
        '=== AC status-open ===\nIntent: Never closed.\n\nsample = """\n',
        1,
    )
    assert broken != _llm_output()

    feature = broken[
        broken.index("=== FEATURE-Status.md ===") : broken.index("=== MANIFEST.md ===")
    ]
    calls: list[str] = []

    def runner(*args, **kwargs):
        # The plan call, then repair calls that return the criterion still unclosed.
        calls.append("call")
        return FakeRun(text=broken if len(calls) == 1 else feature)

    result = create_plan(
        "Example", "Example", tmp_path, runner=runner, allow_diagnostic_recovery=True
    )

    assert "status-open" in result.unbuildable
    assert len(calls) > 1  # the criterion reached the repair loop before the plan was failed

    assert (target_dir / "blueprint" / "FEATURE-Status.md").is_file()
    assert parse_build_plan(target_dir / "MANIFEST.md").state == "draft"
    assert get_sub_state(target_dir) == "unbuildable"
    errors = (target_dir / "ERRORS.md").read_text(encoding="utf-8")
    assert "plan cannot be built as written" in errors
    assert "status-open" in errors


def test_an_idless_end_marker_is_a_terminator_not_a_missing_one():
    """Treated as absent, the unterminated-block pass appended a terminator after the section's
    prose, burying the bare marker and the prose inside the criterion's code."""
    from drydock.planning_session import (
        _normalize_fused_acceptance_boundaries,
        _normalize_unterminated_acceptance_blocks,
    )

    text = "=== AC only ===\nIntent: One.\nassert 1\n=== END AC\n\n## Guardrails\n\n- None.\n"
    blocks = {"FEATURE-Example.md": text}

    assert _normalize_unterminated_acceptance_blocks(blocks) == ()
    assert _normalize_fused_acceptance_boundaries(blocks)
    assert "=== END AC only ===\n\n## Guardrails" in blocks["FEATURE-Example.md"]


def test_a_pattern_without_dtos_is_completed_before_the_persistence_gate():
    """Marina_Luna: fifteen repair-added patterns omitted their DTO tables and the gate ended the
    run. The schema table fixes them, so normalization writes them and the gate sees none."""
    database = (
        "# DATABASE: Accounts\n\n## Access Patterns\n\n"
        "### FEATURE-EXAMPLE-001 — Read account\n"
        "| Field | Value |\n|-------|-------|\n| Owner | FEATURE-Example.md |\n"
        "| Access | read |\n| Repository operation | `accounts.get` |\n"
        "| Compatibility | unchanged |\n\n"
        "## Schema\n\n## `accounts`\n\n| Field | Type | Notes |\n|---|---|---|\n"
        "| id | INTEGER PK | |\n| login | TEXT NOT NULL | |\n"
    )
    blocks = {"DATABASE.md": database, "FEATURE-Example.md": "# FEATURE: Example\n"}
    assert ps._database_contract_defects(blocks)

    warnings = ps._normalize_database_dtos(blocks)

    assert len(warnings) == 1 and "FEATURE-EXAMPLE-001" in warnings[0]
    assert ps._database_contract_defects(blocks) == ()
    assert ps._database_table_defects(blocks) == ()


_UNMASKED_SCREEN_DEFECT = ps.SpecificationError(
    "Plan integrity check failed:\n"
    "  github-screen: SCREEN-SETUP-GITHUB.md: Programmatic Acceptance never calls route(s) "
    "GET /api/setup/github/accounts/connect/{flow_id} — a SCREEN's assertions must call every "
    "route it provides or consumes"
)


def test_a_pass_that_clears_its_files_buys_budget_for_the_defect_it_unmasked():
    """Marina_Luna: three passes repaired DATABASE.md; the third succeeded and exposed a SCREEN
    route-coverage defect that validation had masked. The run failed with no pass left for it."""
    blocks = {"DATABASE.md": "", "SCREEN-SETUP-GITHUB.md": ""}

    budget = ps._extended_repair_budget(
        3, 3, ("DATABASE.md",), _UNMASKED_SCREEN_DEFECT, blocks, batch_size=5, floor=3
    )

    assert budget == 6
    assert ps._repairable_artifact_names(blocks, str(_UNMASKED_SCREEN_DEFECT)) == (
        "SCREEN-SETUP-GITHUB.md",
    )


def test_a_pass_that_leaves_its_own_file_defective_buys_no_budget():
    blocks = {"DATABASE.md": "", "SCREEN-SETUP-GITHUB.md": ""}
    still_broken = ps.SpecificationError("DATABASE.md: table `tags` has no access pattern")

    assert (
        ps._extended_repair_budget(
            3, 2, ("DATABASE.md",), still_broken, blocks, batch_size=5, floor=3
        )
        == 3
    )


def test_unmasked_defects_cannot_extend_the_budget_past_its_ceiling():
    blocks = {"DATABASE.md": "", "SCREEN-SETUP-GITHUB.md": ""}

    budget = ps._extended_repair_budget(
        8, 8, ("DATABASE.md",), _UNMASKED_SCREEN_DEFECT, blocks, batch_size=5, floor=3
    )

    assert budget == 3 * ps._REPAIR_BUDGET_CEILING_FACTOR


def test_schedule_cost_uses_compact_context_and_counts_shared_rules_once(tmp_path, isolated_config):
    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "DOMAIN.md").write_text("full contract " * 4000)
    (blueprint / "DOMAIN_compact.md").write_text("compact contract " * 400)
    (tmp_path / "local-rules.md").write_text("rules " * 400)
    a_text, b_text = "A specification\n", "B specification\n"
    (blueprint / "A.md").write_text(a_text)
    (blueprint / "B.md").write_text(b_text)
    declared = [
        PlannedStory(
            story_id=name,
            story_type="service",
            implements=f"{name.upper()}.md",
            fields={"context": "DOMAIN.md", "rules": "local-rules.md"},
        )
        for name in ("a", "b")
    ]
    computation = ps._compute_schedule(declared, blueprint_dir=blueprint, emitted_files={})
    assert not computation.fatal
    assert len(computation.blocks) == 1
    expected = sum(
        ps.estimate_tokens(len(text.encode()))
        for text in (a_text, b_text, "compact contract " * 400, "rules " * 400)
    )
    assert computation.blocks[0].size_tokens == expected


def test_schedule_full_implementation_wins_over_compact_context(tmp_path, isolated_config):
    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "A.md").write_text("A specification\n")
    (blueprint / "B.md").write_text("B implementation " * 400)
    (blueprint / "B_compact.md").write_text("B interface\n")
    declared = [
        PlannedStory(
            story_id="a",
            story_type="service",
            implements="A.md",
            fields={"context": "B.md", "rules": "local-rules.md"},
        ),
        PlannedStory(
            story_id="b",
            story_type="service",
            implements="B.md",
            fields={"rules": "local-rules.md"},
        ),
    ]
    (tmp_path / "local-rules.md").write_text("rule " * 2000)
    computation = ps._compute_schedule(declared, blueprint_dir=blueprint, emitted_files={})
    assert not computation.fatal
    assert len(computation.blocks) == 1
    expected = sum(
        ps.estimate_tokens(len(text.encode()))
        for text in ("A specification\n", "B implementation " * 400, "rule " * 2000)
    )
    assert computation.blocks[0].size_tokens == expected


@pytest.mark.parametrize("bad_first", [False, True])
def test_complete_plan_preserves_seed_and_freezes_crud_contract(tmp_path, bad_first):
    from drydock.database_contract import parse_database_contract, sqlite_schema_tables
    from drydock.plan_verify import verify

    target = _make_target(tmp_path)
    _select_sqlite(target)
    seed = "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n| value | TEXT | |\n\n- UNIQUE (key, value)\n"
    (target / "blueprint/sources/DATABASE.md").write_text(seed)
    declaration = """## story foundation
summary: Initialize Python.
type: foundational
kind: capability
phase: 1
implements: ARCHITECTURE.md
stack: python.md
acceptance: yes

## story database
summary: Provide settings persistence.
type: foundational
kind: capability
phase: 1
implements: DATABASE.md
stack: sqlite.md
depends: foundation
acceptance: yes

## story status
summary: Build the status command with settings CRUD.
type: service
kind: capability
phase: 2
implements: FEATURE-Status.md
depends: database
acceptance: yes
"""
    patterns = []
    citations = []
    for index, verb in enumerate(("get", "list", "create", "update", "delete"), 1):
        access = "read" if verb in {"get", "list"} else "write"
        identifier = f"FEATURE-X-{index:03}"
        patterns.append(
            _ACCESS_PATTERNS
            .split("## Access Patterns\n\n", 1)[1]
            .replace("FEATURE-X-001", identifier)
            .replace("FEATURE-Example.md", "FEATURE-Status.md")
            .replace("settings.get", f"settings.{verb}")
            .replace("| Access | read |", f"| Access | {access} |")
        )
        if verb == "update":
            # An update matches the key and sets at least one other column.
            patterns[-1] = patterns[-1].replace(
                "| key | str | yes |\n", "| key | str | yes |\n| value | str | no |\n", 1
            )
        citations.append(
            f"- `{identifier}` — {access}: {verb} setting - supplies: `key` - returns: `key`"
        )
    database = _SPEC_HEADER.format(ftype="DATABASE", name="Example", ac="None.")
    database = database.replace(
        "## Programmatic Acceptance",
        "## Access Patterns\n\n"
        + "\n".join(patterns)
        + "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n\n"
        + "## Programmatic Acceptance",
    )
    database = _operation_criteria(database, "get", "list", "create", "update", "delete")
    feature = _feature_block().replace(
        "## Programmatic Acceptance",
        "## Database Interface\n\n" + "\n".join(citations) + "\n\n## Programmatic Acceptance",
    )

    def block(body):
        return f"=== BEGIN ARTIFACT DATABASE.md ===\n{body}\n=== END ARTIFACT ===\n"

    replies = [_declaration_block(declaration)]
    if bad_first:
        replies.append(block(database.replace("| key | TEXT PK |", "| key | INTEGER PK |")))
    replies.extend([block(database), _arch_block() + feature])
    runner = _sequence_runner(*replies)

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == len(replies)
    assert {name for item in result.plan.blocks for name in item.fields.get("implements", ())} == {
        "ARCHITECTURE.md",
        "DATABASE.md",
        "FEATURE-Status.md",
    }
    saved = (target / "blueprint/DATABASE.md").read_text()
    table = sqlite_schema_tables(saved)[0]
    assert [column.name for column in table.columns] == ["key", "value"]
    assert table.constraints[0].columns == ("key", "value")
    assert len(parse_database_contract(saved).patterns) == 5
    assert verify("Example", target).ok
    assert "DATABASE_compact.md" in runner.calls[-1]
    if bad_first:
        assert "changes its seeded type or constraints" in runner.calls[2]


def test_an_emitted_database_whose_criteria_skip_an_operation_is_refused():
    """Plan's Stage 2 gate: every declared repository operation is called by a criterion."""
    from drydock.planning_session import _untested_operation_defects
    from tests.test_plan_verify import _CREATE_CRITERION, _database

    (defect,) = _untested_operation_defects({"DATABASE.md": _database(_CREATE_CRITERION)})

    assert defect.source == "DATABASE.md"
    assert defect.check_id == "tickets.list"
    assert "db.tickets.list(" in defect.reason
    assert _untested_operation_defects({"FEATURE-Status.md": "# FEATURE: Status\n"}) == ()


def test_an_emitted_criterion_calling_an_undeclared_operation_is_refused():
    """Plan's Stage 2 gate: a criterion calls only operations DATABASE.md declares."""
    from drydock.planning_session import _undeclared_operation_defects
    from tests.test_plan_verify import _CREATE_CRITERION, _database

    feature = "# FEATURE: Status\n\n## Programmatic Acceptance\n\n" + _CREATE_CRITERION.replace(
        "assert created.id", "assert db.tickets.get(id=created.id)"
    )
    blocks = {"DATABASE.md": _database(_CREATE_CRITERION), "FEATURE-Status.md": feature}

    (defect,) = _undeclared_operation_defects(blocks)

    assert (defect.source, defect.check_id) == ("FEATURE-Status.md", "ticket-create")
    assert "`tickets.get(...)`" in defect.reason
    assert _undeclared_operation_defects({"FEATURE-Status.md": feature}) == ()


@pytest.mark.parametrize("partial_progress", [False, True])
def test_damaged_continuation_names_the_artifact_in_progress_and_retry(partial_progress):
    from drydock.prompt_assembly import PromptAssembly

    prompts = []
    progress = []
    first = "=== BEGIN ARTIFACT FEATURE-X.md ===\n# FEATURE: X\n"
    declared = [PlannedStory(story_id="story-x", implements="FEATURE-X.md")]
    if partial_progress:
        first = "=== BEGIN ARTIFACT FEATURE-Y.md ===\n# FEATURE: Y\n=== END ARTIFACT ===\n" + first
        declared.insert(0, PlannedStory(story_id="story-y", implements="FEATURE-Y.md"))

    def runner(prompt_text, *_args, **_kwargs):
        prompts.append(prompt_text)
        return FakeRun(
            text=first
            if len(prompts) == 1
            else ("=== BEGIN ARTIFACT FEATURE-X.md ===\n# FEATURE: X\n=== END ARTIFACT ===\n"),
            execution_id=f"exec-{len(prompts)}",
        )

    result = ps._continue_short_plan(
        {"TOPOLOGY.md": "Frozen stories."},
        blocks_text="=== TOPOLOGY.md ===\nFrozen stories.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=tuple(declared),
        target="Example",
        target_dir=Path("Example"),
        llm_provider="codex",
        model=None,
        log_dir=None,
        runner=runner,
        on_text=progress.append,
        attempts=3,
        initial_execution_id="exec-topology",
    )
    assert result.score.is_complete
    assert len(prompts) == 2
    assert (
        "Previous attempt rejected — FEATURE-X.md: incomplete or nested artifact envelope"
        in prompts[1]
    )
    assert "ending with `=== END ARTIFACT ===`" in prompts[1]
    assert any(
        line.startswith("[plan-score]") and "FEATURE-X.md: incomplete or nested" in line
        for line in progress
    )


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (
            "import subprocess\nr = subprocess.run(['go', 'run', './cmd/dupfind'])\nassert r.returncode == 2",
            "go-run",
        ),
        (
            "from drydock_go import cli_runner\ncode, out, err = cli_runner([])\nassert code == 2",
            "go-cli-args",
        ),
        (
            "import subprocess\nr = subprocess.run(['./cmd/dupfind'])\nassert r.returncode == 0",
            "go-package-launch",
        ),
    ],
)
def test_go_cli_defects_enter_the_artifact_repair_gate(tmp_path, code, kind):
    from drydock.planning_session import CriteriaDefect, _validate_plan_output

    technology_stack.write(tmp_path, [technology_stack.StackEntry("Go", "go.md")])
    blueprint_dir = tmp_path / "blueprint"
    blueprint_dir.mkdir()
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": (
            "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
            "=== AC usage ===\nIntent: Usage errors exit 2.\n" + code + "\n=== END AC usage ===\n"
        ),
        "MANIFEST.md": manifest,
    }
    with pytest.raises(CriteriaDefect) as raised:
        _validate_plan_output(dict(blocks), blueprint_dir, FakeRun(text=_llm_output(manifest)))
    assert [(k, d.source, d.check_id) for k, d in raised.value.defects] == [
        (kind, "FEATURE-Status.md", "usage")
    ]
    # Exhausted repairs still preserve paid-for artifacts for the final buildability gate.
    plan, _ = _validate_plan_output(
        dict(blocks), blueprint_dir, FakeRun(text=_llm_output(manifest)), enforce_criteria=False
    )
    assert plan.blocks


def test_refused_batch_names_retry_or_exhaustion() -> None:
    """A refused batch says whether a retry follows; an operator reads bare "Rejected" as fatal."""
    assert ps._refused_batch("bad", 0, 3) == "Retrying (2 left): bad"
    assert ps._refused_batch("bad", 1, 3) == "Retrying (1 left): bad"
    assert ps._refused_batch("bad", 2, 3) == "Retries exhausted: bad"
