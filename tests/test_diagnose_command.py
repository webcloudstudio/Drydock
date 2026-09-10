"""``drydock diagnose``: evidence collection, verification, confirmation, and every exit path.

No test spends a model call or touches a terminal: the runner and the confirmer are injected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.diagnose_apply import resolve
from drydock.diagnose_command import parse_mode
from drydock.diagnose_evidence import collect
from drydock.diagnose_report import assemble, render_report, verify, write_report
from drydock.errors import UsageError
from drydock.patch import parse_amendments
from drydock.prompts import load_prompt

# ── fixtures ─────────────────────────────────────────────────────────────────────────

STATUS_ROWS = [
    {"label": "INITIALIZED", "result": "pass", "at": "2026-08-21T17:07:00.000+00:00"},
    {"label": "IMPORTED", "result": "pass", "at": "2026-08-21T17:10:00.000+00:00"},
    {"label": "ANALYZED", "result": "pass", "at": "2026-08-21T17:12:00.000+00:00"},
    {
        "label": "PLAN CREATED",
        "result": "fail",
        "at": "2026-08-21T19:18:00.000+00:00",
        "detail": "malformed batch",
        "attempts": 3,
    },
    {"label": "PLAN REPAIRED", "result": "pass", "at": "2026-08-21T19:25:00.000+00:00"},
    {"label": "BUILT", "result": "pass", "at": "2026-08-22T00:36:00.000+00:00"},
    {
        "label": "SCORE AC",
        "result": "fail",
        "at": "2026-08-22T02:01:00.000+00:00",
        "detail": "programmatic acceptance failed: 6 of 45",
        "attempts": 7,
    },
]

GOOD_ANSWER = """### Break Point

`SCORE AC` stopped the run at `blueprint/FEATURE-Lexer.md:41`.

### Reason

Governed-input defect: the criteria do not name the assertion they run.

### Not A Real Failure

- `PLAN CREATED` failed and `PLAN REPAIRED` answered it.
- The seven attempts at `SCORE AC` are one failure retried.

### Blockers and Decisions

None.

### Evidence

- `SCORECARD.md:5` — `PASS 39 FAIL 6`.

### Recommended Amendments

#### 1. Require every criterion to name its assertion

File: `PLAN_COMPASS.md`
Why: Six criteria failed because the assertion was implicit.

```diff
--- a/PLAN_COMPASS.md
+++ b/PLAN_COMPASS.md
@@ -1,3 +1,5 @@
 # Plan Compass

 Rules that govern planning.
+
+Every acceptance criterion must name the assertion it runs.
```

#### 2. A diff that cannot apply

File: `COMPASS.md`
Why: deliberately wrong, to prove verification.

