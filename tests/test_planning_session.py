"""Tests for the LLM-driven ``drydock plan create`` (planning_session.create_plan).

A fake runner supplies canned delimited-block output; no API credits are spent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock import technology_stack
from drydock.acceptance import parse_programmatic_acceptance
from drydock.build_plan import AppliedSpecRecord, parse_build_plan
from drydock.errors import RecordedError, SpecificationError
from drydock.plan_graph import PlannedStory
from drydock.plan_score import score_plan
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


def test_default_feedback_heading_is_plan_compass(tmp_path):
    assert ensure_feedback_file(tmp_path) == "# Plan Compass\n"


def test_plan_prompt_declares_strict_artifact_contract():
    prompt = (Path(__file__).parents[1] / "prompts" / "plan_create.md").read_text(encoding="utf-8")

    assert "Emit exactly one response mode" in prompt
    assert "### Success Mode" in prompt
    assert "=== PLAN_CREATE_ERROR.txt ===" in prompt
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

    assert "`accepts:` is traceability metadata, not a child acceptance command." in prompt
    assert "perform an exhaustive traceability audit" in prompt


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
    with pytest.raises(SpecificationError) as excinfo:
        _parse_strict_blocks(_OPEN_ONLY_OUTPUT, FakeRun(text=_OPEN_ONLY_OUTPUT))
    message = str(excinfo.value)
    assert "Delimiter pairing mismatch" in message
    assert "=== END MANIFEST.md ===" in message


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
    assert progress[0].startswith(
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

    # Acceptance is mandatory: a surface-declaring spec still lacking assertions after
    # a failed conform pass aborts the plan instead of writing with a warning.
    with pytest.raises(RecordedError) as excinfo:
        create_plan(
            "Example",
            "Example",
            tmp_path,
            runner=_conform_runner(block),
        )
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="Programmatic Acceptance assertion",
    )

    # Original imported content is left intact when conform fails to author acceptance.
    assert "Verify status prints the build state." in feature.read_text(encoding="utf-8")


def test_no_conform_flag_skips_conform_pass(tmp_path):
    target_dir, feature = _seed_conform_target(tmp_path, feature_text=_FEATURE_EMPTY_ACCEPTANCE)
    seen: list[str] = []

    # Conform is suppressed, so the surface-declaring spec keeps its bare `- None.`
    # acceptance and the mandatory-acceptance gate aborts the plan.
    with pytest.raises(RecordedError) as excinfo:
        create_plan(
            "Example",
            "Example",
            tmp_path,
            conform=False,
            runner=_conform_runner("unused", seen=seen),
        )
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="Programmatic Acceptance assertion",
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

    assert progress[0].startswith(
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

    assert progress[0].startswith(
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
    db = _SPEC_HEADER.format(ftype="DATABASE", name="Example Data", ac="None.")
    manifest = _manifest().replace(
        "scope: both\nstate: pending",
        "scope: both\ncontext: README.md, ARCHITECTURE.md\nstate: pending",
    )
    out = (
        f"=== ARCHITECTURE.md ===\n{_SPEC_HEADER.format(ftype='ARCHITECTURE', name='Example', ac='None.')}\n=== END ARCHITECTURE.md ===\n"
        f"=== DATABASE.md ===\n{db}\n=== END DATABASE.md ===\n"
        f"=== FEATURE-Status.md ===\n{_SPEC_HEADER.format(ftype='FEATURE', name='Status', ac='Status command exits successfully.')}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n"
    )

    create_plan("Example", "Example", tmp_path, runner=_fake(out))

    text = (target_dir / "MANIFEST.md").read_text(encoding="utf-8")
    assert "context: README.md, ARCHITECTURE_compact.md, DATABASE_compact.md" in text
    assert not (target_dir / "blueprint" / "ARCHITECTURE_compact.md").exists()
    assert not (target_dir / "blueprint" / "DATABASE_compact.md").exists()


def test_compass_routed_source_is_dropped_from_manifest_context(tmp_path):
    """A sources/ context ref to a compass-routed (non-promoted) file is dropped, not rewritten.

    ED_INSTRUCTIONS.md is author intent: analyze routes it to COMPASS.md and it is never
    emitted into blueprint/. The LLM still references ``sources/ED_INSTRUCTIONS.md`` as build
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
    # It landed in the Compass, which is correct.
    assert "Build it exactly this way." in (target_dir / "COMPASS.md").read_text(encoding="utf-8")
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


