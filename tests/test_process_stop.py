"""Fatal provider failures halt the Target through ``STOP_NOW.md`` (ReadingList 20261022.205653)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import drydock.llm
from drydock.cli import _build_parser, _declare_process_stop, _process_stop_gate
from drydock.errors import LlmError
from drydock.llm import FatalStop, fatal_stop, fatal_stop_reason, run_prompt
from drydock.stop_condition import read_stop, write_stop
from tests.test_cli import APPROVED_PLAN_STATUS, run_cli
from tests.test_llm import FakePopen

USAGE_LIMIT = "You've hit your usage limit. Upgrade to Pro or try again at 9:31 PM."


@pytest.mark.parametrize(
    ("error", "provider_error", "timed_out", "kind"),
    [
        (USAGE_LIMIT, f"provider rate limit: {USAGE_LIMIT}", False, "provider rate limit"),
        ("OAuth session expired", None, False, "provider authentication required"),
        ("execution timed out", None, True, "provider timeout"),
        ("", "provider error 503: Service Unavailable", False, "provider outage"),
        ("", "provider error: Overloaded", False, "provider outage"),
        ("", "provider error 400: invalid request", False, None),
        ("response was not valid JSON", None, False, None),
    ],
)
def test_fatal_stop_reason_names_only_failures_another_call_cannot_fix(
    error, provider_error, timed_out, kind
):
    assert fatal_stop_reason(error, provider_error, timed_out=timed_out) == kind


def _usage_limited(monkeypatch) -> list[object]:
    raw = json.dumps({"type": "turn.failed", "error": {"message": USAGE_LIMIT}}) + "\n"
    spawned: list[object] = []

    def popen(command, **kwargs):
        spawned.append(command)
        return FakePopen(command, stdout_text=raw, returncode=1, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return spawned


def test_a_usage_limit_ends_the_process_provider_work(tmp_path, monkeypatch):
    """A retry loop above run_prompt must not resubmit into the same limit."""
    spawned = _usage_limited(monkeypatch)

    first = run_prompt("Work", tmp_path, llm="codex", command_name="build")
    with pytest.raises(LlmError, match="provider rate limit"):
        run_prompt("Work again", tmp_path, llm="codex", command_name="build")

    assert not first.ok
    assert len(spawned) == 1
    stop = fatal_stop()
    assert stop is not None and stop.kind == "provider rate limit"
    assert USAGE_LIMIT in stop.message and stop.execution_id == first.execution_id


def _target(tmp_target_root, monkeypatch):
    from drydock.init_specification import init_specification

    target_dir = tmp_target_root / "TestTarget"
    init_specification("TestTarget", target_dir)
    (target_dir / "MANIFEST.md").write_text(APPROVED_PLAN_STATUS, encoding="utf-8")
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
    return target_dir


def test_a_fatal_stop_is_written_with_its_recovery(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    drydock.llm._record_fatal_stop(
        FatalStop("provider rate limit", USAGE_LIMIT, "codex", "build", "exec-1")
    )
    args = _build_parser().parse_args(["build", "TestTarget"])

    assert _declare_process_stop(args, ["build", "TestTarget"])

    stop = read_stop(target_dir)
    assert stop is not None and stop.stage == "build"
    assert stop.reason.startswith("provider rate limit: ") and "9:31 PM" in stop.reason
    assert "exec-1" in stop.reason
    assert "Wait for the provider limit to reset" in stop.recovery
    assert "Then rerun: drydock build TestTarget" in stop.recovery


def test_ready_reports_a_stop_and_ends_the_build_loop(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    assert run_cli("status", "TestTarget", "--ready")[0] == 0
    write_stop(target_dir, "build", f"provider rate limit: {USAGE_LIMIT}")

    rc, out, err = run_cli("status", "TestTarget", "--ready")

    assert rc == 1
    assert out.startswith("STOPPED: TestTarget  (build: provider rate limit")
    assert err == ""


def test_status_dashboard_ends_with_the_stop_and_its_recovery(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_stop(target_dir, "build", "provider timeout: execution timed out", "Check the network.")

    rc, out, _ = run_cli("status", "TestTarget")

    assert rc == 0
    tail = out[out.index("STOPPED: TestTarget") :]
    assert "build" in tail and "provider timeout" in tail and "Check the network." in tail


def test_an_unattended_llm_command_refuses_while_stopped(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_stop(target_dir, "build", f"provider rate limit: {USAGE_LIMIT}", "Wait for the reset.")
    monkeypatch.setattr(
        drydock.llm, "run_prompt", lambda *a, **k: pytest.fail("a stopped Target called a model")
    )

    rc, _, err = run_cli("analyze", "TestTarget")

    assert rc == 1
    assert "STOPPED: TestTarget" in err and "Wait for the reset." in err
    assert read_stop(target_dir) is not None


@pytest.mark.parametrize(("answer", "proceeds"), [("y", True), ("", False)])
def test_an_interactive_command_offers_to_clear_the_stop(
    tmp_target_root, isolated_config, monkeypatch, answer, proceeds
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_stop(target_dir, "build", f"provider rate limit: {USAGE_LIMIT}")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.__stdout__, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    args = _build_parser().parse_args(["diagnose", "TestTarget"])

    assert _process_stop_gate(args) is proceeds
    assert (read_stop(target_dir) is None) is proceeds


def test_deterministic_commands_ignore_the_stop(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_stop(target_dir, "build", "provider outage: provider error 503")

    for argv in (["build", "status", "TestTarget"], ["plan", "verify", "TestTarget"]):
        assert _process_stop_gate(_build_parser().parse_args(argv))


def test_plan_repair_is_gated_and_plan_verify_is_not(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_stop(target_dir, "build", "provider outage: provider error 503")

    assert not _process_stop_gate(_build_parser().parse_args(["plan", "repair", "TestTarget"]))
    assert _process_stop_gate(_build_parser().parse_args(["plan", "verify", "TestTarget"]))
