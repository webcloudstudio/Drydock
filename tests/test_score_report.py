"""``drydock score report`` — run assembly from the journals, and the published receipt."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

from drydock.score_report import REPORT_DIRNAME, ReportError, collect_run, write_report
from drydock.standard_artifacts import (
    SOUNDINGS_HEADER,
    VERIFIED_FAIL,
    VERIFIED_PASS,
    VERIFIED_UNVERIFIED,
)


def _history(workspace: Path, records: list[dict]) -> None:
    logs = workspace / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "history.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def _record(
    command: str,
    *,
    target: str = "widget",
    stamp: str = "",
    time: str = "2026-01-01 09:00",
    return_code: int = 0,
    transcript: str = "",
    elapsed_ms: int | None = None,
) -> dict:
    record: dict = {
        "command": f"drydock {command}",
        "time": time,
        "target": target,
        "return_code": return_code,
        "argv": command.split(),
    }
    if stamp:
        record["stamp"] = stamp
    if transcript:
        record["transcript"] = transcript
    if elapsed_ms is not None:
        record["elapsed_ms"] = elapsed_ms
    return record


def _soundings(target_dir: Path, statuses: list[str]) -> None:
    lines = [
        "# Soundings",
        "",
        "| " + " | ".join(SOUNDINGS_HEADER) + " |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {status} | SPEC.md | ac-{index} | Criterion {index}. |  | 2026-01-01T09:00:00+00:00 |"
        for index, status in enumerate(statuses, start=1)
    ]
    (target_dir / "SOUNDINGS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "logs").mkdir(parents=True)
    (root / "targets" / "widget").mkdir(parents=True)
    return root


@pytest.fixture
def target_dir(workspace: Path) -> Path:
    return workspace / "targets" / "widget"


# ── run assembly ─────────────────────────────────────────────────────────────────────


def test_collect_run_reports_nothing_for_an_unrecorded_target(workspace, target_dir):
    _history(workspace, [_record("init other", target="other")])
    with pytest.raises(ReportError):
        collect_run("widget", workspace, target_dir)


def test_collect_run_window_opens_at_the_latest_init(workspace, target_dir):
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build widget", stamp="20260101.100000.000Z"),
            _record("init widget", stamp="20260102.090000.000Z"),
            _record("plan widget", stamp="20260102.100000.000Z"),
            _record("build widget", stamp="20260102.110000.000Z"),
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert result["run_id"] == "20260102.090000.000Z"
    assert [command["label"] for command in result["commands"]] == [
        "01-init",
        "02-plan",
        "03-build",
    ]


def test_collect_run_reports_a_target_that_predates_any_recorded_init(workspace, target_dir):
    """History older than the ``init`` journal entry is reported, never silently dropped."""
    _history(
        workspace,
        [
            _record("build widget", stamp="20260101.090000.000Z"),
            _record("build widget", stamp="20260101.100000.000Z"),
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert len(result["commands"]) == 2


def test_collect_run_reads_records_written_before_the_journal_was_widened(workspace, target_dir):
    """A record with only ``command`` and ``time`` still orders, labels, and reports."""
    _history(
        workspace,
        [
            {
                "command": "drydock init widget",
                "time": "2026-01-01 09:00",
                "target": "widget",
                "return_code": 0,
            },
            {
                "command": "drydock build widget",
                "time": "2026-01-01 10:00",
                "target": "widget",
                "return_code": 1,
            },
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert result["run_id"] == "20260101.090000.000Z"
    assert [command["returncode"] for command in result["commands"]] == [0, 1]
    assert result["commands"][0]["argv"] == ["drydock", "init", "widget"]


def test_collect_run_links_each_command_to_its_recorded_transcript(workspace, target_dir):
    (workspace / "logs" / "20260101.090000.000Z_widget_init.log").write_text("ok\n")
    _history(
        workspace,
        [
            _record(
                "init widget",
                stamp="20260101.090000.000Z",
                transcript="logs/20260101.090000.000Z_widget_init.log",
                elapsed_ms=1500,
            )
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    command = result["commands"][0]
    assert command["stdout_path"] == "logs/20260101.090000.000Z_widget_init.log"
    assert command["elapsed_ms"] == 1500


def test_collect_run_joins_a_legacy_record_to_its_transcript_by_minute_and_command(
    workspace, target_dir
):
    (workspace / "logs" / "20260101.090012.000Z_widget_init.log").write_text("ok\n")
    _history(
        workspace,
        [
            {
                "command": "drydock init widget",
                "time": "2026-01-01 09:00",
                "target": "widget",
                "return_code": 0,
            }
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert result["commands"][0]["stdout_path"] == "logs/20260101.090012.000Z_widget_init.log"


def test_collect_run_links_no_transcript_when_the_minute_is_ambiguous(workspace, target_dir):
    """Two transcripts for the same command in one minute identify neither."""
    (workspace / "logs" / "20260101.090012.000Z_widget_build.log").write_text("one\n")
    (workspace / "logs" / "20260101.090045.000Z_widget_build.log").write_text("two\n")
    _history(
        workspace,
        [
            {
                "command": "drydock build widget",
                "time": "2026-01-01 09:00",
                "target": "widget",
                "return_code": 0,
            }
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert result["commands"][0]["stdout_path"] == ""


def test_collect_run_keeps_a_neighbouring_targets_logs_out_of_the_receipt(workspace, target_dir):
    """``widget`` and ``widget_2`` share a filename prefix and must not share evidence."""
    (workspace / "targets" / "widget_2").mkdir()
    (workspace / "logs" / "20260101.090000.000Z_widget_init.log").write_text("mine\n")
    (workspace / "logs" / "20260101.093000.000Z_widget_2_build.log").write_text("theirs\n")
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    result = collect_run("widget", workspace, target_dir)
    build = write_report("widget", workspace, target_dir, target_dir.parent / "build")
    copied = {path.name for path in (build.parent / "logs").iterdir()}
    assert "20260101.090000.000Z_widget_init.log" in copied
    assert "20260101.093000.000Z_widget_2_build.log" not in copied
    assert result["target"] == "widget"


def test_collect_run_totals_usage_for_this_target_only(workspace, target_dir):
    records = [
        {
            "execution_id": "20260101.093000.000Z-aaaa",
            "job": {"target": "widget", "llm": "codex", "model": "m", "command_name": "build"},
            "result": {
                "returncode": 0,
                "stats": {
                    "input_tokens": 100,
                    "cached_input_tokens": 40,
                    "output_tokens": 7,
                    "elapsed_ms": 2000,
                },
            },
        },
        {
            "execution_id": "20260101.094000.000Z-bbbb",
            "job": {"target": "other", "llm": "codex", "model": "m", "command_name": "build"},
            "result": {
                "returncode": 0,
                "stats": {
                    "input_tokens": 900,
                    "cached_input_tokens": 0,
                    "output_tokens": 90,
                    "elapsed_ms": 5000,
                },
            },
        },
    ]
    (workspace / "logs" / "llm.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    usage = collect_run("widget", workspace, target_dir)["usage"]
    assert usage["calls"] == 1
    assert usage["output_tokens"] == 7
    assert usage["cached_input_tokens"] == 40
    assert usage["llm_elapsed_ms"] == 2000


def test_collect_run_records_the_score_exit_code_whichever_operand_order_was_used(
    workspace, target_dir
):
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("score widget release", stamp="20260101.100000.000Z", return_code=1),
            _record("score ac widget", stamp="20260101.110000.000Z", return_code=0),
        ],
    )
    assert collect_run("widget", workspace, target_dir)["score_exit_codes"] == {
        "release": 1,
        "ac": 0,
    }


# ── verdict ──────────────────────────────────────────────────────────────────────────


def _ladder(target_dir: Path, *labels: str) -> None:
    """Drive the Target's state machine through *labels* in order."""
    from drydock.project_status import record_status

    for label in labels:
        record_status(target_dir, label, passed=True, command=f"drydock {label.lower()} widget")


