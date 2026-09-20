"""Technology Stack artifact: parse/render, seeding, migration, and suggestion."""

from __future__ import annotations

import json

from drydock import technology_stack
from drydock.technology_stack import StackEntry

_ENTRIES = [
    StackEntry("Python", "python.md"),
    StackEntry("FastAPI", "fastapi.md", "Served by uvicorn."),
    StackEntry("marina-library", None, "Internal library; no Rigging guidance."),
]


# ── parse / render ──────────────────────────────────────────────────────────────


def test_round_trip_preserves_entries():
    assert technology_stack.parse(technology_stack.render(_ENTRIES)) == _ENTRIES


def test_render_writes_the_none_marker_for_an_unmatched_technology():
    text = technology_stack.render([StackEntry("uvicorn")])
    assert f"| uvicorn | {technology_stack.NONE_CELL} |" in text


def test_parse_treats_placeholder_cells_as_no_rigging():
    text = (
        "# Technology Stack\n\n"
        "| Technology | Rigging | Notes |\n|---|---|---|\n"
        "| A | — | |\n| B | - | |\n| C |  | |\n| D | none | |\n| E | N/A | |\n"
    )
    assert [e.rigging for e in technology_stack.parse(text)] == [None] * 5


def test_parse_skips_malformed_rows_rather_than_raising():
    text = (
        "# Technology Stack\n\n"
        "| Technology | Rigging | Notes |\n|---|---|---|\n"
        "| Python | python.md | |\n"
        "| | orphan.md | row with no technology |\n"
        "| Truncated |\n"
        "| Flask | flask.md | |\n"
    )
    entries = technology_stack.parse(text)
    assert [(e.technology, e.rigging) for e in entries] == [
        ("Python", "python.md"),
        ("Truncated", None),
        ("Flask", "flask.md"),
    ]


def test_parse_reads_backticked_cells_as_plain_names():
    """A code-span filename names the same Rigging file as the bare form.

    The specification prints filenames as code spans, so hand-edited and LLM-proposed
    stacks arrive backticked; parsing them as distinct names silently loses the guidance.
    """
    text = (
        "# Technology Stack\n\n"
        "| Technology | Rigging | Notes |\n|---|---|---|\n"
        "| Python | `python.md` | conventional |\n| Flask | `flask.md` | |\n"
    )
    entries = technology_stack.parse(text)
    assert [(e.technology, e.rigging) for e in entries] == [
        ("Python", "python.md"),
        ("Flask", "flask.md"),
    ]
    assert technology_stack.stack_files_from(entries) == ["python.md", "flask.md"]


def test_parse_returns_empty_when_no_table_is_present():
    assert technology_stack.parse("# Technology Stack\n\nNo table yet.\n") == []


def test_parse_escapes_survive_a_pipe_in_a_cell():
    entries = [StackEntry("Redis", "—", "Used for a | b routing")]
    assert (
        technology_stack.parse(technology_stack.render(entries))[0].notes
        == "Used for a | b routing"
    )


def test_stack_files_returns_distinct_rigging_names_in_order():
    entries = [
        StackEntry("FastAPI", "fastapi.md"),
        StackEntry("uvicorn", None),
        StackEntry("Starlette", "fastapi.md"),
        StackEntry("SQLite", "sqlite.md"),
    ]
    assert technology_stack.stack_files_from(entries) == ["fastapi.md", "sqlite.md"]


# ── load / write / ensure ───────────────────────────────────────────────────────


def test_load_returns_empty_for_an_absent_file(tmp_path):
    assert technology_stack.load(tmp_path) == []
    assert technology_stack.load_text(tmp_path) == ""


def test_write_then_load_round_trips(tmp_path):
    technology_stack.write(tmp_path, _ENTRIES)
    assert technology_stack.load(tmp_path) == _ENTRIES


def test_ensure_creates_the_file_when_absent(tmp_path):
    written = technology_stack.ensure_technology_stack(tmp_path, _ENTRIES)
    assert written is not None and written.is_file()
    assert technology_stack.load(tmp_path) == _ENTRIES


def test_ensure_never_overwrites_an_existing_file(tmp_path):
    technology_stack.write(tmp_path, [StackEntry("Commander choice", "flask.md")])
    assert technology_stack.ensure_technology_stack(tmp_path, _ENTRIES) is None
    assert [e.technology for e in technology_stack.load(tmp_path)] == ["Commander choice"]


def test_ensure_with_nothing_to_seed_writes_nothing(tmp_path):
    assert technology_stack.ensure_technology_stack(tmp_path) is None
    assert not technology_stack.path_for(tmp_path).is_file()


# ── migration from the superseded stack questionnaire ───────────────────────────


def _write_legacy(tmp_path, answer: str, **extra):
    path = tmp_path / "QuarterDeck" / "questionnaires" / "discovery-stack.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "id": "discovery-stack",
            "questions": [
                {"id": "stack_components", "required_before_plan": True, "answer": answer}
            ],
            **extra,
        }),
        encoding="utf-8",
    )
    return path


