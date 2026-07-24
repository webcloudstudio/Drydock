"""Every Drydock log file derives its name from one shared basename builder."""

from __future__ import annotations

import sys

import pytest

from drydock.execution import ExecutionArtifacts, log_basename, log_component
from drydock.logging import setup_command_logging

TIMESTAMP = "20260724T183418168588Z"


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


def test_log_basename_omits_empty_parts():
    assert log_basename(TIMESTAMP, "", "status", "") == f"{TIMESTAMP}_status"
    assert (
        log_basename(TIMESTAMP, "commonmark_2", "import", "") == f"{TIMESTAMP}_commonmark_2_import"
    )
    assert (
        log_basename(TIMESTAMP, "commonmark_2", "analyze", "codex")
        == f"{TIMESTAMP}_commonmark_2_analyze_codex"
    )


def test_transcript_and_evidence_share_one_prefix(tmp_path):
    """The command transcript and its LLM evidence resolve to the same target/command stem."""
    logs = tmp_path / "logs"

    logging = setup_command_logging(logs, "analyze", stdout=sys.stdout, target="commonmark_2")
    logging.close()

    artifacts = ExecutionArtifacts.create(
        tmp_path, "analyze", "codex", log_dir=logs, target="commonmark_2"
    )

    transcript = logging.transcript_path.name
    assert transcript.endswith("_commonmark_2_analyze.log")
    # Evidence adds only the provider qualifier to the same target/command stem.
    assert artifacts.prompt_file.name.endswith("_commonmark_2_analyze_codex.prompt.md")
    assert "_commonmark_2_analyze" in transcript


def test_transcript_omits_absent_target(tmp_path):
    logs = tmp_path / "logs"
    logging = setup_command_logging(logs, "config show", stdout=sys.stdout)
    logging.close()
    assert logging.transcript_path.name.endswith("_config-show.log")
