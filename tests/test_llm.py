"""Tests for streaming subscription CLI execution and durable execution records."""

from __future__ import annotations

import io
import json
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

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def _records(target: Path) -> list[dict]:
    return [
        json.loads(line) for line in (target / "logs" / "executions.jsonl").read_text().splitlines()
    ]


def _events(target: Path) -> list[dict]:
    return [
        json.loads(line) for line in (target / "logs" / "events.jsonl").read_text().splitlines()
    ]


def test_build_prompt_breakdown_shows_block_and_stories():
    assembly = PromptAssembly(
        parts=(
            lines_part(
                "Build block job",
                [
                    "## Build block job",
                    "- TARGET: Demo",
                    "- FEATURE_BLOCK: Catalog (feature-catalog)",
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
    assert "plan-create_claude" in result.artifacts.log_file.name
    assert result.artifacts.prompt_file.read_text() == "Reply READY"
    assert result.artifacts.output_file.read_text() == "READY"
    assert "execution started" in result.artifacts.log_file.read_text()
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
    assert [event["event"] for event in _events(tmp_path)] == [
        "execution.started",
        "provider.event",
        "provider.event",
        "execution.completed",
    ]
    assert _events(tmp_path)[1]["provider_event_type"] == "stream_event"
    assert _events(tmp_path)[-1]["elapsed_ms"] is not None


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


def test_run_codex_streams_agent_message_and_removes_api_environment(tmp_path, monkeypatch):
    raw = json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "CODEX READY"},
        "model": "codex-test",
        "usage": {"input_tokens": 8, "output_tokens": 2},
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
    assert isolated_home.name.startswith("drydock-codex-home-")
    assert captured["env"]["HOME"] == "/original/home"
    assert captured["auth_text"] == '{"token": "subscription"}'
    assert captured["has_agents"] is False
    assert captured["has_config"] is False
    assert not isolated_home.exists()


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
    assert isolated_home.name.startswith("drydock-codex-home-")
    assert captured["has_auth"] is False
    assert not isolated_home.exists()


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
        lambda llm, working_directory, artifacts, model, allow_tools=False, codex_sandbox="danger-full-access": (
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
        lambda llm, working_directory, artifacts, model, allow_tools=False, codex_sandbox="danger-full-access": (
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

    with pytest.raises(KeyboardInterrupt):
        run_prompt(
            "ignored",
            tmp_path,
            llm="claude",
            on_text=lambda text: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    assert process.returncode == -15
    record = _records(tmp_path)[0]
    assert record["status"] == "failed"
    assert record["result"]["returncode"] == 130
    assert _events(tmp_path)[-1]["event"] == "execution.interrupted"


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


def test_file_log_contains_debug_details_without_debug_console(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command,
            stdout_text=json.dumps({"type": "result", "result": "OK"}) + "\n",
            **kwargs,
        ),
    )

    result = run_prompt(
        "Work",
        tmp_path,
        llm="claude",
        parameters={"ticket": "TICKET-1"},
        debug=False,
    )

    log_text = result.artifacts.log_file.read_text()
    assert "parameters=" in log_text
    assert "[prompt]" in log_text
    stderr = capsys.readouterr().err
    assert "parameters=" not in stderr
    assert "parts=" not in stderr
    assert "[llm]" in stderr
    assert "elapsed=" in stderr
