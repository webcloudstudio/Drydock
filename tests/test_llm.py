"""Tests for streaming subscription CLI execution and durable execution records."""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

import drydock.llm
import drydock.model_config
from drydock.errors import LlmConfigurationError, LlmError
from drydock.llm import LlmResult, LlmStats, failure_detail, run_prompt
from drydock.prompt_assembly import PromptAssembly, lines_part, part


@pytest.fixture(autouse=True)
def isolated_provider_home(tmp_path, monkeypatch):
    """Keep adapter tests away from real subscription credentials and user configuration."""
    provider_home = tmp_path / "provider-home"
    provider_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: provider_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)


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


def test_codex_command_skips_git_repository_check(tmp_path):
    artifacts = drydock.llm.ExecutionArtifacts.create(tmp_path, "build", "codex")

    command = drydock.llm._command("codex", tmp_path, artifacts, model=None, allow_tools=True)

    assert "--skip-git-repo-check" in command


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


def test_run_claude_prints_fatal_block_for_spend_limit_without_error_status(
    tmp_path, monkeypatch, capsys
):
    """A refused Claude turn names its own limit even with no ``api_error_status`` to read."""
    message = "You've hit your monthly spend limit · raise it at claude.ai/settings/usage"
    raw = "\n".join([
        json.dumps({
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"},
        }),
        json.dumps({"type": "result", "is_error": True, "result": message}),
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
    assert message in stderr


def test_run_claude_allowed_quota_window_is_not_reported_as_the_failure(tmp_path, monkeypatch):
    """Claude reports quota state on healthy calls; an allowed window never explains a failure."""
    raw = "\n".join([
        json.dumps({
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour"},
        }),
        json.dumps({"type": "result", "result": "partial work"}),
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
    assert "rate limit" not in (result.stderr or "")


def test_run_codex_prints_fatal_block_for_usage_limit(tmp_path, monkeypatch, capsys):
    """Codex reports an exhausted quota as a stream event, not a terminal ``result`` record."""
    message = "You've hit your usage limit. Upgrade to Pro or try again at Aug 20th, 2026 3:39 AM."
    raw = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "error", "message": message}),
        json.dumps({"type": "turn.failed", "error": {"message": message}}),
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

    result = run_prompt("Work", tmp_path, llm="codex", command_name="build")

    stderr = capsys.readouterr().err
    assert not result.ok
    assert "FATAL ERROR - PROVIDER RATE LIMIT" in stderr
    assert message in stderr
    assert result.stderr == f"provider rate limit: {message}"
    assert _records(tmp_path)[0]["result"]["error"] == result.stderr


def test_run_codex_surfaces_non_quota_stream_error(tmp_path, monkeypatch):
    raw = "\n".join([
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "turn.failed", "error": {"message": "upstream connection reset"}}),
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

    result = run_prompt("Work", tmp_path, llm="codex", command_name="build")

    assert not result.ok
    assert result.stderr == "provider error: upstream connection reset"


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

    result = run_prompt(
        "Work",
        tmp_path,
        llm="codex",
        command_name="build",
        allow_tools=True,
        on_text=chunks.append,
    )

    assert result.ok
    assert result.text == "CODEX READY"
    assert result.command[:2] == ("codex", "exec")
    assert "--ignore-user-config" in result.command
    assert "--ignore-rules" in result.command
    assert "--ephemeral" in result.command
    assert "--skip-git-repo-check" in result.command
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
        "Work",
        tmp_path,
        llm="codex",
        command_name="build",
        allow_tools=True,
        codex_sandbox="workspace-write",
    )

    assert result.command[result.command.index("--sandbox") + 1] == "workspace-write"


def test_run_codex_workspace_write_fails_fast_when_helper_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(drydock.llm.sys, "platform", "linux")
    monkeypatch.setattr(drydock.llm.shutil, "which", lambda name: None)

    with pytest.raises(LlmConfigurationError) as excinfo:
        run_prompt(
            "Work",
            tmp_path,
            llm="codex",
            command_name="build",
            allow_tools=True,
            codex_sandbox="workspace-write",
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
        "Work",
        tmp_path,
        llm="codex",
        command_name="build",
        allow_tools=True,
        codex_sandbox="danger-full-access",
    )

    assert result.command[result.command.index("--sandbox") + 1] == "danger-full-access"


def _codex_ok_popen(monkeypatch):
    raw = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}})

    def fake_popen(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("OK")
        return FakePopen(command, stdout_text=raw + "\n", **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)


def test_run_codex_without_tools_forces_read_only_sandbox(tmp_path, monkeypatch):
    """Text-only commands must not get a writable codex.

    codex exec always carries a shell tool, so the sandbox is the only lever. A writable
    codex edits the target and returns a narrative summary, which the caller then writes
    over the file the model just wrote.
    """
    _codex_ok_popen(monkeypatch)

    result = run_prompt(
        "Work",
        tmp_path,
        llm="codex",
        command_name="rigging_compact",
        codex_sandbox="danger-full-access",
    )

    assert result.command[result.command.index("--sandbox") + 1] == "read-only"


def test_run_codex_without_tools_ignores_configured_sandbox(tmp_path, monkeypatch):
    _codex_ok_popen(monkeypatch)
    monkeypatch.setenv("DRYDOCK_CODEX_SANDBOX", "danger-full-access")

    result = run_prompt("Work", tmp_path, llm="codex", command_name="rigging_compact")

    assert result.command[result.command.index("--sandbox") + 1] == "read-only"


def test_run_codex_without_tools_skips_helper_preflight(tmp_path, monkeypatch):
    """The forced floor is Drydock's own, and codex enforces read-only natively."""
    _codex_ok_popen(monkeypatch)
    monkeypatch.setattr(drydock.llm.sys, "platform", "linux")
    monkeypatch.setattr(drydock.llm.shutil, "which", lambda name: None)

    result = run_prompt("Work", tmp_path, llm="codex", command_name="rigging_compact")

    assert result.command[result.command.index("--sandbox") + 1] == "read-only"


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
    assert not (fake_home / ".drydock" / "claude-home").exists()


_PARENT_PYPROJECT = b'[project]\nname = "drydock"\nversion = "1.0"\n'
_PARENT_LOCK = b"version = 1\n"


def _nested_build(tmp_path, monkeypatch, agent_edit):
    """Run a tool-using call in a build nested under a uv project; ``agent_edit`` acts mid-call."""
    repo = tmp_path / "repo"
    build = repo / "uat" / "runs" / "1" / "build" / "FxRates"
    build.mkdir(parents=True)
    (repo / "pyproject.toml").write_bytes(_PARENT_PYPROJECT)
    (repo / "uv.lock").write_bytes(_PARENT_LOCK)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    def fake_popen(command, **kwargs):
        agent_edit(repo)
        return FakePopen(command, stdout_text=_claude_result_raw(), **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    result = run_prompt("Work", build, llm="claude", command_name="build", allow_tools=True)
    return repo, result


@pytest.mark.parametrize("member", ["uat/runs/1/build/FxRates", "uat/runs/*/build/*"])
def test_agent_registration_in_an_enclosing_uv_workspace_is_restored_and_fails(
    tmp_path, monkeypatch, member
):
    # FxRates 20261024.164835: Codex's login shell put the real uv ahead of the 39e4e10 shim, and
    # the agent's `uv init` registered the build in Drydock's own pyproject.toml and uv.lock.
    def register(repo):
        (repo / "pyproject.toml").write_bytes(
            _PARENT_PYPROJECT + f'\n[tool.uv.workspace]\nmembers = ["{member}"]\n'.encode()
        )
        (repo / "uv.lock").write_bytes(_PARENT_LOCK + b'[[package]]\nname = "fxrates"\n')

    repo, result = _nested_build(tmp_path, monkeypatch, register)

    assert (repo / "pyproject.toml").read_bytes() == _PARENT_PYPROJECT
    assert (repo / "uv.lock").read_bytes() == _PARENT_LOCK
    assert not result.ok
    assert "enclosing uv workspace" in result.failure
    assert member in result.failure


def test_a_parent_uv_lock_the_agent_created_is_removed(tmp_path, monkeypatch):
    def register(repo):
        (repo / "uv.lock").unlink()
        with (repo / "pyproject.toml").open("ab") as handle:
            handle.write(b'\n[tool.uv.workspace]\nmembers = ["uat/runs/1/build/FxRates/api"]\n')
        (repo / "uv.lock").write_bytes(b"created\n")

    repo, result = _nested_build(tmp_path, monkeypatch, register)

    assert (repo / "uv.lock").read_bytes() == _PARENT_LOCK
    assert not result.ok


def test_an_unrelated_change_to_an_enclosing_project_is_kept(tmp_path, monkeypatch):
    bumped = _PARENT_PYPROJECT.replace(b"1.0", b"1.1")

    def bump(repo):
        (repo / "pyproject.toml").write_bytes(
            bumped + b'\n[tool.uv.workspace]\nmembers = ["packages/other"]\n'
        )

    repo, result = _nested_build(tmp_path, monkeypatch, bump)

    assert (repo / "pyproject.toml").read_bytes().startswith(bumped)
    assert result.ok


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

    result = run_prompt(
        "ignored",
        tmp_path,
        llm="claude",
        on_text=lambda text: callback_times.append(time.monotonic()),
    )
    completed = time.monotonic()

    assert result.ok
    assert callback_times
    # The callback fired while the provider was still running; start-up time is not measured.
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
    captured = capsys.readouterr()
    assert "parameters=" not in captured.err
    assert "parts=" not in captured.err
    # Run telemetry is progress, not a diagnostic: it belongs on stdout.
    assert "Completed CLAUDE" not in captured.err
    assert "Completed CLAUDE" in captured.out
    # Token and cost accounting is neither: it is written to the LLM log alone.
    assert "elapsed=" not in captured.out
    assert "elapsed=" not in captured.err


def test_run_telemetry_is_recorded_in_the_llm_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command,
            stdout_text=json.dumps({"type": "result", "result": "OK"}) + "\n",
            **kwargs,
        ),
    )

    run_prompt("Work", tmp_path, llm="claude")
    capsys.readouterr()

    logs = sorted((tmp_path / "logs").glob("*.llm.log"))
    assert len(logs) == 1
    recorded = logs[0].read_text(encoding="utf-8")
    assert "Calling CLAUDE" in recorded
    assert "Completed CLAUDE" in recorded
    # The accounting line the console no longer shows is preserved here.
    assert "elapsed=" in recorded
    # A stderr artifact still means the provider reported something on stderr.
    assert sorted((tmp_path / "logs").glob("*.stderr.log")) == []


