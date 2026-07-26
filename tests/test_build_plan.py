"""Tests for canonical MANIFEST.md parsing and frontier calculation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from drydock.build_plan import (
    AppliedSpecRecord,
    CompactRecommendation,
    _format_applied_registry,
    _parse_applied_registry,
    cascade_reset_ids,
    compact_recommendations,
    compact_source,
    disambiguate_manifest_ids,
    foundational_source,
    parse_build_plan,
    set_applied_registry,
    set_applied_specs,
    set_plan_state,
    spec_name_variants,
    stale_applied_specs,
)
from drydock.errors import SpecificationError


def write_plan(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def plan_path(tmp_path: Path) -> Path:
    return write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
updated:     2026-06-11T12:00:00
plan_hash:   abc123

## story 1: Foundation
id:           foundation
summary:      Build the foundation.
state:        closed/verified

## story 2: Import documents
id:           import-documents
depends:      foundation
state:        pending

## story 3: Unknown dependency
id:           blocked-story
depends:      missing-block
state:        pending

## story 4: Awaiting checks
id:           awaiting-checks
state:        implemented

## ac 1: System starts
id:           system-starts
parent:       awaiting-checks
state:        pending

## ac 2: Foundation check
id:           foundation-check
parent:       foundation
state:        pending
""",
    )


def test_parse_build_plan(plan_path: Path):
    plan = parse_build_plan(plan_path)

    assert plan.project == "Example"
    assert plan.updated == "2026-06-11T12:00:00"
    assert plan.plan_hash == "abc123"
    assert len(plan.blocks) == 6
    assert plan.blocks[1].depends == ("foundation",)


def test_parse_build_plan_accepts_whitespace_separated_depends(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## story 1: First
id: first
state: closed/verified

## story 2: Second
id: second
depends: first third
state: pending

## story 3: Third
id: third
state: closed/verified

## ac 1: Second accepted
id: second-accepted
parent: second
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert plan.by_id()["second"].depends == ("first", "third")


def test_parse_build_plan_reads_covers_as_a_list(tmp_path: Path):
    # `covers:` traces a story back to the ANALYSIS.md Story IDs it delivers; the
    # planning coverage gate reads it as a list, alongside parent/depends.
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## feature 1: Parser
id: feat-parser
state: pending

## story 1: Blocks
id: blocks
parent: feat-parser
covers: PARSER-001, PARSER-002
state: pending

## ac 1: Blocks parse
id: blocks-parse
parent: blocks
state: pending
""",
    )

    plan = parse_build_plan(path)
    story = plan.by_id()["blocks"]

    assert story.fields["covers"] == ("PARSER-001", "PARSER-002")
    assert story.parent == "feat-parser"
    assert story.depends == ()


def test_ac_cross_story_depends_are_dropped(tmp_path: Path):
    # Self-only-depends hard guard: an ac may depend on its own parent story only;
    # a cross-story edge is dropped on read so it never drags forward dependencies.
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: approved

## story 1: Library
id: marlib
state: pending

## story 2: Infra
id: infra
state: pending

## ac 1: Marlib works
id: ac-marlib-1
parent: marlib
depends: infra
kind: smoke
check: test -f lib
state: pending
""",
    )

    plan = parse_build_plan(path)

    # The cross-story edge to infra is dropped; parent gating alone remains.
    assert plan.by_id()["ac-marlib-1"].depends == ()


