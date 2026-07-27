"""Tests for the LLM-driven ``drydock plan create`` (planning_session.create_plan).

A fake runner supplies canned delimited-block output; no API credits are spent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.build_plan import AppliedSpecRecord, parse_build_plan
from drydock.errors import RecordedError, SpecificationError
from drydock.planning_session import (
    _answered_discovery,
    _assemble_prompt,
    _load_prior_plan_state,
    _normalize_existing_specs,
    _parse_blocks,
    _parse_strict_blocks,
    _repair_missing_leading_delimiter,
    _spec_is_conformant,
    _spec_is_dirty,
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
    so route paths appear inside the section for test-driven route coverage."""
    blocks = []
    for index, code in enumerate(snippets, start=1):
        blocks.append(f"### check-{index}\nRoute acceptance {index}.\n\n```python\n{code}\n```")
    return "\n\n".join(blocks)


def test_default_feedback_heading_is_plan_compass(tmp_path):
    assert ensure_feedback_file(tmp_path) == "# Plan Compass\n"


def test_plan_prompt_declares_strict_artifact_contract():
    prompt = (Path(__file__).parents[1] / "prompts" / "plan_create.md").read_text(encoding="utf-8")

    assert "Emit exactly one response mode" in prompt
    assert "### Success Mode" in prompt
    assert "=== PLAN_CREATE_ERROR.txt ===" in prompt
    assert "Never emit `MANIFEST.md` in Error Mode or Blocked Mode" in prompt
    assert "Every `implements:` filename in `MANIFEST.md` must exactly match" in prompt
    assert "Never emit `AGENTS.md`." in prompt
    assert "The response is processed by a deterministic parser." in prompt
    assert "Now the Manifest." in prompt
    assert "No non-whitespace text exists outside the blocks." in prompt


def test_plan_prompt_separates_final_sea_trial_traceability_from_story_execution():
    prompt = (Path(__file__).parents[1] / "prompts" / "plan_create.md").read_text(encoding="utf-8")

    assert "`accepts:` is traceability metadata, not a child acceptance command." in prompt
    assert "perform an exhaustive traceability audit" in prompt


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

## Open Questions

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
    + "\n\n## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n\n## Open Questions\n\n- None.\n"
)

_FEATURE_EMPTY_ACCEPTANCE = (
    "# FEATURE: Status\n\n"
    "| Field       | Value |\n|-------------|-------|\n"
    "| Version     | 20260528 V1 |\n| Description | Status feature. |\n"
    "| Depends On  | ARCHITECTURE.md |\n| Provides    | drydock status |\n| Phase       | 2 |\n\n"
    "## Trigger\n\n- User runs drydock status.\n\n"
    "## Test\n\n- Verify status prints the build state.\n\n"
    "## Programmatic Acceptance\n\n- None.\n\n"
    "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n\n## Open Questions\n\n- None.\n"
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
    + "\n\n## User Acceptance\n\n- None.\n\n## Guardrails\n\n- None.\n\n## Open Questions\n\n- None.\n"
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
    # Reuse requires built specs: a replan discards anything with no build record.
    _mark_built(target_dir, "ARCHITECTURE.md", "FEATURE-Status.md")
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
    """Record specs in MANIFEST.md ``applied_specs``, as ``drydock build`` does on success.

    A replan preserves built specs and discards the rest, so a test that exercises reuse
    must first establish that the specs it seeds were actually built against.
    """
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

    # Reuse requires built specs: a replan discards anything with no build record.
    _mark_built(target_dir, "ARCHITECTURE.md", "FEATURE-Status.md")
    architecture_before = architecture.read_text(encoding="utf-8")
    feature_before = feature.read_text(encoding="utf-8")

    def runner(prompt_text, *a, **k):
        prompt_texts.append(prompt_text)
        return FakeRun(text=f"=== MANIFEST.md ===\n{manifest}\n=== END MANIFEST.md ===\n")

    result = create_plan("Example", "Example", tmp_path, runner=runner, on_text=progress.append)

    assert result.plan.state == "draft"
    assert progress[0].startswith(
        "[plan] mode=reuse-manifest-first prompt=plan_reuse existing_specs=2 imported_sources=1"
    )
    assert "reuse-mode: preserving existing Blueprint specs" in "".join(progress)
    assert "# Request" not in prompt_texts[0]
    assert "Preserve this architecture body." in prompt_texts[0]
    assert "Preserve this feature body." in prompt_texts[0]
    assert "Do not emit any existing conformant Blueprint file again." in prompt_texts[0]
    assert "## Programmatic Acceptance" in architecture.read_text(encoding="utf-8")
    # Built specs are preserved verbatim — headers are not restamped and terminal
    # sections are not completed, so the story stays clean and does not rebuild.
    assert architecture.read_text(encoding="utf-8") == architecture_before
    assert feature.read_text(encoding="utf-8") == feature_before


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


def test_replan_preserves_closed_verified_block_with_clean_file(tmp_path):
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
    assert "state: closed/verified" in text


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


def test_replan_restores_applied_specs(tmp_path):
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
    assert "FEATURE-Status.md" in plan.applied_specs
    assert plan.applied_specs["FEATURE-Status.md"].applied_by == "story-status"


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


def test_missing_stack_questionnaire_blocks_planning(tmp_path):
    target_dir = _make_target(tmp_path)
    (target_dir / "QuarterDeck" / "questionnaires" / "discovery-stack.json").unlink()

    with pytest.raises(SpecificationError, match="Technology Stack questionnaire"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


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
    _make_target(tmp_path, analysis=None)
    with pytest.raises(SpecificationError, match="ANALYSIS.md"):
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))


