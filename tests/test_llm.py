"""Tests for streaming subscription CLI execution and durable execution records."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import drydock.llm
from drydock.errors import LlmConfigurationError, LlmError
from drydock.llm import run_prompt
from drydock.prompt_assembly import PromptAssembly, lines_part, part


class FakeStdin(io.StringIO):
    def close(self) -> None:
        self.seek(0)


class FakePopen:
    def __init__(
        self,
        command,
        *,
        stdout_text: str,
        stderr_text: str = "",
        returncode: int = 0,
        **kwargs,
    ):
        self.command = command
        self.kwargs = kwargs
        self.stdin = FakeStdin()
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def _records(target: Path) -> list[dict]:
    return [json.loads(line) for line in (target / "logs" / "llm.jsonl").read_text().splitlines()]


def test_build_prompt_breakdown_shows_block_and_stories():
    assembly = PromptAssembly(
        parts=(
            lines_part(
                "Build block job",
                [
                    "## Build block job",
                    "- TARGET: Demo",
                    "- BUILD_BLOCK: Catalog (feature-catalog)",
                    "",
                ],
                kind="job",
            ),
            lines_part(
                "Stories in this block",
                [
                    "## Stories in this block",
                    "- Report Ingest & Health Read (report-ingest) [story]",
                    "- S3 Share Index & Access (s3-share) [story]",
                    "",
                ],
            ),
            part("COMPASS.md", "compass", kind="file", role="compass"),
            part("FEATURE-REPORT-INGEST.md", "report", kind="file", role="implements"),
            part("Build instructions", "instructions", kind="instructions"),
            part("Prompt body", "body", kind="prompt-body"),
        )
    )

    lines = drydock.llm._prompt_breakdown_summary("build", assembly)

    assert lines[0] == "PROMPT BUILD BLOCK: Catalog (feature-catalog)"
    assert "  [STORIES RUN]" in lines
    assert any("Report Ingest & Health Read (report-ingest) [story]" in line for line in lines)
    assert "  [IMPLEMENTS - Authoritative Story Specifications]" in lines
    assert any("FEATURE-REPORT-INGEST.md" in line and "role=implements" in line for line in lines)


def test_run_claude_saves_prompt_logs_stats_and_reproducible_job(tmp_path, monkeypatch):
    raw = "\n".join([
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "READY"},
            },
        }),
        json.dumps({
            "type": "result",
            "result": "READY",
            "model": "claude-test",
            "duration_ms": 123,
            "num_turns": 2,
            "total_cost_usd": 0.0,
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 4,
                "cache_creation_input_tokens": 2,
                "output_tokens": 1,
            },
        }),
    ])
    captured = {}

    def fake_popen(command, **kwargs):
        process = FakePopen(command, stdout_text=raw + "\n", **kwargs)
        captured["process"] = process
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-propagate")
    text_chunks = []
    streamed_events = []

    result = run_prompt(
        "Reply READY",
        tmp_path,
        llm="claude",
        model="sonnet",
        command_name="plan-create",
        parameters={"spec": "Example", "block": 3},
        on_text=text_chunks.append,
        on_event=streamed_events.append,
        prompt_assembly=PromptAssembly(
            parts=(
                part("Prompt body", "Reply ", kind="prompt-body"),
                part("Task", "READY", kind="section"),
            )
        ),
    )

    process = captured["process"]
    assert process.command[:2] == ("claude", "-p")
    assert process.command[process.command.index("--tools") + 1] == ""
    assert process.stdin.getvalue() == "Reply READY"
    assert process.kwargs["cwd"] == tmp_path
    assert "ANTHROPIC_API_KEY" not in process.kwargs["env"]
    assert text_chunks == ["READY"]
    assert result.ok
    assert result.text == "READY"
    assert result.stats.model == "claude-test"
    assert result.stats.elapsed_ms is not None
    assert result.stats.input_tokens == 10
    assert result.command[-2:] == ("--model", "sonnet")
    assert result.artifacts.prompt_file.read_text() == "Reply READY"
    assert result.artifacts.output_file.read_text() == "READY"
    assert list(tmp_path.glob("*.debug.log")) == []
    assert streamed_events[0]["event"] == "execution.started"
    assert streamed_events[-1]["event"] == "execution.completed"

    record = _records(tmp_path)[0]
    assert record["schema_version"] == 1
    assert record["status"] == "succeeded"
    assert record["job"]["command_name"] == "plan-create"
    assert record["job"]["model"] == "sonnet"
    assert record["job"]["parameters"] == {"block": 3, "spec": "Example"}
    assert record["job"]["argv"][:2] == ["claude", "-p"]
    assert record["prompt"]["sha256"]
    assert record["prompt"]["total_tokens_estimate"] == 4
    assert len(record["prompt"]["parts"]) == 2
    assert record["result"]["raw_sha256"]
    assert record["result"]["output_sha256"]
    assert record["result"]["stats"]["elapsed_ms"] is not None
    assert [event["event"] for event in streamed_events] == [
        "execution.started",
        "provider.event",
        "provider.event",
        "execution.completed",
    ]
    assert streamed_events[1]["provider_event_type"] == "stream_event"
    assert streamed_events[-1]["elapsed_ms"] is not None
    assert not (tmp_path / "logs" / "events.jsonl").exists()


def test_claude_content_block_boundaries_are_forwarded_to_live_output(tmp_path, monkeypatch):
    raw = "\n".join([
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "text", "text": ""},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "First step."},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "text", "text": ""},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Second step."},
            },
        }),
        json.dumps({"type": "result", "result": "Second step."}),
    ])
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(command, stdout_text=raw + "\n", **kwargs),
    )
    chunks = []

    run_prompt("Work", tmp_path, llm="claude", on_text=chunks.append)

    assert chunks == ["\n", "First step.", "\n", "Second step."]


def test_run_claude_prefers_streamed_text_over_corrupted_final_result(tmp_path, monkeypatch):
    raw = "\n".join([
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "=== A.md ===\nalpha\n=== END A.md ===\n"},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "=== B.md ===\nbeta\n=== END B.md ===\n"},
            },
        }),
        json.dumps({
            "type": "result",
            "result": "=== B.md ===\nbeta\n=== END B.md ===\n",
            "model": "claude-test",
        }),
    ])
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(command, stdout_text=raw + "\n", **kwargs),
    )

    result = run_prompt("Work", tmp_path, llm="claude")

    expected = "=== A.md ===\nalpha\n=== END A.md ===\n=== B.md ===\nbeta\n=== END B.md ===\n"
    assert result.text == expected
    assert result.artifacts.output_file.read_text() == expected


def test_run_claude_surfaces_final_provider_error_with_streamed_text(tmp_path, monkeypatch):
    raw = "\n".join([
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Work before failure."},
            },
        }),
        json.dumps({
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "rejected",
                "rateLimitType": "five_hour",
                "overageDisabledReason": "out_of_credits",
            },
        }),
        json.dumps({
            "type": "result",
            "is_error": True,
            "api_error_status": 429,
            "result": "You've hit your session limit",
        }),
    ])
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command,
            stdout_text=raw + "\n",
            returncode=1,
            **kwargs,
        ),
    )

    result = run_prompt("Work", tmp_path, llm="claude", command_name="build")

    assert not result.ok
    assert result.text == "Work before failure."
    assert result.stderr == "provider rate limit 429: You've hit your session limit"
    assert _records(tmp_path)[0]["result"]["error"] == result.stderr


def test_run_claude_prints_login_block_for_authentication_failure(tmp_path, monkeypatch, capsys):
    raw = "\n".join([
        json.dumps({
            "type": "assistant",
            "message": {
                "model": "<synthetic>",
                "role": "assistant",
                "type": "message",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "content": [
                    {
                        "type": "text",
                        "text": "Failed to authenticate: OAuth session expired and could not be refreshed",
                    }
                ],
            },
            "error": "authentication_failed",
        }),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "terminal_reason": "api_error",
        }),
    ])
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command,
            stdout_text=raw + "\n",
            returncode=1,
            **kwargs,
        ),
    )

    result = run_prompt("Work", tmp_path, llm="claude", command_name="rigging compact")

    stderr = capsys.readouterr().err
    assert not result.ok
    assert "FATAL ERROR - LLM AUTHENTICATION REQUIRED" in stderr
    assert "Drydock could not run 'rigging compact' with the claude provider." in stderr
    assert "Failed to authenticate: OAuth session expired" in stderr
    assert "*   claude" in stderr
    assert result.execution_id in stderr
    assert _records(tmp_path)[0]["result"]["error"] == result.stderr


def test_run_claude_prints_fatal_block_for_rate_limit(tmp_path, monkeypatch, capsys):
    raw = "\n".join([
        json.dumps({
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "rejected",
                "rateLimitType": "five_hour",
                "overageDisabledReason": "out_of_credits",
            },
        }),
        json.dumps({
            "type": "result",
            "is_error": True,
            "api_error_status": 429,
            "result": "You've hit your session limit",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }),
    ])
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command,
            stdout_text=raw + "\n",
            returncode=1,
            **kwargs,
        ),
    )

    result = run_prompt("Work", tmp_path, llm="claude", command_name="build")

    stderr = capsys.readouterr().err
    assert not result.ok
    assert "FATAL ERROR - PROVIDER RATE LIMIT" in stderr
    assert "provider rate limit 429: You've hit your session limit" in stderr
    assert "Wait for the provider quota or session limit to reset" in stderr
    assert result.execution_id in stderr
    assert _records(tmp_path)[0]["result"]["error"] == result.stderr


def test_run_codex_streams_agent_message_and_removes_api_environment(tmp_path, monkeypatch):
    raw = json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "CODEX READY"},
        "model": "codex-test",
        "usage": {"input_tokens": 8, "cached_input_tokens": 5, "output_tokens": 2},
    })

    def fake_popen(command, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("CODEX READY")
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "OPENAI_BASE_URL" not in kwargs["env"]
        return FakePopen(command, stdout_text=raw + "\n", **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-propagate")
    monkeypatch.setenv("OPENAI_BASE_URL", "must-not-propagate")
    chunks = []

    result = run_prompt("Work", tmp_path, llm="codex", command_name="build", on_text=chunks.append)

    assert result.ok
    assert result.text == "CODEX READY"
    assert result.command[:2] == ("codex", "exec")
    assert "--ignore-user-config" in result.command
    assert "--ignore-rules" in result.command
    assert "--ephemeral" in result.command
    assert result.command[result.command.index("--sandbox") + 1] == "danger-full-access"
    assert result.stats.model == "codex-test"
    assert result.stats.input_tokens == 8
    assert result.stats.cached_input_tokens == 5
    assert result.stats.output_tokens == 2
    assert chunks == ["CODEX READY"]


def test_run_codex_sandbox_override_passes_through(tmp_path, monkeypatch):
    raw = json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "OK"},
        "model": "codex-test",
    })

    def fake_popen(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("OK")
        return FakePopen(command, stdout_text=raw + "\n", **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    # workspace-write triggers the Linux helper preflight; make the helper resolvable.
    monkeypatch.setattr(drydock.llm.shutil, "which", lambda name: "/usr/bin/codex-linux-sandbox")

    result = run_prompt(
        "Work", tmp_path, llm="codex", command_name="build", codex_sandbox="workspace-write"
    )

    assert result.command[result.command.index("--sandbox") + 1] == "workspace-write"


def test_run_codex_workspace_write_fails_fast_when_helper_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(drydock.llm.sys, "platform", "linux")
    monkeypatch.setattr(drydock.llm.shutil, "which", lambda name: None)

    with pytest.raises(LlmConfigurationError) as excinfo:
        run_prompt(
            "Work", tmp_path, llm="codex", command_name="build", codex_sandbox="workspace-write"
        )

    message = str(excinfo.value)
    assert "execution environment unavailable" in message
    assert "codex-linux-sandbox" in message


def test_run_codex_danger_full_access_skips_helper_preflight(tmp_path, monkeypatch):
    raw = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}})

    def fake_popen(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("OK")
        return FakePopen(command, stdout_text=raw + "\n", **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(drydock.llm.sys, "platform", "linux")
    # Helper absent, but danger-full-access needs none: must not raise.
    monkeypatch.setattr(drydock.llm.shutil, "which", lambda name: None)

    result = run_prompt(
        "Work", tmp_path, llm="codex", command_name="build", codex_sandbox="danger-full-access"
    )

    assert result.command[result.command.index("--sandbox") + 1] == "danger-full-access"


def _claude_result_raw(text: str = "READY") -> str:
    return json.dumps({"type": "result", "result": text, "model": "claude-test"}) + "\n"


def _capture_env_popen(captured: dict, raw: str):
    def fake_popen(command, **kwargs):
        captured["env"] = kwargs["env"]
        return FakePopen(command, stdout_text=raw, **kwargs)

    return fake_popen


def test_claude_isolates_config_home_and_seeds_credentials(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    real_config = fake_home / ".claude"
    real_config.mkdir(parents=True)
    (real_config / ".credentials.json").write_text('{"token": "subscription"}')

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    captured = {}
    monkeypatch.setattr(subprocess, "Popen", _capture_env_popen(captured, _claude_result_raw()))

    run_prompt("Work", tmp_path, llm="claude", command_name="build")

    build_home = fake_home / ".drydock" / "claude-home"
    assert captured["env"]["HOME"] == str(build_home)
    assert captured["env"]["CLAUDE_CONFIG_DIR"] == str(build_home)
    seeded = build_home / ".credentials.json"
    assert seeded.read_text() == '{"token": "subscription"}'


def test_claude_isolation_skipped_without_credentials(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)  # no .credentials.json

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", "/original/home")
    captured = {}
    monkeypatch.setattr(subprocess, "Popen", _capture_env_popen(captured, _claude_result_raw()))

    run_prompt("Work", tmp_path, llm="claude", command_name="build")

    assert captured["env"]["HOME"] == "/original/home"
    assert "CLAUDE_CONFIG_DIR" not in captured["env"]
    assert not (fake_home / ".drydock").exists()


def test_codex_isolates_codex_home_and_seeds_auth_only(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    real_codex = fake_home / ".codex"
    real_codex.mkdir(parents=True)
    (real_codex / "auth.json").write_text('{"token": "subscription"}')
    (real_codex / "AGENTS.md").write_text("# ambient instructions\n")
    (real_codex / "config.toml").write_text('model = "gpt-5"\n')

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("HOME", "/original/home")
    raw = json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "OK"},
        "model": "codex-test",
    })

    def fake_popen(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("OK")
        captured["env"] = kwargs["env"]
        isolated_home = Path(kwargs["env"]["CODEX_HOME"])
        captured["isolated_home"] = isolated_home
        captured["auth_text"] = (isolated_home / "auth.json").read_text()
        captured["has_agents"] = (isolated_home / "AGENTS.md").exists()
        captured["has_config"] = (isolated_home / "config.toml").exists()
        return FakePopen(command, stdout_text=raw + "\n", **kwargs)

    captured = {}
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    run_prompt("Work", tmp_path, llm="codex", command_name="build")

    isolated_home = captured["isolated_home"]
    # Persistent and outside /tmp: codex refuses to install its PATH helpers beneath a
    # temporary directory and then leaks a hung child on every model-refresh retry.
    assert isolated_home == fake_home / ".drydock" / "codex-home"
    assert captured["env"]["HOME"] == "/original/home"
    assert captured["auth_text"] == '{"token": "subscription"}'
    assert captured["has_agents"] is False
    assert captured["has_config"] is False
    assert isolated_home.is_dir()
    assert sorted(p.name for p in isolated_home.iterdir()) == ["auth.json"]


def test_codex_isolation_still_creates_clean_home_without_auth(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".codex").mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    raw = json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "OK"},
        "model": "codex-test",
    })

    captured = {}

    def fake_popen(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("OK")
        captured["env"] = kwargs["env"]
        captured["isolated_home"] = Path(kwargs["env"]["CODEX_HOME"])
        captured["has_auth"] = (captured["isolated_home"] / "auth.json").exists()
        return FakePopen(command, stdout_text=raw + "\n", **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    run_prompt("Work", tmp_path, llm="codex", command_name="build")

    isolated_home = captured["isolated_home"]
    assert isolated_home == fake_home / ".drydock" / "codex-home"
    assert captured["has_auth"] is False
    assert isolated_home.is_dir()


def test_live_callback_occurs_before_process_completes(tmp_path, monkeypatch):
    code = (
        "import json,time;"
        "print(json.dumps({'type':'content_block_delta','delta':"
        "{'type':'text_delta','text':'first'}}),flush=True);"
        "time.sleep(0.4);"
        "print(json.dumps({'type':'result','result':'first done'}),flush=True)"
    )
    monkeypatch.setattr(
        drydock.llm,
        "_command",
        lambda llm, working_directory, artifacts, model, allow_tools=False, **kwargs: (
            sys.executable,
            "-u",
            "-c",
            code,
        ),
    )
    callback_times = []
    started = time.monotonic()

    result = run_prompt(
        "ignored",
        tmp_path,
        llm="claude",
        on_text=lambda text: callback_times.append(time.monotonic()),
    )
    completed = time.monotonic()

    assert result.ok
    assert callback_times
    assert callback_times[0] - started < 0.3
    assert completed - callback_times[0] >= 0.2


def test_timeout_terminates_process_and_writes_failed_record(tmp_path, monkeypatch):
    code = "import time; time.sleep(10)"
    monkeypatch.setattr(
        drydock.llm,
        "_command",
        lambda llm, working_directory, artifacts, model, allow_tools=False, **kwargs: (
            sys.executable,
            "-u",
            "-c",
            code,
        ),
    )

    result = run_prompt("ignored", tmp_path, llm="claude", timeout_seconds=0.1)

    assert not result.ok
    assert result.returncode == 124
    record = _records(tmp_path)[0]
    assert record["status"] == "failed"
    assert record["result"]["timed_out"] is True


def test_interrupt_terminates_process_and_writes_failed_record(tmp_path, monkeypatch):
    raw = json.dumps({
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "stop"},
    })
    process = FakePopen(("claude",), stdout_text=raw + "\n")
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: process)
    streamed_events = []

    with pytest.raises(KeyboardInterrupt):
        run_prompt(
            "ignored",
            tmp_path,
            llm="claude",
            on_text=lambda text: (_ for _ in ()).throw(KeyboardInterrupt()),
            on_event=streamed_events.append,
        )

    assert process.returncode == -15
    record = _records(tmp_path)[0]
    assert record["status"] == "failed"
    assert record["result"]["returncode"] == 130
    assert streamed_events[-1]["event"] == "execution.interrupted"


def test_missing_executable_writes_failed_record_and_prompt(tmp_path, monkeypatch):
    def fake_popen(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    with pytest.raises(LlmError, match="execution_id"):
        run_prompt("Preserve me", tmp_path, llm="claude", command_name="analyze")

    record = _records(tmp_path)[0]
    assert record["status"] == "failed"
    assert record["job"]["command_name"] == "analyze"
    assert Path(record["prompt"]["path"]).read_text() == "Preserve me"
    assert record["result"]["error"]


def test_provider_defaults_from_configuration(tmp_path, isolated_config, monkeypatch):
    from drydock.config import config_set

    config_set("llm_provider", "codex")

    def fake_popen(command, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("OK")
        return FakePopen(command, stdout_text="", **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    assert run_prompt("Work", tmp_path).llm == "codex"


def test_debug_details_are_not_persisted_or_printed_without_debug(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command,
            stdout_text=json.dumps({"type": "result", "result": "OK"}) + "\n",
            **kwargs,
        ),
    )

    run_prompt(
        "Work",
        tmp_path,
        llm="claude",
        parameters={"ticket": "TICKET-1"},
        debug=False,
    )

    assert list(tmp_path.glob("*.debug.log")) == []
    stderr = capsys.readouterr().err
    assert "parameters=" not in stderr
    assert "parts=" not in stderr
    assert "Completed CLAUDE" in stderr
    assert "elapsed=" in stderr


def test_debug_details_print_to_console_without_debug_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command,
            stdout_text=json.dumps({"type": "result", "result": "OK"}) + "\n",
            **kwargs,
        ),
    )

    run_prompt(
        "Work",
        tmp_path,
        llm="claude",
        parameters={"ticket": "TICKET-1"},
        debug=True,
    )

    stderr = capsys.readouterr().err
    assert "parameters=" in stderr
    assert "[prompt]" in stderr
    assert list(tmp_path.glob("*.debug.log")) == []


def test_token_summary_sums_cache_reads_for_claude():
    # Claude reports input_tokens exclusive of cache reads, so everything sent to the
    # model is the sum, and the hit rate is the cache-read share of that total.
    from drydock.llm import LlmStats, format_token_summary

    line = format_token_summary(
        LlmStats(
            input_tokens=21_904,
            cached_input_tokens=160_437,
            cache_creation_input_tokens=12_010,
            output_tokens=4_812,
            cost_usd=0.61,
        ),
        llm="claude",
    )
    assert line == (
        "in=182,341 · fresh 21,904 · cached 160,437 (88% hit) · write 12,010 · "
        "out=4,812 · cost=$0.6100"
    )


def test_token_summary_treats_codex_input_as_cache_inclusive():
    from drydock.llm import LlmStats, format_token_summary

    line = format_token_summary(
        LlmStats(input_tokens=1_000, cached_input_tokens=900, output_tokens=50),
        llm="codex",
    )
    assert line == "in=1,000 · fresh 100 · cached 900 (90% hit) · out=50"


def test_token_summary_omits_absent_segments():
    from drydock.llm import LlmStats, format_token_summary

    assert format_token_summary(LlmStats(output_tokens=12), llm="claude") == "out=12"
    assert format_token_summary(LlmStats(model="x", elapsed_ms=10), llm="claude") is None
    assert format_token_summary(None, llm="claude") is None


def test_done_line_reports_normalized_tokens_and_cache_hit_rate():
    from drydock.llm import LlmStats, _performance_summary

    line = _performance_summary(
        llm="claude",
        command_name="build",
        execution_id="exec-1",
        returncode=0,
        stats=LlmStats(
            model="claude-opus-5",
            elapsed_ms=2_000,
            input_tokens=100,
            cached_input_tokens=900,
            output_tokens=50,
        ),
    )
    assert "in=1,000 · fresh 100 · cached 900 (90% hit) · out=50" in line
    assert "tps=25.0" in line


def test_done_line_falls_back_to_requested_model():
    # Providers that do not report the model in their result stats (e.g. codex) must still show
    # the requested model on the DONE line rather than a bare `-`.
    from drydock.llm import LlmStats, _performance_summary

    line = _performance_summary(
        llm="codex",
        command_name="plan",
        execution_id="exec-1",
        returncode=0,
        stats=LlmStats(model=None, elapsed_ms=1000),
        requested_model="gpt-5.6-luna",
    )
    assert "Completed CODEX/gpt-5.6-luna (plan)" in line


def test_done_line_prefers_reported_model_over_requested():
    from drydock.llm import LlmStats, _performance_summary

    line = _performance_summary(
        llm="claude",
        command_name="plan",
        execution_id="exec-1",
        returncode=0,
        stats=LlmStats(model="claude-opus-4-8", elapsed_ms=1000),
        requested_model="sonnet",
    )
    assert "Completed CLAUDE/claude-opus-4-8 (plan)" in line


def test_provider_model_conflict_flags_cross_provider_model():
    from drydock.llm import provider_model_conflict

    problem = provider_model_conflict("codex", "opus")
    assert problem is not None
    assert "opus" in problem and "codex" in problem
    assert "--llm-provider claude" in problem


def test_provider_model_conflict_flags_claude_with_gpt_model():
    from drydock.llm import provider_model_conflict

    problem = provider_model_conflict("claude", "gpt-5.6-luna")
    assert problem is not None
    assert "--llm-provider codex" in problem


def test_provider_model_conflict_rejects_unknown_provider():
    from drydock.llm import provider_model_conflict

    assert "Valid providers" in (provider_model_conflict("gpt", "opus") or "")


def test_provider_model_conflict_allows_matching_and_unknown_models():
    from drydock.llm import provider_model_conflict

    assert provider_model_conflict("codex", "gpt-5.6-luna") is None
    assert provider_model_conflict("claude", "opus") is None
    assert provider_model_conflict("claude", "claude-opus-4-8") is None
    # A model name that names neither provider cannot be judged; allow it through.
    assert provider_model_conflict("codex", "some-custom-model") is None
    assert provider_model_conflict("codex", None) is None


# --- Provider process lifecycle -------------------------------------------------------
#
# A provider agent runs shell commands, and those grandchildren inherit fd 1/2. A
# survivor holds the pipe's write end open, so pipe EOF cannot be the completion signal:
# process exit is. These tests pin that, and pin that no descendant outlives the run.


def _orphan_command(marker: Path, hold_seconds: int = 30) -> str:
    """Shell that prints a line, backgrounds a child holding stdout, then exits."""
    return (
        f'python3 -c "import os,sys,time;'
        f"open({str(marker)!r},'w').write(str(os.getpid()));"
        f"sys.stdout.write('held\\n');sys.stdout.flush();"
        f'time.sleep({hold_seconds})" & '
        f'echo \'{{"type":"item.completed","item":{{"type":"agent_message","text":"done"}}}}\'; '
        f"exit 0"
    )


def _fake_shell_command(monkeypatch, script: str) -> None:
    monkeypatch.setattr(
        drydock.llm,
        "_command",
        lambda llm, working_directory, artifacts, model, allow_tools=False, **kwargs: (
            "/bin/bash",
            "-c",
            script,
        ),
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_orphan_holding_stdout_does_not_delay_completion(tmp_path, monkeypatch):
    """Completion follows process exit, not pipe EOF.

    Before the lifecycle fix this blocked for the full lifetime of the orphan, because
    ``readline`` only sees EOF once every inheritor of the pipe closes it.
    """
    marker = tmp_path / "orphan.pid"
    _fake_shell_command(monkeypatch, _orphan_command(marker, hold_seconds=30))
    monkeypatch.setattr(drydock.llm, "_DRAIN_GRACE_SECONDS", 0.3)

    started = time.monotonic()
    result = run_prompt("ignored", tmp_path, llm="codex")
    elapsed = time.monotonic() - started

    assert result.ok
    assert elapsed < 10, f"completion waited on the orphan ({elapsed:.1f}s)"
    # Output produced before the provider exited is still captured as evidence.
    assert "held" in result.artifacts.raw_file.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_surviving_descendants_are_reaped(tmp_path, monkeypatch):
    marker = tmp_path / "orphan.pid"
    _fake_shell_command(monkeypatch, _orphan_command(marker, hold_seconds=30))
    monkeypatch.setattr(drydock.llm, "_DRAIN_GRACE_SECONDS", 0.3)

    run_prompt("ignored", tmp_path, llm="codex")

    orphan_pid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(orphan_pid, 0)
        except OSError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"descendant {orphan_pid} survived the run")


def test_command_activity_streams_to_console_but_not_result_text(tmp_path, monkeypatch):
    """Shell activity is console-only.

    ``LlmResult.text`` is what ``build_run`` parses for the agent's reported result, so
    command lines must never contaminate it.
    """
    events = [
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "/bin/bash -lc 'pytest -q'"},
        },
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "/bin/bash -lc 'pytest -q'",
                "exit_code": 0,
            },
        },
        {"type": "item.completed", "item": {"type": "agent_message", "text": "RESULT: SUCCESS"}},
    ]
    raw = "\n".join(json.dumps(event) for event in events) + "\n"

    def fake_popen(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("RESULT: SUCCESS")
        return FakePopen(command, stdout_text=raw, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    streamed: list[str] = []

    result = run_prompt("ignored", tmp_path, llm="codex", on_text=streamed.append)

    console = "".join(streamed)
    assert "$ /bin/bash -lc 'pytest -q'" in console
    assert "-> exit 0" in console
    assert "pytest -q" not in result.text
    assert "exit 0" not in result.text
    assert result.text.strip() == "RESULT: SUCCESS"


def test_long_command_is_truncated_in_activity_line():
    from drydock.llm import _activity_from_event

    line = _activity_from_event(
        "codex",
        {"type": "item.started", "item": {"type": "command_execution", "command": "x" * 500}},
    )
    assert line is not None
    assert len(line) < 200
    assert line.endswith("…")


def test_claude_events_produce_no_activity_lines():
    from drydock.llm import _activity_from_event

    assert _activity_from_event("claude", {"type": "item.started", "item": {"type": "x"}}) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_heartbeat_reports_liveness_while_provider_is_silent(tmp_path, monkeypatch):
    """A build has no timeout, so a quiet run must still look alive."""
    script = (
        'sleep 1; echo \'{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\''
    )
    _fake_shell_command(monkeypatch, script)
    monkeypatch.setattr(drydock.llm, "_HEARTBEAT_SECONDS", 0.2)
    streamed: list[str] = []

    result = run_prompt("ignored", tmp_path, llm="codex", on_text=streamed.append)

    assert result.ok
    heartbeats = [line for line in streamed if "[running]" in line]
    assert heartbeats, f"no heartbeat emitted: {streamed}"
    assert "elapsed" in heartbeats[0]


def test_duration_formats_minutes_and_seconds():
    from drydock.llm import _duration

    assert _duration(9.7) == "9s"
    assert _duration(59) == "59s"
    assert _duration(60) == "1m00s"
    assert _duration(605) == "10m05s"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_provider_runs_in_its_own_process_group(tmp_path, monkeypatch):
    """Signalling the provider's group must never be able to reach Drydock."""
    captured: dict[str, object] = {}
    real_popen = subprocess.Popen

    def fake_popen(command, **kwargs):
        captured["kwargs"] = kwargs
        return real_popen(command, **kwargs)

    _fake_shell_command(monkeypatch, 'echo \'{"type":"x"}\'')
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    run_prompt("ignored", tmp_path, llm="codex")

    assert captured["kwargs"]["start_new_session"] is True