def _built(workspace: Path, target_dir: Path | None = None) -> None:
    """A run that reached a recorded build score, in both the journal and the machine."""
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build widget", stamp="20260101.091000.000Z"),
            _record("score build widget", stamp="20260101.092000.000Z"),
        ],
    )
    if target_dir is not None:
        _ladder(target_dir, "INITIALIZED", "BUILT", "SCORE BUILD")


def test_the_ladder_is_the_states_the_machine_holds(workspace, target_dir):
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_PASS])
    _built(workspace, target_dir)
    result = collect_run("widget", workspace, target_dir)
    assert result["acceptance"]["passed"] == 2
    assert [step["label"] for step in result["workflow"]] == [
        "INITIALIZED",
        "BUILT",
        "SCORE BUILD",
    ]
    assert result["state"]["label"] == "SCORE BUILD"
    assert result["status"] == "incomplete"  # scored, but not yet published


def test_publishing_a_clean_scored_run_earns_finalized(workspace, target_dir, build_dir):
    from drydock.project_status import current_state

    _built(workspace, target_dir)
    build_dir.mkdir(parents=True)
    write_report("widget", workspace, target_dir, build_dir)
    assert current_state(target_dir).label == "FINALIZED"
    assert collect_run("widget", workspace, target_dir)["status"] == "passed"