def test_plan_create_blocked_block_refuses(tmp_path):
    target_dir = _make_target(tmp_path)
    out = "=== PLAN_CREATE_BLOCKED.txt ===\nBlocked.\n=== END PLAN_CREATE_BLOCKED.txt ===\n"
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="Planning cannot proceed",
    )


def test_plan_create_error_block_refuses_without_writes(tmp_path):
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

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="could not produce a complete plan",
    )

    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()
    assert not (target_dir / "QuarterDeck" / "tickets.json").exists()


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


def test_unbuilt_specs_are_discarded_and_regenerated(tmp_path):
    """Nothing built: every prior spec is prior plan output, so the replan rewrites it."""
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    (blueprint_dir / "ARCHITECTURE.md").write_text("STALE ARCHITECTURE\n", encoding="utf-8")
    (blueprint_dir / "FEATURE-Status.md").write_text("STALE FEATURE\n", encoding="utf-8")
    (blueprint_dir / "FEATURE-Ghost.md").write_text("ORPHAN SPEC\n", encoding="utf-8")
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


def test_built_spec_is_preserved_and_unbuilt_sibling_regenerated(tmp_path):
    """The guardrail: a spec delivered code was built against survives the replan."""
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    architecture.write_text(_ARCH_CONFORMANT, encoding="utf-8")
    (blueprint_dir / "FEATURE-Status.md").write_text("STALE FEATURE\n", encoding="utf-8")
    _mark_built(target_dir, "ARCHITECTURE.md")
    before = architecture.read_text(encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert architecture.read_text(encoding="utf-8") == before
    assert "STALE" not in (blueprint_dir / "FEATURE-Status.md").read_text(encoding="utf-8")


def test_author_edited_built_spec_is_not_overwritten(tmp_path):
    """A built spec the author edited keeps the author's content; the LLM's is discarded."""
    target_dir = _make_target(tmp_path)
    blueprint_dir = target_dir / "blueprint"
    architecture = blueprint_dir / "ARCHITECTURE.md"
    architecture.write_text(_ARCH_CONFORMANT, encoding="utf-8")
    _mark_built(target_dir, "ARCHITECTURE.md")
    # Author edits after the build: the applied_specs sha256 no longer matches.
    edited = _ARCH_CONFORMANT.replace("Architecture body.", "AUTHOR EDIT — keep this.")
    architecture.write_text(edited, encoding="utf-8")

    create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output()))

    assert architecture.read_text(encoding="utf-8") == edited


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
implements: FEATURE-Status.md
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


def test_story_without_acceptance_is_fatal(tmp_path):
    target_dir = _make_target(tmp_path)
    # Drop the ac block — a story with no acceptance gate must not be emitted.
    manifest = _manifest().split("## ac 1:")[0].rstrip() + "\n"
    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="plan output validation failed",
        detail="no acceptance check",
    )


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
        "import subprocess\n"
        "result = subprocess.run(\n"
        '    ["python3", "sources/spec_tests.py", "--number", "1"],\n'
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
        "## Open Questions\n\n- None.\n"
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


def test_empty_initial_frontier_warns(tmp_path):
    _make_target(tmp_path)
    # The only empty-depends block is the (non-executable) feature; the sole story
    # gates on it, so no story or spike can run first. Acyclic, but no frontier.
    manifest = _manifest().replace(
        "implements: FEATURE-Status.md\nscope: both\nstate: pending",
        "implements: FEATURE-Status.md\nscope: both\ndepends: feature-status\nstate: pending",
    )
    result = create_plan("Example", "Example", tmp_path, runner=_fake(_llm_output(manifest)))

    assert any("initial runnable frontier is empty" in w for w in result.warnings)


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
        "implements: FEATURE-Status.md\n"
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
        detail="missing === MANIFEST.md",
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


def test_duplicate_artifact_block_refuses_without_writes(tmp_path):
    target_dir = _make_target(tmp_path)
    arch = _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None.")
    out = (
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== ARCHITECTURE.md ===\n{arch}\n=== END ARCHITECTURE.md ===\n"
        f"=== MANIFEST.md ===\n{_manifest(implements='ARCHITECTURE.md')}\n=== END MANIFEST.md ===\n"
    )

    with pytest.raises(RecordedError) as excinfo:
        create_plan("Example", "Example", tmp_path, runner=_fake(out))
    _assert_recorded_error(
        excinfo,
        target_dir,
        classification="model artifact contract failed",
        detail="Duplicate artifact block: ARCHITECTURE.md",
    )

    assert not (target_dir / "MANIFEST.md").exists()
    assert not (target_dir / "blueprint" / "ARCHITECTURE.md").exists()


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