def test_absent_technology_stack_does_not_block_planning(tmp_path):
    """An undecided stack is planning input, not a gate. Nothing here may raise."""
    target_dir = _make_target(tmp_path)
    (target_dir / "QuarterDeck" / "questionnaires" / "discovery-stack.json").unlink()
    assert not (target_dir / technology_stack.FILENAME).exists()

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))
    assert (target_dir / "MANIFEST.md").is_file()


def test_empty_technology_stack_does_not_block_planning(tmp_path):
    target_dir = _make_target(tmp_path)
    technology_stack.write(target_dir, [])

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))
    assert (target_dir / "MANIFEST.md").is_file()


def test_technology_stack_is_injected_into_the_plan_prompt(tmp_path):
    target_dir = _make_target(tmp_path)
    technology_stack.write(
        target_dir,
        [
            technology_stack.StackEntry("FastAPI", "fastapi.md"),
            technology_stack.StackEntry("marina-library", None, "Internal."),
        ],
    )
    captured = {}

    def runner(*args, **kwargs):
        captured["assembly"] = kwargs.get("prompt_assembly")
        return FakeRun(text=_llm_output())

    create_plan("Example", "Example", tmp_path, runner=runner)
    prompt = captured["assembly"].rendered_text
    assert technology_stack.FILENAME in prompt
    assert "fastapi.md" in prompt
    assert "marina-library" in prompt


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


def test_unbounded_test_suite_inside_acceptance_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    ).replace(
        "## Programmatic Acceptance\n\n",
        "## Programmatic Acceptance\n\n"
        "### check-0\nThe full conformance test suite passes.\n\n"
        "```python\n"
        "import subprocess, sys\n"
        'subprocess.run([sys.executable, "tests/spec_tests.py"], check=True)\n'
        "```\n\n",
    )
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="runs the whole test suite",
    )


def test_scoped_suite_cannot_require_zero_skipped(tmp_path):
    # The zero-skipped claim is read from a report the harness writes, not from captured stdout:
    # a tally asserted as a literal substring of a runner's output is stripped as unsatisfiable
    # before this rule is reached, so the rule is exercised on the form that survives that pass.
    target_dir = _make_target(tmp_path)
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    ).replace(
        "## Programmatic Acceptance\n\n",
        "## Programmatic Acceptance\n\n"
        "### check-scoped\nThe owned conformance slice passes.\n\n"
        "Suite: scoped\n\n"
        "```python\n"
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        "result = subprocess.run(\n"
        '    [sys.executable, "tests/spec_tests.py", "--pattern", "Escapes"],\n'
        "    capture_output=True, text=True,\n"
        ")\n"
        "assert result.returncode == 0\n"
        'assert "0 skipped" in Path("report.txt").read_text(encoding="utf-8")\n'
        "```\n\n",
    )
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="declares Suite: scoped but asserts zero skipped tests",
    )


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


def test_required_sea_trial_requires_manifest_or_proof_traceability(tmp_path):
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

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="lack implementation/proof coverage",
    )


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


def test_missing_programmatic_acceptance_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    # A programmatic-surface spec (Provides: drydock status) shipped with bare `- None.`
    # acceptance is a hard emission gate — the plan must not write.
    bare = _SPEC_HEADER.replace(_SPEC_HEADER_PA_BODY, "- None.")
    arch = bare.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = bare.format(ftype="FEATURE", name="Status", ac="Status command exits successfully.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="Programmatic Acceptance assertion",
    )


def test_inline_justified_none_acceptance_does_not_warn(tmp_path):
    _make_target(tmp_path)
    justified = _SPEC_HEADER.replace(
        _SPEC_HEADER_PA_BODY,
        "- None. Visual-only surface; behavior covered by its backing feature.",
    )
    arch = justified.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    feature = justified.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    )
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== FEATURE-Status.md ===\n{feature}\n=== END FEATURE-Status.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest()}\n=== END MANIFEST.md ===\n"
    )

    result = create_plan("Example", "Example", tmp_path, runner=_fake(out))

    assert not any("Programmatic Acceptance assertion" in w for w in result.warnings)


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
    assert not any("Programmatic Acceptance assertion" in w for w in result.warnings)