def test_ac_depends_on_own_parent_is_kept(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: approved

## story 1: Library
id: marlib
state: pending

## ac 1: Marlib works
id: ac-marlib-1
parent: marlib
depends: marlib
kind: smoke
check: test -f lib
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert plan.by_id()["ac-marlib-1"].depends == ("marlib",)


def test_story_depends_on_ac_id_rewritten_to_ac_parent(tmp_path: Path):
    # Stories block on stories: a story depends: entry naming an ac id is
    # rewritten on read to the ac's parent story, with duplicates collapsed.
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: approved

## story 1: Library
id: marlib
state: pending

## ac 1: Marlib works
id: marlib-passes
parent: marlib
kind: smoke
check: test -f lib
state: pending

## story 2: Infra
id: infra
depends: marlib-passes marlib
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert plan.by_id()["infra"].depends == ("marlib",)


def test_parse_build_plan_captures_block_scalar_instructions(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## story 1: First
id: first
implements: A.md
instructions: |
  Build the first thing.
  Keep it small.
depends:
state: pending
""",
    )

    plan = parse_build_plan(path)

    block = plan.by_id()["first"]
    assert block.fields["instructions"] == "Build the first thing.\nKeep it small."
    # Fields after a block scalar are still parsed.
    assert block.depends == ()
    assert block.state == "pending"
    assert block.fields["implements"] == ("A.md",)


def test_runnable_frontier_applies_dependency_and_ac_parent_rules(plan_path: Path):
    plan = parse_build_plan(plan_path)

    assert [block.block_id for block in plan.runnable_frontier()] == [
        "import-documents",
        "system-starts",
    ]


def test_state_counts(plan_path: Path):
    counts = parse_build_plan(plan_path).state_counts()

    assert counts["pending"] == 4
    assert counts["implemented"] == 1
    assert counts["closed/verified"] == 1
    assert counts["closed/failed"] == 0


def test_missing_plan_raises(tmp_path: Path):
    with pytest.raises(SpecificationError, match="MANIFEST.md not found"):
        parse_build_plan(tmp_path / "MANIFEST.md")


def test_missing_id_raises(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        "# MANIFEST: Example\n\n## story 1: No id\nstate: pending\n",
    )

    with pytest.raises(SpecificationError, match="Missing id"):
        parse_build_plan(path)


def test_duplicate_id_raises(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example

## story 1: First
id: duplicate
state: pending

## spike 1: Second
id: duplicate
state: pending
""",
    )

    with pytest.raises(SpecificationError, match="Duplicate block id"):
        parse_build_plan(path)


def test_ac_requires_parent(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        "# MANIFEST: Example\n\n## ac 1: Check\nid: check\nstate: pending\n",
    )

    with pytest.raises(SpecificationError, match="Missing parent"):
        parse_build_plan(path)


def test_compact_ac_expands_to_canonical_block(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example

## story 1: Foundation
id:      foundation
summary: Build it.
state:   pending

## ac 1: Health endpoint returns status=ok (smoke: curl -sf http://h/health | python3 -c "json.load(sys.stdin)")
## ac 2: Startup aborts outside git (assertion: run in /tmp, confirm exit 1)
""",
    )

    plan = parse_build_plan(path)
    acs = [b for b in plan.blocks if b.block_type == "ac"]

    assert [b.block_id for b in acs] == [
        "health-endpoint-returns-status-ok",
        "startup-aborts-outside-git",
    ]
    assert all(b.parent == "foundation" for b in acs)
    assert acs[0].fields["kind"] == "smoke"
    # Greedy match keeps embedded parens from json.load(sys.stdin) inside check.
    assert acs[0].fields["check"] == 'curl -sf http://h/health | python3 -c "json.load(sys.stdin)"'
    assert acs[1].fields["kind"] == "assertion"
    assert acs[1].fields["check"] == "run in /tmp, confirm exit 1"
    assert acs[0].name == "Health endpoint returns status=ok"


def test_compact_ac_slugs_deduplicate(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example

## story 1: Foundation
id:      foundation
summary: Build it.
state:   pending

## ac 1: Check passes (smoke: a)
## ac 2: Check passes (smoke: b)
""",
    )

    plan = parse_build_plan(path)
    acs = [b for b in plan.blocks if b.block_type == "ac"]
    assert [b.block_id for b in acs] == ["check-passes", "check-passes-2"]


def test_compact_ac_without_parent_still_raises(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        "# MANIFEST: Example\n\n## ac 1: Orphan check (smoke: true)\n",
    )

    with pytest.raises(SpecificationError, match="Missing parent"):
        parse_build_plan(path)


def test_invalid_state_raises(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        "# MANIFEST: Example\n\n## story 1: Bad\nid: bad\nstate: running\n",
    )

    with pytest.raises(SpecificationError, match="Invalid state"):
        parse_build_plan(path)


def test_runnable_frontier_ignores_legacy_plan_state(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## story 1: Work
id: work
scope: target
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert plan.blocks[0].scope == "target"
    assert [block.block_id for block in plan.runnable_frontier()] == ["work"]


def test_set_plan_state_preserves_legacy_compatibility(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: draft

## feature 1: Workflow
id: workflow
state: pending

## story 1: Work
id: work
parent: workflow
state: pending
""",
    )

    plan = set_plan_state(path, "approved")

    assert plan.state == "approved"
    assert plan.by_id()["work"].state == "pending"


def test_non_executable_feature_closes_after_all_children(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: approved

## feature 1: Workflow
id: workflow
state: pending

## story 1: Work
id: work
parent: workflow
state: closed/verified

## ac 1: Workflow accepted
id: workflow-accepted
parent: workflow
state: closed/verified
""",
    )

    plan = parse_build_plan(path)

    assert [block.block_id for block in plan.closable_features()] == ["workflow"]


def test_feature_acceptance_runs_after_feature_work_closes(tmp_path: Path):
    path = write_plan(
        tmp_path / "MANIFEST.md",
        """# MANIFEST: Example
state: approved

## feature 1: Workflow
id: workflow
state: pending

## story 1: Work
id: work
parent: workflow
state: closed/verified

## ac 1: Workflow accepted
id: workflow-accepted
parent: workflow
state: pending
""",
    )

    plan = parse_build_plan(path)

    assert [block.block_id for block in plan.runnable_frontier()] == ["workflow-accepted"]


class TestAppliedRegistry:
    _MANIFEST = "# MANIFEST: Test\nstate: approved\n\n## story 1: S\nid: s\nstate: pending\n"

    def test_empty_registry_by_default(self, tmp_path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(self._MANIFEST, encoding="utf-8")
        plan = parse_build_plan(path)
        assert plan.applied_registry == {}

    def test_parse_applied_from_preamble(self, tmp_path):
        manifest = "# MANIFEST: Test\nstate: approved\napplied: common.md=abc123,python.md=def456\n\n## story 1: S\nid: s\nstate: pending\n"
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        plan = parse_build_plan(path)
        assert plan.applied_registry == {"common.md": "abc123", "python.md": "def456"}

    def test_set_applied_registry_writes_field(self, tmp_path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(self._MANIFEST, encoding="utf-8")
        set_applied_registry(path, {"common.md": "abc123"})
        plan = parse_build_plan(path)
        assert plan.applied_registry == {"common.md": "abc123"}

    def test_set_applied_registry_updates_existing(self, tmp_path):
        manifest = "# MANIFEST: Test\nstate: approved\napplied: common.md=old123\n\n## story 1: S\nid: s\nstate: pending\n"
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        set_applied_registry(path, {"common.md": "new456", "python.md": "xyz789"})
        plan = parse_build_plan(path)
        assert plan.applied_registry == {"common.md": "new456", "python.md": "xyz789"}

    def test_parse_applied_registry_helper(self):
        assert _parse_applied_registry("a.md=abc,b.md=def") == {"a.md": "abc", "b.md": "def"}
        assert _parse_applied_registry("") == {}
        assert _parse_applied_registry("bad-entry") == {}

    def test_format_applied_registry_helper(self):
        result = _format_applied_registry({"b.md": "222", "a.md": "111"})
        assert result == "a.md=111,b.md=222"  # sorted


class TestAppliedSpecs:
    _MANIFEST = "# MANIFEST: Test\nstate: approved\n\n## story 1: S\nid: s\nstate: pending\n"

    def test_empty_applied_specs_by_default(self, tmp_path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(self._MANIFEST, encoding="utf-8")
        plan = parse_build_plan(path)
        assert plan.applied_specs == {}

    def test_parse_applied_specs_from_preamble(self, tmp_path):
        manifest = """# MANIFEST: Test
state: approved
applied_specs: |
  DATABASE.md sha256=abc123 commit=commit1 applied_by=foundation applied_at=2026-06-26T12:00:00+00:00
  features/FEATURE-A.md sha256=def456 commit=- applied_by=feature-a applied_at=2026-06-26T12:01:00+00:00

## story 1: S
id: s
state: pending
"""
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        plan = parse_build_plan(path)

        assert plan.applied_specs["DATABASE.md"].sha256 == "abc123"
        assert plan.applied_specs["DATABASE.md"].commit == "commit1"
        assert plan.applied_specs["features/FEATURE-A.md"].commit == "-"

    def test_set_applied_specs_writes_block_scalar(self, tmp_path):
        path = tmp_path / "MANIFEST.md"
        path.write_text(self._MANIFEST, encoding="utf-8")
        set_applied_specs(
            path,
            {
                "DATABASE.md": AppliedSpecRecord(
                    path="DATABASE.md",
                    sha256="abc123",
                    commit="commit1",
                    applied_by="foundation",
                    applied_at="2026-06-26T12:00:00+00:00",
                )
            },
        )

        text = path.read_text(encoding="utf-8")
        plan = parse_build_plan(path)
        assert "applied_specs: |" in text
        assert "  DATABASE.md sha256=abc123 commit=commit1" in text
        assert plan.applied_specs["DATABASE.md"].applied_by == "foundation"

    def test_set_applied_specs_preserves_applied_registry(self, tmp_path):
        manifest = (
            "# MANIFEST: Test\n"
            "state: approved\n"
            "applied: common.md=stackcommit\n\n"
            "## story 1: S\n"
            "id: s\n"
            "state: pending\n"
        )
        path = tmp_path / "MANIFEST.md"
        path.write_text(manifest, encoding="utf-8")
        set_applied_specs(
            path,
            {
                "DATABASE.md": AppliedSpecRecord(
                    path="DATABASE.md",
                    sha256="abc123",
                    commit="-",
                    applied_by="foundation",
                    applied_at="2026-06-26T12:00:00+00:00",
                )
            },
        )

        plan = parse_build_plan(path)
        assert plan.applied_registry == {"common.md": "stackcommit"}
        assert plan.applied_specs["DATABASE.md"].sha256 == "abc123"


class TestCompactRecommendations:
    _PLAN_TEMPLATE = """\
# MANIFEST: Proj
state: approved

## story 1: Alpha
id: alpha
state: pending
implements: ARCH.md
context: RULES.md, COMMON.md

## story 2: Beta
id: beta
state: pending
context: RULES.md, COMMON.md

## story 3: Gamma
id: gamma
state: pending
context: RULES.md

## story 4: Delta
id: delta
state: pending
context: RARE.md
"""

    def _plan(self, tmp_path):
        p = tmp_path / "MANIFEST.md"
        p.write_text(self._PLAN_TEMPLATE, encoding="utf-8")
        return parse_build_plan(p)

    def test_returns_files_meeting_threshold(self, tmp_path):
        plan = self._plan(tmp_path)
        recs = compact_recommendations(plan)
        files = [r.file for r in recs]
        assert "RULES.md" in files  # 3 context refs
        assert "COMMON.md" in files  # 2 context refs
        assert "RARE.md" not in files  # 1 context ref — below threshold

    def test_sorted_by_context_count_descending(self, tmp_path):
        plan = self._plan(tmp_path)
        recs = compact_recommendations(plan)
        counts = [r.context_count for r in recs]
        assert counts == sorted(counts, reverse=True)

    def test_implements_count_tracked(self, tmp_path):
        plan = self._plan(tmp_path)
        recs = compact_recommendations(plan)
        arch_rec = next((r for r in recs if r.file == "ARCH.md"), None)
        # ARCH.md only has 1 context ref (below threshold=2) but 1 implements
        assert arch_rec is None
        rules_rec = next(r for r in recs if r.file == "RULES.md")
        assert rules_rec.context_count == 3
        assert rules_rec.implements_count == 0

    def test_custom_threshold(self, tmp_path):
        plan = self._plan(tmp_path)
        recs = compact_recommendations(plan, threshold=3)
        files = [r.file for r in recs]
        assert "RULES.md" in files
        assert "COMMON.md" not in files  # only 2 context refs

    def test_empty_plan_returns_empty(self, tmp_path):
        p = tmp_path / "MANIFEST.md"
        p.write_text(
            "# MANIFEST: Empty\nstate: approved\n\n## story 1: S\nid: s\nstate: pending\n",
            encoding="utf-8",
        )
        plan = parse_build_plan(p)
        assert compact_recommendations(plan) == []

    def test_returns_compact_recommendation_instances(self, tmp_path):
        plan = self._plan(tmp_path)
        recs = compact_recommendations(plan)
        assert all(isinstance(r, CompactRecommendation) for r in recs)


class TestSpecNameHelpers:
    def test_compact_source_maps_derivatives(self):
        assert compact_source("DATABASE_compact.md") == "DATABASE.md"
        assert compact_source("DATABASE_compact.skip.md") == "DATABASE.md"
        assert compact_source("DATABASE.md") == "DATABASE.md"
        assert compact_source("sub/UI-GENERAL_compact.md") == "sub/UI-GENERAL.md"

    def test_spec_name_variants_covers_all_siblings(self):
        variants = spec_name_variants("ARCHITECTURE_compact.md")
        assert variants == frozenset({
            "ARCHITECTURE.md",
            "ARCHITECTURE_compact.md",
            "ARCHITECTURE_compact.skip.md",
        })

    def test_foundational_source_recognizes_sealed_files_and_derivatives(self):
        assert foundational_source("DATABASE.md") == "DATABASE.md"
        assert foundational_source("UI-GENERAL_compact.md") == "UI-GENERAL.md"
        assert foundational_source("ARCHITECTURE_compact.skip.md") == "ARCHITECTURE.md"
        assert foundational_source("SCREEN-SETUP.md") is None
        assert foundational_source("FEATURE-X_compact.md") is None


_CASCADE_PLAN = """# MANIFEST: Cascade
state: approved
applied_specs: |
  DATABASE.md sha256={db_hash} commit=- applied_by=foundation applied_at=2026-07-01
  SCREEN-A.md sha256={screen_hash} commit=- applied_by=screen-a applied_at=2026-07-01

## feature 1: Core
id: feat-core
state: closed/verified

## story 1: Foundation
id: foundation
parent: feat-core
implements: DATABASE.md
state: closed/verified

## ac 1: DB smoke
id: ac-db
parent: foundation
state: closed/verified

## story 2: Screen A
id: screen-a
parent: feat-core
implements: SCREEN-A.md
context: DATABASE_compact.md
depends: foundation
state: closed/verified

## story 3: Screen B
id: screen-b
depends: screen-a
state: closed/verified

## story 4: Unrelated
id: unrelated
implements: OTHER.md
state: closed/verified
"""


class TestStaleAndCascade:
    def _plan(self, tmp_path, db_content: str = "db\n", screen_content: str = "screen\n"):
        import hashlib

        blueprint = tmp_path / "blueprint"
        blueprint.mkdir(exist_ok=True)
        (blueprint / "DATABASE.md").write_text(db_content, encoding="utf-8")
        (blueprint / "SCREEN-A.md").write_text(screen_content, encoding="utf-8")
        db_hash = hashlib.sha256(b"db\n").hexdigest()
        screen_hash = hashlib.sha256(b"screen\n").hexdigest()
        path = tmp_path / "MANIFEST.md"
        path.write_text(
            _CASCADE_PLAN.format(db_hash=db_hash, screen_hash=screen_hash), encoding="utf-8"
        )
        return parse_build_plan(path), blueprint

    def test_stale_applied_specs_clean_when_content_matches(self, tmp_path):
        plan, blueprint = self._plan(tmp_path)
        assert stale_applied_specs(plan, blueprint) == ()

    def test_stale_applied_specs_reports_changed_and_missing(self, tmp_path):
        plan, blueprint = self._plan(tmp_path, db_content="db changed\n")
        (blueprint / "SCREEN-A.md").unlink()
        stale = {s.rel_path: s.reason for s in stale_applied_specs(plan, blueprint)}
        assert stale == {"DATABASE.md": "changed", "SCREEN-A.md": "missing"}

    def test_missing_generated_derivative_is_not_stale_while_its_source_stands(self, tmp_path):
        """A *_compact.md record survives deletion of the derivative: it is regenerable."""
        plan, blueprint = self._plan(tmp_path)
        applied = dict(plan.applied_specs)
        applied["DATABASE_compact.md"] = replace(applied["DATABASE.md"], path="DATABASE_compact.md")
        plan = replace(plan, applied_specs=applied)

        assert stale_applied_specs(plan, blueprint) == ()

    def test_missing_derivative_is_stale_when_its_source_is_gone_too(self, tmp_path):
        plan, blueprint = self._plan(tmp_path)
        applied = dict(plan.applied_specs)
        applied["DATABASE_compact.md"] = replace(applied["DATABASE.md"], path="DATABASE_compact.md")
        plan = replace(plan, applied_specs=applied)
        (blueprint / "DATABASE.md").unlink()

        stale = {s.rel_path: s.reason for s in stale_applied_specs(plan, blueprint)}
        assert stale == {"DATABASE.md": "missing", "DATABASE_compact.md": "missing"}

    def test_cascade_resets_consumers_dependents_children_and_parent_feature(self, tmp_path):
        plan, _ = self._plan(tmp_path)
        reset = cascade_reset_ids(plan, ["DATABASE.md"])
        # foundation implements it; screen-a consumes the compact derivative and
        # depends on foundation; screen-b depends on screen-a; ac-db is a child of
        # foundation; feat-core is the parent feature. unrelated stays untouched.
        assert set(reset) == {"feat-core", "foundation", "ac-db", "screen-a", "screen-b"}
        assert "unrelated" not in reset

    def test_cascade_small_radius_for_leaf_spec(self, tmp_path):
        plan, _ = self._plan(tmp_path)
        reset = cascade_reset_ids(plan, ["SCREEN-A.md"])
        assert set(reset) == {"feat-core", "screen-a", "screen-b"}

    def test_cascade_matches_compact_derivative_path(self, tmp_path):
        plan, _ = self._plan(tmp_path)
        assert set(cascade_reset_ids(plan, ["DATABASE_compact.md"])) == set(
            cascade_reset_ids(plan, ["DATABASE.md"])
        )


# A feature and its sole same-named story sharing one id, with an ac child and a
# downstream story that depends on the colliding story — the exact shape the
# planning LLM produced for commonmark.
_COLLIDING_MANIFEST = (
    "# MANIFEST: Demo\n"
    "state: approved\n\n"
    "## feature 1: Block Parsing\n"
    "id:      block-parsing\n"
    "summary: Block parsing feature.\n"
    "state:   pending\n\n"
    "## story 1: Block Parsing\n"
    "id:           block-parsing\n"
    "parent:       block-parsing\n"
    "implements:   FEATURE-Blocks.md\n"
    "depends:\n"
    "state:        pending\n"
    "scope:        both\n\n"
    "## ac 1: Block parsing check\n"
    "id:       block-parsing-check\n"
    "parent:   block-parsing\n"
    "kind:     smoke\n"
    "check:    true\n"
    "state:    pending\n\n"
    "## story 2: Inline Parsing\n"
    "id:           inline-parsing\n"
    "parent:       block-parsing\n"
    "implements:   FEATURE-Inlines.md\n"
    "depends:      block-parsing\n"
    "state:        pending\n"
    "scope:        both\n"
)


class TestDisambiguateManifestIds:
    def _parse(self, tmp_path, text):
        path = tmp_path / "MANIFEST.md"
        path.write_text(text, encoding="utf-8")
        return parse_build_plan(path)

    def test_feature_story_collision_is_resolved(self, tmp_path):
        fixed = disambiguate_manifest_ids(_COLLIDING_MANIFEST)
        plan = self._parse(tmp_path, fixed)
        ids = [b.block_id for b in plan.blocks]
        assert len(ids) == len(set(ids))  # every id unique
        by_id = plan.by_id()
        # The feature and story now carry type-prefixed ids.
        assert "feature-block-parsing" in by_id
        assert by_id["feature-block-parsing"].block_type == "feature"
        assert by_id["story-block-parsing"].block_type == "story"

    def test_references_repoint_by_hierarchy(self, tmp_path):
        plan = self._parse(tmp_path, disambiguate_manifest_ids(_COLLIDING_MANIFEST))
        by_id = plan.by_id()
        story = by_id["story-block-parsing"]
        ac = by_id["block-parsing-check"]
        downstream = by_id["inline-parsing"]
        # story.parent -> the feature; ac.parent -> the story; depends -> the story.
        assert story.parent == "feature-block-parsing"
        assert ac.parent == "story-block-parsing"
        assert downstream.depends == ("story-block-parsing",)

    def test_unresolvable_reference_is_left_for_parser(self, tmp_path):
        # Two stories share an id AND a third block depends on it: the reference
        # cannot be resolved structurally, so the text is returned untouched and
        # the parser reports the duplicate rather than the guard guessing.
        ambiguous = (
            "# MANIFEST: Demo\nstate: approved\n\n"
            "## story 1: A\nid: dup\nparent: feat\nstate: pending\n\n"
            "## story 2: B\nid: dup\nparent: feat\nstate: pending\n\n"
            "## story 3: C\nid: c\nparent: feat\ndepends: dup\nstate: pending\n"
        )
        assert disambiguate_manifest_ids(ambiguous) == ambiguous
        with pytest.raises(SpecificationError, match="Duplicate block id"):
            self._parse(tmp_path, ambiguous)

    def test_unique_manifest_is_unchanged(self, tmp_path):
        # With distinct ids the disambiguator is a verbatim no-op.
        text = (
            "# MANIFEST: Demo\nstate: approved\n\n"
            "## feature 1: X\nid: feat-x\nstate: pending\n\n"
            "## story 1: Y\nid: story-y\nparent: feat-x\nstate: pending\n"
        )
        assert disambiguate_manifest_ids(text) == text