def test_verdict_fails_on_a_failed_criterion_even_when_every_command_exited_clean(
    workspace, target_dir, build_dir
):
    """The product's verdict, not the harness's: clean exits do not earn a PASSED stamp."""
    from drydock.project_status import current_state

    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_FAIL])
    _built(workspace, target_dir)
    _ladder(target_dir, "LLM ACCEPTANCE CHECKS OK", "SCORE BUILD")
    build_dir.mkdir(parents=True)
    write_report("widget", workspace, target_dir, build_dir)

    # The board on disk contradicts the recorded state, so the machine is corrected — which
    # voids the scores above it and leaves the run unpublishable.
    state = current_state(target_dir)
    assert state.label == "LLM ACCEPTANCE CHECKS OK"
    assert state.passed is False
    assert state.detail == "1 criteria failed"
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "failed"
    assert result["acceptance"]["failures"] == ("ac-2",)
    assert "FINALIZED" not in [step["label"] for step in result["workflow"]]


def test_an_unverified_criterion_does_not_fail_the_run(workspace, target_dir, build_dir):
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_UNVERIFIED])
    _built(workspace, target_dir)
    build_dir.mkdir(parents=True)
    write_report("widget", workspace, target_dir, build_dir)
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "passed"
    assert result["acceptance"]["unverified"] == 1


def test_a_built_and_scored_target_passes_without_an_acceptance_board(
    workspace, target_dir, build_dir
):
    """The verdict is the state the machine holds, not the presence of one artifact."""
    _built(workspace, target_dir)
    build_dir.mkdir(parents=True)
    write_report("widget", workspace, target_dir, build_dir)
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "passed"
    assert result["acceptance"]["recorded"] is False


def test_an_unscored_run_is_incomplete_rather_than_failed(workspace, target_dir, build_dir):
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    _ladder(target_dir, "INITIALIZED", "ANALYZED")
    build_dir.mkdir(parents=True)
    write_report("widget", workspace, target_dir, build_dir)
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "incomplete"
    assert [step["label"] for step in result["workflow"]] == ["INITIALIZED", "ANALYZED"]


def test_a_recorded_failure_fails_the_state_and_voids_the_scores(workspace, target_dir):
    """A build can exit 0 with stalled blocks; the command that knew that recorded it."""
    from drydock.project_status import record_status

    _built(workspace, target_dir)
    record_status(target_dir, "BUILT", passed=False, detail="2 block(s) stalled")
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "failed"
    assert [step["label"] for step in result["workflow"]] == ["INITIALIZED", "BUILT"]
    assert result["state"]["detail"] == "2 block(s) stalled"