def test_fenced_python_acceptance_counts_toward_surface_gate(tmp_path):
    # Regression: the plan gate must count canonical ``### check-id`` + fenced
    # ``python`` blocks — the format the build engine executes and the model
    # emits — not legacy ``- assert`` bullets. Two fenced checks clear the gate.
    target_dir = _make_target(tmp_path)
    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))
    assert not any("Programmatic Acceptance assertion" in w for w in result.warnings)
    arch_text = (target_dir / "blueprint" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "```python" in arch_text


def test_acceptance_status_counts_fenced_blocks_not_bullets():
    from drydock.planning_session import _acceptance_status

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


def test_leading_preamble_is_reported_without_diagnostic_recovery(tmp_path):
    target_dir = _make_target(tmp_path)
    out = "Blueprint already contains all required specs, so I'm emitting MANIFEST.md.\n\n"
    out += _llm_output()

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail='before ARCHITECTURE.md: "Blueprint already contains',
    )
    assert not (target_dir / "MANIFEST.md").exists()


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


def test_transition_text_between_blocks_is_reported_without_recovery(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace(
        "=== MANIFEST.md ===\n",
        "Continuing with the remaining files next.\n=== MANIFEST.md ===\n",
        1,
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(output))

    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail="Continuing with the remaining files next.",
    )
    assert not (target_dir / "MANIFEST.md").exists()


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
        "Now the Manifest.\n\n=== MANIFEST.md ===\n",
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
    assert any("diagnostic approval removed 17 outside character(s)" in w for w in result.warnings)
    assert any(
        'between FEATURE-Status.md and MANIFEST.md: "Now the Manifest."' in w
        for w in result.warnings
    )
    assert any("requesting diagnostic approval" in line for line in progress)
    assert len(runner.calls) == 2
    waiver_prompt, waiver_kwargs = runner.calls[1]
    assert 'TEXT_JSON: "Now the Manifest."' in waiver_prompt
    assert "STRUCTURE_VALID: true" in waiver_prompt
    assert "PLAN_VALID: true" in waiver_prompt
    assert waiver_kwargs["parameters"]["decision"] == "artifact-waiver"


def test_rejected_outside_text_writes_no_artifacts_and_spends_one_diagnostic(tmp_path):
    target_dir = _make_target(tmp_path)
    output = _llm_output().replace(
        "=== MANIFEST.md ===\n",
        "The Manifest omits two unresolved stories.\n=== MANIFEST.md ===\n",
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
        ("x" * 101) + "\n=== MANIFEST.md ===\n",
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


def test_legacy_corpus_marker_no_longer_exempts_a_full_suite_run(tmp_path):
    """``Corpus:`` is retired: only ``Suite: full`` declares a deliberate full run. A check
    marked with the legacy spelling that runs the suite unbounded is rejected like any other."""
    target_dir = _make_target(tmp_path)
    feature = _SPEC_HEADER.format(
        ftype="FEATURE", name="Status", ac="Status command exits successfully."
    ).replace(
        "## Programmatic Acceptance\n\n",
        "## Programmatic Acceptance\n\n"
        "### conformance-full\nCorpus: full\nThe full conformance test suite passes.\n\n"
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

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="runs the whole test suite",
    )


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


def test_plan_strips_an_unsatisfiable_criterion_before_writing_the_graph(tmp_path):
    from drydock.planning_session import ACCEPTANCE_REMOVED_MARKER, _validate_plan_output

    manifest = _manifest()
    spec = _spec_with(
        _pa("Status reports state.", "Status exits clean.") + "\n\n" + _MALFORMED_CRITERION
    )
    blocks = {"MANIFEST.md": manifest, "FEATURE-Status.md": spec}

    _plan, warnings = _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))

    # The emitted spec is sanitized in place, so what gets written is buildable.
    written = blocks["FEATURE-Status.md"]
    assert "scoped-number" not in written
    assert "PYTHONPATH=sources" not in written
    assert "### check-1" in written and "### check-2" in written
    # And the removal is surfaced, leading the warning list.
    assert ACCEPTANCE_REMOVED_MARKER in warnings[0]
    assert "FEATURE-Status.md [scoped-number]" in warnings[0]
    assert "the intended command never runs" in warnings[0]


def test_plan_leaves_a_satisfiable_spec_and_its_warnings_alone(tmp_path):
    from drydock.planning_session import ACCEPTANCE_REMOVED_MARKER, _validate_plan_output

    manifest = _manifest()
    spec = _spec_with(_pa("Status reports state.", "Status exits clean."))
    blocks = {"MANIFEST.md": manifest, "FEATURE-Status.md": spec}

    _plan, warnings = _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))

    assert blocks["FEATURE-Status.md"] == spec
    assert not any(ACCEPTANCE_REMOVED_MARKER in w for w in warnings)