def test_sub_command_labels_console_progress_but_not_the_evidence_command(
    tmp_path, monkeypatch, capsys
):
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
        "Work", tmp_path, llm="claude", model="m", command_name="plan", sub_command="topology"
    )
    out = capsys.readouterr().out

    assert "Calling CLAUDE/m (plan · topology)..." in out
    assert "Completed CLAUDE/m (plan · topology)  rc=0" in out
    record = (tmp_path / "logs" / "llm.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    job = json.loads(record)["job"]
    assert job["command_name"] == "plan"
    assert job["sub_command"] == "topology"


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

    captured = capsys.readouterr()
    assert "parameters=" in captured.err
    assert "[prompt]" in captured.out
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
        "cached=160,437 (88% hit) · uncached=21,904 · write 12,010 · out=4,812 · cost=$0.6100"
    )


def test_token_summary_treats_codex_input_as_cache_inclusive():
    from drydock.llm import LlmStats, format_token_summary

    line = format_token_summary(
        LlmStats(input_tokens=1_000, cached_input_tokens=900, output_tokens=50),
        llm="codex",
    )
    assert line == "cached=900 (90% hit) · uncached=100 · out=50"


def test_token_summary_omits_absent_segments():
    from drydock.llm import LlmStats, format_token_summary

    assert format_token_summary(LlmStats(output_tokens=12), llm="claude") == "out=12"
    assert format_token_summary(LlmStats(model="x", elapsed_ms=10), llm="claude") is None
    assert format_token_summary(None, llm="claude") is None