def test_a_reattempted_state_reports_how_many_attempts_it_took(workspace, target_dir):
    from drydock.project_status import record_status

    _built(workspace, target_dir)
    record_status(target_dir, "BUILT", passed=False, detail="1 step(s) failed")
    record_status(target_dir, "BUILT", passed=True)
    result = collect_run("widget", workspace, target_dir)
    built = next(step for step in result["workflow"] if step["label"] == "BUILT")
    assert built["passed"] is True
    assert built["attempts"] == 3


# ── publishing ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def build_dir(workspace: Path) -> Path:
    return workspace.parent / "build" / "widget"


@pytest.fixture
def published(workspace: Path, target_dir: Path, build_dir: Path) -> Path:
    """A published receipt for a Target with one command, evidence, and delivered code."""
    (workspace / "logs" / "20260101.090000.000Z_widget_build_codex.log").write_text("built\n")
    (workspace / "logs" / "20260101.090000.000Z_widget_build_codex.prompt.md").write_text("# ask\n")
    (workspace / "logs" / "20260101.090000.000Z_widget_build_codex.raw.jsonl").write_text(
        '{"type":"wire"}\n', encoding="utf-8"
    )
    llm_log = workspace / "logs" / "20260101.090000.000Z_widget_build_codex.llm.log"
    llm_log.write_text("tokens: 10\n")
    (workspace / "logs" / "llm.jsonl").write_text(
        json.dumps({
            "execution_id": "20260101.090000.000Z-aaaa",
            "job": {
                "target": "widget",
                "llm": "codex",
                "model": "m",
                "command_name": "build",
                "working_directory": str(workspace),
            },
            "artifacts": {
                "prompt": str(
                    workspace / "logs" / "20260101.090000.000Z_widget_build_codex.prompt.md"
                ),
                "output": str(workspace / "logs" / "gone.output.txt"),
                "llm_log": str(llm_log),
            },
            "result": {"returncode": 0, "stats": {"input_tokens": 10, "output_tokens": 2}},
        })
        + "\n",
        encoding="utf-8",
    )
    (target_dir / "MANIFEST.md").write_text("# Manifest\n", encoding="utf-8")
    (target_dir / "blueprint" / "sources").mkdir(parents=True)
    (target_dir / "blueprint" / "FEATURE-Widget.md").write_text("# Widget\n", encoding="utf-8")
    (target_dir / "blueprint" / "sources" / "spec.md").write_text("# Imported\n", encoding="utf-8")
    (target_dir / "QuarterDeck").mkdir(parents=True)
    (target_dir / "QuarterDeck" / "commanders_chair.html").write_text(
        "<h1>Chair</h1>\n", encoding="utf-8"
    )
    (target_dir / "evidence").mkdir(parents=True)
    (target_dir / "evidence" / "block-1.md").write_text("# Block 1\n", encoding="utf-8")
    (target_dir / ".git").mkdir()
    (target_dir / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    _soundings(target_dir, [VERIFIED_PASS])
    _history(
        workspace,
        [
            _record(
                "build widget",
                stamp="20260101.090000.000Z",
                transcript="logs/20260101.090000.000Z_widget_build_codex.log",
            ),
            _record("score build widget", stamp="20260101.091000.000Z"),
        ],
    )
    _ladder(target_dir, "BUILT", "SCORE BUILD")
    (build_dir / "src").mkdir(parents=True)
    (build_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (build_dir / "src" / "__pycache__").mkdir()
    (build_dir / "src" / "__pycache__" / "app.pyc").write_bytes(b"\x00")
    (build_dir / ".git").mkdir()
    (build_dir / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return write_report("widget", workspace, target_dir, build_dir)


def test_write_report_publishes_the_receipt_in_the_target_workspace(published, target_dir):
    """The receipt describes the delivery; it is not part of it, and never lands in the build."""
    assert published.name == "index.html"
    assert published.parent == target_dir / REPORT_DIRNAME
    assert not (published.parent.parent / "build").exists()


def test_write_report_carries_the_evidence_the_page_links(published):
    root = published.parent
    assert (root / "result.json").is_file()
    assert (root / "logs" / "20260101.090000.000Z_widget_build_codex.log").is_file()
    assert (root / "logs" / "20260101.090000.000Z_widget_build_codex.llm.log").is_file()
    assert (root / "logs" / "history.jsonl").is_file()
    assert (root / "logs" / "llm.jsonl").is_file()
    assert (root / "workspace" / "MANIFEST.md").is_file()
    assert (root / "workspace" / "SOUNDINGS.md").is_file()


def test_write_report_does_not_carry_the_delivered_code(published):
    """The receipt is a hosted page kept in version control; the code is already versioned."""
    assert not (published.parent / "delivered").exists()


def test_write_report_carries_the_blueprint_the_manifest_cites(published):
    """Every block names the specification it implements; a receipt carries what it cites."""
    root = published.parent / "workspace" / "blueprint"
    assert (root / "FEATURE-Widget.md").is_file()
    assert (root / "sources" / "spec.md").is_file()


def test_write_report_carries_the_quarterdeck_and_the_build_evidence(published):
    """The two Target subtrees the page reports over travel with it; nothing else does."""
    root = published.parent / "workspace"
    assert (root / "QuarterDeck" / "commanders_chair.html").is_file()
    assert (root / "evidence" / "block-1.md").is_file()


def test_write_report_carries_neither_the_wire_transcript_nor_the_assembled_prompt(published):
    """Between them they are almost everything a run writes, and neither is the audit.

    A prompt injects the specification and Blueprint on every call, so a build repeats
    substantially the same payload once per block. The transcript and the output stay.
    """
    logs = published.parent / "logs"
    assert not list(logs.glob("*.raw.jsonl"))
    assert not list(logs.glob("*.prompt.md"))
    assert (logs / "20260101.090000.000Z_widget_build_codex.log").is_file()


def test_write_report_copies_no_dot_directory_from_the_target(published):
    """``.git`` is excluded from the inventory, so a copied one is unhashed dead weight."""
    assert not (published.parent / "workspace" / ".git").exists()


def test_the_receipt_does_not_carry_a_copy_of_itself(published):
    assert not (published.parent / "workspace" / REPORT_DIRNAME).exists()


# ── the plan tab ─────────────────────────────────────────────────────────────────────

_RECEIPT_PLAN = """# MANIFEST: Widget
state: approved

## feature 1: Core
id: core

## story 2: Foundation
id: foundation
parent: core
state: closed/verified

## story 3: Service
id: service
parent: core
state: closed/failed

## story 4: Reports
id: reports
parent: core
state: closed/implemented
"""

_RECEIPT_SCORECARD = """# Release Scorecard: Widget

- Verdict: PASSED
- Code identity: -

## Project acceptance

| ID | Type | Criterion | Verdict | Observed |
|---|---|---|---|---|
| AC-1 | technical | Widget answers | MET | pytest returned 0 |
| AC-2 | technical | Widget retries | NOT MET | pytest returned 1 |

## Failures

AC-2: Widget retries
"""


@pytest.fixture
def planned(workspace: Path, target_dir: Path, build_dir: Path) -> str:
    """A published receipt whose Target carries a real Manifest, scorecard, and Compass."""
    (target_dir / "MANIFEST.md").write_text(_RECEIPT_PLAN, encoding="utf-8")
    (target_dir / "SCORECARD.md").write_text(_RECEIPT_SCORECARD, encoding="utf-8")
    (target_dir / "COMPASS.md").write_text("# Compass\n\nHold the **line**.\n", encoding="utf-8")
    _soundings(target_dir, [VERIFIED_PASS])
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    build_dir.mkdir(parents=True)
    return write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")


def _panel(page: str, slug: str) -> str:
    start = page.index(f'id="panel-{slug}"')
    return page[start : page.index("</section>", start)]


def test_the_manifest_is_rendered_as_a_board_not_listed_as_a_file(planned):
    """The Manifest is the one plan document nobody reads as text; the Chair's board is why."""
    panel = _panel(planned, "plan-manifest")
    assert '<div class="story-feature">Core</div>' in panel
    assert '<span class="story-name">Foundation</span>' in panel
    assert '<span class="badge badge-verified">done</span>' in panel
    assert '<span class="badge badge-failed">failed</span>' in panel
    assert '<div class="stat-label">Blocks</div>' in panel


def test_a_block_that_closed_without_verification_reads_as_built_not_pending(planned):
    """``closed/implemented`` had no badge, so a fully built plan read as all-pending."""
    panel = _panel(planned, "plan-manifest")
    assert '<span class="badge badge-review">built</span>' in panel
    assert "closed/implemented" not in panel


def test_the_manifest_card_row_counts_blocks_rather_than_a_verified_percentage(planned):
    """A Target verified by criteria, not block states, would otherwise head its plan at 0%."""
    panel = _panel(planned, "plan-manifest")
    assert '<div class="stat-value">3</div><div class="stat-label">Blocks</div>' in panel
    assert '<div class="stat-value">1</div><div class="stat-label">Built</div>' in panel
    assert "%</div>" not in panel


def test_the_scorecard_is_rendered_as_a_verdict_board(planned):
    """The board reads the table ``score.py`` writes today, columns found by name."""
    panel = _panel(planned, "plan-scorecard")
    assert '<div class="question-status">PASSED</div>' in panel
    assert "AC-1 — Widget answers" in panel
    assert '<span class="badge badge-verified">✓ MET</span>' in panel
    assert '<span class="badge badge-failed">✗ NOT MET</span>' in panel


def test_a_markdown_plan_document_gets_its_own_rendered_tab(planned):
    panel = _panel(planned, "plan-compass")
    assert "<strong>line</strong>" in panel
    assert 'class="doc"' in panel


def test_a_plan_document_the_target_never_wrote_gets_no_tab(planned):
    assert 'id="panel-plan-build-compass"' not in planned


def test_the_plan_tab_still_offers_the_hashed_workspace_inventory(planned):
    """Every carried file stays reachable and checkable, rendered tabs or not."""
    assert 'id="panel-plan-workspace"' in planned


def test_the_command_row_names_the_model_instead_of_linking_its_log(published):
    """A transcript and an error belong beside a command; a log file index does not."""
    page = published.read_text(encoding="utf-8")
    row = page[page.index("<th>#</th>") : page.index("</table>", page.index("<th>#</th>"))]
    assert "<th>llm</th>" not in row
    assert "codex/m" in row
    assert "transcript" in row


def test_a_command_that_called_no_model_names_none(workspace, target_dir, build_dir):
    _soundings(target_dir, [VERIFIED_PASS])
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    build_dir.mkdir(parents=True)
    index = write_report("widget", workspace, target_dir, build_dir)
    page = index.read_text(encoding="utf-8")
    row = page[page.index("<th>#</th>") : page.index("</table>", page.index("<th>#</th>"))]
    assert ".llm.log" not in row
    assert "codex/" not in row


def test_a_rerun_command_is_kept_and_labelled(workspace, target_dir, build_dir):
    """A command that failed and was run again shows both attempts, each with its own result."""
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build widget", stamp="20260101.091000.000Z", return_code=1),
            _record("build widget", stamp="20260101.092000.000Z"),
            _record("score build widget", stamp="20260101.093000.000Z"),
        ],
    )
    build_dir.mkdir(parents=True)
    page = write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")
    assert "rerun 1 of 2" in page
    assert "rerun 2 of 2" in page
    assert (
        '<span class="tag pass" title="exit 1; later rerun exited 0"><span '
        'class="failure-history">FAIL<br>RERUN</span></span>'
    ) in page


def test_an_unrepaired_command_failure_shows_its_return_code_in_the_receipt(
    workspace, target_dir, build_dir
):
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build widget", stamp="20260101.091000.000Z", return_code=1),
        ],
    )
    build_dir.mkdir(parents=True)

    page = write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")

    assert '<span class="tag fail" title="exit 1">FAIL<br>rc=1</span>' in page


