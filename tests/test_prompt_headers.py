"""Tests for JSON-backed prompt header metadata."""

from __future__ import annotations

from pathlib import Path

from drydock.prompt_headers import (
    prompt_header,
    prompt_header_for_file,
    prompt_header_for_path,
    prompt_headers,
)


def test_prompt_headers_load_from_json():
    headers = {header.filename: header for header in prompt_headers()}

    assert "ANALYZE_COMPASS.md" in headers
    assert headers["ANALYZE_COMPASS.md"].item_id == "analyze_compass"
    assert headers["ANALYZE_COMPASS.md"].default_text == "# Analyze Compass\n"


def test_prompt_header_lookup_by_item_id():
    header = prompt_header("plan_compass")

    assert header is not None
    assert header.filename == "PLAN_COMPASS.md"
    assert header.prompt_text.strip()


def test_prompt_header_lookup_by_filename():
    header = prompt_header_for_file("COMPASS.md")

    assert header is not None
    assert header.item_id == "compass_edit"
    assert "injected into every build step" in header.help_text
    assert header.prompt_text.strip()


def test_prompt_header_lookup_for_injected_file():
    header = prompt_header_for_file("ANALYSIS.md")

    assert header is not None
    assert header.item_id is None
    assert header.role == "planning basis"
    assert header.prompt_text.strip()


def test_prompt_header_lookup_for_injected_prefix():
    header = prompt_header_for_file("FEATURE-Auth.md")

    assert header is not None
    assert header.item_id is None
    assert header.role == "feature contract"
    assert header.label == "Feature Contract"


def test_prompt_header_lookup_for_imported_source_path():
    header = prompt_header_for_path(Path("/tmp/Target/blueprint/sources/ARCHITECTURE.md"))

    assert header is not None
    assert header.role == "source reference"
    assert header.label == "Imported Source"


def test_prompt_header_lookup_for_questionnaire_path():
    header = prompt_header_for_path(Path("/tmp/Target/QuarterDeck/questionnaires/discovery-auth.json"))

    assert header is not None
    assert header.role == "questionnaire"
    assert header.label == "Questionnaire"
