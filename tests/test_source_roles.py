from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.source_roles import (
    _staged_destination,
    parse_source_roles,
    promote_imported_sources,
    source_role_for,
    stage_build_assets,
    verify_staged_assets,
)


def test_promotes_assets_and_routes_author_intent_to_compass(tmp_path):
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "spec.txt").write_text("example", encoding="utf-8")
    (sources / "ED_INSTRUCTIONS.md").write_text("# Author Intent\n\nBuild it.\n", encoding="utf-8")
    roles = parse_source_roles(
        """## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| sources/spec.txt | normative conformance test suite | context | stage |
| sources/ED_INSTRUCTIONS.md | author intent | compass | none |
"""
    )

    promote_imported_sources(blueprint, roles, tmp_path)

    assert (blueprint / "spec.txt").read_text(encoding="utf-8") == "example"
    assert (sources / "spec.txt").read_text(encoding="utf-8") == "example"
    assert not (blueprint / "ED_INSTRUCTIONS.md").exists()
    assert "Build it." in (tmp_path / "COMPASS.md").read_text(encoding="utf-8")


def test_markdown_source_is_interpreted_not_promoted_over_blueprint(tmp_path):
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    (sources / "ARCHITECTURE.md").write_text(
        "# Messy source\n\n## Open Questions\n", encoding="utf-8"
    )
    governed = blueprint / "ARCHITECTURE.md"
    governed.write_text("# ARCHITECTURE: Governed\n", encoding="utf-8")

    promoted = promote_imported_sources(blueprint, {}, tmp_path)

    assert promoted == []
    assert governed.read_text(encoding="utf-8") == "# ARCHITECTURE: Governed\n"


def test_non_markdown_projection_preserves_bytes_and_nested_path(tmp_path):
    blueprint = tmp_path / "blueprint"
    source = blueprint / "sources" / "fixtures" / "sample.py"
    source.parent.mkdir(parents=True)
    payload = b"first\r\nsecond"
    source.write_bytes(payload)

    promote_imported_sources(blueprint, {}, tmp_path)

    assert (blueprint / "fixtures" / "sample.py").read_bytes() == payload


def test_source_role_globs_resolve_imported_files():
    roles = parse_source_roles(
        """## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| sources/FEATURE-*.md | source reference | context | prompt-only |
"""
    )

    role = source_role_for("FEATURE-CATALOG.md", roles)

    assert role is not None
    assert role.plan_disposition == "context"


# ---------------------------------------------------------------------------
# Build-asset staging
# ---------------------------------------------------------------------------

_ROLES_TABLE = """## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| sources/spec.txt | conformance test suite | context | stage |
| sources/kit/harness.py | conformance harness | context | stage |
| sources/NOTES.md | author intent | compass | stage |
| sources/cmark.py | reference implementation | context | none |
| sources/helper.py | test helper | context | prompt-only |
"""


def _kit(tmp_path):
    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    (sources / "kit").mkdir(parents=True)
    (sources / "spec.txt").write_text("EXAMPLE" * 100, encoding="utf-8")
    (sources / "kit" / "harness.py").write_text("print('harness')\n", encoding="utf-8")
    (sources / "NOTES.md").write_text("# Notes\n", encoding="utf-8")
    (sources / "cmark.py").write_text("reference\n", encoding="utf-8")
    (sources / "helper.py").write_text("helper\n", encoding="utf-8")
    (sources / ".gitkeep").write_text("", encoding="utf-8")
    (sources / ".drydock-import").write_text("marker\n", encoding="utf-8")
    return blueprint, tmp_path / "build"


def test_stages_only_files_marked_stage(tmp_path):
    blueprint, build = _kit(tmp_path)

    staged, replaced = stage_build_assets(blueprint, parse_source_roles(_ROLES_TABLE), build)

    assert [a.relative_path for a in staged] == ["sources/kit/harness.py", "sources/spec.txt"]
    assert replaced == ()
    # The test suite is staged byte-identical to the import, nested paths preserved.
    assert (build / "sources" / "spec.txt").read_text(encoding="utf-8") == "EXAMPLE" * 100
    assert (build / "sources" / "kit" / "harness.py").is_file()
    # `none` and `prompt-only` stage nothing; `.md` is prompt material even when marked stage.
    assert not (build / "sources" / "cmark.py").exists()
    assert not (build / "sources" / "helper.py").exists()
    assert not (build / "sources" / "NOTES.md").exists()
    # Import bookkeeping never reaches the deliverable.
    assert not (build / "sources" / ".gitkeep").exists()
    assert not (build / "sources" / ".drydock-import").exists()
    # No Drydock layout leaks into the build tree, and nothing lands at its root.
    assert not (build / "blueprint").exists()
    assert not (build / "spec.txt").exists()