def test_migration_converts_a_legacy_selection_into_rows(tmp_path):
    legacy = _write_legacy(tmp_path, "python.md, flask.md, sqlite.md")

    technology_stack.ensure_technology_stack(tmp_path)

    assert [(e.technology, e.rigging) for e in technology_stack.load(tmp_path)] == [
        ("python", "python.md"),
        ("flask", "flask.md"),
        ("sqlite", "sqlite.md"),
    ]
    data = json.loads(legacy.read_text(encoding="utf-8"))
    assert data["archived"] is True
    assert data["superseded_by"] == technology_stack.FILENAME
    assert data["questions"][0]["required_before_plan"] is False


def test_migration_archives_the_questionnaire_even_when_the_file_already_exists(tmp_path):
    legacy = _write_legacy(tmp_path, "flask.md")
    technology_stack.write(tmp_path, _ENTRIES)

    assert technology_stack.ensure_technology_stack(tmp_path) is None

    assert json.loads(legacy.read_text(encoding="utf-8"))["archived"] is True
    assert technology_stack.load(tmp_path) == _ENTRIES


def test_migration_ignores_an_unanswered_questionnaire(tmp_path):
    _write_legacy(tmp_path, "")
    assert technology_stack.ensure_technology_stack(tmp_path) is None
    assert not technology_stack.path_for(tmp_path).is_file()


def test_migration_tolerates_malformed_questionnaire_json(tmp_path):
    path = tmp_path / "QuarterDeck" / "questionnaires" / "discovery-stack.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert technology_stack.ensure_technology_stack(tmp_path) is None


# ── Rigging catalog and suggestion ──────────────────────────────────────────────

_CATALOG = ["fastapi.md", "flask.md", "sqlite.md", "aws-dynamodb.md", "uv_ruff.md", "python.md"]


def test_suggest_matches_case_and_punctuation_insensitively():
    assert technology_stack.suggest_rigging("FastAPI", _CATALOG) == "fastapi.md"
    assert technology_stack.suggest_rigging("SQLite", _CATALOG) == "sqlite.md"
    assert technology_stack.suggest_rigging("AWS DynamoDB", _CATALOG) == "aws-dynamodb.md"
    assert technology_stack.suggest_rigging("uv/ruff", _CATALOG) == "uv_ruff.md"


def test_suggest_returns_none_rather_than_a_wrong_guess():
    assert technology_stack.suggest_rigging("marina-library", _CATALOG) is None
    assert technology_stack.suggest_rigging("HTMX", _CATALOG) is None
    assert technology_stack.suggest_rigging("", _CATALOG) is None
    assert technology_stack.suggest_rigging("Python", []) is None


def test_rigging_catalog_reads_the_real_rigging_tree():
    names = technology_stack.rigging_names()
    assert "python.md" in names
    assert "README.md" not in names
    assert not any("_compact" in name for name in names)


def test_rigging_groups_order_known_categories_first():
    groups = technology_stack.rigging_groups([
        ("zeta.md", "Unknown"),
        ("sqlite.md", "Persistence"),
        ("flask.md", "Web Server"),
    ])
    assert [g["label"] for g in groups] == ["Web Server", "Persistence", "Unknown"]


def test_an_unapproved_document_carries_no_approval_marker(tmp_path):
    technology_stack.write(tmp_path, [technology_stack.StackEntry("FastAPI", "fastapi.md")])

    text = technology_stack.load_text(tmp_path)
    assert "**Approved:**" not in text
    assert technology_stack.approved_on(tmp_path) is None
    assert not technology_stack.is_approved(tmp_path)


def test_approve_records_a_dated_marker_and_round_trips_the_rows(tmp_path):
    entries = [
        technology_stack.StackEntry("FastAPI", "fastapi.md", "Served by uvicorn"),
        technology_stack.StackEntry("marina-library", None, ""),
    ]
    technology_stack.write(tmp_path, entries)

    technology_stack.approve(tmp_path, "2026-08-06")

    assert technology_stack.approved_on(tmp_path) == "2026-08-06"
    assert technology_stack.is_approved(tmp_path)
    assert technology_stack.load(tmp_path) == entries


def test_approve_defaults_to_today_and_re_dates_an_approved_stack(tmp_path):
    from datetime import date

    technology_stack.write(tmp_path, [technology_stack.StackEntry("Go")], "2020-01-01")

    technology_stack.approve(tmp_path)

    assert technology_stack.approved_on(tmp_path) == date.today().isoformat()
    assert technology_stack.load_text(tmp_path).count("**Approved:**") == 1


def test_a_python_target_with_a_database_needs_no_orm_selection(tmp_path):
    (tmp_path / "blueprint").mkdir()
    (tmp_path / "blueprint" / "DATABASE.md").write_text("# DATABASE: Example\n", encoding="utf-8")
    entries = [StackEntry("Python", "python.md")]
    technology_stack.write(tmp_path, entries)

    assert technology_stack.declared_language(tmp_path) == "python"
    assert technology_stack.unsupported_persistence(tmp_path) is None

    technology_stack.approve(tmp_path, "2026-09-19")

    assert technology_stack.is_approved(tmp_path)


