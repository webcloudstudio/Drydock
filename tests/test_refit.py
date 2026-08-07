"""Tests for drydock refit — change ticket conformance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drydock.refit import (
    RefitResult,
    _assemble_refit_prompt,
    _find_block_boundaries,
    _parse_amends,
    _parse_parent_depends,
    _parse_refit_output,
    _patch_manifest,
    _resolve_ticket_deps,
    _split_manifest_blocks,
    refit_target,
)

# ---------------------------------------------------------------------------
# Fake runner helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "exec-fake"


def _fake_runner(response_text: str, *, ok: bool = True):
    """Return a runner that captures prompts and returns a canned response."""
    seen: list[str] = []

    def run(prompt, working_directory, **kwargs):
        seen.append(prompt)
        return FakeRun(ok=ok, text=response_text)

    run.seen = seen  # type: ignore[attr-defined]
    return run


def _make_response(ticket_filename: str, ticket_content: str, manifest_rows: str) -> str:
    return (
        f"=== changes/{ticket_filename} ===\n"
        f"{ticket_content}\n"
        f"=== END changes/{ticket_filename} ===\n\n"
        f"=== MANIFEST_ROWS ===\n"
        f"{manifest_rows}\n"
        f"=== END MANIFEST_ROWS ===\n"
    )


# ---------------------------------------------------------------------------
# _parse_amends
# ---------------------------------------------------------------------------


class TestParseAmends:
    def test_from_header_table(self):
        text = "# CHANGE: Test\n\n| Amends | FEATURE-Copy.md |\n"
        assert _parse_amends(text) == "FEATURE-Copy.md"

    def test_from_header_table_with_spaces(self):
        text = "| Field | Value |\n|---|---|\n| Amends      | FEATURE-Copy.md   |\n"
        assert _parse_amends(text) == "FEATURE-Copy.md"

    def test_from_bare_line(self):
        text = "Some content\nAmends: FEATURE-Copy.md\nMore content"
        assert _parse_amends(text) == "FEATURE-Copy.md"

    def test_missing_returns_none(self):
        text = "# CHANGE: Test\n\n| Version | 20260101 V1 |\n"
        assert _parse_amends(text) is None

    def test_empty_returns_none(self):
        assert _parse_amends("") is None


# ---------------------------------------------------------------------------
# _parse_parent_depends
# ---------------------------------------------------------------------------


class TestParseParentDepends:
    def test_extracts_comma_list(self):
        text = "| Depends On | DATABASE.md, ARCHITECTURE.md |\n"
        result = _parse_parent_depends(text)
        assert result == ["DATABASE.md", "ARCHITECTURE.md"]

    def test_single_dep(self):
        text = "| Depends On | DATABASE.md |\n"
        assert _parse_parent_depends(text) == ["DATABASE.md"]

    def test_no_field_returns_empty(self):
        assert _parse_parent_depends("| Version | 20260101 V1 |") == []

    def test_strips_whitespace(self):
        text = "| Depends On  |  DATABASE.md ,  ARCHITECTURE.md  |\n"
        result = _parse_parent_depends(text)
        assert result == ["DATABASE.md", "ARCHITECTURE.md"]


# ---------------------------------------------------------------------------
# _resolve_ticket_deps
# ---------------------------------------------------------------------------


class TestResolveTicketDeps:
    def test_prepends_parent_to_deps(self, tmp_path):
        blueprint = tmp_path / "blueprint"
        blueprint.mkdir()
        (blueprint / "FEATURE-Copy.md").write_text(
            "| Depends On | DATABASE.md, ARCHITECTURE.md |", encoding="utf-8"
        )
        result = _resolve_ticket_deps("FEATURE-Copy.md", blueprint)
        assert result == ["FEATURE-Copy.md", "DATABASE.md", "ARCHITECTURE.md"]

    def test_parent_not_in_deps_twice(self, tmp_path):
        blueprint = tmp_path / "blueprint"
        blueprint.mkdir()
        (blueprint / "FEATURE-Copy.md").write_text(
            "| Depends On | FEATURE-Copy.md, DATABASE.md |", encoding="utf-8"
        )
        result = _resolve_ticket_deps("FEATURE-Copy.md", blueprint)
        assert result.count("FEATURE-Copy.md") == 1

    def test_parent_absent_returns_amends_only(self, tmp_path):
        blueprint = tmp_path / "blueprint"
        blueprint.mkdir()
        result = _resolve_ticket_deps("FEATURE-Missing.md", blueprint)
        assert result == ["FEATURE-Missing.md"]

    def test_no_depends_on_in_parent(self, tmp_path):
        blueprint = tmp_path / "blueprint"
        blueprint.mkdir()
        (blueprint / "FEATURE-Copy.md").write_text("| Version | 20260101 V1 |", encoding="utf-8")
        result = _resolve_ticket_deps("FEATURE-Copy.md", blueprint)
        assert result == ["FEATURE-Copy.md"]


# ---------------------------------------------------------------------------
# _assemble_refit_prompt
# ---------------------------------------------------------------------------


class TestAssembleRefitPrompt:
    def test_contains_job_block_fields(self):
        assembly = _assemble_refit_prompt(
            "## Prompt body",
            ticket_filename="TICKET-001-Test.md",
            ticket_text="Amends: FEATURE-Copy.md\n\nDo the thing.",
            parent_filename="FEATURE-Copy.md",
            parent_text="# FEATURE: Copy\n\n| Version | 20260101 V1 |",
            resolved_deps=["FEATURE-Copy.md", "DATABASE.md"],
            today="2026-06-30",
        )
        rendered = assembly.rendered_text
        assert "TICKET_PATH: changes/TICKET-001-Test.md" in rendered
        assert "DATE: 2026-06-30" in rendered
        assert "AMENDS: FEATURE-Copy.md" in rendered
        assert "DEPENDS_ON: FEATURE-Copy.md, DATABASE.md" in rendered

    def test_declares_scope_and_omits_story_ids_when_absent(self):
        assembly = _assemble_refit_prompt(
            "## Prompt body",
            ticket_filename="TICKET-001-Test.md",
            ticket_text="Amends: FEATURE-Copy.md",
            parent_filename="FEATURE-Copy.md",
            parent_text="# FEATURE: Copy",
            resolved_deps=["FEATURE-Copy.md"],
            today="2026-06-30",
        )
        rendered = assembly.rendered_text
        assert "SCOPE: amending" in rendered
        assert "STORY_IDS" not in rendered

    def test_hands_back_declared_story_ids_so_reconforming_replaces_in_place(self):
        # refit_target reprocesses every ticket on every run. Without the declared ids the model
        # invents new ones and _patch_manifest appends duplicate stories instead of replacing.
        assembly = _assemble_refit_prompt(
            "## Prompt body",
            ticket_filename="TICKET-007-Mark-Read.md",
            ticket_text="Amends: DATABASE.md",
            parent_filename="DATABASE.md",
            parent_text="# DATABASE",
            resolved_deps=["DATABASE.md"],
            today="2026-08-06",
            scope="additive",
            declared_stories=("mark-read-schema", "mark-read-route"),
        )
        rendered = assembly.rendered_text
        assert "SCOPE: additive" in rendered
        assert "STORY_IDS: mark-read-schema, mark-read-route" in rendered

    def test_contains_ticket_content(self):
        assembly = _assemble_refit_prompt(
            "body",
            ticket_filename="TICKET-001-Test.md",
            ticket_text="Amends: FEATURE-Copy.md\nDo the thing.",
            parent_filename="FEATURE-Copy.md",
            parent_text="parent content here",
            resolved_deps=["FEATURE-Copy.md"],
            today="2026-06-30",
        )
        rendered = assembly.rendered_text
        assert "Do the thing." in rendered
        assert "parent content here" in rendered

    def test_empty_deps_shows_none(self):
        assembly = _assemble_refit_prompt(
            "body",
            ticket_filename="TICKET-001-Test.md",
            ticket_text="Amends: FEATURE-Copy.md",
            parent_filename="FEATURE-Copy.md",
            parent_text="",
            resolved_deps=[],
            today="2026-06-30",
        )
        assert "DEPENDS_ON: (none)" in assembly.rendered_text


# ---------------------------------------------------------------------------
# _parse_refit_output
# ---------------------------------------------------------------------------


class TestParseRefitOutput:
    def test_extracts_both_blocks(self):
        ticket_content = "# CHANGE: Test\n| Version | 20260630 V1 |"
        manifest_rows = "## story 1: Do thing\nid: ticket-001\nstate: pending"
        text = _make_response("TICKET-001-Test.md", ticket_content, manifest_rows)
        t, m, err = _parse_refit_output(text, "TICKET-001-Test.md")
        assert t == ticket_content
        assert "story 1" in m
        assert err is None

    def test_error_block_sets_error(self):
        text = (
            "=== REFIT_ERROR.txt ===\n"
            "Error type: missing-information\n"
            "Reason:\n- No parent spec found\n"
            "=== END REFIT_ERROR.txt ===\n"
        )
        t, m, err = _parse_refit_output(text, "TICKET-001-Test.md")
        assert t is None
        assert m is None
        assert "missing-information" in err

    def test_empty_output_sets_error(self):
        t, m, err = _parse_refit_output("", "TICKET-001-Test.md")
        assert t is None
        assert m is None
        assert err is not None


# ---------------------------------------------------------------------------
# _split_manifest_blocks / _find_block_boundaries / _patch_manifest
# ---------------------------------------------------------------------------


class TestSplitManifestBlocks:
    def test_splits_multiple_blocks(self):
        rows = (
            "## story 1: First\nid: first\nstate: pending\n\n"
            "## story 2: Second\nid: second\nstate: pending\n"
        )
        blocks = _split_manifest_blocks(rows)
        assert len(blocks) == 2
        assert any("first" in b for b in blocks)
        assert any("second" in b for b in blocks)

    def test_empty_returns_empty(self):
        assert _split_manifest_blocks("") == []


class TestFindBlockBoundaries:
    def test_finds_existing_block(self):
        text = "# MANIFEST: P\nstate: draft\n\n## story 1: Do thing\nid: do-thing\nstate: pending\n"
        bounds = _find_block_boundaries(text, "do-thing")
        assert bounds is not None
        start, end = bounds
        assert "do-thing" in text[start:end]

    def test_returns_none_for_missing_id(self):
        text = "## story 1: Do thing\nid: do-thing\nstate: pending\n"
        assert _find_block_boundaries(text, "nonexistent") is None


_MANIFEST_HEADER = (
    "# MANIFEST: TestProject\nupdated: 2026-06-30T00:00:00\nplan_hash: abc123\nstate: approved\n\n"
)


class TestPatchManifest:
    def test_appends_new_block(self, tmp_path):
        manifest = tmp_path / "MANIFEST.md"
        manifest.write_text(
            _MANIFEST_HEADER + "## story 1: Foundation\nid: foundation\nstate: closed/verified\n",
            encoding="utf-8",
        )
        new_rows = "## story 2: New thing\nid: new-thing\nstate: pending\n"
        _patch_manifest(manifest, new_rows)
        result = manifest.read_text(encoding="utf-8")
        assert "new-thing" in result
        assert "foundation" in result

    def test_replaces_pending_block(self, tmp_path):
        manifest = tmp_path / "MANIFEST.md"
        manifest.write_text(
            _MANIFEST_HEADER
            + "## story 1: Old summary\nid: ticket-001\nstate: pending\ninstructions: old\n",
            encoding="utf-8",
        )
        new_rows = "## story 1: New summary\nid: ticket-001\nstate: pending\ninstructions: new\n"
        _patch_manifest(manifest, new_rows)
        result = manifest.read_text(encoding="utf-8")
        assert "New summary" in result
        assert "Old summary" not in result

    def test_preserves_verified_block(self, tmp_path):
        manifest = tmp_path / "MANIFEST.md"
        manifest.write_text(
            _MANIFEST_HEADER + "## story 1: Done thing\nid: done-thing\nstate: closed/verified\n",
            encoding="utf-8",
        )
        new_rows = "## story 1: Done thing\nid: done-thing\nstate: pending\n"
        _patch_manifest(manifest, new_rows)
        result = manifest.read_text(encoding="utf-8")
        assert "closed/verified" in result

    def test_noop_when_manifest_absent(self, tmp_path):
        manifest = tmp_path / "MANIFEST.md"
        _patch_manifest(manifest, "## story 1: Thing\nid: thing\nstate: pending\n")
        assert not manifest.exists()

    def test_noop_when_rows_empty(self, tmp_path):
        manifest = tmp_path / "MANIFEST.md"
        original = _MANIFEST_HEADER + "## story 1: X\nid: x\nstate: pending\n"
        manifest.write_text(original, encoding="utf-8")
        _patch_manifest(manifest, "")
        assert manifest.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# refit_target integration
# ---------------------------------------------------------------------------


def _make_target(tmp_path: Path, tickets: dict[str, str], parent_specs: dict[str, str]) -> Path:
    """Create a minimal target directory structure."""
    target = tmp_path / "targets" / "MyProject"
    target.mkdir(parents=True)
    blueprint = target / "blueprint"
    blueprint.mkdir()
    changes = blueprint / "changes"
    changes.mkdir()

    for name, content in tickets.items():
        (changes / name).write_text(content, encoding="utf-8")

    for name, content in parent_specs.items():
        (blueprint / name).write_text(content, encoding="utf-8")

    return target


class TestRefitTarget:
    def test_no_changes_dir_returns_empty_result(self, tmp_path, monkeypatch):
        target = tmp_path / "targets" / "MyProject"
        target.mkdir(parents=True)
        (target / "blueprint").mkdir()
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))

        result = refit_target(target, runner=_fake_runner(""))
        assert isinstance(result, RefitResult)
        assert result.items == []
        assert result.exit_code() == 0

    def test_ticket_without_amends_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = _make_target(
            tmp_path,
            tickets={"TICKET-001-Test.md": "# CHANGE: Test\n\nNo amends field here."},
            parent_specs={},
        )
        result = refit_target(target, runner=_fake_runner(""))
        assert len(result.items) == 1
        assert result.items[0].status == "skipped-no-amends"
        assert result.exit_code() == 0

    def test_conforms_ticket_and_patches_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = _make_target(
            tmp_path,
            tickets={
                "TICKET-001-AddCopy.md": (
                    "Amends: FEATURE-Copy.md\n\nAdd a copy button to the status screen."
                )
            },
            parent_specs={
                "FEATURE-Copy.md": (
                    "# FEATURE: Copy\n\n| Depends On | DATABASE.md |\n\n## Summary\n\nCopy feature."
                )
            },
        )
        manifest = target / "MANIFEST.md"
        manifest.write_text(
            _MANIFEST_HEADER + "## story 1: Foundation\nid: foundation\nstate: closed/verified\n",
            encoding="utf-8",
        )

        ticket_content = (
            "# CHANGE: AddCopy\n\n"
            "| Field | Value |\n"
            "|-------|-------|\n"
            "| Version | 20260630 V1 |\n"
            "| Amends | FEATURE-Copy.md |\n"
            "| Depends On | FEATURE-Copy.md, DATABASE.md |\n\n"
            "## Summary\n\nAdd a copy button.\n\n"
            "## Acceptance Criteria\n\n- Button is present.\n\n"
            "## Guardrails\n\n- None.\n\n"
            "## Questions\n\n- None.\n"
        )
        manifest_rows = (
            "## story 2: Add copy button\n"
            "id: ticket-001-add-copy\n"
            "summary: Add copy button to status screen.\n"
            "implements: changes/TICKET-001-AddCopy.md\n"
            "context: FEATURE-Copy.md, ARCHITECTURE.md\n"
            "depends: foundation\n"
            "instructions: |\n  Add the copy button per the change ticket.\n"
            "state: pending\n"
        )
        runner = _fake_runner(
            _make_response("TICKET-001-AddCopy.md", ticket_content, manifest_rows)
        )

        result = refit_target(target, runner=runner)

        assert result.exit_code() == 0
        assert len(result.items) == 1
        assert result.items[0].status == "conformed"

        # Ticket header should be normalized
        updated_ticket = (target / "blueprint" / "changes" / "TICKET-001-AddCopy.md").read_text(
            encoding="utf-8"
        )
        assert "20260630 V1" in updated_ticket
        assert "FEATURE-Copy.md" in updated_ticket

        # Manifest should have the new story row
        updated_manifest = manifest.read_text(encoding="utf-8")
        assert "ticket-001-add-copy" in updated_manifest
        # Existing verified row preserved
        assert "foundation" in updated_manifest

    def test_llm_failure_sets_failed_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = _make_target(
            tmp_path,
            tickets={"TICKET-001-Test.md": "Amends: FEATURE-Copy.md\n\nSomething."},
            parent_specs={"FEATURE-Copy.md": "| Version | 20260101 V1 |"},
        )
        result = refit_target(target, runner=_fake_runner("", ok=False))
        assert result.exit_code() == 1
        assert result.items[0].status == "failed"

    def test_llm_error_block_sets_failed_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = _make_target(
            tmp_path,
            tickets={"TICKET-001-Test.md": "Amends: FEATURE-Copy.md\n\nSomething."},
            parent_specs={"FEATURE-Copy.md": "| Version | 20260101 V1 |"},
        )
        error_response = (
            "=== REFIT_ERROR.txt ===\n"
            "Error type: missing-information\n"
            "Reason:\n- Cannot process\n"
            "=== END REFIT_ERROR.txt ===\n"
        )
        result = refit_target(target, runner=_fake_runner(error_response))
        assert result.exit_code() == 1
        assert result.items[0].status == "failed"


# ---------------------------------------------------------------------------
# drift reconciliation
# ---------------------------------------------------------------------------


def _drift_manifest(db_hash: str, screen_hash: str) -> str:
    return f"""# MANIFEST: TestProject
