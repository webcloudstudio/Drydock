"""The HTML surface of the Drydock Incident Report.

The page and the Markdown render from one verified diagnosis, so the tests that matter are the
ones proving they agree and that no model text reaches the page unescaped.
"""

from __future__ import annotations

import re

import pytest

from drydock.diagnose_html import render_page
from drydock.diagnose_report import render_report, verify
from tests.test_diagnose_command import (  # noqa: F401 — fixtures
    GOOD_ANSWER,
    bundle,
    workspace,
)

STAMP = "20260830.120000.000Z"


@pytest.fixture
def page(bundle):  # noqa: F811
    return render_page(bundle, verify(GOOD_ANSWER, bundle), stamp=STAMP)


# ── the page ─────────────────────────────────────────────────────────────────────────


def test_page_is_a_complete_standalone_document(page):
    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page and "</html>" in page
    assert "<script>" in page


def test_page_carries_the_letterhead_and_the_verdict_stamp(page):
    assert "DRYDOCK INCIDENT REPORT" in page
    assert "Demo — Incident Report" in page
    assert "STOPPED" in page


def test_page_shows_the_milestone_ladder_not_the_raw_states(page):
    for milestone in ("INIT", "ANALYZE", "PLAN", "BUILD", "SCORE"):
        assert milestone in page
    assert "PASSED" in page and "FAILED" in page


def test_page_names_the_state_that_superseded_a_failure(page):
    """PLAN CREATED failed and PLAN REPAIRED answered it; the page must say so."""
    assert "PLAN REPAIRED" in page
    assert "PLAN CREATED" in page


def test_page_has_a_tab_for_every_reader_task(page):
    for label in ("Findings", "Amendments", "Commands", "Log Files"):
        assert f">{label}</button>" in page


def test_page_colours_the_diff(page):
    assert 'class="add"' in page
    assert 'class="hunk"' in page


def test_page_reports_the_unapplicable_amendment(page):
    assert "Not Offered" in page
    assert "does not apply" in page


def test_page_cites_the_log_files(bundle, page):  # noqa: F811
    assert "Log Files" in page
    if bundle.logs:
        assert bundle.logs[0].sha256[:16] in page


# ── agreement with the Markdown ──────────────────────────────────────────────────────


def test_both_surfaces_report_the_same_stop(bundle, page):  # noqa: F811
    markdown = render_report(bundle, verify(GOOD_ANSWER, bundle), stamp=STAMP)
    assert bundle.stop.milestone in page
    assert bundle.stop.milestone in markdown
    assert bundle.stop.classification in page
    assert bundle.stop.classification in markdown


def test_both_surfaces_offer_the_same_amendments(bundle):  # noqa: F811
    diagnosis = verify(GOOD_ANSWER, bundle)
    page = render_page(bundle, diagnosis, stamp=STAMP)
    markdown = render_report(bundle, diagnosis, stamp=STAMP)
    for amendment in diagnosis.amendments:
        assert amendment.summary in page
        assert amendment.summary in markdown


# ── malformed and empty states ───────────────────────────────────────────────────────


def test_a_malformed_diagnosis_stamps_incomplete_and_keeps_the_raw_answer(bundle):  # noqa: F811
    diagnosis = verify("the model said something else", bundle)
    page = render_page(bundle, diagnosis, stamp=STAMP)
    assert "INCOMPLETE" in page
    assert "Diagnosis incomplete" in page
    assert "the model said something else" in page
    assert ">Raw Answer</button>" in page


def test_a_run_with_no_live_failure_stamps_no_stop(workspace):  # noqa: F811
    from drydock.diagnose_evidence import collect

    target = workspace / "targets" / "Demo"
    (target / "PROJECT_STATUS.jsonl").write_text(
        '{"label": "SCORE RELEASE", "result": "pass", "at": ""}\n', encoding="utf-8"
    )
    clean = collect("Demo", workspace, target)
    page = render_page(clean, verify(GOOD_ANSWER, clean), stamp=STAMP)
    assert "NO STOP" in page
    assert "No live failure recorded for Demo" in page


# ── escaping ─────────────────────────────────────────────────────────────────────────


def test_model_text_never_reaches_the_page_as_markup(bundle):  # noqa: F811
    hostile = GOOD_ANSWER.replace(
        "Why: Six criteria failed because the assertion was implicit.",
        "Why: <script>alert('x')</script>",
    )
    page = render_page(bundle, verify(hostile, bundle), stamp=STAMP)
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert" in page


def test_a_hostile_diff_body_is_escaped(bundle):  # noqa: F811
    hostile = GOOD_ANSWER.replace("+Every acceptance criterion", "+<img src=x onerror=1>")
    page = render_page(bundle, verify(hostile, bundle), stamp=STAMP)
    assert "<img src=x" not in page


def test_the_page_has_no_unbalanced_pre_blocks(page):
    assert len(re.findall(r"<pre", page)) == len(re.findall(r"</pre>", page))