def test_a_failure_a_later_rerun_cleared_is_not_reported_as_an_error(
    workspace, target_dir, build_dir
):
    """The run's outcome is the last attempt's, so a cleared failure opens no Error tab."""
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record(
                "score release widget",
                stamp="20260101.091000.000Z",
                return_code=1,
                transcript="the release score refused",
            ),
            _record("score release widget", stamp="20260101.092000.000Z"),
        ],
    )
    build_dir.mkdir(parents=True)
    page = write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")
    assert "Recorded failure output" not in page
    assert 'data-panel="error"' not in page
    assert "was rerun clean" in page


def test_a_rerun_that_changed_model_still_clears_the_earlier_failure(
    workspace, target_dir, build_dir
):
    """The same step run again is the same command, whatever provider or model drove it."""
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record(
                "build widget --llm-provider codex --model m",
                stamp="20260101.091000.000Z",
                return_code=1,
            ),
            _record(
                "build widget --llm-provider claude --model haiku", stamp="20260101.092000.000Z"
            ),
        ],
    )
    build_dir.mkdir(parents=True)
    page = write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")
    assert 'data-panel="error"' not in page


def test_a_failure_no_later_run_cleared_is_still_reported_as_an_error(
    workspace, target_dir, build_dir
):
    """A rerun clears only the command it repeats; an uncleared failure keeps its Error tab."""
    log = workspace / "logs" / "20260101.091000.000Z_widget_score.log"
    log.write_text("the release score refused\n", encoding="utf-8")
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record(
                "score release widget",
                stamp="20260101.091000.000Z",
                return_code=1,
                transcript=f"logs/{log.name}",
            ),
            _record("score ac widget", stamp="20260101.092000.000Z"),
        ],
    )
    build_dir.mkdir(parents=True)
    page = write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")
    assert 'data-panel="error"' in page
    assert "the release score refused" in page
    assert "with no later clean rerun" in page


