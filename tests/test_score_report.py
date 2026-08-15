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


def test_verdict_passes_when_every_recorded_criterion_passed(workspace, target_dir):
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_PASS])
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "passed"
    assert result["acceptance"]["passed"] == 2


def test_verdict_fails_on_a_failed_criterion_even_when_every_command_exited_clean(
    workspace, target_dir
):
    """The product's verdict, not the harness's: clean exits do not earn a PASSED stamp."""
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_FAIL])
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z", return_code=0)])
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "failed"
    assert result["acceptance"]["failures"] == ("ac-2",)


def test_an_unverified_criterion_does_not_fail_the_run(workspace, target_dir):
    _soundings(target_dir, [VERIFIED_PASS, VERIFIED_UNVERIFIED])
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "passed"
    assert result["acceptance"]["unverified"] == 1


def test_a_target_with_no_acceptance_board_is_unproven_not_passed(workspace, target_dir):
    _history(workspace, [_record("init widget", stamp="20260101.090000.000Z")])
    result = collect_run("widget", workspace, target_dir)
    assert result["status"] == "unproven"
    assert result["acceptance"]["recorded"] is False


# ── publishing ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def published(workspace: Path, target_dir: Path) -> Path:
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
    _soundings(target_dir, [VERIFIED_PASS])
    _history(
        workspace,
        [
            _record(
                "build widget",
                stamp="20260101.090000.000Z",
                transcript="logs/20260101.090000.000Z_widget_build_codex.log",
            )
        ],
    )
    build_dir = workspace.parent / "build" / "widget"
    (build_dir / "src").mkdir(parents=True)
    (build_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (build_dir / "src" / "__pycache__").mkdir()
    (build_dir / "src" / "__pycache__" / "app.pyc").write_bytes(b"\x00")
    return write_report("widget", workspace, target_dir, build_dir)


def test_write_report_publishes_the_receipt_inside_the_build_tree(published, workspace):
    assert published.name == "index.html"
    assert published.parent.name == REPORT_DIRNAME
    assert published.parent.parent.name == "widget"


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


def test_write_report_writes_no_checksum_file(published):
    """Digests exist to let a third party verify a published kit; a build receipt is not that."""
    assert not (published.parent / "SHA256SUMS").exists()
    assert not (published.parent / ".gitignore").exists()


def test_the_page_links_nothing_it_did_not_carry(published):
    html = published.read_text(encoding="utf-8")
    root = published.parent
    hrefs = {
        href
        for href in re.findall(r'href="([^"]+)"', html)
        if not href.startswith(("http", "#", "data:"))
    }
    assert hrefs
    assert [href for href in hrefs if not (root / href).exists()] == []


def test_the_page_links_the_llm_activity_log(published):
    html = published.read_text(encoding="utf-8")
    assert "20260101.090000.000Z_widget_build_codex.llm.log.html" in html
    assert ">llm</a>" in html


def test_the_page_states_no_absolute_path_from_the_generating_machine(published, workspace):
    html = published.read_text(encoding="utf-8")
    record = (published.parent / "logs" / "llm.jsonl").read_text(encoding="utf-8")
    assert str(workspace) not in html
    assert str(workspace) not in record


def test_the_page_stamps_the_product_verdict_and_names_the_delivered_code(published):
    html = published.read_text(encoding="utf-8")
    assert "Build Receipt" in html
    assert "WIDGET: PASSED".title() in html or "widget: PASSED" in html
    assert "Accepted" in html
    assert "app.py" in html


def test_publishing_prunes_regenerable_caches_from_the_copy(published):
    assert not list(published.parent.rglob("__pycache__"))


def test_republishing_replaces_the_previous_receipt(published, workspace, target_dir):
    stale = published.parent / "logs" / "stale.log"
    stale.write_text("left over\n", encoding="utf-8")
    again = write_report("widget", workspace, target_dir, published.parent.parent)
    assert again == published
    assert not stale.exists()


def test_the_receipt_names_every_claim_the_record_does_not_settle(published):
    html = published.read_text(encoding="utf-8")
    assert "Acceptance criteria verified" in html
    assert "Build blocks verified" in html
    assert "Release score passed" in html
    assert "UNPROVEN" in html  # no release score was recorded for this run


def test_the_written_record_round_trips(published):
    result = json.loads((published.parent / "result.json").read_text(encoding="utf-8"))
    assert result["target"] == "widget"
    assert result["status"] == "passed"
    assert result["usage"]["calls"] == 1


def test_the_delivered_tree_excludes_the_report_that_sits_inside_it(published):
    """The receipt lives in the build tree it inventories and must not list itself as code."""
    html = published.read_text(encoding="utf-8")
    result = json.loads((published.parent / "result.json").read_text(encoding="utf-8"))
    assert f"{REPORT_DIRNAME}/logs" not in html
    assert "app.py" in html
    assert result["target"] == "widget"


def test_the_delivered_tree_omits_caches_without_deleting_them(published):
    """A report has no business removing files from the operator's build directory."""
    build_dir = published.parent.parent
    assert (build_dir / "src" / "__pycache__" / "app.pyc").is_file()
    assert "__pycache__" not in published.read_text(encoding="utf-8")