def test_staging_is_idempotent(tmp_path):
    blueprint, build = _kit(tmp_path)
    roles = parse_source_roles(_ROLES_TABLE)

    stage_build_assets(blueprint, roles, build)
    staged, replaced = stage_build_assets(blueprint, roles, build)

    assert replaced == ()
    assert len(staged) == 2


def test_staging_overwrites_and_reports_a_substituted_asset(tmp_path):
    """The failure this contract exists to prevent: a build agent writing its own miniature
    test suite over the imported one."""
    blueprint, build = _kit(tmp_path)
    roles = parse_source_roles(_ROLES_TABLE)
    stage_build_assets(blueprint, roles, build)
    (build / "sources" / "spec.txt").write_text("# 2 examples\n", encoding="utf-8")

    staged, replaced = stage_build_assets(blueprint, roles, build)

    assert replaced == ("sources/spec.txt",)
    assert (build / "sources" / "spec.txt").read_text(encoding="utf-8") == "EXAMPLE" * 100
    assert staged


def test_no_source_roles_table_stages_nothing(tmp_path):
    blueprint, build = _kit(tmp_path)

    staged, replaced = stage_build_assets(blueprint, {}, build)

    assert (staged, replaced) == ((), ())
    assert not (build / "sources").exists()


def test_missing_sources_directory_is_not_an_error(tmp_path):
    staged, replaced = stage_build_assets(tmp_path / "blueprint", {}, tmp_path / "build")

    assert (staged, replaced) == ((), ())


def test_staged_destination_rejects_a_path_escaping_the_asset_directory(tmp_path):
    """Defense in depth. `stage_build_assets` derives every rel from `relative_to(sources/)`,
    so it cannot itself produce an escaping path; the guard protects future callers."""
    assert _staged_destination(tmp_path, "kit/harness.py") == (
        tmp_path / "sources" / "kit" / "harness.py"
    )
    with pytest.raises(SpecificationError, match="escapes the build asset directory"):
        _staged_destination(tmp_path, "../../escape.txt")


def test_verify_detects_and_restores_a_tampered_asset(tmp_path):
    blueprint, build = _kit(tmp_path)
    staged, _ = stage_build_assets(blueprint, parse_source_roles(_ROLES_TABLE), build)
    (build / "sources" / "spec.txt").write_text("truncated", encoding="utf-8")

    tampered = verify_staged_assets(staged, build)

    assert tampered == ("sources/spec.txt",)
    assert (build / "sources" / "spec.txt").read_text(encoding="utf-8") == "EXAMPLE" * 100


def test_verify_reports_a_deleted_asset(tmp_path):
    blueprint, build = _kit(tmp_path)
    staged, _ = stage_build_assets(blueprint, parse_source_roles(_ROLES_TABLE), build)
    (build / "sources" / "spec.txt").unlink()

    assert verify_staged_assets(staged, build) == ("sources/spec.txt",)
    assert (build / "sources" / "spec.txt").is_file()


def test_verify_without_restore_leaves_the_artifact_as_scored(tmp_path):
    blueprint, build = _kit(tmp_path)
    staged, _ = stage_build_assets(blueprint, parse_source_roles(_ROLES_TABLE), build)
    (build / "sources" / "spec.txt").write_text("truncated", encoding="utf-8")

    tampered = verify_staged_assets(staged, build, restore=False)

    assert tampered == ("sources/spec.txt",)
    assert (build / "sources" / "spec.txt").read_text(encoding="utf-8") == "truncated"


def test_verify_is_silent_when_the_kit_is_intact(tmp_path):
    blueprint, build = _kit(tmp_path)
    staged, _ = stage_build_assets(blueprint, parse_source_roles(_ROLES_TABLE), build)

    assert verify_staged_assets(staged, build) == ()