def test_a_status_query_that_reports_unfinished_work_is_not_an_error(
    workspace, target_dir, build_dir
):
    """``drydock build status`` returns the Target's state; nonzero is the answer, not a fault."""
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build status widget", stamp="20260101.091000.000Z", return_code=1),
        ],
    )
    build_dir.mkdir(parents=True)
    page = write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")
    assert 'data-panel="error"' not in page


def test_write_report_seals_the_published_receipt(published):
    """The receipt is a published artifact in its own right, so it is hashed like a UAT kit."""
    sums = published.parent / "SHA256SUMS"
    assert sums.is_file()
    lines = sums.read_text(encoding="utf-8").splitlines()
    assert any(line.endswith("workspace/MANIFEST.md") for line in lines)
    assert not any("index.html" in line for line in lines)
    for line in lines:
        digest, _, relative = line.partition("  ")
        assert (published.parent / relative).is_file()
        assert len(digest) == 64


def test_the_receipt_hashes_nothing_from_a_dot_directory(published):
    """A repository's own bookkeeping is not build evidence and bloats the seal."""
    sums = (published.parent / "SHA256SUMS").read_text(encoding="utf-8")
    assert ".git/" not in sums
    assert ".git" not in published.read_text(encoding="utf-8")


def test_the_page_links_nothing_it_did_not_carry(published):
    page = published.read_text(encoding="utf-8")
    root = published.parent
    hrefs = {
        href
        for href in re.findall(r'href="([^"]+)"', page)
        if not href.startswith(("http", "#", "data:"))
    }
    assert hrefs
    assert [href for href in hrefs if not (root / href).exists()] == []


