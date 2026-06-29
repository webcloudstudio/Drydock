"""Tests for the drydock survey capability."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.survey import (
    AcItem,
    CommandSpec,
    band_for,
    compute_score,
    import_specs,
    load_records,
    load_specs,
    parse_ac_file,
    render_scoreboard,
    run_survey,
    survey_dir_for,
)

AC_FILE = """# SURVEY-SPEC: drydock status

| Field   | Value |
|---------|-------|
| Command | drydock status |

## Goal

A user knows where the project stands, what to do next, and what just happened.

## Acceptance Criteria — Code

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| STATUS-C1 | Output states the status | D1 | A | 2 | output has phase line |
| STATUS-C3 | Last 10 commands by target | D1 | A | 3 | seed 11, assert 10 |

## Acceptance Criteria — Specification

| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| STATUS-D2 | Reads MANIFEST.md not legacy build-plan filenames | D5 | A | 2 | grep source |
"""


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "exec-fake"


def _make_target(tmp_path: Path, ac_text: str = AC_FILE) -> tuple[str, Path]:
    target_dir = tmp_path / "targets" / "Demo"
    ac_dir = target_dir / "survey" / "ac"
    ac_dir.mkdir(parents=True)
    (ac_dir / "SURVEY-status.md").write_text(ac_text, encoding="utf-8")
    (target_dir / "blueprint").mkdir()
    return "Demo", target_dir


class TestParse:
    def test_parses_command_goal_and_ac(self, tmp_path):
        _, target_dir = _make_target(tmp_path)
        spec = parse_ac_file(target_dir / "survey" / "ac" / "SURVEY-status.md")
        assert spec.command == "drydock status"
        assert spec.goal.startswith("A user knows")
        assert [a.id for a in spec.ac] == ["STATUS-C1", "STATUS-C3", "STATUS-D2"]
        assert spec.ac[0].dimension == "D1"
        assert spec.ac[0].check == "assertion"
        assert spec.ac[1].weight == 3.0

    def test_load_specs_filters_by_command(self, tmp_path):
        _, target_dir = _make_target(tmp_path)
        survey_dir = survey_dir_for(target_dir)
        assert len(load_specs(survey_dir)) == 1
        assert load_specs(survey_dir, "status")[0].command == "drydock status"
        with pytest.raises(SpecificationError):
            load_specs(survey_dir, "nonesuch")


class TestScoring:
    def _spec(self) -> CommandSpec:
        return CommandSpec(
            command="c",
            goal="",
            ac=[
                AcItem("A1", "", "D1", "assertion", 2),
                AcItem("A2", "", "D1", "assertion", 2),
                AcItem("A3", "", "D5", "assertion", 1),
            ],
            path=Path("x"),
        )

    def test_all_pass_is_100_not_provisional(self):
        scored = compute_score(self._spec(), {"A1": "pass", "A2": "pass", "A3": "pass"})
        assert scored.score == 100
        assert scored.provisional is False

    def test_partial_and_fail_weighted(self):
        # D1: (2*1 + 2*0)/4 = 50 ; D5: 1*0.5 = 50 -> redistributed both assessed
        scored = compute_score(self._spec(), {"A1": "pass", "A2": "fail", "A3": "partial"})
        assert scored.dimensions["D1"] == 50.0
        assert scored.dimensions["D5"] == 50.0
        assert scored.score == 50

    def test_unassessed_dimension_is_provisional(self):
        scored = compute_score(self._spec(), {"A1": "pass", "A2": "pass"})
        assert scored.assessed == ["D1"]
        assert scored.provisional is True
        assert scored.score == 100

    def test_band_thresholds(self):
        assert band_for(95) == "SEAWORTHY"
        assert band_for(80) == "SEA_TRIALS"
        assert band_for(65) == "TAKING_WATER"
        assert band_for(40) == "DRY_DOCK"

    def test_breach_caps_band(self):
        assert band_for(95, ["guardrail-breach"]) == "TAKING_WATER"
        assert band_for(95, ["regression"]) == "TAKING_WATER"
        assert band_for(40, ["regression"]) == "DRY_DOCK"


class TestRunSurvey:
    def test_scores_and_appends_record(self, tmp_path):
        target, target_dir = _make_target(tmp_path)
        payload = (
            '{"surveys":[{"command":"drydock status",'
            '"ac":[{"id":"STATUS-C1","result":"pass","note":"ok"},'
            '{"id":"STATUS-C3","result":"partial","note":"limit 5"},'
            '{"id":"STATUS-D2","result":"fail","note":"BUILD_PLAN"}],'
            '"flags":["contract-drift"],"actions":["route plan reads through one loader"]}]}'
        )

        def runner(prompt, working_directory, **kwargs):
            return FakeRun(text=payload)

        records = run_survey(target, target_dir, runner=runner)
        assert len(records) == 1
        rec = records[0]
        assert rec["command"] == "drydock status"
        assert rec["flags"] == ["contract-drift"]
        assert rec["band"] in {"TAKING_WATER", "DRY_DOCK", "SEA_TRIALS"}
        # persisted and reloadable (meta line skipped)
        reloaded = load_records(survey_dir_for(target_dir))
        assert len(reloaded) == 1
        assert reloaded[0]["command"] == "drydock status"

    def test_failed_execution_raises(self, tmp_path):
        target, target_dir = _make_target(tmp_path)

        def runner(prompt, working_directory, **kwargs):
            return FakeRun(ok=False, text="")

        with pytest.raises(SpecificationError):
            run_survey(target, target_dir, runner=runner)

    def test_cli_overrides_are_passed_to_runner(self, tmp_path):
        target, target_dir = _make_target(tmp_path)
        calls = []

        def runner(prompt, working_directory, **kwargs):
            calls.append(kwargs)
            return FakeRun(text='{"surveys":[]}')

        run_survey(target, target_dir, runner=runner, model="gpt-5.4", llm_provider="codex")
        assert calls[0]["model"] == "gpt-5.4"
        assert calls[0]["llm"] == "codex"


class TestRender:
    def test_scoreboard_contains_command_and_band(self, tmp_path):
        target, target_dir = _make_target(tmp_path)

        def runner(prompt, working_directory, **kwargs):
            return FakeRun(
                text='{"surveys":[{"command":"drydock status","ac":[{"id":"STATUS-C1","result":"pass"}],"flags":[],"actions":["x"]}]}'
            )

        run_survey(target, target_dir, runner=runner)
        out = render_scoreboard(load_records(survey_dir_for(target_dir)))
        assert "drydock status" in out
        assert "Surveyor scoreboard" in out

    def test_empty_scoreboard_hints_run(self):
        assert "--run" in render_scoreboard([])


class TestImport:
    def test_writes_ac_files(self, tmp_path):
        target, target_dir = _make_target(tmp_path)
        source = tmp_path / "blueprint"
        source.mkdir()
        (source / "FEATURE-Login.md").write_text("# FEATURE: Login\n", encoding="utf-8")
        block = (
            "=== SURVEY-login.md ===\n"
            "# SURVEY-SPEC: drydock login\n\n## Goal\n\nLog in.\n"
            "=== END SURVEY-login.md ===\n"
        )

        def runner(prompt, working_directory, **kwargs):
            return FakeRun(text=block)

        written = import_specs(target, target_dir, source, runner=runner)
        assert len(written) == 1
        assert written[0].name == "SURVEY-login.md"
        assert "drydock login" in written[0].read_text(encoding="utf-8")

    def test_import_rejects_text_outside_blocks_without_writes(self, tmp_path):
        target, target_dir = _make_target(tmp_path)
        source = tmp_path / "blueprint"
        source.mkdir()
        (source / "FEATURE-Login.md").write_text("# FEATURE: Login\n", encoding="utf-8")

        def runner(prompt, working_directory, **kwargs):
            return FakeRun(
                text=(
                    "Here are the files.\n"
                    "=== SURVEY-login.md ===\n"
                    "# SURVEY-SPEC: drydock login\n"
                    "=== END SURVEY-login.md ===\n"
                )
            )

        with pytest.raises(SpecificationError, match="Text appeared outside"):
            import_specs(target, target_dir, source, runner=runner)

        assert not (target_dir / "survey" / "ac" / "SURVEY-login.md").exists()

    def test_import_rejects_unexpected_artifact_without_writes(self, tmp_path):
        target, target_dir = _make_target(tmp_path)
        source = tmp_path / "blueprint"
        source.mkdir()
        (source / "FEATURE-Login.md").write_text("# FEATURE: Login\n", encoding="utf-8")

        def runner(prompt, working_directory, **kwargs):
            return FakeRun(text="=== NOTES.md ===\n# Notes\n=== END NOTES.md ===\n")

        with pytest.raises(SpecificationError, match="unexpected artifact"):
            import_specs(target, target_dir, source, runner=runner)

        assert not (target_dir / "survey" / "ac" / "NOTES.md").exists()

    def test_import_cli_overrides_are_passed_to_runner(self, tmp_path):
        target, target_dir = _make_target(tmp_path)
        source = tmp_path / "blueprint"
        source.mkdir()
        (source / "FEATURE-Login.md").write_text("# FEATURE: Login\n", encoding="utf-8")
        calls = []

        def runner(prompt, working_directory, **kwargs):
            calls.append(kwargs)
            return FakeRun(
                text="=== SURVEY-login.md ===\n# SURVEY-SPEC: drydock login\n=== END SURVEY-login.md ===\n"
            )

        import_specs(
            target,
            target_dir,
            source,
            runner=runner,
            model="gpt-5.4-mini",
            llm_provider="codex",
        )
        assert calls[0]["model"] == "gpt-5.4-mini"
        assert calls[0]["llm"] == "codex"
