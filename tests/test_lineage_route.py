from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.lineage_route import (
    RoutedRequirement,
    RoutedStory,
    RouteProposal,
    Unseatable,
    assemble_route_prompt,
    assign_schedule,
    blueprint_names,
    parse_route_output,
    render_graph,
    route_requirements,
    validate_route,
)
from drydock.manifest import DrydockManifest

_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Persist books.
id: database
summary: Persist books.
type: foundational
phase: 1
block: 1
implements: DATABASE.md
provides: books persistence interface
state: closed/verified

## story 2: Show the list.
id: display
summary: Show the list.
type: feature
phase: 2
block: 3
implements: SCREEN-Reading-List.md
consumes: books persistence interface
depends: database
state: closed/verified
"""

_OUTPUT = """I will route this change.

<requirement name="mark-book-read">
The reader can mark a book as read.
</requirement>

<story id="mark-read-schema" implements="DATABASE.md" scope="amending" sections="Schema"
       requirement="mark-book-read" contract="changed">
Add persisted read state per book.
</story>

<story id="mark-read-view" implements="SCREEN-Reading-List.md" scope="additive"
       requirement="mark-book-read" depends="mark-read-schema">
Render read state per book.
</story>

<deleted provides="legacy interface"/>
"""


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "fake"


def _manifest() -> DrydockManifest:
    return DrydockManifest.parse(_MANIFEST, source="test")


def _blueprints(tmp_path: Path) -> Path:
    blueprint_dir = tmp_path / "blueprint"
    blueprint_dir.mkdir(parents=True)
    for name in ("DATABASE.md", "SCREEN-Reading-List.md", "COMPASS.md", "MANIFEST.md"):
        (blueprint_dir / name).write_text(f"# {name}\n\n## Schema\n\nbody\n", encoding="utf-8")
    (blueprint_dir / "DATABASE_compact.md").write_text("compact database\n", encoding="utf-8")
    return blueprint_dir


def _story(**overrides) -> RoutedStory:
    values = {
        "id": "mark-read-schema",
        "implements": "DATABASE.md",
        "scope": "amending",
        "summary": "Add read state.",
        "requirement": "mark-book-read",
    }
    values.update(overrides)
    return RoutedStory(**values)


def test_blueprint_names_excludes_compacts_and_governance(tmp_path):
    assert blueprint_names(_blueprints(tmp_path)) == ("DATABASE.md", "SCREEN-Reading-List.md")


def test_render_graph_exposes_the_edges_the_router_needs():
    rendered = render_graph(_manifest())

    assert '<story id="database"' in rendered
    assert 'provides="books persistence interface"' in rendered
    assert 'depends="database"' in rendered


def test_assemble_route_prompt_injects_diff_graph_and_blueprints(tmp_path):
    blueprint_dir = _blueprints(tmp_path)

    assembled = assemble_route_prompt(
        "BODY",
        diffs=[("spec.md", "d6f6e56", "4579751", "+mark as read")],
        manifest=_manifest(),
        blueprint_dir=blueprint_dir,
        names=blueprint_names(blueprint_dir),
    )

    assert assembled.startswith("BODY")
    assert '<diff source="spec.md" base="4579751" head="d6f6e56">' in assembled
    assert "+mark as read" in assembled
    assert "<graph>" in assembled
    assert '<blueprint name="DATABASE.md"' in assembled
    # The compact form is what compaction exists to provide.
    assert "compact database" in assembled


def test_assemble_route_prompt_names_the_authored_sections_behind_a_compact(tmp_path):
    # An amending story must name headings from the authored Blueprint, but the compact form
    # injected as the body carries none. Without the closed set the model can only invent one.
    blueprint_dir = _blueprints(tmp_path)

    assembled = assemble_route_prompt(
        "BODY",
        diffs=[("spec.md", "d6f6e56", "4579751", "+mark as read")],
        manifest=_manifest(),
        blueprint_dir=blueprint_dir,
        names=blueprint_names(blueprint_dir),
    )

    assert '<blueprint name="DATABASE.md" sections="Schema">' in assembled
    assert "## Schema" not in assembled.split("compact database")[0].split("<blueprints>")[-1]


def test_assemble_route_prompt_marks_a_first_import_as_having_no_base(tmp_path):
    blueprint_dir = _blueprints(tmp_path)

    assembled = assemble_route_prompt(
        "BODY",
        diffs=[("spec.md", "d6f6e56", None, "+everything")],
        manifest=_manifest(),
        blueprint_dir=blueprint_dir,
        names=(),
    )

    assert 'base="(none)"' in assembled


def test_parse_route_output_reads_requirements_stories_and_deletions():
    proposal = parse_route_output(_OUTPUT)

    assert [item.name for item in proposal.requirements] == ["mark-book-read"]
    assert [story.id for story in proposal.stories] == ["mark-read-schema", "mark-read-view"]
    schema, view = proposal.stories
    assert schema.scope == "amending"
    assert schema.sections == ("Schema",)
    assert schema.contract_changed is True
    assert view.scope == "additive"
    assert view.depends == ("mark-read-schema",)
    assert view.contract_changed is False
    assert proposal.deleted_provisions == ("legacy interface",)


def test_parse_route_output_ignores_model_preamble():
    proposal = parse_route_output(_OUTPUT)

    assert "I will route this change" not in proposal.requirements[0].text


def test_validate_route_accepts_a_well_formed_proposal(tmp_path):
    stories = validate_route(
        parse_route_output(_OUTPUT),
        manifest=_manifest(),
        blueprint_dir=_blueprints(tmp_path),
    )

    assert [story.id for story in stories] == ["mark-read-schema", "mark-read-view"]


def test_validate_route_fails_on_an_unseatable_requirement(tmp_path):
    proposal = RouteProposal(
        unseatable=(Unseatable("user-accounts", "no Blueprint owns identity"),)
    )

    with pytest.raises(SpecificationError, match="Replan required"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_rejects_an_unknown_blueprint(tmp_path):
    proposal = RouteProposal(stories=(_story(implements="FEATURE-Invented.md"),))

    with pytest.raises(SpecificationError, match="never creates a Blueprint"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_rejects_a_compact_blueprint_target(tmp_path):
    proposal = RouteProposal(stories=(_story(implements="DATABASE_compact.md"),))

    with pytest.raises(SpecificationError, match="does not exist"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_rejects_an_invalid_story_id(tmp_path):
    proposal = RouteProposal(stories=(_story(id="Mark Read"),))

    with pytest.raises(SpecificationError, match="not a valid slug"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_rejects_an_unknown_scope(tmp_path):
    proposal = RouteProposal(stories=(_story(scope="whatever"),))

    with pytest.raises(SpecificationError, match="unknown scope"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_rejects_an_unknown_dependency(tmp_path):
    proposal = RouteProposal(stories=(_story(depends=("nonexistent",)),))

    with pytest.raises(SpecificationError, match="unknown story id"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_accepts_a_dependency_on_an_existing_story(tmp_path):
    proposal = RouteProposal(stories=(_story(depends=("database",)),))

    stories = validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))

    assert stories[0].depends == ("database",)


def test_validate_route_rejects_a_dependency_cycle(tmp_path):
    proposal = RouteProposal(
        stories=(
            _story(id="one", depends=("two",)),
            _story(id="two", depends=("one",)),
        )
    )

    with pytest.raises(SpecificationError, match="dependency cycle"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_renames_a_colliding_id_and_rewrites_siblings(tmp_path):
    # Replacing an existing story would discard verified work, so the incoming one is renamed.
    proposal = RouteProposal(
        stories=(
            _story(id="database"),
            _story(id="mark-read-view", implements="SCREEN-Reading-List.md", depends=("database",)),
        )
    )

    stories = validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))

    assert stories[0].id == "database-2"
    assert stories[1].depends == ("database-2",)


def test_validate_route_rejects_a_requirement_that_was_never_routed(tmp_path):
    proposal = RouteProposal(
        requirements=(RoutedRequirement("orphan", "text"),),
        stories=(_story(),),
    )

    with pytest.raises(SpecificationError, match="unrouted"):
        validate_route(proposal, manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_validate_route_rejects_an_empty_proposal(tmp_path):
    with pytest.raises(SpecificationError, match="no stories"):
        validate_route(RouteProposal(), manifest=_manifest(), blueprint_dir=_blueprints(tmp_path))


def test_assign_schedule_places_a_story_after_what_it_depends_on():
    stories = (
        _story(id="mark-read-schema"),
        _story(id="mark-read-view", implements="SCREEN-Reading-List.md", depends=("display",)),
    )

    schedule = assign_schedule(stories, _manifest())

    assert schedule["mark-read-schema"]["phase"] == "1"
    assert schedule["mark-read-view"]["phase"] == "2"
    assert schedule["mark-read-schema"]["block"] == "4"


def test_route_requirements_uses_the_injected_runner(tmp_path):
    seen: dict[str, str] = {}

    def runner(prompt, working_directory, **kwargs):
        seen["prompt"] = prompt
        return FakeRun(text=_OUTPUT)

    proposal = route_requirements(
        [("spec.md", "d6f6e56", "4579751", "+mark as read")],
        _manifest(),
        _blueprints(tmp_path),
        runner=runner,
    )

    assert [story.id for story in proposal.stories] == ["mark-read-schema", "mark-read-view"]
    assert "<graph>" in seen["prompt"]


def test_route_requirements_fails_loudly_when_the_model_returns_nothing(tmp_path):
    def runner(prompt, working_directory, **kwargs):
        return FakeRun(ok=False, text="")

    with pytest.raises(SpecificationError, match="Source routing failed"):
        route_requirements(
            [("spec.md", "d6f6e56", None, "+x")],
            _manifest(),
            _blueprints(tmp_path),
            runner=runner,
        )