def test_a_language_with_no_shipped_adapter_is_refused_rather_than_ignored(tmp_path):
    import pytest

    (tmp_path / "blueprint").mkdir()
    (tmp_path / "blueprint" / "DATABASE.md").write_text("# DATABASE: Example\n", encoding="utf-8")
    technology_stack.write(tmp_path, [StackEntry("Go", "go.md")])

    assert technology_stack.unsupported_persistence(tmp_path) == "go"
    with pytest.raises(ValueError, match="ships no persistence adapter for go"):
        technology_stack.approve(tmp_path)
    assert not technology_stack.is_approved(tmp_path)


def test_an_unsupported_language_without_a_database_is_not_gated(tmp_path):
    technology_stack.write(tmp_path, [StackEntry("Go", "go.md")])

    assert technology_stack.unsupported_persistence(tmp_path) is None

    technology_stack.approve(tmp_path, "2026-09-19")

    assert technology_stack.is_approved(tmp_path)


def test_an_undeclared_language_leaves_the_stack_undecided_rather_than_blocked(tmp_path):
    (tmp_path / "blueprint").mkdir()
    (tmp_path / "blueprint" / "DATABASE.md").write_text("# DATABASE: Example\n", encoding="utf-8")
    technology_stack.write(tmp_path, [StackEntry("Bootstrap 5", "bootstrap5.md")])

    assert technology_stack.declared_language(tmp_path) is None
    assert technology_stack.unsupported_persistence(tmp_path) is None


def test_is_approved_is_false_for_a_missing_document(tmp_path):
    assert not technology_stack.is_approved(tmp_path / "absent")


# ── Foundation selection ────────────────────────────────────────────────────────


def test_foundation_groups_read_in_build_order():
    """Language first: a web server or a database is built into the tree and the environment
    only the language foundation lays down."""
    groups = technology_stack.foundation_groups([])

    assert [group["label"] for group in groups] == ["Language", "Web Server", "Database", "CLI"]
    assert [group["tier"] for group in groups] == [
        "language",
        "platform",
        "platform",
        "platform",
    ]
    assert [group["tier_number"] for group in groups] == [1, 2, 2, 2]


def test_a_target_nobody_has_decided_for_gets_the_default_stack():
    groups = {group["kind"]: group["selected"] for group in technology_stack.foundation_groups([])}

    assert groups["language"] == "python.md"
    assert groups["web-server"] == "fastapi.md"
    assert groups["database"] == "sqlite.md"
    assert groups["cli"] == ""


def test_a_stack_that_names_no_web_server_has_decided_it_has_none():
    """The default is a starting point for an undecided Target, never an override of a decision."""
    entries = [technology_stack.StackEntry("Python", "python.md")]

    groups = {
        group["kind"]: group["selected"] for group in technology_stack.foundation_groups(entries)
    }

    assert groups["language"] == "python.md"
    assert groups["web-server"] == ""


def test_split_foundations_pulls_an_unanswered_foundation_row_into_the_selector():
    """A half-answered foundation row belongs in the exclusive selector, not in the free-text
    table where it can only stay half-answered."""
    entries = [
        technology_stack.StackEntry("FastAPI", None),
        technology_stack.StackEntry("Redis", None),
    ]

    chosen, remaining = technology_stack.split_foundations(entries)

    assert chosen == {"web-server": ""}
    assert [entry.technology for entry in remaining] == ["Redis"]


def test_with_foundations_replaces_the_choices_and_keeps_everything_else():
    entries = [
        technology_stack.StackEntry("FastAPI", "fastapi.md"),
        technology_stack.StackEntry("Bootstrap 5", "bootstrap5.md"),
        technology_stack.StackEntry("Redis", None, "cache"),
    ]

    result = technology_stack.with_foundations(
        entries, {"language": "python.md", "web-server": "flask.md", "database": ""}
    )

    assert [(entry.technology, entry.rigging) for entry in result] == [
        ("python", "python.md"),
        ("flask", "flask.md"),
        ("Bootstrap 5", "bootstrap5.md"),
        ("Redis", None),
    ]
    assert result[-1].notes == "cache"


def test_the_frontend_files_are_no_longer_offered_as_web_servers():
    """bootstrap5.md is not a web server. It was filed under Web Server and shown to the
    Commander next to the three files that are."""
    groups = {group["label"]: group["options"] for group in technology_stack.rigging_groups()}

    assert "bootstrap5.md" in groups["Frontend"]
    assert "ui-flask.bootstrap-client.md" in groups["Frontend"]
    assert groups["Web Server"] == ["django.md", "fastapi.md", "flask.md"]
    assert groups["Language"] == ["go.md", "python.md", "typescript.md"]
