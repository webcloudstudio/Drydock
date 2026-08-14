"""Every Drydock log file derives its name from one shared basename builder."""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime

import pytest

from drydock.cli import _invocation_uses_llm, _log_llm, _log_target
from drydock.execution import ExecutionArtifacts, log_basename, log_component, log_timestamp
from drydock.logging import setup_command_logging

TIMESTAMP = "20260725.004228.288Z"
TIMESTAMP_RE = re.compile(r"^\d{8}\.\d{6}\.\d{3}Z$")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("commonmark_2", "commonmark_2"),
        ("rigging compact", "rigging-compact"),
        ("Config Show", "config-show"),
        ("  codex  ", "codex"),
        ("", ""),
        ("--", ""),
    ],
)
def test_log_component_normalizes_consistently(value, expected):
    assert log_component(value) == expected


def test_log_timestamp_is_readable_and_sortable():
    value = datetime(2026, 7, 25, 0, 42, 28, 288279, tzinfo=UTC)
    assert log_timestamp(value) == TIMESTAMP
    assert TIMESTAMP_RE.match(log_timestamp(value))
    earlier = datetime(2026, 7, 24, 23, 59, 59, 999999, tzinfo=UTC)
    assert log_timestamp(earlier) < log_timestamp(value)


def test_log_basename_omits_empty_parts():
    assert log_basename(TIMESTAMP, "", "status", "") == f"{TIMESTAMP}_status"
    assert (
        log_basename(TIMESTAMP, "commonmark_2", "import", "") == f"{TIMESTAMP}_commonmark_2_import"
    )
    assert (
        log_basename(TIMESTAMP, "commonmark_2", "analyze", "codex")
        == f"{TIMESTAMP}_commonmark_2_analyze_codex"
    )


def test_transcript_and_evidence_share_one_stem(tmp_path):
    """A transcript and its LLM evidence carry the identical target/command/provider stem."""
    logs = tmp_path / "logs"

    logging = setup_command_logging(
        logs, "analyze", stdout=sys.stdout, target="commonmark_2", llm="codex"
    )
    logging.stdout.write("analyzing\n")
    logging.close()

    artifacts = ExecutionArtifacts.create(
        tmp_path, "analyze", "codex", log_dir=logs, target="commonmark_2"
    )

    stem = "_commonmark_2_analyze_codex"
    assert logging.transcript_path.name.endswith(f"{stem}.log")
    assert artifacts.prompt_file.name.endswith(f"{stem}.prompt.md")


def test_evidence_names_keep_the_full_stamp_before_the_extension(tmp_path):
    """The dotted timestamp must survive extension handling on every evidence file."""
    artifacts = ExecutionArtifacts.create(
        tmp_path, "build", "codex", log_dir=tmp_path / "logs", target="commonmark_2"
    )
    stamp = artifacts.prompt_file.name.split("_", 1)[0]
    assert TIMESTAMP_RE.match(stamp)
    for path, extension in (
        (artifacts.prompt_file, ".prompt.md"),
        (artifacts.raw_file, ".raw.jsonl"),
        (artifacts.output_file, ".output.txt"),
        (artifacts.stderr_file, ".stderr.log"),
    ):
        assert path.name == f"{stamp}_commonmark_2_build_codex{extension}"
    assert artifacts.execution_id.startswith(f"{stamp}-")


def test_transcript_name_keeps_the_full_stamp(tmp_path):
    logging = setup_command_logging(
        tmp_path / "logs", "build", stdout=sys.stdout, target="commonmark_2", llm="claude"
    )
    logging.close()
    name = logging.transcript_path.name
    assert TIMESTAMP_RE.match(name.split("_", 1)[0])
    assert name.endswith("_commonmark_2_build_claude.log")


def test_transcript_omits_absent_components(tmp_path):
    """A command with no Target still names the provider; an unresolved provider is dropped."""
    logs = tmp_path / "logs"
    logging = setup_command_logging(logs, "config show", stdout=sys.stdout, llm="codex")
    logging.close()
    assert logging.transcript_path.name.endswith("_config-show_codex.log")

    logging = setup_command_logging(logs, "config show", stdout=sys.stdout)
    logging.close()
    assert logging.transcript_path.name.endswith("_config-show.log")


def test_empty_transcript_is_pruned_on_close(tmp_path):
    """A command that prints nothing — ``status --ready`` — leaves no zero-byte log behind."""
    logs = tmp_path / "logs"
    logging = setup_command_logging(logs, "status", stdout=sys.stdout, target="commonmark_2")
    logging.close()
    assert not logging.transcript_path.exists()
    assert list(logs.glob("*.log")) == []


def test_transcript_with_content_is_kept(tmp_path):
    logs = tmp_path / "logs"
    logging = setup_command_logging(logs, "status", stdout=sys.stdout, target="commonmark_2")
    logging.stdout.write("Drydock status — commonmark_2\n")
    logging.close()
    assert logging.transcript_path.is_file()
    assert "commonmark_2" in logging.transcript_path.read_text(encoding="utf-8")


def test_empty_stderr_evidence_is_pruned_and_dropped_from_paths(tmp_path):
    artifacts = ExecutionArtifacts.create(
        tmp_path, "build", "codex", log_dir=tmp_path / "logs", target="commonmark_2"
    )
    artifacts.stderr_file.write_text("", encoding="utf-8")
    artifacts.prune_empty()
    assert not artifacts.stderr_file.exists()
    assert "stderr" not in artifacts.paths()


