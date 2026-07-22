"""Tests for the standoff diagnosis of opaque failures."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from drydock import diagnose as diagnose_module
from drydock.diagnose import (
    BLOCKED_PREFIXES,
    assemble_prompt,
    clamp_diagnosis,
    diagnose,
    render_standoff_banner,
    reset_diagnosis_guard,
    should_diagnose,
)
from drydock.errors import (
    ConfigurationError,
    DrydockError,
    SpecificationError,
    UsageError,
    read_error_record,
    write_error_record,
)


@dataclass
class FakeRun:
    """Stand-in for an LlmResult — never spends API credits."""

    ok: bool = True
    text: str = "CAUSE: the build agent wrote no files.\nDO: rerun drydock build widgets --resume\n"
    execution_id: str = "exec-fake"


def fake_runner(result: FakeRun | None = None):
    def run(prompt, working_directory, **kwargs):
        run.seen.append(prompt)
        run.seen_kwargs.append(kwargs)
        return result if result is not None else FakeRun()

    run.seen = []  # type: ignore[attr-defined]
    run.seen_kwargs = []  # type: ignore[attr-defined]
    return run


def make_record(tmp_path, **overrides):
    fields = {
        "command": "build",
        "phase": "LLM execution",
        "classification": "no build files written",
        "detail": "The build agent finished but produced no files under the build directory.",
        "recovery": "Rerun the block.",
    }
    fields.update(overrides)
    return write_error_record(tmp_path, **fields)


@pytest.fixture(autouse=True)
def _reset_guard():
    reset_diagnosis_guard()
    yield
    reset_diagnosis_guard()


# ── should_diagnose ─────────────────────────────────────────────────────────


def test_post_llm_record_qualifies(tmp_path):
    assert should_diagnose(record=make_record(tmp_path)) is True


def test_unclassified_exception_qualifies():
    assert should_diagnose(exc=RuntimeError("dict object has no attribute keys")) is True


@pytest.mark.parametrize("prefix", BLOCKED_PREFIXES)
def test_classifications_with_their_own_remediation_are_blocked(tmp_path, prefix):
    record = make_record(tmp_path, classification=f"{prefix}: 2 issue(s)")
    assert should_diagnose(record=record) is False


def test_authentication_failure_is_blocked(tmp_path):
    record = make_record(tmp_path, detail="OAuth session expired and could not be refreshed.")
    assert should_diagnose(record=record) is False


def test_rate_limit_failure_is_blocked(tmp_path):
    record = make_record(tmp_path, detail="provider returned a rate limit response")
    assert should_diagnose(record=record) is False


@pytest.mark.parametrize(
    "exc",
    [
        UsageError("bad arguments"),
        ConfigurationError("workspace not set"),
        SpecificationError("blueprint invalid"),
        DrydockError("plain failure"),
        KeyboardInterrupt(),
    ],
)
def test_deterministic_and_interrupted_failures_are_blocked(exc):
    assert should_diagnose(exc=exc) is False


def test_no_failure_does_not_diagnose():
    assert should_diagnose() is False


def test_only_one_diagnosis_per_invocation(tmp_path):
    record = make_record(tmp_path)
    assert diagnose(tmp_path, command="drydock build w", record=record, runner=fake_runner())
    assert should_diagnose(record=record) is False
    assert (
        diagnose(tmp_path, command="drydock build w", record=record, runner=fake_runner()) is None
    )


# ── prompt assembly ─────────────────────────────────────────────────────────


def test_assembled_prompt_carries_the_record_and_evidence(tmp_path):
    evidence = tmp_path / "evidence" / "block-1.md"
    evidence.parent.mkdir()
    evidence.write_text("## Failure\nagent halted at step 3\n", encoding="utf-8")
    record = make_record(tmp_path, evidence=str(evidence))
    (tmp_path / "METADATA.md").write_text(
        "name: widgets\nstack: python\nbuild_state: implement\n", encoding="utf-8"
    )

    text = assemble_prompt(
        "PROMPT BODY",
        command="drydock build widgets",
        target="widgets",
        record=record,
        exc=None,
        target_dir=tmp_path,
    ).rendered_text

    assert "# Input Context" in text
    assert "# Agent Task" in text
    assert "PROMPT BODY" in text
    assert "no build files written" in text
    assert "agent halted at step 3" in text
    assert "BUILD_STATE: implement" in text


def test_assembled_prompt_carries_traceback_and_failing_source():
    try:
        read_error_record(None)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - the exception under test
        text = assemble_prompt(
            "PROMPT BODY",
            command="drydock status widgets",
            target="widgets",
            record=None,
            exc=exc,
            target_dir=__import__("pathlib").Path("."),
        ).rendered_text

    assert "Traceback" in text
    assert "errors.py" in text
    assert "def read_error_record" in text


# ── output contract ─────────────────────────────────────────────────────────


def test_clamp_keeps_only_contracted_lines():
    text = (
        "Here is my analysis of the failure.\n\n"
        "```\nCAUSE: the manifest block has no acceptance criteria.\n"
        "DO: add a Programmatic Acceptance section to FEATURE-1.md\n```\n"
        "Let me know if you want more detail.\n"
    )
    assert clamp_diagnosis(text) == (
        "CAUSE: the manifest block has no acceptance criteria.\n"
        "DO: add a Programmatic Acceptance section to FEATURE-1.md"
    )


def test_clamp_caps_line_count():
    text = "\n".join(["CAUSE: x"] + [f"DO: step {n}" for n in range(20)])
    assert len(clamp_diagnosis(text).splitlines()) == 6


def test_clamp_falls_back_to_raw_tail_when_contract_ignored():
    assert clamp_diagnosis("the provider returned prose") == "the provider returned prose"


def test_banner_names_the_model_and_command():
    banner = render_standoff_banner(llm="codex", model="gpt-5.6", command="drydock build widgets")
    assert "A MAJOR ERROR HAS OCCURRED" in banner
    assert "codex/gpt-5.6 is diagnosing" in banner
    assert "drydock build widgets has stopped" in banner


# ── diagnose() ──────────────────────────────────────────────────────────────


def test_diagnose_returns_clamped_text_and_passes_a_timeout(tmp_path):
    runner = fake_runner()
    text = diagnose(
        tmp_path, command="drydock build w", record=make_record(tmp_path), runner=runner
    )
    assert text == (
        "CAUSE: the build agent wrote no files.\nDO: rerun drydock build widgets --resume"
    )
    assert runner.seen_kwargs[0]["timeout_seconds"] == pytest.approx(90.0)
    assert runner.seen_kwargs[0]["command_name"] == "diagnose"
    assert runner.seen_kwargs[0]["on_text"] is None


def test_diagnose_returns_none_on_failed_run(tmp_path):
    runner = fake_runner(FakeRun(ok=False, text=""))
    assert (
        diagnose(tmp_path, command="drydock build w", record=make_record(tmp_path), runner=runner)
        is None
    )


def test_diagnose_returns_none_on_empty_output(tmp_path):
    runner = fake_runner(FakeRun(ok=True, text="   \n"))
    assert (
        diagnose(tmp_path, command="drydock build w", record=make_record(tmp_path), runner=runner)
        is None
    )


def test_diagnose_never_raises(tmp_path):
    def exploding_runner(prompt, working_directory, **kwargs):
        raise OSError("provider binary vanished")

    assert (
        diagnose(
            tmp_path,
            command="drydock build w",
            record=make_record(tmp_path),
            runner=exploding_runner,
        )
        is None
    )


def test_diagnose_defaults_to_run_prompt_without_a_runner(tmp_path, monkeypatch):
    """The runner is resolved at call time so no real provider is ever reached in tests."""
    calls = []

    def fake_run_prompt(prompt, working_directory, **kwargs):
        calls.append(kwargs)
        return FakeRun()

    monkeypatch.setattr("drydock.llm.run_prompt", fake_run_prompt)
    assert diagnose(tmp_path, command="drydock build w", record=make_record(tmp_path))
    assert calls and calls[0]["command_name"] == "diagnose"
    assert diagnose_module.PROMPT_NAME == "diagnose"
