from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drydock import sea_trials, technology_stack
from drydock.errors import SpecificationError
from drydock.metadata import render_metadata
from drydock.uat import (
    CommandResult,
    discover_fixtures,
    make_streaming_runner,
    render_summary,
    run_sort_key,
    run_uat,
    subprocess_runner,
)


def _fixture(root: Path, name: str = "ReadingList", *, updated: bool = True) -> Path:
    fixture = root / name
    fixture.mkdir(parents=True)
    (fixture / "sources").mkdir()
    (fixture / "sources" / "reading-list.md").write_text("# Initial\n", encoding="utf-8")
    updates: list[str] = []
    if updated:
        update = fixture / "updates" / "reading-list.md"
        update.parent.mkdir()
        update.write_text("# Updated\n", encoding="utf-8")
        updates.append("updates/reading-list.md")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": name,
            "sources": ["sources/reading-list.md"],
            "updates": updates,
            "test_command": ["sh", "bin/test.sh"],
            "acceptance": {"full": ["sh", "sources/full_test.sh"]},
        }),
        encoding="utf-8",
    )
    return fixture


def _declare(fixture: Path, **fields: str) -> None:
    path = fixture / "uat.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.update(fields)
    path.write_text(json.dumps(config), encoding="utf-8")


def test_discover_fixture_uses_explicit_sources_and_updates(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    found = discover_fixtures(tmp_path)[0]

    assert found.sources == ((fixture / "sources" / "reading-list.md").resolve(),)
    assert found.updates == ((fixture / "updates" / "reading-list.md").resolve(),)
    assert found.test_command == ("sh", "bin/test.sh")


def test_discover_fixture_reads_declared_technology_stack(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    stack = fixture / "inputs" / "TECHNOLOGY_STACK.md"
    stack.parent.mkdir()
    stack.write_text(
        technology_stack.render([technology_stack.StackEntry("Go", "go.md")], "2026-08-09"),
        encoding="utf-8",
    )
    _declare(fixture, technology_stack="inputs/TECHNOLOGY_STACK.md")

    found = discover_fixtures(tmp_path)[0]

    assert found.stack == stack.resolve()


def test_discover_fixture_without_technology_stack_leaves_the_choice_to_analyze(
    tmp_path: Path,
) -> None:
    _fixture(tmp_path)

    assert discover_fixtures(tmp_path)[0].stack is None


def test_discover_fixture_reads_declared_sea_trials(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    contract = fixture / "inputs" / "SEA_TRIALS.md"
    contract.parent.mkdir()
    contract.write_text(
        "# Sea Trials: Demo\n\n## st-001: Example\n"
        "Type: technical\nRequired: yes\nCriterion: The system shall work.\n"
        "Verification: proof\n",
        encoding="utf-8",
    )
    _declare(fixture, sea_trials="inputs/SEA_TRIALS.md")

    assert discover_fixtures(tmp_path)[0].sea_trials == contract.resolve()


def test_discover_fixture_rejects_declared_malformed_sea_trials(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    contract = fixture / "inputs" / "SEA_TRIALS.md"
    contract.parent.mkdir()
    contract.write_text("# Sea Trials: Demo\n", encoding="utf-8")
    _declare(fixture, sea_trials="inputs/SEA_TRIALS.md")

    with pytest.raises(SpecificationError, match="Invalid UAT fixture Sea Trials"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_technology_stack_naming_unknown_rigging_file(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    stack = fixture / "inputs" / "TECHNOLOGY_STACK.md"
    stack.parent.mkdir()
    stack.write_text(
        technology_stack.render([technology_stack.StackEntry("Go", "nosuchstack.md")]),
        encoding="utf-8",
    )
    _declare(fixture, technology_stack="inputs/TECHNOLOGY_STACK.md")

    with pytest.raises(SpecificationError, match="nosuchstack.md"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_empty_technology_stack(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    stack = fixture / "inputs" / "TECHNOLOGY_STACK.md"
    stack.parent.mkdir()
    stack.write_text("# Technology Stack\n", encoding="utf-8")
    _declare(fixture, technology_stack="inputs/TECHNOLOGY_STACK.md")

    with pytest.raises(SpecificationError, match="declares no technologies"):
        discover_fixtures(tmp_path)


def test_run_uat_seeds_declared_stack_into_target_before_analyze(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, updated=False)
    declared = technology_stack.render([technology_stack.StackEntry("Go", "go.md")], "2026-08-09")
    stack = fixture / "inputs" / "TECHNOLOGY_STACK.md"
    stack.parent.mkdir()
    stack.write_text(declared, encoding="utf-8")
    _declare(fixture, technology_stack="inputs/TECHNOLOGY_STACK.md")
    seen_at_analyze: list[str] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        parts = tuple(argv[3:])
        if parts[:1] == ("analyze",):
            path = (
                Path(env["DRYDOCK_WORKSPACE"])
                / "targets"
                / "ReadingList"
                / technology_stack.FILENAME
            )
            seen_at_analyze.append(path.read_text(encoding="utf-8"))
        returncode = 1 if parts[:2] == ("status", "ReadingList") and "--ready" in parts else 0
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert seen_at_analyze == [declared]
    proof_input = (
        fixtures_root
        / "ReadingList"
        / "runs"
        / "20260809.000000"
        / "inputs"
        / technology_stack.FILENAME
    )
    assert proof_input.read_text(encoding="utf-8") == declared


def test_discover_selected_fixture_rejects_unknown_project(tmp_path: Path) -> None:
    _fixture(tmp_path)

    with pytest.raises(SpecificationError, match="Unknown UAT kit"):
        discover_fixtures(tmp_path, "Missing")


def test_undeclared_root_lifecycle_inputs_are_ignored(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (fixture / sea_trials.FILENAME).write_text("not a contract\n", encoding="utf-8")
    (fixture / technology_stack.FILENAME).write_text("not a stack\n", encoding="utf-8")

    found = discover_fixtures(tmp_path)[0]

    assert found.sea_trials is None
    assert found.stack is None


_COMPASS = (
    "# COMPASS: Demo\n\n## Compass\nBuild a thing.\n\n"
    "## Constraints\n- Standard library only.\n\n## Guardrails\n- Do not vendor a dependency.\n"
)


def _kit_compass(fixture: Path, text: str = _COMPASS) -> Path:
    path = fixture / "inputs" / "COMPASS.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _declare(fixture, compass="inputs/COMPASS.md")
    return path


def test_discover_fixture_reads_declared_compass(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = _kit_compass(fixture)

    assert discover_fixtures(tmp_path)[0].compass == path.resolve()


def test_discover_fixture_without_compass_lets_analyze_compose_one(tmp_path: Path) -> None:
    _fixture(tmp_path)

    assert discover_fixtures(tmp_path)[0].compass is None


def test_discover_fixture_rejects_a_compass_missing_a_body_section(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _kit_compass(fixture, "# COMPASS: Demo\n\n## Compass\nBuild a thing.\n")

    with pytest.raises(SpecificationError, match="missing required sections"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_a_compass_carrying_an_html_comment(tmp_path: Path) -> None:
    """``analyze`` reads any HTML comment as an unfilled template and overwrites the file.

    A kit that seeds one governs nothing and the substitution is silent, so it is rejected at
    discovery where the operator can still see it.
    """
    fixture = _fixture(tmp_path)
    _kit_compass(fixture, _COMPASS + "\n<!-- a note -->\n")

    with pytest.raises(SpecificationError, match="must not contain an HTML comment"):
        discover_fixtures(tmp_path)


def test_a_seeded_compass_survives_analyze_as_a_populated_file(tmp_path: Path) -> None:
    """The seeded body must not read as an unfilled template, or analyze replaces it."""
    from drydock.analyze import _is_compass_unpopulated
    from drydock.uat import seed_compass

    fixture_dir = _fixture(tmp_path)
    _kit_compass(fixture_dir)
    fixture = discover_fixtures(tmp_path)[0]

    written = seed_compass(fixture, tmp_path / "workspace")

    assert written == tmp_path / "workspace" / "targets" / "ReadingList" / "COMPASS.md"
    assert written.read_text(encoding="utf-8") == _COMPASS
    assert _is_compass_unpopulated(written) is False


_METADATA = (
    "# AUTHORITATIVE PROJECT METADATA — FIELDS SHOULD BE CURRENT\n\n"
    "name: ReadingList\n"
    "display_name: Reading List\n"
    "short_description: A list of books.\n"
    "stack: Python\n"
    "version: \n"
    "build_state: \n"
    "build_sub_state: \n"
    "last_analyzed: \n"
    "last_planned: \n"
    "last_built: \n"
    "build_dir: \n"
    "brand: \n"
    "git_repo: \n"
    "release_tag: \n"
)


def _kit_metadata(fixture: Path, text: str = _METADATA) -> Path:
    path = fixture / "inputs" / "METADATA.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _declare(fixture, metadata="inputs/METADATA.md")
    return path


def test_discover_fixture_reads_declared_metadata(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = _kit_metadata(fixture)

    assert discover_fixtures(tmp_path)[0].metadata == path.resolve()


def test_discover_fixture_without_metadata_keeps_the_init_scaffold(tmp_path: Path) -> None:
    _fixture(tmp_path)

    assert discover_fixtures(tmp_path)[0].metadata is None


def test_discover_fixture_rejects_metadata_naming_another_target(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _kit_metadata(fixture, _METADATA.replace("name: ReadingList", "name: Other"))

    with pytest.raises(SpecificationError, match="declares name 'Other'"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_metadata_carrying_lifecycle_state(tmp_path: Path) -> None:
    """A populated lifecycle field would tell every later command the run is already advanced."""
    fixture = _fixture(tmp_path)
    _kit_metadata(
        fixture,
        _METADATA.replace("build_state: ", "build_state: built").replace(
            "build_dir: ", "build_dir: /elsewhere"
        ),
    )

    with pytest.raises(SpecificationError, match="build_state, build_dir"):
        discover_fixtures(tmp_path)


def test_seeded_metadata_overwrites_the_init_scaffold_and_survives_analyze(
    tmp_path: Path,
) -> None:
    """analyze backfills these fields only when blank, so the kit's values are the run's."""
    from drydock.metadata import parse_metadata, set_field
    from drydock.uat import seed_metadata

    fixture_dir = _fixture(tmp_path)
    _kit_metadata(fixture_dir)
    fixture = discover_fixtures(tmp_path)[0]
    target_dir = tmp_path / "workspace" / "targets" / "ReadingList"
    target_dir.mkdir(parents=True)
    (target_dir / "METADATA.md").write_text(
        render_metadata("ReadingList"), encoding="utf-8", newline="\n"
    )

    written = seed_metadata(fixture, tmp_path / "workspace")

    assert written == target_dir / "METADATA.md"
    set_field(written, "stack", "Node.js", overwrite=False)
    set_field(written, "display_name", "Proposed", overwrite=False)
    fields = parse_metadata(written)
    assert fields["stack"] == "Python"
    assert fields["display_name"] == "Reading List"
    assert fields["build_state"] == ""


def test_the_shipped_jq_compass_governs_harness_invocation_and_the_terminal_story():
    """The run that failed had all of this in prose the model ignored; it is now a kit input."""
    root = Path(__file__).resolve().parents[1] / "uat"
    fixture = discover_fixtures(root, "jq")[0]

    assert fixture.compass == (root / "jq" / "inputs" / "COMPASS.md").resolve()
    text = fixture.compass.read_text(encoding="utf-8")
    assert 'JQ="$PWD/jq" python3 sources/run_conformance.py' in text
    assert 'env={**os.environ, "JQ"' in text
    assert "### The terminal story" in text
    assert "the last story in the build order" in text


@pytest.mark.parametrize("field", ["sea_trials", "technology_stack", "compass"])
@pytest.mark.parametrize("value", ["", "../outside.md", "inputs/missing.md"])
def test_declared_lifecycle_input_path_must_be_valid(
    tmp_path: Path, field: str, value: str
) -> None:
    fixture = _fixture(tmp_path)
    (tmp_path / "outside.md").write_text("outside\n", encoding="utf-8")
    _declare(fixture, **{field: value})

    with pytest.raises(SpecificationError, match=field):
        discover_fixtures(tmp_path)


def test_discover_fixture_loads_nested_local_source(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    source = fixture / "kit" / "suite.py"
    source.parent.mkdir()
    source.write_text("# suite\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": "Example",
            "sources": ["sources/reading-list.md", "kit/suite.py"],
            "updates": [],
            "test_command": ["sh", "full_test.sh"],
            "acceptance": {"full": ["sh", "sources/full_test.sh"]},
        }),
        encoding="utf-8",
    )

    found = discover_fixtures(tmp_path)[0]

    assert found.sources == (
        (fixture / "sources" / "reading-list.md").resolve(),
        source.resolve(),
    )
    assert found.test_command == ("sh", "full_test.sh")


def test_discover_fixture_rejects_a_kit_with_no_governed_scoring_entry_point(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, updated=False)
    config = json.loads((fixture / "uat.json").read_text(encoding="utf-8"))
    del config["acceptance"]
    (fixture / "uat.json").write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(SpecificationError, match="must declare acceptance.full"):
        discover_fixtures(tmp_path)


def test_discover_fixture_defaults_the_test_command_to_the_scoring_entry_point(
    tmp_path: Path,
) -> None:
    # The two are the same command by construction, so a kit only states both when it wants
    # them to differ.
    fixture = _fixture(tmp_path, updated=False)
    config = json.loads((fixture / "uat.json").read_text(encoding="utf-8"))
    del config["test_command"]
    (fixture / "uat.json").write_text(json.dumps(config), encoding="utf-8")

    found = discover_fixtures(tmp_path)[0]

    assert found.test_command == ("sh", "sources/full_test.sh")
    assert found.acceptance.full == ("sh", "sources/full_test.sh")


def test_discover_fixture_rejects_source_outside_fixture(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    outside = tmp_path / "outside.py"
    outside.write_text("# outside\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "sources": ["../outside.py"],
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="Invalid UAT fixture source path"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_flattened_source_collision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    duplicate = fixture / "kit" / "reading-list.md"
    duplicate.parent.mkdir()
    duplicate.write_text("# duplicate\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "sources": ["sources/reading-list.md", "kit/reading-list.md"],
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="collide after import flattening"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_update_for_unknown_basename(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    update = fixture / "other.md"
    update.write_text("# other\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "sources": ["sources/reading-list.md"],
            "updates": ["other.md"],
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="replace an imported basename"):
        discover_fixtures(tmp_path)


def test_run_uat_builds_initial_and_updated_sources_and_gates_on_the_release_verdict(
    tmp_path: Path,
) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root)
    calls: list[tuple[str, ...]] = []
    ready_calls = 0

    def fake_runner(argv, cwd, env, output_dir, label):
        nonlocal ready_calls
        del env
        parts = tuple(argv[3:])
        calls.append(parts)
        returncode = 0
        if parts[:2] == ("status", "ReadingList") and "--ready" in parts:
            ready_calls += 1
            returncode = 0 if ready_calls in {1, 3} else 1
        if parts[:3] == ("score", "release", "ReadingList"):
            returncode = 1
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_id, results = run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    result = results[0]
    # The release gate is the project's acceptance verdict, not an advisory number, so a
    # non-zero ``score release`` fails the run. The two statuses stay separate: Drydock ran the
    # whole lifecycle without an infrastructure fault, and the product did not pass acceptance.
    assert result.status == "failed"
    assert result.execution_status == "PASS"
    assert result.acceptance_status == "FAIL"
    assert result.build_passes == 2
    assert result.score_exit_codes == {"acceptance": 0, "build-report": 0, "release": 1}
    assert ("import", "ReadingList", "--update") in calls
    assert ("refit", "ReadingList", "--sources") in calls
    assert ("build", "status", "ReadingList") in calls
    assert ("status", "ReadingList") in calls
    assert ("status",) in calls
    case_root = fixtures_root / "ReadingList" / "runs" / run_id
    assert (case_root / "sources" / "reading-list.md").read_text() == "# Updated\n"
    evidence = json.loads((case_root / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    labels = [command["label"] for command in evidence["commands"]]
    assert any(label.endswith("after-refit-1-build-status") for label in labels)
    assert any(label.endswith("after-refit-1-build-workspace-status") for label in labels)
    assert (case_root / "result.json").is_file()
    assert "ReadingList: FAILED" in (case_root / "README.md").read_text(encoding="utf-8")
    assert (case_root / "index.html").is_file()


def _plan_gate_runner(calls: list, *, verify_codes: dict[int, int]):
    """A fake runner that fails ``plan verify`` on the attempts named in ``verify_codes``."""
    seen = {"verify": 0}

    def fake_runner(argv, cwd, env, output_dir, label):
        del env
        parts = tuple(argv[3:])
        calls.append(parts)
        returncode = 0
        if parts[:2] == ("plan", "verify"):
            seen["verify"] += 1
            returncode = verify_codes.get(seen["verify"], 0)
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    return fake_runner


def test_a_clean_plan_verify_skips_the_repair_call(tmp_path: Path) -> None:
    """Verification is free and repair is not, so a clean plan never pays for one."""
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root)
    calls: list[tuple[str, ...]] = []

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_plan_gate_runner(calls, verify_codes={}),
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert ("plan", "verify", "ReadingList") in calls
    assert not any(parts[:2] == ("plan", "repair") for parts in calls)


def test_a_failed_plan_verify_buys_exactly_one_repair_and_reverifies(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root)
    calls: list[tuple[str, ...]] = []

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        # First verification red, the one after the repair green.
        runner=_plan_gate_runner(calls, verify_codes={1: 1}),
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert [parts for parts in calls if parts[:2] == ("plan", "repair")] == [
        ("plan", "repair", "ReadingList")
    ]
    assert len([parts for parts in calls if parts[:2] == ("plan", "verify")]) == 2
    assert any(parts[0] == "build" and "status" not in parts for parts in calls)


def test_criteria_still_unrunnable_after_one_repair_end_the_run_at_the_plan(
    tmp_path: Path,
) -> None:
    """Building over criteria that cannot run spends the whole budget to learn nothing."""
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root)
    calls: list[tuple[str, ...]] = []

    _, results = run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_plan_gate_runner(calls, verify_codes={1: 1, 2: 1}),
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert results[0].status == "failed"
    assert "still cannot run after one repair pass" in results[0].error
    # No repair is retried, and no build is attempted on an unrunnable plan.
    assert len([parts for parts in calls if parts[:2] == ("plan", "repair")]) == 1
    assert not any(parts[0] == "build" and "status" not in parts for parts in calls)


def test_run_uat_carries_unproven_guardrails_into_the_run_record(tmp_path: Path) -> None:
    """A passing run still reports the prohibitions a human must settle by hand.

    The list is harvested from the Target's own score evidence rather than the console, so
    `--report` reproduces it for a run it did not execute.
    """
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    unproven = (
        "Guardrail st-003 is UNPROVEN (no code-bound proof references this criterion): "
        "The application shall never store a book whose title or author is empty."
    )

    ready_calls = 0

    def fake_runner(argv, cwd, env, output_dir, label):
        nonlocal ready_calls
        del env
        parts = tuple(argv[3:])
        returncode = 0
        # The build stops when nothing is left buildable, which `--ready` reports by exiting 1.
        if parts[:2] == ("status", "ReadingList") and "--ready" in parts:
            ready_calls += 1
            returncode = 0 if ready_calls == 1 else 1
        if parts[:3] == ("score", "release", "ReadingList"):
            evidence = Path(cwd) / "targets" / "ReadingList" / "evidence"
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / "score-release.json").write_text(
                json.dumps({"complete": True, "qualified": True, "attestations": [unproven]}),
                encoding="utf-8",
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_id, results = run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    result = results[0]
    assert result.status == "passed"
    assert result.attestations == (unproven,)
    case_root = fixtures_root / "ReadingList" / "runs" / run_id
    record = json.loads((case_root / "result.json").read_text(encoding="utf-8"))
    assert record["attestations"] == [unproven]
    assert "## Manual verification required" in (case_root / "README.md").read_text(
        encoding="utf-8"
    )
    # The operator reading the run summary is the one who must settle these.
    summary = render_summary(results)
    assert "ReadingList: PASSED" in summary
    assert "### Manual verification required" in summary
    assert f"- {unproven}" in summary


def test_run_uat_records_no_attestations_when_the_gate_settled_everything(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    ready_calls = 0

    def fake_runner(argv, cwd, env, output_dir, label):
        nonlocal ready_calls
        del env
        parts = tuple(argv[3:])
        returncode = 0
        if parts[:2] == ("status", "ReadingList") and "--ready" in parts:
            ready_calls += 1
            returncode = 0 if ready_calls == 1 else 1
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    _, results = run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].attestations == ()
    assert "Manual verification required" not in render_summary(results)


def test_required_pipeline_failure_stops_fixture_and_writes_result(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    def failing_runner(argv, cwd, env, output_dir, label):
        del cwd, env
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("failed", encoding="utf-8")
        returncode = 1 if tuple(argv[3:5]) == ("analyze", "ReadingList") else 0
        return CommandResult(tuple(argv), returncode, 1, str(stdout), str(stderr))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=failing_runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert results[0].status == "failed"
    assert "analyze exited 1" in results[0].error
    assert "FAILED" in render_summary(results)
    evidence = Path(results[0].evidence_dir)
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["commands"]) == 3
    assert manifest["commands"][2]["returncode"] == 1
    assert manifest["commands"][2]["stdout"]["sha256"]
    assert manifest["commands"][2]["stderr"]["sha256"]
    assert (evidence / "README.md").is_file()


def test_uat_collects_llm_prompts_outputs_and_raw_transcripts(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    def evidence_runner(argv, cwd, env, output_dir, label):
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("standard output", encoding="utf-8")
        stderr.write_text("standard error", encoding="utf-8")
        logs = Path(env["DRYDOCK_WORKSPACE"]) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "call.prompt.md").write_text("prompt", encoding="utf-8")
        (logs / "call.output.txt").write_text("answer", encoding="utf-8")
        (logs / "call.raw.jsonl").write_text("{}\n", encoding="utf-8")
        (logs / "call.llm.log").write_text("tokens: 10\n", encoding="utf-8")
        (logs / "llm.jsonl").write_text("", encoding="utf-8")
        parts = tuple(argv)
        returncode = 1 if parts[3:5] == ("status", "ReadingList") and "--ready" in parts else 0
        return CommandResult(parts, returncode, 1, str(stdout), str(stderr), label, str(cwd))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=evidence_runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    evidence = Path(results[0].evidence_dir)
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert (evidence / "prompts" / "call.prompt.md").read_text() == "prompt"
    assert (evidence / "prompt_outputs" / "call.output.txt").read_text() == "answer"
    assert (evidence / "provider_raw" / "call.raw.jsonl").read_text() == "{}\n"
    assert (evidence / "llm_logs" / "call.llm.log").read_text() == "tokens: 10\n"
    assert {item["kind"] for item in manifest["llm_artifacts"]} == {
        "prompt",
        "prompt_output",
        "provider_raw",
        "llm_log",
        "llm_execution_records",
    }
    labels = [command["label"] for command in manifest["commands"]]
    for suffix in (
        "after-plan-build-status",
        "after-plan-target-status",
        "after-plan-workspace-status",
        "after-initial-build-build-status",
        "after-initial-build-target-status",
        "after-initial-build-workspace-status",
    ):
        assert any(label.endswith(suffix) for label in labels)


def test_run_uat_flattens_sources_and_tests_completed_build(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, name="CommonMark", updated=False)
    source = fixture / "test" / "spec_tests.py"
    source.parent.mkdir()
    source.write_text("# suite\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": "commonmark",
            "sources": ["sources/reading-list.md", "test/spec_tests.py"],
            "updates": [],
            "test_command": ["sh", "full_test.sh"],
            "acceptance": {"full": ["sh", "sources/full_test.sh"]},
        }),
        encoding="utf-8",
    )
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        del env
        parts = tuple(argv)
        calls.append((parts, cwd))
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        returncode = 1 if parts[3:5] == ("status", "commonmark") and "--ready" in parts else 0
        return CommandResult(parts, returncode, 1, str(stdout), str(stderr))

    run_id, results = run_uat(
        tmp_path,
        selected="CommonMark",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert results[0].status == "passed"
    staged_root = fixtures_root / "CommonMark" / "runs" / run_id / "sources"
    assert (staged_root / "spec_tests.py").read_text(encoding="utf-8") == "# suite\n"
    assert not (staged_root / "test").exists()
    assert any(str(staged_root) in argv for argv, _ in calls)
    assert (
        ("sh", "full_test.sh"),
        fixtures_root / "CommonMark" / "runs" / run_id / "build" / "commonmark",
    ) in calls


def test_run_uat_does_not_inject_a_retry_mode(tmp_path: Path) -> None:
    # UAT and interactive builds share one repair policy, so no mode marker crosses the process
    # boundary.
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    seen: list[str | None] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        seen.append(env.get("DRYDOCK_UAT"))
        parts = tuple(argv[3:])
        returncode = 1 if parts[:2] == ("status", "ReadingList") and "--ready" in parts else 0
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert seen and set(seen) == {None}


class _RecordingSink:
    """Collect what a streaming runner reports, in order, without any console formatting."""

    def __init__(self) -> None:
        self.steps: list[tuple[tuple[str, ...], str]] = []
        self.chunks: list[tuple[str, str]] = []
        self.finished: list[tuple[int, int]] = []

    def step(self, argv, label) -> None:
        self.steps.append((tuple(argv), label))

    def chunk(self, source, text) -> None:
        self.chunks.append((source, text))

    def finish(self, returncode, elapsed_ms) -> None:
        self.finished.append((returncode, elapsed_ms))

    def text(self, source: str) -> str:
        return "".join(text for name, text in self.chunks if name == source)


def _child(program: str) -> tuple[str, ...]:
    return (sys.executable, "-c", program)


def test_subprocess_runner_tees_both_streams_to_the_sink_and_to_evidence(tmp_path: Path) -> None:
    sink = _RecordingSink()
    program = (
        "import sys\n"
        "sys.stdout.write('building step 1\\n')\n"
        "sys.stderr.write('warning: no stack\\n')\n"
        "sys.stdout.write('done\\n')\n"
    )

    result = subprocess_runner(
        _child(program), tmp_path, dict(os.environ), tmp_path, "07-build", sink=sink
    )

    assert result.returncode == 0
    assert result.label == "07-build"
    assert sink.steps == [(tuple(_child(program)), "07-build")]
    assert sink.text("stdout") == "building step 1\ndone\n"
    assert sink.text("stderr") == "warning: no stack\n"
    # The evidence logs still hold the child's complete output, unchanged by the console.
    assert Path(result.stdout_path).read_text(encoding="utf-8") == "building step 1\ndone\n"
    assert Path(result.stderr_path).read_text(encoding="utf-8") == "warning: no stack\n"
    assert sink.finished and sink.finished[0][0] == 0


def test_subprocess_runner_preserves_carriage_returns_and_unterminated_lines(
    tmp_path: Path,
) -> None:
    # A progress line redraws with \r and never ends with \n. Line-buffered teeing would hold
    # it back until the process exited, which is the failure this runner exists to prevent.
    sink = _RecordingSink()
    program = "import sys\nsys.stdout.write('pass 1\\rpass 2')\n"

    result = subprocess_runner(
        _child(program), tmp_path, dict(os.environ), tmp_path, "08-progress", sink=sink
    )

    assert sink.text("stdout") == "pass 1\rpass 2"
    # Read as bytes: universal-newline decoding would hide whether the \r survived.
    assert Path(result.stdout_path).read_bytes() == b"pass 1\rpass 2"


def test_subprocess_runner_reports_a_failing_child_with_its_output_preserved(
    tmp_path: Path,
) -> None:
    sink = _RecordingSink()
    program = "import sys\nsys.stderr.write('boom\\n')\nraise SystemExit(3)\n"

    result = subprocess_runner(
        _child(program), tmp_path, dict(os.environ), tmp_path, "09-fail", sink=sink
    )

    assert result.returncode == 3
    assert sink.finished[0][0] == 3
    assert Path(result.stderr_path).read_text(encoding="utf-8") == "boom\n"


def test_streaming_runner_matches_the_runner_contract(tmp_path: Path) -> None:
    sink = _RecordingSink()
    runner = make_streaming_runner(sink)

    result = runner(_child("print('ok')"), tmp_path, dict(os.environ), tmp_path, "01-init")

    assert result.returncode == 0
    assert sink.text("stdout").strip() == "ok"
    assert sink.steps[0][1] == "01-init"


def test_run_uat_gives_every_child_an_unbuffered_environment(tmp_path: Path) -> None:
    # Buffering into a pipe would withhold a step's output until it exited.
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    seen: list[str | None] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        seen.append(env.get("PYTHONUNBUFFERED"))
        parts = tuple(argv[3:])
        returncode = 1 if parts[:2] == ("status", "ReadingList") and "--ready" in parts else 0
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert seen and set(seen) == {"1"}


def _stub_runner(calls: list[tuple[str, ...]], *, fail: tuple[str, ...] = ()):
    """Return a runner that records lifecycle argv and fails the named stage."""

    def runner(argv, cwd, env, output_dir, label):
        del env
        parts = tuple(argv[3:])
        calls.append(parts)
        returncode = 0
        if parts[:2] == ("status", "ReadingList") and "--ready" in parts:
            returncode = 1  # never ready: one status check, no build pass
        if fail and parts[: len(fail)] == fail:
            returncode = 1
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    return runner


def _seed_target_artifact(fixtures_root: Path, run_id: str, name: str) -> None:
    """Write the Target artifact a resumed stage requires, which a fake runner never produces."""
    target = (
        fixtures_root / "ReadingList" / "runs" / run_id / "workspace" / "targets" / "ReadingList"
    )
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_text(f"# {name}\n", encoding="utf-8")


def test_resume_reenters_the_newest_run_at_the_named_stage(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    first: list[tuple[str, ...]] = []
    run_id, failed = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner(first, fail=("plan",)),
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    assert failed[0].status == "failed"
    _seed_target_artifact(fixtures_root, run_id, "ANALYSIS.md")

    resumed_calls: list[tuple[str, ...]] = []
    resumed_id, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner(resumed_calls),
        start_stage="plan",
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    # The resumed run re-enters the same directory: no new run id, no repeated LLM stages.
    assert resumed_id == run_id
    assert results[0].status == "passed"
    assert results[0].resumed_from == "plan"
    assert ("plan", "ReadingList", "--override") in resumed_calls
    assert not [parts for parts in resumed_calls if parts[:1] in {("init",), ("analyze",)}]
    assert not [parts for parts in resumed_calls if parts[:1] == ("import",)]


def test_resume_supersedes_the_replayed_steps_and_keeps_their_numbers(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    run_id, failed = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner([], fail=("plan",)),
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    case_root = fixtures_root / "ReadingList" / "runs" / run_id
    before = sorted(path.name for path in (case_root / "evidence" / "commands").glob("*.log"))
    _seed_target_artifact(fixtures_root, run_id, "ANALYSIS.md")

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner([]),
        start_stage="plan",
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    commands_dir = case_root / "evidence" / "commands"
    after = sorted(path.name for path in commands_dir.glob("*.log"))
    labels = [command.label for command in results[0].commands]
    prior_labels = [command.label for command in failed[0].commands]
    # Steps before the resumed stage are untouched; the plan step is re-recorded at its own
    # number rather than appended past the end of the prior attempt.
    kept = [label for label in prior_labels if not label.endswith("-plan")]
    assert labels[: len(kept)] == kept
    assert "04-plan" in labels
    assert len(labels) == len(set(labels))
    # Numbering never runs past the step count: the live logs are exactly the receipt's steps.
    assert sorted(after) == sorted(
        f"{label}.{stream}.log" for label in labels for stream in ("stdout", "stderr")
    )
    # The superseded attempt is preserved, out of the way, under its own timestamp.
    archived = sorted(path.name for path in commands_dir.glob("superseded/*/*.log"))
    assert any(name.startswith("04-plan") for name in archived)
    assert set(before) <= set(archived) | set(after)


def test_resume_rejects_an_unknown_stage_and_a_run_without_a_stage(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    with pytest.raises(SpecificationError, match="Unknown UAT stage"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner([]),
            start_stage="compile",
        )
    with pytest.raises(SpecificationError, match="resume stage"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner([]),
            run="20260809T000000.000000Z",
        )


def test_resume_without_a_prior_run_names_the_missing_history(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    with pytest.raises(SpecificationError, match="No completed run to resume"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner([]),
            start_stage="build",
        )


def test_resume_into_a_stage_with_no_input_names_the_producing_stage(tmp_path: Path) -> None:
    # Resuming at `build` after a failed `plan` must not spend two commands discovering that
    # no MANIFEST.md exists; it must name the stage that produces one.
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    run_id, _ = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner([], fail=("plan",)),
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    target = fixtures_root / "ReadingList" / "runs" / run_id / "workspace" / "targets"
    # ``init`` seeds the governed acceptance contract, so the Target directory already exists.
    (target / "ReadingList").mkdir(parents=True, exist_ok=True)
    (target / "ReadingList" / "ANALYSIS.md").write_text("# analysis\n", encoding="utf-8")

    calls: list[tuple[str, ...]] = []
    with pytest.raises(SpecificationError, match=r"MANIFEST.md does not exist"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner(calls),
            start_stage="build",
        )
    assert calls == []

    # The stage whose input does exist is accepted.
    run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner(calls),
        start_stage="plan",
    )
    assert ("plan", "ReadingList", "--override") in calls


def test_shipped_kits_declare_every_asset_their_score_command_runs() -> None:
    # A kit whose scoring entry point is not among its declared sources leaves the script to be
    # authored by the build agent, which is both nondeterministic and self-scoring. When the
    # command names a path under `sources/`, that asset must ship with the kit.
    uat_root = Path(__file__).resolve().parents[1] / "uat"
    for config_path in sorted(uat_root.glob("*/uat.json")):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        declared = set(config["sources"])
        for source in declared:
            assert (config_path.parent / source).is_file(), f"{config_path}: missing {source}"
        commands = [config["acceptance"]["full"], config.get("test_command") or []]
        for argument in [item for command in commands for item in command]:
            if argument.startswith("sources/"):
                assert argument in declared, f"{config_path}: {argument} is not a declared source"


def test_every_shipped_kit_is_graded_by_a_staged_commander_owned_harness() -> None:
    """Each kit's release gate must run an oracle the build cannot author.

    Without a governed full gate the release verdict rests entirely on the grader's judgement,
    and a criterion the grader cannot settle is MANUAL, which never blocks — so an unbuilt
    project reads as PASSED. One staged ``sources/full_test.sh`` per kit closes that path.
    """
    uat_root = Path(__file__).resolve().parents[1] / "uat"
    configs = sorted(uat_root.glob("*/uat.json"))
    assert configs
    for config_path in configs:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["acceptance"]["full"] == ["sh", "sources/full_test.sh"], config_path
        harness = config_path.parent / "sources" / "full_test.sh"
        assert harness.is_file(), f"{config_path}: no staged sources/full_test.sh"
        assert subprocess.run(["sh", "-n", str(harness)]).returncode == 0, harness


def test_run_ids_are_readable_and_stay_chronological_across_the_format_change() -> None:
    # A run id is read by a person before it is parsed by anything, and one kit cannot start
    # two runs in the same second. Ordering must still hold against ids written by the
    # retired format, which punctuates the same instant differently.
    assert datetime(2026, 8, 9, 20, 44, 59, tzinfo=UTC).strftime("%Y%m%d.%H%M%S") == (
        "20260809.204459"
    )
    ordered = sorted(
        ["20260809T204459.901240Z", "20260809.204500", "20260808.235959"], key=run_sort_key
    )
    assert ordered == ["20260808.235959", "20260809T204459.901240Z", "20260809.204500"]


# --- Degraded runs -----------------------------------------------------------
#
# A build that exhausts its repair budget is a terminal state, not an aborted one. Stopping
# the run there discards the measurement the UAT exists to take: the partial application, the
# scores over it, and the test command's verdict are the only record of how far Drydock got.


def _staged_runner(tmp_path: Path, *, failing: tuple[str, ...], ready_passes: int = 1):
    """A runner that reports the target ready ``ready_passes`` times, then fails ``failing``."""
    seen: list[str] = []

    def runner(argv, cwd, env, output_dir, label):
        del env
        parts = tuple(argv[3:])
        seen.append(label)
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        returncode = 0
        if parts[:1] == ("status",) and "--ready" in parts:
            returncode = 0 if sum(1 for item in seen if "ready" in item) <= ready_passes else 1
        elif any(token in label for token in failing):
            returncode = 1
        return CommandResult(tuple(argv), returncode, 1, str(stdout), str(stderr), label, str(cwd))

    return runner, seen


def test_a_failed_build_stops_the_run(tmp_path: Path) -> None:
    """A build that reached its terminal state ends the run; nothing downstream is measured.

    Scoring a build that stopped part way grades the absence of the entry point the last
    stories deliver, and publishes a number that invites acting on it.
    """
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, seen = _staged_runner(tmp_path, failing=("initial-build",))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    result = results[0]
    assert result.status == "failed"
    assert "stopped at initial-build-1" in result.error
    assert "initial-build-1 exited 1" in result.degraded
    assert not any(label.endswith("initial-complete") for label in seen)
    assert not any(label.endswith("-test") for label in seen)
    # No score is taken over a build that never finished.
    assert not any("score-" in label for label in seen)
    assert result.score_exit_codes == {}


def test_a_stopped_run_records_why_at_the_target_root(tmp_path: Path) -> None:
    """``STOP_NOW.md`` is the first file to open in a halted run tree."""
    from drydock.stop_condition import read_stop

    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, _ = _staged_runner(tmp_path, failing=("initial-build",))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    target_dir = (
        fixtures_root
        / "ReadingList"
        / "runs"
        / results[0].run_id
        / "workspace"
        / "targets"
        / "ReadingList"
    )
    halt = read_stop(target_dir)
    assert halt is not None
    assert halt.stage == "initial-build-1"
    assert "exited 1" in halt.reason
    assert halt.declared_at


def test_incomplete_status_snapshot_does_not_gate_an_empty_frontier(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, seen = _staged_runner(
        tmp_path,
        failing=("initial-complete",),
        ready_passes=0,
    )

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    result = results[0]
    assert result.status == "passed"
    assert result.execution_status == "PASS"
    assert result.build_passes == 0
    assert any(label.endswith("initial-complete") for label in seen)
    assert not result.degraded


def test_a_stopped_run_never_reaches_final_validation(
    tmp_path: Path,
) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, seen = _staged_runner(tmp_path, failing=("initial-build", "test"))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    # The scoring command is the terminal story's deliverable, so a build that stopped early has
    # nothing to run it against. Running it anyway records a missing harness as a product
    # failure, which is the one thing the run must not claim.
    result = results[0]
    assert result.status == "failed"
    assert not any(label.endswith("-test") for label in seen)
    # Never observed, therefore never graded — not passed, and not failed.
    assert result.acceptance_status == "NOT_RUN"


def test_a_clean_build_that_fails_its_test_command_still_fails_the_run(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, seen = _staged_runner(tmp_path, failing=("test",))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].status == "failed"
    assert "test exited 1" in results[0].error
    # The scores still ran: they describe the same application the test command just measured.
    assert any("score-release" in label for label in seen)


# ── the fixture's expected verdict ────────────────────────────────────────────
# UAT does not ask "did the fixture project pass". It asks "did Drydock reach the correct
# conclusion about it". A fixture carrying a known product defect expects FAILED, and Drydock
# naming that defect is the harness working — the run passes. Read the other way, eight runs of
# a fixture with a real defect produced no signal about Drydock at all, because every one of them
# read as Drydock failing.


def test_a_fixture_expects_passed_unless_it_says_otherwise(tmp_path: Path) -> None:
    _fixture(tmp_path)

    assert discover_fixtures(tmp_path)[0].expected_verdict == "PASSED"


def test_a_fixture_declares_the_verdict_it_expects(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _declare(fixture, expect={"verdict": "failed"})

    assert discover_fixtures(tmp_path)[0].expected_verdict == "FAILED"


def test_an_unknown_expected_verdict_is_refused_at_discovery(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _declare(fixture, expect={"verdict": "DEGRADED"})

    with pytest.raises(SpecificationError) as excinfo:
        discover_fixtures(tmp_path)
    assert "expect.verdict" in str(excinfo.value)


def test_a_fixture_that_expects_failure_passes_by_reporting_one(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, updated=False)
    _declare(fixture, expect={"verdict": "FAILED"})
    runner, _ = _staged_runner(tmp_path, failing=("test",))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].status == "passed"
    assert results[0].observed_verdict == "FAILED"
    assert results[0].acceptance_status == "FAIL"
    # The run passed and the product failure is still named. A harness that swallowed it here
    # would be reporting that nothing happened.
    assert "test exited 1" in results[0].error


def test_a_fixture_that_expects_failure_and_passes_instead_fails_the_run(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, updated=False)
    _declare(fixture, expect={"verdict": "FAILED"})
    runner, _ = _staged_runner(tmp_path, failing=())

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].status == "failed"
    assert results[0].observed_verdict == "PASSED"
    assert "expected verdict FAILED, observed PASSED" in results[0].error


def test_an_infrastructure_fault_never_satisfies_an_expected_failure(tmp_path: Path) -> None:
    """ERROR is not FAILED. A run that could not execute has said nothing about the product."""
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, updated=False)
    _declare(fixture, expect={"verdict": "FAILED"})
    runner, _ = _staged_runner(tmp_path, failing=("build",))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].status != "passed"
    assert results[0].execution_status == "ERROR"
    assert results[0].observed_verdict == "ERROR"


def test_the_summary_states_the_expected_and_observed_verdicts(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, _ = _staged_runner(tmp_path, failing=())

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert "Verdict: expected PASSED, observed PASSED" in render_summary(results)


def test_every_shipped_kit_declares_the_verdict_it_expects() -> None:
    """The kits are Drydock's own acceptance record, so each must state what it is testing for."""
    root = Path(__file__).resolve().parents[1] / "uat"
    for kit in sorted(path for path in root.iterdir() if (path / "uat.json").is_file()):
        config = json.loads((kit / "uat.json").read_text(encoding="utf-8"))
        assert config.get("expect", {}).get("verdict"), f"{kit.name} declares no expected verdict"


def test_a_run_with_no_failures_still_passes(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, _ = _staged_runner(tmp_path, failing=())

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].status == "passed"
    assert results[0].degraded == ()


def test_a_stopped_build_skips_refit_and_scoring_alike(tmp_path: Path) -> None:
    """A refit re-specifies work against a build that completed, so a stopped build has none.

    Nothing downstream of the halt runs: not the refit, not the test command, not the scores.
    """
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=True)
    runner, seen = _staged_runner(tmp_path, failing=("initial-build",))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].status == "failed"
    assert not any("import-update" in label for label in seen)
    assert not any("refit-update" in label for label in seen)
    assert not any("score-" in label for label in seen)


def test_a_clean_build_still_runs_its_refit_stage(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=True)
    runner, seen = _staged_runner(tmp_path, failing=())

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert results[0].status == "passed"
    assert any("import-update" in label for label in seen)
    assert any("refit-update" in label for label in seen)


# --- Frozen fixture Sea Trials ------------------------------------------------
#
# Without this the model authors the exam it is then graded on, so every run is a fresh
# random draw of acceptance criteria and no two runs measure the same thing. That is why a
# fixture could stop passing without changing.


def test_every_shipped_fixture_ships_a_parseable_frozen_contract():
    from drydock.sea_trials import parse_sea_trials_text
    from drydock.uat import discover_fixtures

    fixtures = discover_fixtures(Path(__file__).resolve().parents[1] / "uat")

    assert fixtures
    for fixture in fixtures:
        assert fixture.sea_trials is not None, fixture.name
        document = parse_sea_trials_text(fixture.sea_trials.read_text(encoding="utf-8"))
        assert document.trials
        # A frozen exam whose policy is not also frozen is only half fixed.
        assert document.policy_declared is True


def test_shipped_fixtures_declare_lifecycle_inputs_under_inputs():
    root = Path(__file__).resolve().parents[1] / "uat"

    for name in ("CommonMark", "ReadingList", "Toml"):
        config = json.loads((root / name / "uat.json").read_text(encoding="utf-8"))
        assert config["sea_trials"] == "inputs/SEA_TRIALS.md"
        assert config["technology_stack"] == "inputs/TECHNOLOGY_STACK.md"
        assert (root / name / config["sea_trials"]).is_file()
        assert (root / name / config["technology_stack"]).is_file()


def test_commonmark_has_one_deterministic_blocking_proof_criterion():
    document = sea_trials.parse_sea_trials_text(
        (Path(__file__).resolve().parents[1] / "uat/CommonMark/inputs/SEA_TRIALS.md").read_text(
            encoding="utf-8"
        )
    )

    assert document.policy_declared is True
    assert len(document.trials) == 1
    trial = document.trials[0]
    assert trial.criterion_id == "st-001"
    assert trial.required is True
    assert trial.testability == "deterministic"
    assert trial.consequence == "blocks"
    assert trial.verification == "proof"
    assert trial.criterion == (
        "The completed parser shall pass every test run by sh sources/full_test.sh."
    )


def test_a_fixture_contract_is_seeded_into_the_target(tmp_path):
    from drydock.uat import UATFixture, seed_sea_trials

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    contract = fixture_root / "SEA_TRIALS.md"
    contract.write_text(
        "# Sea Trials: Demo\n\n## st-001: Example\n"
        "Type: technical\nRequired: yes\nCriterion: The system shall work.\n"
        "Verification: proof\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"

    written = seed_sea_trials(
        UATFixture("Demo", "Demo", fixture_root, (), (), (), None, contract), workspace
    )

    assert written == workspace / "targets" / "Demo" / "SEA_TRIALS.md"
    assert written.read_text(encoding="utf-8") == contract.read_text(encoding="utf-8")


def test_a_fixture_without_a_contract_seeds_nothing(tmp_path):
    from drydock.uat import UATFixture, seed_sea_trials

    assert seed_sea_trials(UATFixture("Demo", "Demo", tmp_path, (), (), ()), tmp_path) is None


def test_an_unparseable_fixture_contract_is_refused_at_discovery(tmp_path):
    from drydock.uat import _fixture_sea_trials

    (tmp_path / "SEA_TRIALS.md").write_text(
        "# Sea Trials: Demo\n\nnothing here\n", encoding="utf-8"
    )

    with pytest.raises(SpecificationError, match="Invalid UAT fixture Sea Trials"):
        _fixture_sea_trials(tmp_path / "SEA_TRIALS.md")


def test_the_environment_records_the_package_version_without_installed_metadata(monkeypatch):
    from importlib import metadata

    from drydock import __version__
    from drydock.uat import _environment

    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)

    assert _environment("model", "provider", None)["drydock_version"] == __version__


# ── resuming at a recorded step ───────────────────────────────────────────────


def test_every_recorded_label_maps_to_the_stage_that_produced_it() -> None:
    from drydock.uat import stage_for_label

    assert stage_for_label("01-init") == "init"
    assert stage_for_label("02-import-sources") == "import"
    assert stage_for_label("03-analyze") == "analyze"
    assert stage_for_label("04-plan") == "plan"
    assert stage_for_label("05-after-plan-build-status") == "plan"
    # ``init`` is a prefix of ``initial-``; the build stage must win.
    assert stage_for_label("10-initial-ready") == "build"
    assert stage_for_label("12-after-initial-build-target-status") == "build"
    assert stage_for_label("20-import-update-1") == "refit"
    assert stage_for_label("21-refit-update-1") == "refit"
    assert stage_for_label("22-after-refit-1-build-status") == "refit"
    assert stage_for_label("15-test") == "test"
    assert stage_for_label("16-score-acceptance") == "score"


def test_an_unmapped_label_is_rejected_rather_than_guessed() -> None:
    from drydock.uat import stage_for_label

    with pytest.raises(SpecificationError, match="no resumable stage"):
        stage_for_label("07-compile-everything")


def _failed_run(tmp_path: Path) -> tuple[Path, str]:
    """Produce a real run directory whose scoring step is the one an operator would re-enter."""
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    run_id, _ = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner([]),
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    return fixtures_root, run_id


def test_a_step_number_resolves_to_the_stage_that_owns_it(tmp_path: Path) -> None:
    from drydock.uat import resolve_step_stage, run_steps

    fixtures_root, run_id = _failed_run(tmp_path)
    fixture = discover_fixtures(fixtures_root, "ReadingList")[0]
    steps = run_steps(fixtures_root / "ReadingList" / "runs" / run_id)
    scoring = next(step.number for step in steps if "score-acceptance" in step.label)

    resolved_run, step, entry = resolve_step_stage(fixture, None, scoring)

    assert resolved_run == run_id
    assert step.stage == "score"
    assert step.number == scoring
    # The stage replays from its first step, which the operator is told about by number.
    assert entry.stage == "score"
    assert entry.number == next(item.number for item in steps if item.stage == "score")


def test_a_step_outside_the_recorded_run_is_rejected(tmp_path: Path) -> None:
    from drydock.uat import resolve_step_stage

    fixtures_root, _ = _failed_run(tmp_path)
    fixture = discover_fixtures(fixtures_root, "ReadingList")[0]

    with pytest.raises(SpecificationError, match="out of range"):
        resolve_step_stage(fixture, None, 999)
    with pytest.raises(SpecificationError, match="out of range"):
        resolve_step_stage(fixture, None, 0)


def test_resuming_at_the_init_step_directs_the_operator_to_a_new_run(tmp_path: Path) -> None:
    from drydock.uat import resolve_step_stage

    fixtures_root, _ = _failed_run(tmp_path)
    fixture = discover_fixtures(fixtures_root, "ReadingList")[0]

    with pytest.raises(SpecificationError, match="Start a new run"):
        resolve_step_stage(fixture, None, 1)


def test_the_step_listing_numbers_every_recorded_step_with_its_stage(tmp_path: Path) -> None:
    from drydock.uat import render_steps

    fixtures_root, run_id = _failed_run(tmp_path)
    fixture = discover_fixtures(fixtures_root, "ReadingList")[0]

    listing = render_steps(fixture, None)

    assert f"ReadingList run {run_id}" in listing
    assert "  1  01-init" in listing
    assert "score" in listing
    assert "--from-step" in listing


def test_a_kit_named_in_another_case_still_records_the_directory_spelling(tmp_path: Path) -> None:
    """A case-insensitive filesystem must not leak the operator's spelling into recorded paths."""
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, name="CommonMark", updated=False)

    fixtures = discover_fixtures(fixtures_root, "commonmark")

    assert fixtures[0].root.name == "CommonMark"


# ── LLM executions are recorded per command ───────────────────────────────────


def test_each_command_records_the_llm_executions_it_produced(tmp_path: Path) -> None:
    """The report joins transcripts to steps with these ids, not with console banners."""
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    written: list[str] = []

    def runner(argv, cwd, env, output_dir, label):
        del env
        parts = tuple(argv[3:])
        records = cwd / "logs" / "llm.jsonl"
        records.parent.mkdir(parents=True, exist_ok=True)
        # analyze makes one call and prints a banner; build makes two and prints nothing.
        calls = {"analyze": 1, "build": 2}.get(parts[0] if parts else "", 0)
        with records.open("a", encoding="utf-8") as handle:
            for index in range(calls):
                execution_id = f"{parts[0]}-{len(written) + index}"
                written.append(execution_id)
                handle.write(json.dumps({"execution_id": execution_id}) + "\n")
        returncode = 1 if parts[:2] == ("status", "ReadingList") and "--ready" in parts else 0
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    by_label = {command.label: command.llm_executions for command in results[0].commands}
    analyze = next(ids for label, ids in by_label.items() if label.endswith("-analyze"))
    assert len(analyze) == 1
    # A command that made no call claims none of another command's executions.
    assert by_label[next(label for label in by_label if label.endswith("-init"))] == ()
    assert sum(len(ids) for ids in by_label.values()) == len(written)


# ── assertion attribution and decision carry-forward ──────────────────────────────────


def test_an_unverified_assertion_is_not_also_charged_to_the_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``failed`` was ``total - passed``, which counted every harness defect twice: once as the
    kit fault it is, and once as a product defect it is not."""
    from drydock import uat as uat_module

    class _Report:
        total_checks = 5
        passed_checks = 3
        unverified_checks = 2

    monkeypatch.setattr(uat_module, "build_score_report", lambda *a, **k: _Report())

    counts = uat_module._assertion_outcomes(tmp_path, "Demo", tmp_path / "llm.jsonl")

    assert counts == {
        "passed": 3,
        "failed": 0,
        "unverified": 2,
        "product_defects": 0,
        "harness_defects": 2,
    }
    assert counts["passed"] + counts["failed"] + counts["unverified"] == _Report.total_checks


def test_answered_decisions_carry_into_the_next_run(tmp_path: Path) -> None:
    """UAT is a process, not a clean room: a question a human answered stays answered."""
    from drydock.decisions import Decision, load_decisions, write_decisions
    from drydock.uat import discover_fixtures, prior_decisions, seed_prior_decisions

    fixture_root = _fixture(tmp_path)
    fixture = discover_fixtures(tmp_path)[0]
    prior = fixture_root / "runs" / "20260101.000000" / "inputs"
    prior.mkdir(parents=True)
    write_decisions(
        prior / "DECISIONS.json",
        (
            Decision(
                id="analyze-display_name",
                type="text",
                severity="material",
                origin="analyze-questionnaire",
                blueprint="ARCHITECTURE.md",
                story=None,
                status="answered",
                archived=False,
                title="Display Name",
                description="",
                options=(),
                system_choice="Proposed",
                commander_direction="Chosen By Hand",
            ),
            # Drydock's own proposal. Re-derived every run, so carrying it would cache a machine
            # decision and hide that Drydock stopped making it.
            Decision(
                id="build-env-x",
                type="text",
                severity="material",
                origin="build",
                blueprint="FEATURE-X.md",
                story=None,
                status="recommended",
                archived=False,
                title="Acceptance environment supplied: x",
                description="",
                options=(),
                system_choice="JQ=./jq",
            ),
        ),
    )

    case_root = fixture_root / "runs" / "20260202.000000"
    case_root.mkdir(parents=True)
    workspace = case_root / "workspace"
    assert [item.id for item in prior_decisions(fixture, case_root)] == ["analyze-display_name"]

    written = seed_prior_decisions(fixture, workspace, case_root)
    assert written is not None
    seeded = load_decisions(written)
    assert [item.id for item in seeded] == ["analyze-display_name"]
    assert seeded[0].commander_direction == "Chosen By Hand"


def test_the_runs_decisions_become_an_input_for_the_next_run(tmp_path: Path) -> None:
    from drydock.decisions import Decision, write_decisions
    from drydock.uat import capture_decisions, discover_fixtures

    fixture_root = _fixture(tmp_path)
    fixture = discover_fixtures(tmp_path)[0]
    case_root = fixture_root / "runs" / "20260202.000000"
    target_dir = case_root / "workspace" / "targets" / "ReadingList"
    target_dir.mkdir(parents=True)
    write_decisions(
        target_dir / "DECISIONS.json",
        (
            Decision(
                id="analyze-display_name",
                type="text",
                severity="material",
                origin="analyze-questionnaire",
                blueprint="ARCHITECTURE.md",
                story=None,
                status="answered",
                archived=False,
                title="Display Name",
                description="",
                options=(),
                system_choice="Proposed",
                commander_direction="Chosen By Hand",
            ),
        ),
    )

    captured = capture_decisions(fixture, case_root / "workspace", case_root)

    assert captured == case_root / "inputs" / "DECISIONS.json"
    assert captured.is_file()


def test_no_prior_run_seeds_nothing(tmp_path: Path) -> None:
    from drydock.uat import discover_fixtures, seed_prior_decisions

    fixture_root = _fixture(tmp_path)
    fixture = discover_fixtures(tmp_path)[0]
    case_root = fixture_root / "runs" / "20260202.000000"
    assert seed_prior_decisions(fixture, case_root / "workspace", case_root) is None


def test_an_unbuildable_manifest_stops_the_run_before_the_first_build_pass(
    tmp_path: Path,
) -> None:
    """A frontier that was empty on arrival is a halt, not a completed build.

    ``status --ready`` returns the same nonzero code for a Target that finished and one whose
    stories are all parked behind blocking decisions. Before the first pass the two are
    opposites, and ``status --check`` separates them.
    """
    from drydock.stop_condition import read_stop

    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, seen = _staged_runner(
        tmp_path,
        failing=("initial-unstarted-check",),
        ready_passes=0,
    )

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    result = results[0]
    assert result.status == "failed"
    assert result.build_passes == 0
    assert any(
        "no buildable frontier before the first build pass" in item for item in result.degraded
    )
    assert "stopped at initial" in result.error
    # Nothing below the build is measured: there is no application to measure.
    assert not any(label.endswith("-test") for label in seen)
    assert not any("score-" in label for label in seen)

    target_dir = (
        fixtures_root
        / "ReadingList"
        / "runs"
        / sorted((fixtures_root / "ReadingList" / "runs").iterdir())[-1].name
        / "workspace"
        / "targets"
        / "ReadingList"
    )
    stop = read_stop(target_dir)
    assert stop is not None
    assert "DECISIONS.json" in stop.reason


def test_a_complete_target_still_passes_with_an_empty_frontier_at_pass_zero(
    tmp_path: Path,
) -> None:
    """A resumed stage may legitimately arrive with the work already done."""
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    runner, seen = _staged_runner(tmp_path, failing=(), ready_passes=0)

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=runner,
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    result = results[0]
    assert result.status == "passed"
    assert not result.degraded
    assert any(label.endswith("initial-unstarted-check") for label in seen)