def test_process_group_helper_refuses_to_signal_drydocks_own_group():
    """Signalling Drydock's own group would kill Drydock."""
    from drydock.llm import _capture_process_group

    class SameGroup:
        pid = os.getpid()

    assert _capture_process_group(SameGroup()) is None


def test_process_group_helper_tolerates_test_double():
    from drydock.llm import _capture_process_group, _reap_process_group

    double = FakePopen(("codex",), stdout_text="")
    assert _capture_process_group(double) is None
    _reap_process_group(None)  # must not raise


# ── reasoning effort ──────────────────────────────────────────────────────────


def _effort_command(
    llm: str, effort: str | None, tmp_path: Path, model: str = "sonnet"
) -> tuple[str, ...]:
    from types import SimpleNamespace

    from drydock.llm import _command

    artifacts = SimpleNamespace(output_file=tmp_path / "out.txt")
    return _command(llm, tmp_path, artifacts, model, effort=effort)


def test_claude_command_omits_effort_by_default(tmp_path):
    """Effort is opt-in: a command that does not ask for it keeps the provider default."""
    assert "--effort" not in _effort_command("claude", None, tmp_path)


def test_claude_command_passes_effort_through(tmp_path):
    command = _effort_command("claude", "max", tmp_path)
    assert command[command.index("--effort") + 1] == "max"