def test_done_line_uses_two_line_format_without_timestamp_or_execution_id():
    from drydock.llm import LlmStats, _performance_summary

    line = _performance_summary(
        llm="codex",
        command_name="build",
        execution_id="exec-1",
        returncode=0,
        stats=LlmStats(
            model="gpt-5.6-luna",
            elapsed_ms=444_000,
            input_tokens=4_831_579,
            cached_input_tokens=4_673_280,
            output_tokens=13_768,
        ),
    )
    assert line == (
        "  Completed CODEX/gpt-5.6-luna (build)  rc=0\n"
        "    elapsed=7m 24.0s   cached=4,673,280 (97% hit)   uncached=158,299   "
        "out=13,768   tps=31.0"
    )


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
    """Shell that prints a line, backgrounds a child holding stdout, then exits.

    The shell exits only after the child has written its pid, so the child provably exists and
    holds stdout before the reaper runs. Without the wait, interpreter start-up under a loaded
    parallel suite outlasts the drain grace and the child is reaped before it starts.
    """
    return (
        f'python3 -c "import os,sys,time;'
        f"sys.stdout.write('held\\n');sys.stdout.flush();"
        f"open({str(marker)!r},'w').write(str(os.getpid()));"
        f'time.sleep({hold_seconds})" & '
        f"while [ ! -s {shlex.quote(str(marker))} ]; do sleep 0.01; done; "
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


def test_claude_command_supports_explicit_session_start_and_resume(tmp_path):
    from types import SimpleNamespace

    from drydock.llm import _command

    artifacts = SimpleNamespace(output_file=tmp_path / "out.txt")
    started = _command("claude", tmp_path, artifacts, "sonnet", claude_session_id="start-session")
    resumed = _command(
        "claude", tmp_path, artifacts, "sonnet", claude_resume_session_id="resume-session"
    )

    assert started[started.index("--session-id") + 1] == "start-session"
    assert "--resume" not in started
    assert resumed[resumed.index("--resume") + 1] == "resume-session"
    assert "--session-id" not in resumed


def test_claude_prompt_session_resumes_only_an_extended_or_explicitly_reused_context():
    from drydock.llm import ClaudePromptSession

    session = ClaudePromptSession()
    started = session.invocation("base", "sonnet")
    resumed = session.invocation("base\nrepair", "sonnet")
    restarted = session.invocation("different", "sonnet")
    delta_resumed = session.invocation("only the appended ledger", "sonnet", context_reused=True)
    model_restarted = session.invocation("only the appended ledger\nnext", "haiku")

    assert started.keys() == {"claude_session_id"}
    assert resumed == {"claude_resume_session_id": started["claude_session_id"]}
    assert restarted.keys() == {"claude_session_id"}
    assert restarted["claude_session_id"] != started["claude_session_id"]
    assert delta_resumed == {"claude_resume_session_id": restarted["claude_session_id"]}
    assert model_restarted.keys() == {"claude_session_id"}
    assert model_restarted["claude_session_id"] != restarted["claude_session_id"]


def test_claude_session_is_queryable_in_execution_evidence(tmp_path, monkeypatch):
    """The record and operator log distinguish a session start from a resume."""
    from drydock import llm as llm_module

    monkeypatch.setattr(llm_module, "_command", lambda *_args, **_kwargs: ("true",))

    result = llm_module.run_prompt(
        "continue",
        tmp_path,
        llm="claude",
        model="sonnet",
        command_name="plan",
        claude_resume_session_id="session-123",
        announce=False,
    )

    record = _records(tmp_path)[0]
    assert record["job"]["claude_session"] == {"mode": "resume", "id": "session-123"}
    assert "Claude session: resume id=session-123" in result.artifacts.llm_log_file.read_text()


def _run_effort(tmp_path, monkeypatch, llm: str, model: str, effort: str | None = None):
    from drydock import llm as llm_module

    seen: dict = {}

    def fake_command(*_args, **kwargs):
        seen.update(kwargs)
        return ("true",)

    monkeypatch.setattr(llm_module, "_command", fake_command)
    monkeypatch.delenv("DRYDOCK_EFFORT", raising=False)
    llm_module.run_prompt("x", tmp_path, llm=llm, model=model, effort=effort, announce=False)
    return seen["effort"]


@pytest.mark.parametrize(
    ("llm", "model", "expected"),
    [
        ("claude", "opus", "low"),
        ("claude", "claude-opus-5-5", "low"),
        ("codex", "gpt-6.1-sol", "low"),
        ("claude", "sonnet", None),
        ("codex", "gpt-5.6-luna", None),
    ],
)
def test_model_row_effort_applies_when_none_is_requested(
    tmp_path, monkeypatch, llm, model, expected
):
    assert _run_effort(tmp_path, monkeypatch, llm, model) == expected


def test_requested_effort_overrides_the_model_row(tmp_path, monkeypatch):
    assert _run_effort(tmp_path, monkeypatch, "claude", "opus", effort="high") == "high"
    monkeypatch.setenv("DRYDOCK_EFFORT", "medium")
    from drydock import llm as llm_module

    seen: dict = {}
    monkeypatch.setattr(llm_module, "_command", lambda *_a, **kw: seen.update(kw) or ("true",))
    llm_module.run_prompt("x", tmp_path, llm="claude", model="opus", announce=False)
    assert seen["effort"] == "medium"


def test_sol_selects_codex():
    from drydock.llm import resolve_provider

    assert resolve_provider(None, "sol") == "codex"
    assert resolve_provider(None, "gpt-6.1-sol") == "codex"


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


def test_full_cli_and_sub_command_are_recorded_in_execution_record(monkeypatch, tmp_path):
    """New fields full_cli and sub_command are captured in llm.jsonl records."""
    from drydock import llm as llm_module
    from drydock.llm_usage import read_records

    def fake_command(*args, **kwargs):
        return ("true",)

    monkeypatch.setattr(llm_module, "_command", fake_command)

    result = llm_module.run_prompt(
        "hello",
        tmp_path,
        llm="claude",
        model="haiku",
        command_name="analyze",
        target="test-project",
        log_dir=tmp_path,
        announce=False,
        full_cli="drydock analyze --llm=claude --model=haiku test-project",
        sub_command="codex",
    )

    assert result.ok
    records, _ = read_records(tmp_path / "llm.jsonl")
    assert len(records) == 1

    record = records[0]
    job = record.get("job", {})
    result_section = record.get("result", {})

    # Check new fields in job
    assert job.get("full_cli") == "drydock analyze --llm=claude --model=haiku test-project"
    assert job.get("sub_command") == "codex"

    # Check timing in result
    assert "timing" in result_section
    timing = result_section.get("timing", {})
    assert timing.get("client_elapsed_ms") is not None
    assert isinstance(timing.get("client_elapsed_ms"), int)
    assert timing.get("client_elapsed_ms") >= 0
    # llm_server_duration_ms may be None if provider doesn't report it
    assert "llm_server_duration_ms" in timing


def test_new_record_fields_are_optional(monkeypatch, tmp_path):
    """Existing code that doesn't pass full_cli/sub_command still works."""
    from drydock import llm as llm_module
    from drydock.llm_usage import read_records

    def fake_command(*args, **kwargs):
        return ("true",)

    monkeypatch.setattr(llm_module, "_command", fake_command)

    # Call run_prompt WITHOUT full_cli and sub_command
    result = llm_module.run_prompt(
        "hello",
        tmp_path,
        llm="claude",
        model="haiku",
        command_name="plan",
        target="other-project",
        log_dir=tmp_path,
        announce=False,
    )

    assert result.ok
    records, _ = read_records(tmp_path / "llm.jsonl")
    assert len(records) == 1

    record = records[0]
    job = record.get("job", {})

    # Fields should be present but None
    assert job.get("full_cli") is None
    assert job.get("sub_command") is None


def _claude_stream(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def _text(text: str) -> dict:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    }


def _stop(reason: str, output_tokens: int, thinking_tokens: int) -> dict:
    return {
        "type": "stream_event",
        "event": {
            "type": "message_delta",
            "delta": {"stop_reason": reason},
            "usage": {
                "output_tokens": output_tokens,
                "output_tokens_details": {"thinking_tokens": thinking_tokens},
            },
        },
    }


def _truncated_analyze_stream() -> str:
    """The observed Haiku failure: cut inside SEA_TRIALS.md, then the artifact restarted."""
    return _claude_stream(
        _text("=== BEGIN ARTIFACT ANALYSIS.md ===\n# Analysis\n=== END ARTIFACT ===\n"),
        _text("=== BEGIN ARTIFACT SEA_TRIALS.md ===\n## st-001: Setup\nARCHITECTURE.md states"),
        _stop("max_tokens", 32000, 15845),
        _text("=== BEGIN ARTIFACT SEA_TRIALS.md ===\n## st-001: Setup\n=== END ARTIFACT ===\n"),
        _stop("end_turn", 2224, 121),
        {"type": "result", "result": "", "model": "claude-haiku-4-5", "usage": {}},
    )


def _capture_env(monkeypatch, raw: str) -> dict:
    captured: dict = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return FakePopen(command, stdout_text=raw, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return captured


def test_run_claude_haiku_4_gets_the_output_ceiling_and_a_fixed_thinking_budget(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("DRYDOCK_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("DRYDOCK_HAIKU_THINKING_TOKENS", raising=False)
    # Drydock owns both settings; values inherited from the caller's shell are replaced.
    monkeypatch.setenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "1")
    monkeypatch.setenv("MAX_THINKING_TOKENS", "999")
    captured = _capture_env(monkeypatch, _claude_stream(_text("READY")))

    result = run_prompt(
        "Reply READY", tmp_path, llm="claude", model="claude-haiku-4-5", announce=False
    )

    assert result.ok
    assert captured["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "128000"
    assert captured["env"]["MAX_THINKING_TOKENS"] == "16000"


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "haiku"])
def test_run_claude_haiku_5_5_sizes_thinking_from_effort_not_a_budget(tmp_path, monkeypatch, model):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("DRYDOCK_MAX_OUTPUT_TOKENS", raising=False)
    # Haiku 5.5 rejects a fixed thinking budget, so an inherited one is removed.
    monkeypatch.setenv("MAX_THINKING_TOKENS", "999")
    captured = _capture_env(monkeypatch, _claude_stream(_text("READY")))

    result = run_prompt(
        "Reply READY", tmp_path, llm="claude", model=model, effort="low", announce=False
    )

    assert result.ok
    assert captured["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "128000"
    assert "MAX_THINKING_TOKENS" not in captured["env"]
    assert captured["command"][captured["command"].index("--model") + 1] == model
    assert captured["command"][captured["command"].index("--effort") + 1] == "low"


def test_run_claude_sonnet_gets_the_output_ceiling_and_never_a_thinking_budget(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DRYDOCK_MAX_OUTPUT_TOKENS", "64000")
    monkeypatch.setenv("MAX_THINKING_TOKENS", "999")
    captured = _capture_env(monkeypatch, _claude_stream(_text("READY")))

    result = run_prompt("Reply READY", tmp_path, llm="claude", model="sonnet", announce=False)

    assert result.ok
    assert captured["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "64000"
    assert "MAX_THINKING_TOKENS" not in captured["env"]


def test_run_claude_fails_a_text_response_cut_at_the_output_limit(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DRYDOCK_MAX_OUTPUT_TOKENS", "128000")
    monkeypatch.setenv("DRYDOCK_HAIKU_THINKING_TOKENS", "16000")
    _capture_env(monkeypatch, _truncated_analyze_stream())

    result = run_prompt(
        "Analyze", tmp_path, llm="claude", model="claude-haiku-4-5", command_name="analyze"
    )

    # The CLI continued the response, so the process succeeded; the response is still unusable.
    assert result.returncode == 0
    assert not result.ok
    assert "32000 tokens (15845 spent on thinking)" in result.failure
    assert "inside SEA_TRIALS.md" in result.failure
    record = _records(tmp_path)[-1]
    assert record["status"] == "failed"
    assert record["result"]["truncation"] == {
        "output_tokens": 32000,
        "thinking_tokens": 15845,
        "open_artifact": "SEA_TRIALS.md",
    }
    banner = capsys.readouterr().err
    assert "FATAL ERROR - LLM OUTPUT TRUNCATED" in banner
    assert "drydock config set haiku_thinking_tokens 8000" in banner
    assert "32000 tokens is this model's output maximum" in banner


def test_truncation_advice_for_an_effort_model_names_effort_and_the_output_limit(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DRYDOCK_MAX_OUTPUT_TOKENS", "32000")
    _capture_env(monkeypatch, _truncated_analyze_stream())

    result = run_prompt("Analyze", tmp_path, llm="claude", model="sonnet", command_name="analyze")

    assert not result.ok
    banner = capsys.readouterr().err
    assert "--effort low" in banner
    assert "haiku_thinking_tokens" not in banner
    assert "drydock config set max_output_tokens <tokens>" in banner


def test_run_claude_records_but_does_not_fail_truncation_in_a_tool_run(tmp_path, monkeypatch):
    _capture_env(monkeypatch, _truncated_analyze_stream())

    result = run_prompt("Build", tmp_path, llm="claude", model="haiku", allow_tools=True)

    assert result.ok
    record = _records(tmp_path)[-1]
    assert record["status"] == "succeeded"
    assert record["result"]["truncation"]["output_tokens"] == 32000


def _gemini_payload(
    *, response: str = "OK", error: dict | None = None, indent: int | None = 2
) -> str:
    """One ``gemini --output-format json`` transcript, shaped as the CLI really emits it.

    The two-model split is not synthetic: a router model classifies the request before the
    main model answers, and both are billed.
    """
    payload: dict = {"session_id": "decdcc88-dc5a-4f93-bb79-39e0f9ba044f"}
    if error is not None:
        payload["error"] = error
        return json.dumps(payload, indent=indent)
    payload["response"] = response
    payload["stats"] = {
        "models": {
            "gemini-3.1-flash-lite": {
                "api": {"totalRequests": 1, "totalErrors": 0, "totalLatencyMs": 4364},
                "tokens": {
                    "input": 2706,
                    "prompt": 2706,
                    "candidates": 34,
                    "total": 3206,
                    "cached": 0,
                    "thoughts": 466,
                    "tool": 0,
                },
                "roles": {"utility_router": {"totalRequests": 1}},
            },
            "gemini-3.5-flash": {
                "api": {"totalRequests": 1, "totalErrors": 0, "totalLatencyMs": 1782},
                "tokens": {
                    "input": 9718,
                    "prompt": 9718,
                    "candidates": 1,
                    "total": 9959,
                    "cached": 512,
                    "thoughts": 240,
                    "tool": 0,
                },
                "roles": {"main": {"totalRequests": 1}},
            },
        },
        "tools": {"totalCalls": 3, "totalSuccess": 3, "totalFail": 0},
        "files": {"totalLinesAdded": 0, "totalLinesRemoved": 0},
    }
    return json.dumps(payload, indent=indent)


def test_gemini_command_is_headless_and_read_only_without_tools(tmp_path):
    artifacts = drydock.llm.ExecutionArtifacts.create(tmp_path, "analyze", "gemini")

    command = drydock.llm._command(
        "gemini", tmp_path, artifacts, model="gemini-3.5-flash", allow_tools=False
    )

    assert command[0] == "gemini"
    # Headless gemini refuses an untrusted directory outright.
    assert "--skip-trust" in command
    assert ("--output-format", "json") == command[command.index("--output-format") :][:2]
    assert command[command.index("--approval-mode") + 1] == "plan"
    assert command[command.index("--model") + 1] == "gemini-3.5-flash"
    # ``--prompt`` selects headless mode; the prompt text itself arrives on stdin.
    assert command[-2:] == ("--prompt", "")


def test_gemini_command_allows_writes_for_build(tmp_path):
    artifacts = drydock.llm.ExecutionArtifacts.create(tmp_path, "build", "gemini")

    command = drydock.llm._command("gemini", tmp_path, artifacts, model=None, allow_tools=True)

    assert command[command.index("--approval-mode") + 1] == "yolo"
    assert "--model" not in command


def test_gemini_effort_is_not_passed_through(tmp_path):
    """gemini exposes no reasoning-effort control; Drydock's ladder has nothing to map onto."""
    artifacts = drydock.llm.ExecutionArtifacts.create(tmp_path, "analyze", "gemini")

    command = drydock.llm._command(
        "gemini", tmp_path, artifacts, model=None, allow_tools=False, effort="xhigh"
    )

    assert "xhigh" not in command


def test_run_gemini_returns_response_and_sums_tokens_across_billed_models(tmp_path, monkeypatch):
    raw = _gemini_payload()
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return FakePopen(command, stdout_text=raw, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = run_prompt("Say OK.", tmp_path, llm="gemini", command_name="analyze")

    assert result.ok
    assert result.text == "OK"
    # The model that served the ``main`` role, not the router that preceded it.
    assert result.stats.model == "gemini-3.5-flash"
    assert result.stats.input_tokens == 2706 + 9718
    assert result.stats.cached_input_tokens == 512
    # ``thoughts`` are generated and billed, so they count as output alongside ``candidates``.
    assert result.stats.output_tokens == 34 + 466 + 1 + 240
    assert result.stats.turns == 2
    assert result.stats.duration_ms == 4364 + 1782
    # gemini reports no per-call cost.
    assert result.stats.cost_usd is None


def test_gemini_transcript_survives_console_preamble_before_the_json(tmp_path, monkeypatch):
    """The CLI prints unstructured notices before its payload; parsing starts at the brace."""
    raw = "Warning: True color (24-bit) support not detected.\nRipgrep is not available.\n"
    raw += _gemini_payload(response="Parsed anyway")

    monkeypatch.setattr(
        subprocess, "Popen", lambda command, **kwargs: FakePopen(command, stdout_text=raw, **kwargs)
    )

    result = run_prompt("Say OK.", tmp_path, llm="gemini", command_name="analyze")

    assert result.text == "Parsed anyway"
    assert result.stats.input_tokens == 2706 + 9718


def test_run_gemini_reports_error_payload_as_the_failure(tmp_path, monkeypatch):
    raw = _gemini_payload(
        error={
            "type": "Error",
            "message": "Resource has been exhausted (e.g. check quota).",
            "code": 429,
        }
    )

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(command, stdout_text=raw, returncode=41, **kwargs),
    )

    result = run_prompt("Say OK.", tmp_path, llm="gemini", command_name="analyze")

    assert not result.ok
    assert result.returncode == 41
    # The cause is only in the payload: a failed gemini run writes no stderr.
    assert "rate limit" in _records(tmp_path)[-1]["result"]["error"].lower()


def test_gemini_retired_model_error_on_stderr_reaches_the_caller(tmp_path, monkeypatch):
    """A model the API has retired fails before any response, so the cause is on stderr only.

    Reproduces a run against gemini-2.5-flash-lite after its withdrawal: stdout is empty, and
    the payload naming the retired model is written to stderr alongside console notices and a
    stack trace. Without this the operator sees nothing but a non-zero exit code.
    """
    stderr = (
        "Warning: True color (24-bit) support not detected.\n"
        "Ripgrep is not available. Falling back to GrepTool.\n"
        "Error when talking to Gemini API Full report available at: /tmp/gemini-client-error.json\n"
        "    at classifyGoogleError (file:///opt/gemini-cli/bundle/chunk.js:307106:12)\n"
        "    at async main (file:///opt/gemini-cli/bundle/gemini.js:17295:5) {\n"
        # The stack trace's closing fragment is brace-delimited but is not JSON, and precedes
        # the real payload. Parsing must not stop here.
        "  code: 404\n"
        "}\n"
        + _gemini_payload(
            error={
                "type": "Error",
                "message": (
                    "This model models/gemini-2.5-flash-lite is no longer available to new "
                    "users. Please update your code to use models/gemini-3.5-flash-lite"
                ),
                "code": 1,
            }
        )
    )

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command, stdout_text="", stderr_text=stderr, returncode=1, **kwargs
        ),
    )

    result = run_prompt("Say OK.", tmp_path, llm="gemini", command_name="analyze")

    assert not result.ok
    assert result.provider_error is not None
    assert "no longer available to new users" in result.provider_error

    detail = failure_detail(result, "Compass normalization failed: LLM execution failed")
    assert detail.startswith("Compass normalization failed: LLM execution failed: ")
    assert "gemini-2.5-flash-lite" in detail
    assert "gemini-3.5-flash-lite" in detail
    # The console notices and stack frames stay in the evidence file, not the message.
    assert "True color" not in detail
    assert "classifyGoogleError" not in detail


def test_failure_detail_falls_back_to_the_first_informative_stderr_line(tmp_path, monkeypatch):
    """A provider that reports no structured error still yields an actionable message."""
    stderr = (
        "Warning: True color (24-bit) support not detected.\n"
        "fatal: credential store is locked\n"
        "    at openStore (file:///opt/cli/bundle/chunk.js:12:1)\n"
    )

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(
            command, stdout_text="", stderr_text=stderr, returncode=1, **kwargs
        ),
    )

    result = run_prompt("Say OK.", tmp_path, llm="gemini", command_name="analyze")

    assert failure_detail(result) == "LLM execution failed: fatal: credential store is locked"


def test_failure_detail_is_the_bare_summary_when_nothing_explains_the_failure(tmp_path):
    """No cause available is reported as before, rather than as an empty appended reason."""
    result = LlmResult(
        execution_id="x",
        llm="gemini",
        command=("gemini",),
        working_directory=tmp_path,
        returncode=1,
        text="",
        stderr="",
        stats=LlmStats(),
        artifacts=None,
        record={},
    )

    assert failure_detail(result) == "LLM execution failed"


def test_gemini_missing_key_is_reported_as_an_authentication_failure(tmp_path, monkeypatch, capsys):
    raw = _gemini_payload(
        error={
            "type": "Error",
            "message": (
                "Please set an Auth method in your settings.json or specify one of the "
                "following environment variables before running: GEMINI_API_KEY"
            ),
            "code": 41,
        }
    )

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(command, stdout_text=raw, returncode=41, **kwargs),
    )

    result = run_prompt("Say OK.", tmp_path, llm="gemini", command_name="analyze")

    assert not result.ok
    # gemini has no login subcommand: the remedy is an environment variable.
    assert "export GEMINI_API_KEY=..." in capsys.readouterr().err


def test_gemini_isolates_its_config_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    real_gemini = fake_home / ".gemini"
    real_gemini.mkdir(parents=True)
    (real_gemini / "settings.json").write_text('{"theme": "user"}')
    (real_gemini / "GEMINI.md").write_text("# ambient instructions\n")

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("GEMINI_API_KEY", "from-the-environment")
    captured = {}

    def fake_popen(command, **kwargs):
        captured["env"] = kwargs["env"]
        return FakePopen(command, stdout_text=_gemini_payload(), **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    run_prompt("Say OK.", tmp_path, llm="gemini", command_name="analyze")

    isolated_home = Path(captured["env"]["HOME"])
    assert isolated_home == fake_home / ".drydock" / "gemini-home"
    assert isolated_home.is_dir()
    # Nothing of the user's own gemini configuration follows the subprocess in.
    assert not (isolated_home / "settings.json").exists()
    assert not (isolated_home / "GEMINI.md").exists()
    # Authentication is an environment variable, so isolating HOME must not break it.
    assert captured["env"]["GEMINI_API_KEY"] == "from-the-environment"


def test_provider_model_conflict_flags_gemini_with_claude_model():
    conflict = drydock.llm.provider_model_conflict("gemini", "claude-opus-5")

    assert conflict is not None
    assert "--llm-provider claude" in conflict


def test_provider_model_conflict_allows_gemini_models():
    assert drydock.llm.provider_model_conflict("gemini", "gemini-3.5-flash") is None
    assert drydock.llm.provider_model_conflict("gemini", "gemma-3") is None


def test_provider_is_inferred_from_the_model(isolated_config):
    """A recognized model names its own provider, so --llm-provider is unnecessary."""
    assert drydock.llm.resolve_provider(None, "gemini-3.5-flash") == "gemini"
    assert drydock.llm.resolve_provider(None, "gpt-5.6-luna") == "codex"
    assert drydock.llm.resolve_provider(None, "claude-opus-5") == "claude"


def test_inferred_provider_beats_the_configured_one(isolated_config, monkeypatch):
    """The model is the specific instruction; the configured provider is only a fallback."""
    monkeypatch.setenv("LLM_PROVIDER", "codex")

    assert drydock.llm.resolve_provider(None, "gemini-3.5-flash") == "gemini"


def test_unrecognized_model_falls_back_to_the_configured_provider(isolated_config, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    assert drydock.llm.resolve_provider(None, "some-unreleased-model") == "gemini"


def test_explicit_provider_wins_over_the_model(isolated_config):
    """An explicit choice is still honored here; the conflict check reports the contradiction."""
    assert drydock.llm.resolve_provider("claude", "gemini-3.5-flash") == "claude"
    assert drydock.llm.provider_model_conflict("claude", "gemini-3.5-flash") is not None


def test_claude_build_gets_only_the_code_builder_tools(tmp_path):
    artifacts = drydock.llm.ExecutionArtifacts.create(tmp_path, "build", "claude")
    command = drydock.llm._command("claude", tmp_path, artifacts, model="haiku", allow_tools=True)
    assert command[command.index("--tools") + 1] == "Bash,Read,Edit,Write,Glob,Grep"
    assert "--strict-mcp-config" in command
    assert "--dangerously-skip-permissions" in command


def test_codex_build_disables_tools_a_builder_does_not_use(tmp_path):
    artifacts = drydock.llm.ExecutionArtifacts.create(tmp_path, "build", "codex")
    command = drydock.llm._command("codex", tmp_path, artifacts, model="gpt-5", allow_tools=True)
    disabled = {command[i + 1] for i, arg in enumerate(command) if arg == "--disable"}
    assert {"apps", "browser_use", "computer_use", "image_generation"} <= disabled
    assert command[-1] == "-"


def _usage_event(tokens: int) -> dict:
    return {"type": "assistant", "message": {"usage": {"input_tokens": tokens}}}


def _init_event() -> dict:
    return {
        "type": "system",
        "subtype": "init",
        "model": "claude-haiku-5-5",
        "claude_code_version": "2.1.296",
    }


def test_haiku_prompt_over_the_price_limit_runs_on_the_escalation_model(tmp_path, monkeypatch):
    captured = _capture_env(monkeypatch, _claude_stream(_text("OK")))
    prompt = "x" * (100_000 * 4)  # tests pin 4 bytes per token

    result = run_prompt(prompt, tmp_path, llm="claude", model="haiku", announce=False)

    command = captured["command"]
    assert command[command.index("--model") + 1] == "sonnet"
    escalation = result.record["job"]["parameters"]["escalation"]
    assert escalation.startswith("upgraded=prompt_limit haiku->sonnet")


def test_haiku_prompt_under_the_price_limit_stays_on_haiku(tmp_path, monkeypatch):
    captured = _capture_env(monkeypatch, _claude_stream(_text("OK")))

    result = run_prompt("x" * 4000, tmp_path, llm="claude", model="haiku", announce=False)

    command = captured["command"]
    assert command[command.index("--model") + 1] == "haiku"
    assert "escalation" not in result.record["job"]["parameters"]


def test_resumed_session_context_counts_toward_the_price_limit(tmp_path, monkeypatch):
    session = "11111111-2222-3333-4444-555555555555"
    _capture_env(monkeypatch, _claude_stream(_init_event(), _usage_event(99_500), _text("OK")))
    run_prompt(
        "x" * 4000,
        tmp_path,
        llm="claude",
        model="haiku",
        announce=False,
        claude_session_id=session,
    )
    captured = _capture_env(monkeypatch, _claude_stream(_text("OK")))

    run_prompt(
        "fix it",
        tmp_path,
        llm="claude",
        model="haiku",
        announce=False,
        claude_resume_session_id=session,
    )

    command = captured["command"]
    assert command[command.index("--model") + 1] == "sonnet"


def test_claude_run_records_a_calibration_observation(tmp_path, monkeypatch):
    _capture_env(monkeypatch, _claude_stream(_init_event(), _usage_event(9_437), _text("OK")))

    run_prompt(
        "x" * 8000,
        tmp_path,
        llm="claude",
        model="haiku",
        allow_tools=True,
        announce=False,
        log_dir=tmp_path / "logs",
    )

    (observation,) = drydock.model_config.read_observations(tmp_path / "logs")
    assert observation.model == "haiku"
    assert observation.mode == "build"
    assert observation.prompt_bytes == 8000
    assert observation.first_request_tokens == 9_437
    assert observation.cli_version == "2.1.296"
    assert not observation.resumed


@pytest.mark.parametrize("output_format", [None, "json", "artifacts"])
def test_output_cleanup_is_opt_in_and_preserves_evidence(tmp_path, monkeypatch, output_format):
    payload = (
        "=== BEGIN ARTIFACT A.md ===\nbody\n=== END ARTIFACT ===\n"
        if output_format == "artifacts"
        else '{"a": 1}'
    )
    original = "Here it is.\n" + payload
    raw = json.dumps({"type": "result", "result": original}) + "\n"
    monkeypatch.setattr(
        subprocess, "Popen", lambda command, **kwargs: FakePopen(command, stdout_text=raw, **kwargs)
    )
    result = run_prompt("Work", tmp_path, llm="claude", output_format=output_format)
    assert result.ok
    assert result.text == (payload if output_format else original)
    assert result.artifacts.output_file.read_text() == original
    if output_format:
        assert result.record["output_contract"]["removed"] == ["Here it is.\n"]
        assert result.record["output_contract"]["defect"] is None
    else:
        assert "output_contract" not in result.record


def test_json_cleanup_reads_the_final_turn_when_earlier_turns_streamed_narration(
    tmp_path, monkeypatch
):
    """ReadingList UAT 20261023.022430: a tool-using grader streamed 789 characters of turn
    narration ahead of a clean fenced JSON final turn, and the whole reply was rejected."""
    narration = "I'll read the tree first. " * 30 + "The probe is the documented path."
    final = '```json\n{"a": 1}\n```'
    raw = _claude_stream(_text(narration), _text(final), {"type": "result", "result": final})
    monkeypatch.setattr(
        subprocess, "Popen", lambda command, **kwargs: FakePopen(command, stdout_text=raw, **kwargs)
    )

    result = run_prompt("Work", tmp_path, llm="claude", output_format="json")

    assert result.text == '{"a": 1}'
    assert result.artifacts.output_file.read_text() == narration + final
    assert result.record["output_contract"]["defect"] is None
    assert result.record["output_contract"]["removed"] == ["earlier-turn text", "JSON code fence"]


def test_artifact_cleanup_never_narrows_to_the_final_turn(tmp_path, monkeypatch):
    """Artifacts may be written across turns; only a single JSON value narrows to the last."""
    stream = "x" * 600 + "\n=== BEGIN ARTIFACT A.md ===\nbody\n=== END ARTIFACT ===\n"
    final = "=== BEGIN ARTIFACT A.md ===\nbody\n=== END ARTIFACT ===\n"
    raw = _claude_stream(_text(stream), {"type": "result", "result": final})
    monkeypatch.setattr(
        subprocess, "Popen", lambda command, **kwargs: FakePopen(command, stdout_text=raw, **kwargs)
    )

    result = run_prompt("Work", tmp_path, llm="claude", output_format="artifacts")

    assert result.text == stream
    assert result.record["output_contract"]["defect"]


def test_invalid_output_format_fails_before_provider_execution(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Provider must not run")

    monkeypatch.setattr(subprocess, "Popen", unexpected)
    with pytest.raises(LlmConfigurationError, match="Unsupported output format"):
        run_prompt("Work", tmp_path, llm="claude", output_format="guess")


def test_ambiguous_output_is_not_rewritten_or_retried(tmp_path, monkeypatch):
    original = '{"a": 1, "a": 2}'
    raw = json.dumps({"type": "result", "result": original}) + "\n"
    calls = []

    def invoke(command, **kwargs):
        calls.append(command)
        return FakePopen(command, stdout_text=raw, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", invoke)
    result = run_prompt("Work", tmp_path, llm="claude", output_format="json")
    assert result.text == original
    assert result.record["output_contract"]["defect"] == "duplicate JSON key: a"
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_final_artifact_close_repair_records_evidence_without_an_extra_call(
    tmp_path, monkeypatch, provider
):
    from hashlib import sha256

    original = "=== BEGIN ARTIFACT FEATURE-X.md ===\n# FEATURE: X\n=== END ARTIFACT"
    expected = original + " ==="
    event = (
        {"type": "result", "result": original}
        if provider == "claude"
        else {"type": "item.completed", "item": {"type": "agent_message", "text": original}}
    )
    raw = json.dumps(event) + "\n"
    calls = []

    def invoke(command, **kwargs):
        calls.append(command)
        if provider == "codex":
            Path(command[command.index("--output-last-message") + 1]).write_text(original)
        return FakePopen(command, stdout_text=raw, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", invoke)
    progress = []
    result = run_prompt(
        "Work",
        tmp_path,
        llm=provider,
        command_name="plan",
        output_format="artifacts",
        on_text=progress.append,
    )
    assert result.ok
    assert result.text == expected
    assert len(calls) == 1
    assert result.artifacts.output_file.read_text() == original
    assert result.artifacts.raw_file.read_text() == raw
    contract = _records(tmp_path)[-1]["output_contract"]
    assert contract["repaired"] == [
        "FEATURE-X.md: completed final `=== END ARTIFACT` as `=== END ARTIFACT ===`"
    ]
    assert contract["normalized_sha256"] == sha256(expected.encode()).hexdigest()
    assert contract["defect"] is None
    assert any("[output] artifacts repaired: FEATURE-X.md:" in line for line in progress)


def test_plan_continuation_accepts_repaired_provider_output_in_one_pass(tmp_path, monkeypatch):
    from drydock.plan_topology import PlannedStory
    from drydock.planning_session import _continue_short_plan

    original = "=== BEGIN ARTIFACT FEATURE-X.md ===\n# FEATURE: X\n=== END ARTIFACT"
    calls = []

    def invoke(command, **kwargs):
        calls.append(command)
        Path(command[command.index("--output-last-message") + 1]).write_text(original)
        raw = (
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": original},
            })
            + "\n"
        )
        return FakePopen(command, stdout_text=raw, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", invoke)
    result = _continue_short_plan(
        {"TOPOLOGY.md": "One frozen story."},
        blocks_text="=== TOPOLOGY.md ===\nOne frozen story.\n=== END TOPOLOGY.md ===\n",
        prompt_assembly=PromptAssembly.single_prompt("CONTEXT\n"),
        declared=(PlannedStory(story_id="story-x", implements="FEATURE-X.md"),),
        target="Example",
        target_dir=tmp_path,
        llm_provider="codex",
        model="gpt-6-luna",
        log_dir=tmp_path / "logs",
        runner=run_prompt,
        on_text=None,
        attempts=3,
        initial_execution_id="exec-topology",
    )
    assert result.score.is_complete
    assert result.blocks["FEATURE-X.md"] == "# FEATURE: X"
    assert len(calls) == result.passes == 1
