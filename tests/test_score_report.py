"""``drydock score report`` — run assembly from the journals, and the published receipt."""

from __future__ import annotations

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


def _built(workspace: Path) -> None:
    """A history that ran the lifecycle through to a recorded build score."""
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build widget", stamp="20260101.091000.000Z"),
            _record("score build widget", stamp="20260101.092000.000Z"),
        ],
    )


def test_verdict_passes_when_the_recorded_lifecycle_finished(workspace, target_dir):
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_PASS])
    _built(workspace)
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "passed"
    assert result["acceptance"]["passed"] == 2
    assert [step["label"] for step in result["workflow"]] == [
        "INITIALIZED",
        "BUILT",
        "SCORE BUILD",
        "FINALIZED",
    ]


def test_verdict_fails_on_a_failed_criterion_even_when_every_command_exited_clean(
    workspace, target_dir
):
    """The product's verdict, not the harness's: clean exits do not earn a PASSED stamp."""
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_FAIL])
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("score ac widget", stamp="20260101.091000.000Z"),
            _record("score build widget", stamp="20260101.092000.000Z"),
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "failed"
    assert result["acceptance"]["failures"] == ("ac-2",)
    assert "FINALIZED" not in [step["label"] for step in result["workflow"]]


def test_an_unverified_criterion_does_not_fail_the_run(workspace, target_dir):
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_UNVERIFIED])
    _built(workspace)
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "passed"
    assert result["acceptance"]["unverified"] == 1


def test_a_built_and_scored_target_passes_without_an_acceptance_board(workspace, target_dir):
    """The verdict is the lifecycle the Target recorded, not the presence of one artifact."""
    _built(workspace)
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "passed"
    assert result["acceptance"]["recorded"] is False


def test_an_unscored_run_is_incomplete_rather_than_failed(workspace, target_dir):
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("analyze widget", stamp="20260101.091000.000Z"),
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "incomplete"
    assert [step["label"] for step in result["workflow"]] == ["INITIALIZED", "ANALYZED"]


def test_a_failed_command_fails_the_state_it_was_establishing(workspace, target_dir):
    _history(
        workspace,
        [
            _record("init widget", stamp="20260101.090000.000Z"),
            _record("build widget", stamp="20260101.091000.000Z", return_code=1),
            _record("score build widget", stamp="20260101.092000.000Z"),
        ],
    )
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "failed"
    built = next(step for step in result["workflow"] if step["label"] == "BUILT")
    assert built["passed"] is False
    assert built["detail"] == "exited 1"


def test_the_recorded_status_file_outranks_the_exit_code(workspace, target_dir):
    """A build can exit 0 with stalled blocks; the command that knew that recorded it."""
    from drydock.project_status import record_status

    _built(workspace)
    record_status(target_dir, "BUILT", passed=False, detail="2 block(s) stalled")
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "failed"
    built = next(step for step in result["workflow"] if step["label"] == "BUILT")
    assert built["detail"] == "2 block(s) stalled"


def test_a_reattempted_state_reports_how_many_attempts_it_took(workspace, target_dir):
    from drydock.project_status import record_status

    _built(workspace)
    record_status(target_dir, "BUILT", passed=False, detail="1 step(s) failed")
    record_status(target_dir, "BUILT", passed=True)
    result = collect_run("widget", workspace, target_dir)
    built = next(step for step in result["workflow"] if step["label"] == "BUILT")
    assert built["passed"] is True
    assert built["attempts"] == 2


# ── publishing ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def build_dir(workspace: Path) -> Path:
    return workspace.parent / "build" / "widget"


@pytest.fixture
def published(workspace: Path, target_dir: Path, build_dir: Path) -> Path:
    """A published receipt for a Target with one command, evidence, and delivered code."""
    (workspace / "logs" / "20260101.090000.000Z_widget_build_codex.log").write_text("built\n")
    (workspace / "logs" / "20260101.090000.000Z_widget_build_codex.prompt.md").write_text("# ask\n")
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
    assert (root / "logs" / "20260101.090000.000Z_widget_build_codex.prompt.md").is_file()
    assert (root / "logs" / "20260101.090000.000Z_widget_build_codex.llm.log").is_file()
    assert (root / "logs" / "history.jsonl").is_file()
    assert (root / "logs" / "llm.jsonl").is_file()
    assert (root / "workspace" / "MANIFEST.md").is_file()
    assert (root / "workspace" / "SOUNDINGS.md").is_file()


def test_write_report_carries_the_delivered_code_it_documents(published):
    """The receipt sits outside the build tree, so the delivered code travels with it."""
    assert (published.parent / "delivered" / "src" / "app.py").is_file()


def test_the_receipt_does_not_carry_a_copy_of_itself(published):
    assert not (published.parent / "workspace" / REPORT_DIRNAME).exists()


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
    assert "FAIL 1" in page


def test_write_report_seals_the_published_receipt(published):
    """The receipt is a published artifact in its own right, so it is hashed like a UAT kit."""
    sums = published.parent / "SHA256SUMS"
    assert sums.is_file()
    lines = sums.read_text(encoding="utf-8").splitlines()
    assert any(line.endswith("delivered/src/app.py") for line in lines)
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


def test_the_page_stamps_the_product_verdict_and_names_the_delivered_code(published):
    page = published.read_text(encoding="utf-8")
    assert "Build Receipt" in page
    assert "widget: PASSED" in page
    assert "Accepted" in page
    assert "app.py" in page


def test_the_page_ladders_the_states_the_target_recorded(published):
    page = published.read_text(encoding="utf-8")
    assert "Workflow" in page
    assert "SCORE BUILD" in page
    assert "FINALIZED" in page
    assert "INITIALIZED" not in page  # never attempted in this run


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
    for label in ("OVERVIEW", "BUILD", "PLAN", "OUTPUT", "INPUT"):
        assert f">{label}</button>" in page


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


def test_the_delivered_tree_omits_caches_without_deleting_them(published, build_dir):
    """A report has no business removing files from the operator's build directory."""
    assert (build_dir / "src" / "__pycache__" / "app.pyc").is_file()
    assert "__pycache__" not in published.read_text(encoding="utf-8")
