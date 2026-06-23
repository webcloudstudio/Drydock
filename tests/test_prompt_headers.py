"""Tests for JSON-backed prompt header metadata."""

from __future__ import annotations

from drydock.prompt_headers import prompt_header, prompt_header_for_file, prompt_headers


def test_prompt_headers_load_from_json():
    headers = {header.filename: header for header in prompt_headers()}

    assert "ANALYZE_COMPASS.md" in headers
    assert headers["ANALYZE_COMPASS.md"].item_id == "analyze_compass"
    assert headers["ANALYZE_COMPASS.md"].default_text == "# Analyze Compass\n"


def test_prompt_header_lookup_by_item_id():
    header = prompt_header("plan_compass")

    assert header is not None
    assert header.filename == "PLAN_COMPASS.md"
    assert "decomposition" in header.prompt_text


def test_prompt_header_lookup_by_filename():
    header = prompt_header_for_file("COMPASS.md")

    assert header is not None
    assert header.item_id == "compass_edit"
    assert "injected into every build step" in header.help_text