def test_a_story_left_without_acceptance_fails_the_plan(tmp_path):
    """Removing every criterion leaves a story that verifies nothing. That is a planning
    defect, and it must surface here — cheaply — not as a failed build."""
    from drydock.planning_session import _validate_plan_output

    manifest = _manifest()
    blocks = {
        "MANIFEST.md": manifest,
        "FEATURE-Status.md": _spec_with(_MALFORMED_CRITERION),
    }

    with pytest.raises(SpecificationError, match="Programmatic Acceptance assertion"):
        _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))


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
        target_dir, [technology_stack.StackEntry("Ghost", "ghost.md", "Technologies")]
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
    repaired = uncovered.replace(
        "implements:   ARCHITECTURE.md", "implements:   ARCHITECTURE.md\ncovers:       ARCH-001"
    )
    runner = _sequence_runner(_topology_output(uncovered), _declaration_block(repaired))

    result = create_plan("Example", "Example", tmp_path, runner=runner)

    assert len(runner.calls) == 2
    assert "Plan Topology Repair" in runner.calls[1]
    assert "not delivered by any Manifest story: ARCH-001" in runner.calls[1]
    assert (target_dir / "MANIFEST.md").is_file()
    assert result.plan.by_id()["story-foundation"].fields["covers"] == ("ARCH-001",)


def test_stage_1_coverage_repair_is_skipped_when_the_declaration_covers_every_story(tmp_path):
    _make_target(tmp_path, analysis=_ANALYSIS_WITH_IDS)
    covered = _TOPOLOGY_DECLARATION.replace(
        "implements:   FEATURE-Status.md",
        "implements:   FEATURE-Status.md\ncovers:       STATUS-001",
    ).replace(
        "implements:   ARCHITECTURE.md", "implements:   ARCHITECTURE.md\ncovers:       ARCH-001"
    )
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
    assert "Original TOPOLOGY.md body" in runner.calls[1]
    assert sorted(result.plan.by_id()) == ["story-foundation", "story-status"]
    assert (target_dir / "blueprint" / "FEATURE-Status.md").is_file()


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


def test_the_continuation_prompt_reuses_the_original_prefix_and_carries_the_ledger(tmp_path):
    """Byte-identical prefix or the cached input is re-billed; the appended block is the gap."""
    _make_target(tmp_path)
    runner = _sequence_runner(_short_output(), _feature_block())

    create_plan("Example", "Example", tmp_path, runner=runner)

    first, second = runner.calls
    assert second.startswith(first)
    appended = second[len(first) :]
    assert "story-status -> FEATURE-Status.md" in appended
    assert "ARCHITECTURE.md" in appended
    assert "do not re-emit" in appended
    assert "# Frozen Stage 1 Output" in appended
    assert "## story story-status" in appended


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


def test_plan_strips_a_staged_call_missing_the_environment_the_asset_requires(tmp_path):
    from drydock.planning_session import ACCEPTANCE_REMOVED_MARKER, _validate_plan_output

    sources = tmp_path / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "run_conformance.sh").write_text(_STAGED_HARNESS_SCRIPT, encoding="utf-8")
    manifest = _manifest()
    spec = _spec_with(
        _pa("Status reports state.", "Status exits clean.") + "\n\n" + _STAGED_CRITERION
    )
    blocks = {"MANIFEST.md": manifest, "FEATURE-Status.md": spec}

    _plan, warnings = _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))

    assert "key-conformance" not in blocks["FEATURE-Status.md"]
    assert "### check-1" in blocks["FEATURE-Status.md"]
    removal = next(w for w in warnings if ACCEPTANCE_REMOVED_MARKER in w)
    assert "FEATURE-Status.md [key-conformance]" in removal
    assert "DECODER" in removal


def test_plan_keeps_the_same_call_when_it_extends_the_inherited_environment(tmp_path):
    from drydock.planning_session import ACCEPTANCE_REMOVED_MARKER, _validate_plan_output

    sources = tmp_path / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "run_conformance.sh").write_text(_STAGED_HARNESS_SCRIPT, encoding="utf-8")
    manifest = _manifest()
    correct = _STAGED_CRITERION.replace(
        "import subprocess", "import os\nimport subprocess"
    ).replace(
        "    capture_output=True,",
        '    env={**os.environ, "DECODER": "./toml-decoder"},\n    capture_output=True,',
    )
    spec = _spec_with(_pa("Status reports state.", "Status exits clean.") + "\n\n" + correct)
    blocks = {"MANIFEST.md": manifest, "FEATURE-Status.md": spec}

    _plan, warnings = _validate_plan_output(blocks, tmp_path, FakeRun(text=_llm_output(manifest)))

    assert "key-conformance" in blocks["FEATURE-Status.md"]
    assert not any(ACCEPTANCE_REMOVED_MARKER in w for w in warnings)
