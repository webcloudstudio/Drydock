from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drydock.lineage import Requirement, load_lineage
from drydock.lineage_attribution import (
    Attribution,
    assemble_attribution_prompt,
    attribute_source,
    parse_attribution_output,
    parse_tag_blocks,
    render_story_catalogue,
    story_ids,
    validate_attribution,
)
from drydock.manifest import DrydockManifest

_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Establish the application structure.
id: architecture
summary: Establish the application structure.
implements: ARCHITECTURE.md
state: pending

## story 2: Persist books.
id: database
summary: Persist books.
implements: DATABASE.md
state: pending

## story 3: Add a book.
id: add-book
summary: Add a book.
implements: FEATURE-Add-Book.md
state: pending
"""

_OUTPUT = """Here is the attribution.

<requirement name="add-books" stories="add-book,database">
The reader can add a book with a title and author.
</requirement>
<unattached story="architecture"/>
"""


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "fake"


def _manifest() -> DrydockManifest:
    return DrydockManifest.parse(_MANIFEST, source="test")


def test_parse_tag_blocks_reads_attributes_and_body():
    blocks = parse_tag_blocks(_OUTPUT, names=frozenset({"requirement", "unattached"}))

    assert [block.name for block in blocks] == ["requirement", "unattached"]
    assert blocks[0].attrs["name"] == "add-books"
    assert blocks[0].text.startswith("The reader can add a book")
    assert blocks[1].attrs["story"] == "architecture"


def test_parse_tag_blocks_ignores_model_preamble():
    blocks = parse_tag_blocks(_OUTPUT, names=frozenset({"requirement"}))

    assert len(blocks) == 1
    assert "Here is the attribution" not in blocks[0].text


def test_parse_attribution_output_splits_stories_and_unattached():
    requirements, unattached = parse_attribution_output(_OUTPUT)

    assert requirements[0].name == "add-books"
    assert requirements[0].stories == ("add-book", "database")
    assert unattached == ("architecture",)


def test_story_ids_and_catalogue_cover_every_story():
    manifest = _manifest()

    assert story_ids(manifest) == ("architecture", "database", "add-book")
    catalogue = render_story_catalogue(manifest)
    assert '<story id="database" implements="DATABASE.md">Persist books.</story>' in catalogue


def test_assemble_attribution_prompt_injects_the_source_and_the_story_set():
    assembled = assemble_attribution_prompt(
        "BODY", rel_path="spec.md", source_text="Add a book.", manifest=_manifest()
    )

    assert assembled.startswith("BODY")
    assert '<source name="spec.md">' in assembled
    assert "<stories>" in assembled
    assert '<story id="add-book"' in assembled


def test_validate_attribution_drops_unknown_story_ids_with_a_warning():
    result = validate_attribution(
        [Requirement("add-books", "text", ("add-book", "invented"))],
        ["architecture"],
        known_stories=("add-book", "architecture"),
    )

    assert result.requirements[0].stories == ("add-book",)
    assert result.unattached == ("architecture",)
    assert "invented" in result.warnings[0]


def test_validate_attribution_keeps_an_unattached_story_without_failing():
    result = validate_attribution([], ["architecture"], known_stories=("architecture",))

    assert result == Attribution((), ("architecture",), ())


def test_attribute_source_returns_validated_requirements(tmp_path):
    seen: dict[str, str] = {}

    def runner(prompt, working_directory, **kwargs):
        seen["prompt"] = prompt
        return FakeRun(text=_OUTPUT)

    result = attribute_source(
        "spec.md", "Add a book.", _manifest(), working_directory=tmp_path, runner=runner
    )

    assert result.requirements[0].stories == ("add-book", "database")
    assert result.unattached == ("architecture",)
    assert '<source name="spec.md">' in seen["prompt"]


def test_attribute_source_skips_an_empty_source_without_calling_the_model(tmp_path):
    def runner(prompt, working_directory, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("the model must not be called for an empty source")

    assert attribute_source(
        "spec.md", "   \n", _manifest(), working_directory=tmp_path, runner=runner
    ) == Attribution((), ())


def test_attribute_source_degrades_to_a_warning_when_the_model_fails(tmp_path):
    def runner(prompt, working_directory, **kwargs):
        return FakeRun(ok=False, text="")

    result = attribute_source(
        "spec.md", "Add a book.", _manifest(), working_directory=tmp_path, runner=runner
    )

    assert result.requirements == ()
    assert "attribution unavailable" in result.warnings[0]


def _target(tmp_path: Path) -> Path:
    """A Target in the real order: import records lineage first, then plan writes the Manifest."""
    from drydock.lineage import record_initial_snapshot

    target = tmp_path / "Demo"
    sources = target / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / "spec.md").write_text("The reader can add a book.\n", encoding="utf-8")
    record_initial_snapshot(target, sources, date="2026-08-05")
    (target / "MANIFEST.md").write_text(_MANIFEST, encoding="utf-8")
    return target


def test_consume_after_plan_records_requirements_against_the_version(tmp_path):
    from drydock.lineage import consume_after_plan

    target = _target(tmp_path)

    def attributor(rel_path: str, text: str) -> Attribution:
        return Attribution((Requirement("add-books", text.strip(), ("add-book",)),), ())

    consume_after_plan(
        target,
        target / "blueprint" / "sources",
        date="2026-08-06",
        commit="abc1234",
        attributor=attributor,
    )

    version = load_lineage(target).sources["spec.md"].versions[-1]
    assert (version.state, version.via, version.commit) == ("consumed", "plan", "abc1234")
    assert version.requirements[0].stories == ("add-book",)


def test_consume_after_plan_without_an_attributor_still_consumes(tmp_path):
    from drydock.lineage import consume_after_plan

    target = _target(tmp_path)

    consume_after_plan(target, target / "blueprint" / "sources", date="2026-08-06")

    version = load_lineage(target).sources["spec.md"].versions[-1]
    assert version.state == "consumed"
    assert version.requirements == ()


def test_consume_after_plan_is_idempotent_across_runs(tmp_path):
    from drydock.lineage import consume_after_plan

    target = _target(tmp_path)

    consume_after_plan(target, target / "blueprint" / "sources", date="2026-08-06")
    consume_after_plan(target, target / "blueprint" / "sources", date="2026-08-07")

    assert len(load_lineage(target).sources["spec.md"].versions) == 1