def test_stderr_evidence_with_content_is_kept(tmp_path):
    artifacts = ExecutionArtifacts.create(
        tmp_path, "build", "codex", log_dir=tmp_path / "logs", target="commonmark_2"
    )
    artifacts.stderr_file.write_text("provider warning\n", encoding="utf-8")
    artifacts.prune_empty()
    assert artifacts.stderr_file.is_file()
    assert artifacts.paths()["stderr"] == str(artifacts.stderr_file)


def test_llm_log_is_created_only_when_activity_is_recorded(tmp_path):
    artifacts = ExecutionArtifacts.create(
        tmp_path, "build", "codex", log_dir=tmp_path / "logs", target="commonmark_2"
    )
    assert artifacts.llm_log_file.name.endswith(".llm.log")
    assert not artifacts.llm_log_file.exists()
    assert "llm_log" not in artifacts.paths()

    artifacts.record_activity("Calling CODEX/gpt-5.6-luna (build)...")
    artifacts.record_activity("Completed CODEX/gpt-5.6-luna (build)  rc=0")

    assert artifacts.llm_log_file.read_text(encoding="utf-8").splitlines() == [
        "Calling CODEX/gpt-5.6-luna (build)...",
        "Completed CODEX/gpt-5.6-luna (build)  rc=0",
    ]
    assert artifacts.paths()["llm_log"] == str(artifacts.llm_log_file)


@pytest.mark.parametrize(
    ("namespace", "expected"),
    [
        ({"Target": "commonmark_2"}, "commonmark_2"),
        ({"args": ["commonmark_2"]}, "commonmark_2"),
        ({"args": ["commonmark_2", "--reset"]}, "commonmark_2"),
        ({"args": ["status", "commonmark_2"]}, "commonmark_2"),  # drydock build status <Target>
        ({"args": ["ac", "commonmark_2"]}, "commonmark_2"),  # drydock score ac <Target>
        ({"args": ["commonmark_2", "--check"]}, "commonmark_2"),
        ({"args": ["--check", "commonmark_2"]}, "commonmark_2"),  # switch before the Target
        ({"args": ["--step", "feature-parser", "commonmark_2"]}, "commonmark_2"),
        ({"args": ["--step=feature-parser", "commonmark_2"]}, "commonmark_2"),
        ({"args": ["commonmark_2", "--step", "feature-parser"]}, "commonmark_2"),
        ({"args": ["generate", "commonmark_2", "--theme", "sail"]}, "commonmark_2"),
        ({"args": ["--unknown-flag", "commonmark_2"]}, ""),  # its value is indistinguishable
        ({"args": []}, ""),  # drydock status — all targets
    ],
)
def test_log_target_resolves_remainder_commands(namespace, expected):
    import argparse

    assert _log_target(argparse.Namespace(**namespace)) == expected


@pytest.mark.parametrize(
    ("namespace", "expected"),
    [
        ({"command": "analyze"}, True),
        ({"command": "plan"}, True),
        ({"command": "refit"}, True),
        ({"command": "survey"}, True),
        ({"command": "import"}, True),
        ({"command": "status", "args": ["commonmark_2"]}, False),
        ({"command": "validate"}, False),
        ({"command": "publish"}, False),
        ({"command": "config", "config_command": "show"}, False),
        ({"command": "build", "args": ["commonmark_2"]}, True),
        ({"command": "build", "args": ["status", "commonmark_2"]}, False),
        ({"command": "build", "args": ["score", "commonmark_2"]}, True),
        ({"command": "score", "args": ["release", "commonmark_2"]}, True),
        ({"command": "score", "args": ["ac", "commonmark_2"]}, False),
        ({"command": "document", "args": ["commonmark_2"]}, True),
        ({"command": "document", "args": ["generate", "commonmark_2"]}, True),
        ({"command": "document", "args": ["assemble", "commonmark_2"]}, False),
        ({"command": "rigging", "rigging_command": "compact"}, True),
        ({"command": "rigging", "rigging_command": "verify"}, False),
        ({"command": "rigging", "rigging_command": "update"}, False),
        ({"command": "prompt", "prompt_command": "review"}, True),
        ({"command": "run", "run_command": "quarterdeck"}, True),
    ],
)
def test_invocation_uses_llm_matches_the_commands_that_call_a_model(namespace, expected):
    import argparse

    assert _invocation_uses_llm(argparse.Namespace(**namespace)) is expected


@pytest.mark.parametrize(
    ("namespace", "expected"),
    [
        ({"command": "analyze", "llm_provider": "codex"}, "codex"),  # declared override flag
        ({"command": "build", "args": ["commonmark_2", "--llm-provider", "codex"]}, "codex"),
        ({"command": "score", "args": ["release", "c2", "--llm-provider=codex"]}, "codex"),
        ({"command": "analyze", "llm_provider": "nonsense"}, ""),  # unresolvable, never fatal
        ({"command": "status", "llm_provider": "codex"}, ""),  # no model runs, so none is named
        ({"command": "score", "args": ["ac", "commonmark_2"]}, ""),
        ({"command": "build", "args": ["status", "commonmark_2"]}, ""),
    ],
)
def test_log_llm_names_a_provider_only_when_one_runs(namespace, expected):
    import argparse

    assert _log_llm(argparse.Namespace(**namespace)) == expected


def test_log_llm_falls_back_to_the_configured_provider(monkeypatch):
    """With no override, the filename records whatever the configuration resolves to."""
    import argparse

    args = argparse.Namespace(command="analyze", llm_provider=None, args=[])
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    assert _log_llm(args) == "codex"
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    assert _log_llm(args) == "claude"
