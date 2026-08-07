from __future__ import annotations

from drydock.lineage_impact import (
    StoryFacts,
    analyse,
    blocking_message,
    consumers_of,
    facts_from_manifest,
    render_notice,
)
from drydock.manifest import DrydockManifest

_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Persist books.
id: database
summary: Persist books.
type: foundational
implements: DATABASE.md
provides: books persistence interface
state: closed/verified

## story 2: Add a book.
id: add-book
summary: Add a book.
type: feature
implements: FEATURE-Add-Book.md
consumes: books persistence interface
state: closed/verified

## story 3: Show the list.
id: display
summary: Show the list.
type: feature
implements: SCREEN-Reading-List.md
consumes: Books Persistence Interface
state: closed/verified

## story 4: Shared layout.
id: ui-general
summary: Shared layout.
type: foundational
implements: UI-GENERAL.md
provides: shared layout patterns
state: closed/verified
"""


def _existing() -> tuple[StoryFacts, ...]:
    return facts_from_manifest(DrydockManifest.parse(_MANIFEST, source="test").blocks)


def test_facts_from_manifest_reads_the_graph_fields():
    facts = {fact.story_id: fact for fact in _existing()}

    assert facts["database"].implements == "DATABASE.md"
    assert facts["database"].story_type == "foundational"
    assert facts["database"].provides == ("books persistence interface",)
    assert facts["add-book"].consumes == ("books persistence interface",)


def test_consumers_of_matches_insensitively_to_case_and_spacing():
    # provides/consumes are free text, so a capitalisation difference must not hide a consumer.
    assert consumers_of("books persistence interface", _existing()) == ("add-book", "display")


def test_contract_change_reports_downstream_consumers_without_blocking():
    routed = (
        StoryFacts(
            story_id="mark-read-schema", implements="DATABASE.md", story_type="foundational"
        ),
    )

    impact = analyse(routed, _existing(), contract_changed=["mark-read-schema"])

    assert impact.foundational == ("mark-read-schema",)
    assert impact.contract_changed == ("mark-read-schema",)
    assert [consumer for consumer, _ in impact.downstream] == ["add-book", "display"]
    assert impact.blocks() is False
    assert "not gated" in render_notice(impact)


def test_a_build_detail_change_on_a_foundational_story_reports_nothing():
    routed = (StoryFacts(story_id="mark-read-schema", implements="DATABASE.md"),)

    impact = analyse(routed, _existing())

    assert impact.foundational == ("mark-read-schema",)
    assert impact.downstream == ()
    assert impact.blocks() is False
    assert render_notice(impact) == ""


def test_a_routed_story_inherits_foundational_from_the_blueprint_it_amends():
    routed = (StoryFacts(story_id="mark-read-view", implements="UI-GENERAL.md"),)

    impact = analyse(routed, _existing())

    assert impact.foundational == ("mark-read-view",)


def test_a_feature_blueprint_change_is_not_foundational():
    routed = (StoryFacts(story_id="mark-read-route", implements="FEATURE-Add-Book.md"),)

    impact = analyse(routed, _existing())

    assert impact.foundational == ()


def test_deleting_a_consumed_provision_blocks():
    impact = analyse((), _existing(), deleted_provisions=["books persistence interface"])

    assert impact.blocks() is True
    assert sorted(consumer for _, consumer in impact.broken) == ["add-book", "display"]
    message = blocking_message(impact)
    assert "would break add-book, display" in message
    assert "Update the specification" in message


def test_deleting_an_unconsumed_provision_does_not_block():
    impact = analyse((), _existing(), deleted_provisions=["shared layout patterns"])

    assert impact.blocks() is False
    assert impact.broken == ()


def test_a_routed_story_is_not_counted_as_its_own_downstream_consumer():
    routed = (
        StoryFacts(
            story_id="add-book",
            implements="FEATURE-Add-Book.md",
            consumes=("books persistence interface",),
        ),
        StoryFacts(
            story_id="mark-read-schema", implements="DATABASE.md", story_type="foundational"
        ),
    )

    impact = analyse(routed, _existing(), contract_changed=["mark-read-schema"])

    assert [consumer for consumer, _ in impact.downstream] == ["display"]


def test_contract_change_on_an_unrouted_story_id_is_ignored():
    impact = analyse((), _existing(), contract_changed=["not-in-this-run"])

    assert impact.contract_changed == ()
    assert impact.downstream == ()