```diff
--- a/COMPASS.md
+++ b/COMPASS.md
@@ -1,2 +1,3 @@
 lines that do not exist
 nor these
+added
```
"""


@dataclass
class FakeRun:
    """Stand-in for an LlmResult — never spends API credits."""

    ok: bool = True
    text: str = GOOD_ANSWER
    execution_id: str = "exec-fake"


def fake_runner(text: str = GOOD_ANSWER, *, ok: bool = True):
    seen: list[str] = []

    def run(prompt, working_directory, **kwargs):
        seen.append(prompt)
        return FakeRun(ok=ok, text=text)

    run.seen = seen  # type: ignore[attr-defined]
    return run


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A Target that planned, repaired, built, and then failed acceptance."""
    ws = tmp_path / "ws"
    target = ws / "targets" / "Demo"
    target.mkdir(parents=True)
    (ws / "logs").mkdir(parents=True)

    (target / "PROJECT_STATUS.jsonl").write_text(
        "\n".join(json.dumps(row) for row in STATUS_ROWS) + "\n", encoding="utf-8"
    )
    (target / "PLAN_COMPASS.md").write_text(
        "# Plan Compass\n\nRules that govern planning.\n", encoding="utf-8"
    )
    (target / "COMPASS.md").write_text("# Compass\n\nProject intent.\n", encoding="utf-8")
    (target / "ANALYZE_COMPASS.md").write_text("# Analyze Compass\n\nRules.\n", encoding="utf-8")
    (target / "MANIFEST.md").write_text(
        "# Manifest\n\n### story-one\n\n### story-two\n", encoding="utf-8"
    )
    (target / "SCORECARD.md").write_text(
        "# Scorecard: Demo\n\n## Acceptance\n\nPASS 39 FAIL 6\n", encoding="utf-8"
    )
    (ws / "logs" / "history.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "command": "drydock init Demo",
                    "time": "2026-08-21 17:07",
                    "return_code": 0,
                    "argv": ["init", "Demo"],
                    "stamp": "20260821.170700.000Z",
                },
                {
                    "command": "drydock score ac Demo",
                    "time": "2026-08-22 02:01",
                    "return_code": 1,
                    "argv": ["score", "ac", "Demo"],
                    "stamp": "20260822.020100.000Z",
                    "transcript": "logs/20260822.020100.000Z_Demo_score-ac_codex.log",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (ws / "logs" / "20260822.020100.000Z_Demo_score-ac_codex.log").write_text(
        "running acceptance\nFAIL lexer-core-syntax\n", encoding="utf-8"
    )
    return ws


@pytest.fixture
def bundle(workspace: Path):
    return collect("Demo", workspace, workspace / "targets" / "Demo")


# ── evidence ─────────────────────────────────────────────────────────────────────────


def test_bundle_names_the_live_stop_not_the_repaired_one(bundle):
    assert bundle.stop is not None
    assert bundle.stop.milestone == "SCORE"
    assert bundle.stop.classification == "programmatic acceptance failed"
    assert [entry.label for entry in bundle.superseded] == ["PLAN CREATED"]


def test_bundle_collects_the_failed_command_transcript(bundle):
    assert bundle.transcripts
    assert "FAIL lexer-core-syntax" in bundle.transcripts[0].text


def test_bundle_reads_every_amendable_file(bundle):
    from drydock.diagnose_evidence import AMENDABLE

    assert {excerpt.name for excerpt in bundle.governed} == set(AMENDABLE)


def test_bundle_reports_absent_evidence_rather_than_inventing_it(workspace):
    bare = workspace / "targets" / "Bare"
    bare.mkdir()
    empty = collect("Bare", workspace, bare)
    assert "SCORECARD.md" in empty.missing
    assert empty.stop is None
    assert all(row.state == "not run" for row in empty.ladder)


def test_bundle_survives_a_corrupt_status_file(workspace):
    target = workspace / "targets" / "Demo"
    (target / "PROJECT_STATUS.jsonl").write_text("{ not json\n", encoding="utf-8")
    result = collect("Demo", workspace, target)
    assert result.stop is None
    assert all(row.state == "not run" for row in result.ladder)


def test_bundle_survives_a_truncated_scorecard(workspace):
    target = workspace / "targets" / "Demo"
    (target / "SCORECARD.md").write_text("# Scorecard\n\n> **FAI", encoding="utf-8")
    assert collect("Demo", workspace, target).scorecard is not None


def test_ladder_notes_come_from_target_artifacts(bundle):
    analyzed = next(row for row in bundle.ladder if row.milestone == "ANALYZE")
    assert analyzed.note == "2 stories"


# ── prompt assembly ──────────────────────────────────────────────────────────────────


def test_prompt_carries_the_deterministic_facts_and_the_amendable_files(bundle):
    text = assemble(bundle, load_prompt("diagnose_report").body).rendered_text
    assert "SCORE" in text
    assert "Superseded failures" in text
    assert "PLAN CREATED" in text
    assert "PLAN_COMPASS.md" in text
    assert "Rules that govern planning." in text


def test_prompt_numbers_the_amendable_lines_so_a_diff_can_apply(bundle):
    text = assemble(bundle, load_prompt("diagnose_report").body).rendered_text
    assert "    1\t# Plan Compass" in text


# ── verification ─────────────────────────────────────────────────────────────────────


def test_a_conforming_answer_verifies_and_keeps_only_applicable_diffs(bundle):
    diagnosis = verify(GOOD_ANSWER, bundle)
    assert diagnosis.ok
    assert [item.file for item in diagnosis.amendments] == ["PLAN_COMPASS.md"]
    assert [item.file for item in diagnosis.unapplicable] == ["COMPASS.md"]
    assert "does not apply" in diagnosis.unapplicable[0].rejection


def test_a_missing_section_is_a_contract_violation(bundle):
    diagnosis = verify(GOOD_ANSWER.replace("### Evidence", "### Notes"), bundle)
    assert not diagnosis.ok
    assert any("Evidence" in problem for problem in diagnosis.problems)


def test_an_amendment_against_a_forbidden_file_is_never_offered(bundle):
    answer = GOOD_ANSWER.replace("File: `PLAN_COMPASS.md`", "File: `src/drydock/cli.py`")
    diagnosis = verify(answer, bundle)
    assert diagnosis.amendments == ()
    assert "not an amendable file" in diagnosis.unapplicable[0].rejection


def test_prose_without_a_diff_is_not_an_amendment():
    assert parse_amendments("#### 1. Do something\n\nFile: `COMPASS.md`\nWhy: because.\n") == ()


# ── the report ───────────────────────────────────────────────────────────────────────


def test_report_carries_every_section_and_the_log_paths(bundle):
    diagnosis = verify(GOOD_ANSWER, bundle)
    text = render_report(bundle, diagnosis, stamp="20260830.120000.000Z")
    for heading in ("Break Point", "Reason", "Not A Real Failure", "Evidence", "Log Files"):
        assert f"## {heading}" in text
    assert "## Stage Ladder" in text
    assert "[FAIL] SCORE" in text
    assert "programmatic acceptance failed" in text


def test_report_shows_the_rejected_amendment_rather_than_hiding_it(bundle):
    text = render_report(bundle, verify(GOOD_ANSWER, bundle), stamp="x")
    assert "### Not Offered" in text
    assert "COMPASS.md" in text


def test_a_malformed_answer_is_still_written_with_the_raw_text(bundle):
    diagnosis = verify("the model said something else entirely", bundle)
    text = render_report(bundle, diagnosis, stamp="x")
    assert "**MALFORMED**" in text
    assert "## Contract Violations" in text
    assert "the model said something else entirely" in text


def test_write_report_writes_both_surfaces_in_the_target_root(bundle):
    written = write_report(bundle, verify(GOOD_ANSWER, bundle), stamp="20260830.120000.000Z")
    assert written.markdown.name == "DIAGNOSE_20260830.120000.000Z.md"
    assert written.html.name == "DIAGNOSE_20260830.120000.000Z.html"
    # The Target root, beside SCORECARD.md and MANIFEST.md — not a subdirectory.
    assert written.markdown.parent == bundle.target_dir
    assert written.html.parent == bundle.target_dir
    assert written.markdown.is_file() and written.html.is_file()


# ── confirmation and application ─────────────────────────────────────────────────────


def test_confirming_an_amendment_edits_the_file(bundle, workspace):
    target = workspace / "targets" / "Demo"
    diagnosis = verify(GOOD_ANSWER, bundle)
    outcome = resolve(diagnosis.amendments, target, mode="confirm", confirm=lambda _: True)
    assert outcome.changed_files == ("PLAN_COMPASS.md",)
    assert "must name the assertion" in (target / "PLAN_COMPASS.md").read_text(encoding="utf-8")


def test_declining_leaves_the_file_alone_and_records_a_decision(bundle, workspace):
    target = workspace / "targets" / "Demo"
    before = (target / "PLAN_COMPASS.md").read_text(encoding="utf-8")
    diagnosis = verify(GOOD_ANSWER, bundle)
    outcome = resolve(diagnosis.amendments, target, mode="confirm", confirm=lambda _: False)

    assert outcome.applied == ()
    assert (target / "PLAN_COMPASS.md").read_text(encoding="utf-8") == before
    recorded = json.loads((target / "DECISIONS.json").read_text(encoding="utf-8"))
    assert recorded[0]["origin"] == "diagnose"
    assert recorded[0]["status"] == "recommended"


def test_apply_mode_asks_nothing(bundle, workspace):
    target = workspace / "targets" / "Demo"

    def never(question):
        raise AssertionError("--apply must not prompt")

    outcome = resolve(verify(GOOD_ANSWER, bundle).amendments, target, mode="apply", confirm=never)
    assert len(outcome.applied) == 1


def test_no_apply_mode_changes_nothing_and_records_everything(bundle, workspace):
    target = workspace / "targets" / "Demo"
    before = (target / "PLAN_COMPASS.md").read_text(encoding="utf-8")
    outcome = resolve(verify(GOOD_ANSWER, bundle).amendments, target, mode="none")

    assert outcome.applied == ()
    assert len(outcome.declined) == 1
    assert (target / "PLAN_COMPASS.md").read_text(encoding="utf-8") == before
    assert (target / "DECISIONS.json").is_file()


def test_recording_the_same_amendment_twice_files_it_once(bundle, workspace):
    target = workspace / "targets" / "Demo"
    amendments = verify(GOOD_ANSWER, bundle).amendments
    resolve(amendments, target, mode="none")
    resolve(amendments, target, mode="none")
    assert len(json.loads((target / "DECISIONS.json").read_text(encoding="utf-8"))) == 1


def test_recording_preserves_decisions_another_command_wrote(bundle, workspace):
    target = workspace / "targets" / "Demo"
    (target / "DECISIONS.json").write_text(
        json.dumps([
            {
                "id": "build-existing",
                "type": "text",
                "severity": "low",
                "origin": "build",
                "status": "open",
                "title": "Pre-existing",
            }
        ]),
        encoding="utf-8",
    )
    resolve(verify(GOOD_ANSWER, bundle).amendments, target, mode="none")
    ids = [row["id"] for row in json.loads((target / "DECISIONS.json").read_text(encoding="utf-8"))]
    assert "build-existing" in ids
    assert len(ids) == 2


# ── the command ──────────────────────────────────────────────────────────────────────


def test_contradictory_flags_are_a_usage_error():
    with pytest.raises(UsageError):
        parse_mode(apply_all=True, no_apply=True)


@pytest.mark.parametrize(
    ("apply_all", "no_apply", "expected"),
    [(False, False, "confirm"), (True, False, "apply"), (False, True, "none")],
)
def test_flags_map_to_modes(apply_all, no_apply, expected):
    assert parse_mode(apply_all=apply_all, no_apply=no_apply) == expected


def _run(workspace, monkeypatch, **kwargs):
    import drydock.config as config
    import drydock.diagnose_command as command

    monkeypatch.setattr(config, "get_workspace", lambda: workspace)
    monkeypatch.setattr(config, "get_target_directory", lambda: workspace / "targets")
    monkeypatch.setattr(command, "_provider_unavailable", lambda llm=None: "")
    printed: list[str] = []
    kwargs.setdefault("runner", fake_runner())
    result = command.run(out=printed.append, **kwargs)
    return result, "\n".join(printed)


def test_run_prints_the_ladder_before_diagnosing(workspace, monkeypatch):
    result, output = _run(workspace, monkeypatch, target="Demo", mode="none")
    assert output.index("[FAIL] SCORE") < output.index("Diagnosing...")
    assert "Drydock failed at SCORE — programmatic acceptance failed" in output
    assert result.report_path is not None


def test_run_prints_the_findings_before_the_report_paths(workspace, monkeypatch):
    result, output = _run(workspace, monkeypatch, target="Demo", mode="none")
    assert "Governed-input defect: the criteria do not name the assertion they run." in output
    assert "`PLAN CREATED` failed and `PLAN REPAIRED` answered it." in output
    assert "1. Require every criterion to name its assertion (PLAN_COMPASS.md)" in output
    assert output.index("BREAK POINT") < output.index(f"Report: {result.report_path}")


def test_run_exits_one_while_a_live_failure_stands(workspace, monkeypatch):
    result, _ = _run(workspace, monkeypatch, target="Demo", mode="none")
    assert result.exit_code == 1


def test_an_unknown_target_names_the_command_that_creates_it(workspace, monkeypatch):
    result, output = _run(workspace, monkeypatch, target="Nope", mode="none")
    assert result.exit_code == 2
    assert "drydock init Nope" in output


def test_a_malformed_diagnosis_names_the_rerun(workspace, monkeypatch):
    result, output = _run(
        workspace, monkeypatch, target="Demo", mode="none", runner=fake_runner("nonsense")
    )
    assert result.exit_code == 1
    assert "Diagnosis incomplete" in output
    assert "RAW MODEL ANSWER\nnonsense" in output
    assert "Next: drydock diagnose Demo" in output
    assert result.report_path.is_file()


def test_a_provider_failure_still_names_a_next_step(workspace, monkeypatch):
    result, output = _run(
        workspace, monkeypatch, target="Demo", mode="none", runner=fake_runner(ok=False, text="")
    )
    assert result.exit_code == 1
    assert "Next: drydock diagnose Demo" in output


def test_a_missing_provider_is_reported_as_setup_not_diagnosis(workspace, monkeypatch):
    import drydock.config as config
    import drydock.diagnose_command as command

    monkeypatch.setattr(config, "get_workspace", lambda: workspace)
    monkeypatch.setattr(config, "get_target_directory", lambda: workspace / "targets")
    monkeypatch.setattr(command, "_provider_unavailable", lambda llm=None: "no agent installed")
    printed: list[str] = []
    result = command.run("Demo", out=printed.append)
    assert result.exit_code == 2
    assert "drydock config set llm-provider" in "\n".join(printed)


def test_no_apply_reports_where_the_amendments_went(workspace, monkeypatch):
    result, output = _run(workspace, monkeypatch, target="Demo", mode="none")
    assert "Recorded 1 declined amendment(s)" in output
    assert "drydock diagnose Demo --apply" in output


def test_confirm_mode_applies_what_the_operator_accepts(workspace, monkeypatch):
    result, output = _run(
        workspace, monkeypatch, target="Demo", mode="confirm", confirm=lambda _: True
    )
    assert "Applied 1 amendment(s) to PLAN_COMPASS.md" in output
    target = workspace / "targets" / "Demo"
    assert "must name the assertion" in (target / "PLAN_COMPASS.md").read_text(encoding="utf-8")