def test_the_page_links_the_llm_activity_log(published):
    page = published.read_text(encoding="utf-8")
    assert "20260101.090000.000Z_widget_build_codex.llm.log.html" in page
    assert ">llm</a>" in page


def test_the_page_states_no_absolute_path_from_the_generating_machine(published, workspace):
    page = published.read_text(encoding="utf-8")
    record = (published.parent / "logs" / "llm.jsonl").read_text(encoding="utf-8")
    assert str(workspace) not in page
    assert str(workspace) not in record


def test_the_page_stamps_the_product_verdict_and_names_the_delivered_code(published, build_dir):
    """The code is named so a reader can find it, and not copied so the page stays hostable."""
    page = published.read_text(encoding="utf-8")
    assert "Build Receipt" in page
    assert "widget: PASSED" in page
    assert "Accepted" in page
    assert html.escape(str(build_dir)) in page


def test_the_page_ladders_every_legitimate_state(published):
    page = published.read_text(encoding="utf-8")
    assert "Workflow" in page
    from drydock.project_status import LABEL_LADDER

    for label in LABEL_LADDER:
        assert label in page
    assert '<span class="tag raw">NOT ESTABLISHED</span>' in page
    assert "This lifecycle gate has not run." in page


def test_an_unfinished_run_is_stamped_in_progress_not_rejected(workspace, target_dir, build_dir):
    _history(workspace, [_record("analyze widget", stamp="20260101.090000.000Z")])
    build_dir.mkdir(parents=True)
    page = write_report("widget", workspace, target_dir, build_dir).read_text(encoding="utf-8")
    assert "widget: INCOMPLETE" in page
    assert "In progress" in page
    assert 'class="stamp warn"' in page