def test_codex_command_maps_effort_to_its_config_key(tmp_path):
    """codex has no --effort flag; the level rides in as a config override."""
    command = _effort_command("codex", "high", tmp_path)
    assert command[command.index("-c") + 1] == "model_reasoning_effort=high"
    assert command[-1] == "-"


def test_codex_serves_xhigh_only_on_the_model_family_that_has_it(tmp_path):
    """xhigh is a codex-max capability; every other model clamps to high rather than
    failing the run on an effort its model does not accept."""
    for level in ("xhigh", "max"):
        command = _effort_command("codex", level, tmp_path, model="gpt-5.1-codex-max")
        assert command[command.index("-c") + 1] == "model_reasoning_effort=xhigh"
        command = _effort_command("codex", level, tmp_path, model="gpt-5.1-codex")
        assert command[command.index("-c") + 1] == "model_reasoning_effort=high"


def test_codex_clamps_top_levels_when_no_model_is_named(tmp_path):
    """With no --model the served model is unknown, so the safe level is the universal one."""
    command = _effort_command("codex", "max", tmp_path, model=None)
    assert command[command.index("-c") + 1] == "model_reasoning_effort=high"


def test_normalize_effort_accepts_every_documented_level():
    from drydock.config import EFFORT_LEVELS
    from drydock.llm import normalize_effort

    assert normalize_effort(None) is None
    assert normalize_effort("  MAX ") == "max"
    for level in EFFORT_LEVELS:
        assert normalize_effort(level) == level