state: approved
applied_specs: |
  DATABASE.md sha256={db_hash} commit=- applied_by=foundation applied_at=2026-07-01
  SCREEN-A.md sha256={screen_hash} commit=- applied_by=screen-a applied_at=2026-07-01

## story 1: Foundation
id: foundation
implements: DATABASE.md
state: closed/verified

## story 2: Screen A
id: screen-a
implements: SCREEN-A.md
context: DATABASE_compact.md
depends: foundation
state: closed/verified

## story 3: Unrelated
id: unrelated
implements: OTHER.md
state: closed/verified
"""


def _make_drift_target(
    tmp_path: Path,
    *,
    db_content: str = "db\n",
    screen_content: str = "screen\n",
    tickets: dict[str, str] | None = None,
) -> Path:
    import hashlib

    target = _make_target(
        tmp_path,
        tickets=tickets or {},
        parent_specs={"DATABASE.md": db_content, "SCREEN-A.md": screen_content},
    )
    db_hash = hashlib.sha256(b"db\n").hexdigest()
    screen_hash = hashlib.sha256(b"screen\n").hexdigest()
    (target / "MANIFEST.md").write_text(_drift_manifest(db_hash, screen_hash), encoding="utf-8")
    return target


class TestDriftReconciliation:
    def test_no_drift_leaves_manifest_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = _make_drift_target(tmp_path)
        original = (target / "MANIFEST.md").read_text(encoding="utf-8")

        result = refit_target(target, runner=_fake_runner(""))
        assert result.resets == []
        assert result.drift_errors == []
        assert result.exit_code() == 0
        assert (target / "MANIFEST.md").read_text(encoding="utf-8") == original

    def test_ordinary_drift_resets_cascade_without_ticket(self, tmp_path, monkeypatch):
        from drydock.build_plan import parse_build_plan

        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = _make_drift_target(tmp_path, screen_content="screen changed\n")

        result = refit_target(target, runner=_fake_runner(""))
        assert result.exit_code() == 0
        assert result.drift_errors == []
        assert len(result.resets) == 1
        reset = result.resets[0]
        assert reset.path == "SCREEN-A.md"
        assert not reset.foundational
        assert set(reset.reset_ids) == {"screen-a"}

        plan = parse_build_plan(target / "MANIFEST.md")
        states = {b.block_id: b.state for b in plan.blocks}
        assert states["screen-a"] == "pending"
        assert states["foundation"] == "closed/verified"
        assert states["unrelated"] == "closed/verified"
        assert "SCREEN-A.md" not in plan.applied_specs
        assert "DATABASE.md" in plan.applied_specs

    def test_foundational_drift_without_ticket_is_blocked(self, tmp_path, monkeypatch):
        from drydock.build_plan import parse_build_plan

        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = _make_drift_target(tmp_path, db_content="db changed\n")

        result = refit_target(target, runner=_fake_runner(""))
        assert result.exit_code() == 1
        assert result.resets == []
        assert len(result.drift_errors) == 1
        assert "Amends: DATABASE.md" in result.drift_errors[0]
        assert "change ticket" in result.drift_errors[0]

        plan = parse_build_plan(target / "MANIFEST.md")
        assert all(b.state == "closed/verified" for b in plan.blocks)
        assert "DATABASE.md" in plan.applied_specs

    def test_foundational_drift_with_ticket_cascades_reset(self, tmp_path, monkeypatch):
        from drydock.build_plan import parse_build_plan

        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        ticket_content = "Amends: DATABASE.md\n\nAllow null in a column."
        target = _make_drift_target(
            tmp_path,
            db_content="db changed\n",
            tickets={"TICKET-001-NullColumn.md": ticket_content},
        )
        manifest_rows = (
            "## story 4: Null column change\n"
            "id: ticket-001-null-column\n"
            "implements: changes/TICKET-001-NullColumn.md\n"
            "state: pending\n"
        )
        runner = _fake_runner(
            _make_response("TICKET-001-NullColumn.md", ticket_content, manifest_rows)
        )

        result = refit_target(target, runner=runner)
        assert result.exit_code() == 0
        assert result.drift_errors == []
        assert result.items[0].status == "conformed"
        assert len(result.resets) == 1
        reset = result.resets[0]
        assert reset.path == "DATABASE.md"
        assert reset.foundational
        assert set(reset.reset_ids) == {"foundation", "screen-a"}

        plan = parse_build_plan(target / "MANIFEST.md")
        states = {b.block_id: b.state for b in plan.blocks}
        assert states["foundation"] == "pending"
        assert states["screen-a"] == "pending"
        assert states["unrelated"] == "closed/verified"
        assert "ticket-001-null-column" in states
        assert "DATABASE.md" not in plan.applied_specs
        # SCREEN-A.md was stamped by the reset screen-a block, so it is dropped too.
        assert "SCREEN-A.md" not in plan.applied_specs