def test_the_page_carries_two_tiers_of_tabs_that_do_not_collide(published):
    """Each strip switches its own panels, so the outer row cannot blank an inner one."""
    page = published.read_text(encoding="utf-8")
    assert 'data-tabgroup="receipt"' in page
    assert 'data-tabgroup="build"' in page
    for label in ("OVERVIEW", "BUILD", "PLAN"):
        assert f">{label}</button>" in page
    for gone in ("OUTPUT", "INPUT"):
        assert f">{gone}</button>" not in page


def test_publishing_prunes_regenerable_caches_from_the_copy(published):
    assert not list(published.parent.rglob("__pycache__"))


def test_republishing_replaces_the_previous_receipt(published, workspace, target_dir, build_dir):
    stale = published.parent / "logs" / "stale.log"
    stale.write_text("left over\n", encoding="utf-8")
    again = write_report("widget", workspace, target_dir, build_dir)
    assert again == published
    assert not stale.exists()


def test_the_receipt_names_every_claim_the_record_does_not_settle(published):
    page = published.read_text(encoding="utf-8")
    assert "Acceptance criteria verified" in page
    assert "Build blocks verified" in page
    assert "Release score passed" in page


def test_the_written_record_round_trips(published):
    result = json.loads((published.parent / "result.json").read_text(encoding="utf-8"))
    assert result["target"] == "widget"
    assert result["status"] == "passed"
    assert result["usage"]["calls"] == 1


def test_publishing_touches_nothing_in_the_build_directory(published, build_dir):
    """A report has no business removing files from the operator's build directory."""
    assert (build_dir / "src" / "app.py").is_file()
    assert (build_dir / "src" / "__pycache__" / "app.pyc").is_file()
    assert "__pycache__" not in published.read_text(encoding="utf-8")


def test_the_command_journal_never_puts_a_state_on_the_ladder(workspace, target_dir):
    """Exit codes are not states. Only a command that recorded one establishes one.

    A usage error, a read-only ``build status``, and a clean ``score build`` all appear in the
    journal; none of them may invent a rung the machine does not hold.
    """
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build status widget", stamp="20260101.091000.000Z", return_code=1),
            _record("score build widget", stamp="20260101.092000.000Z"),
            _record("score widget", stamp="20260101.093000.000Z", return_code=2),
        ],
    )
    _ladder(target_dir, "INITIALIZED")
    result = collect_run("widget", workspace, target_dir)
    assert [step["label"] for step in result["workflow"]] == ["INITIALIZED"]
    assert result["state"]["label"] == "INITIALIZED"


def test_a_rebuild_voids_the_finalized_state_a_previous_publication_earned(
    workspace, target_dir, build_dir
):
    """Reporting twice is not an achievement; FINALIZED cannot outlive the build under it."""
    from drydock.project_status import current_state, record_status

    _built(workspace, target_dir)
    build_dir.mkdir(parents=True)
    write_report("widget", workspace, target_dir, build_dir)
    assert current_state(target_dir).label == "FINALIZED"

    record_status(target_dir, "BUILT", passed=True, command="drydock build widget")

    assert current_state(target_dir).label == "BUILT"
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "incomplete"
    assert "FINALIZED" not in [step["label"] for step in result["workflow"]]