def test_normalize_effort_rejects_an_unknown_level():
    from drydock.llm import LlmConfigurationError, normalize_effort

    with pytest.raises(LlmConfigurationError) as excinfo:
        normalize_effort("ludicrous")
    message = str(excinfo.value)
    assert "ludicrous" in message
    for level in ("low", "medium", "high", "xhigh", "max"):
        assert level in message


def test_effort_falls_back_to_the_configured_level(monkeypatch, tmp_path):
    """A command that names no effort still honors drydock_effort."""
    from drydock import llm as llm_module

    monkeypatch.setenv("DRYDOCK_EFFORT", "xhigh")
    captured: dict = {}

    def fake_command(*args, **kwargs):
        captured.update(kwargs)
        return ("true",)

    monkeypatch.setattr(llm_module, "_command", fake_command)
    llm_module.run_prompt(
        "hello", tmp_path, llm="claude", model="sonnet", log_dir=tmp_path, announce=False
    )
    assert captured["effort"] == "xhigh"


def test_an_explicit_effort_beats_the_configured_level(monkeypatch, tmp_path):
    from drydock import llm as llm_module

    monkeypatch.setenv("DRYDOCK_EFFORT", "xhigh")
    captured: dict = {}

    def fake_command(*args, **kwargs):
        captured.update(kwargs)
        return ("true",)

    monkeypatch.setattr(llm_module, "_command", fake_command)
    llm_module.run_prompt(
        "hello",
        tmp_path,
        llm="claude",
        model="sonnet",
        effort="low",
        log_dir=tmp_path,
        announce=False,
    )
    assert captured["effort"] == "low"
