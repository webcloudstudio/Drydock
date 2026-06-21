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
from drydock.errors import LlmError
from drydock.llm import run_prompt


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


def test_run_claude_saves_prompt_logs_stats_and_reproducible_job(tmp_path, monkeypatch):
    raw = "\n".join(
        [
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "READY"},
                    },
                }
            ),
            json.dumps(
                {
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
                }
            ),
        ]
    )
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
    assert record["result"]["raw_sha256"]
    assert record["result"]["output_sha256"]
    assert [event["event"] for event in _events(tmp_path)] == [
        "execution.started",
        "provider.event",
        "provider.event",
        "execution.completed",
    ]
    assert _events(tmp_path)[1]["provider_event_type"] == "stream_event"


def test_claude_content_block_boundaries_are_forwarded_to_live_output(tmp_path, monkeypatch):
    raw = "\n".join(
        [
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_start",
                        "content_block": {"type": "text", "text": ""},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "First step."},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_start",
                        "content_block": {"type": "text", "text": ""},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "Second step."},
                    },
                }
            ),
            json.dumps({"type": "result", "result": "Second step."}),
        ]
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: FakePopen(command, stdout_text=raw + "\n", **kwargs),
    )
    chunks = []

    run_prompt("Work", tmp_path, llm="claude", on_text=chunks.append)

    assert chunks == ["\n", "First step.", "\n", "Second step."]


def test_run_codex_streams_agent_message_and_removes_api_environment(tmp_path, monkeypatch):
    raw = json.dumps(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "CODEX READY"},
            "model": "codex-test",
            "usage": {"input_tokens": 8, "output_tokens": 2},
        }
    )

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
    assert result.stats.model == "codex-test"
    assert chunks == ["CODEX READY"]


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
        lambda llm, working_directory, artifacts, model, allow_tools=False: (sys.executable, "-u", "-c", code),
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
        lambda llm, working_directory, artifacts, model, allow_tools=False: (sys.executable, "-u", "-c", code),
    )

    result = run_prompt("ignored", tmp_path, llm="claude", timeout_seconds=0.1)

    assert not result.ok
    assert result.returncode == 124
    record = _records(tmp_path)[0]
    assert record["status"] == "failed"
    assert record["result"]["timed_out"] is True


def test_interrupt_terminates_process_and_writes_failed_record(tmp_path, monkeypatch):
    raw = json.dumps(
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "stop"},
        }
    )
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

    assert "parameters=" in result.artifacts.log_file.read_text()
    assert "parameters=" not in capsys.readouterr().err
