"""AC repair: DISPUTED and malformed criteria are repaired blind to the product and kept only
when the empty-directory baseline records them VALID; DISPUTED holds ``status --check``."""

import json

from drydock import ac_repair
from drydock.acceptance import parse_programmatic_acceptance
from drydock.acceptance_status import (
    ERROR_MALFORMED,
    STATUS_ERROR,
    STATUS_UNFIXABLE,
    STATUS_VALID,
    CriterionStatus,
    code_digest,
    current_status,
    read_acceptance_status,
    record_baseline_status,
)
from drydock.status import COMPLETE, RETRYABLE, completion_check

_MANIFEST = """# MANIFEST: Demo
state: approved

## story 1: Greeting
id: greeting
implements: FEATURE-Greeting.md
state: closed/verified
"""

#: A backslash in the expected value is what still marks it re-typed (2026-10-21).
_DISPUTED_CODE = (
    "import subprocess\n"
    'result = subprocess.run(["./greet"], capture_output=True, text=True)\n'
    'assert result.stdout == "Hello, C:\\\\World!\\n"'
)

_SPEC = f"""# FEATURE: Greeting

The greeter prints the banner stated in sources/banner.txt.

## Programmatic Acceptance

=== AC greets ===
Intent: The greeter prints the banner.

{_DISPUTED_CODE}
=== END AC greets ===
"""

_BINDING_REPAIR = """=== AC FEATURE-Greeting.md :: greets ===
Intent: The greeter prints the banner.
Cite: sources/banner.txt:1

import subprocess
result = subprocess.run(["./greet"], capture_output=True, text=True)
assert result.stdout == "Hello, C:\\\\World!\\n"
=== END AC FEATURE-Greeting.md :: greets ===
"""

_PASSES_WITH_NOTHING = """=== AC FEATURE-Greeting.md :: greets ===
Intent: The greeter prints the banner.

assert len("abc") == 3
=== END AC FEATURE-Greeting.md :: greets ===
"""


class _Result:
    def __init__(self, text, ok=True):
        self.ok = ok
        self.text = text
        self.execution_id = "exec-1"
        self.stderr = ""


def _runner(text, calls=None):
    def run(prompt, working_directory, **kwargs):
        if calls is not None:
            calls.append(prompt)
        return _Result(text)

    return run


def _target(tmp_path, *, outcome_binding=False):
    target_dir = tmp_path / "Demo"
    blueprint = target_dir / "blueprint"
    (blueprint / "sources").mkdir(parents=True)
    (blueprint / "sources" / "banner.txt").write_text("Hello, C:\\World!\n", encoding="utf-8")
    (blueprint / "FEATURE-Greeting.md").write_text(_SPEC, encoding="utf-8")
    (target_dir / "MANIFEST.md").write_text(_MANIFEST, encoding="utf-8")
    row = {
        "block": "greeting",
        "details": {
            "acceptance": [{"check_id": "greets", "passed": False, "binding": outcome_binding}]
        },
    }
    (target_dir / "BUILD_LINEAGE.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return target_dir


def _check(target_dir):
    (check,) = parse_programmatic_acceptance(target_dir / "blueprint" / "FEATURE-Greeting.md")
    return check


def test_a_disputed_criterion_is_selected_and_holds_the_completion_check(tmp_path):
    target_dir = _target(tmp_path)

    (candidate,) = ac_repair.select_repairs(target_dir)

    assert candidate.kind == ac_repair.KIND_DISPUTED
    assert "Hello, C:" in candidate.fault
    check = completion_check("Demo", target_dir)
    assert check.outcome == RETRYABLE
    assert "disputed acceptance criteria: greets" in check.reason


def test_a_binding_fail_is_not_selected(tmp_path):
    target_dir = _target(tmp_path, outcome_binding=True)
    assert ac_repair.select_repairs(target_dir) == ()


def test_a_malformed_status_is_selected(tmp_path):
    target_dir = _target(tmp_path, outcome_binding=True)
    check = _check(target_dir)
    record_baseline_status(
        target_dir / "evidence",
        {"greets": CriterionStatus(STATUS_ERROR, ERROR_MALFORMED, code_digest(check.code), "")},
    )
    (candidate,) = ac_repair.select_repairs(target_dir)
    assert candidate.kind == ac_repair.KIND_MALFORMED


def test_the_prompt_carries_specification_and_sources_never_the_product(tmp_path):
    target_dir = _target(tmp_path)
    build = tmp_path / "build"
    build.mkdir()
    (build / "greet").write_text("PRODUCT SOURCE TEXT\n", encoding="utf-8")
    calls: list[str] = []

    ac_repair.repair("Demo", target_dir, runner=_runner(_BINDING_REPAIR, calls))

    (prompt,) = calls
    assert 'kind="disputed"' in prompt
    assert "The greeter prints the banner stated in sources/banner.txt." in prompt
    assert "    1| Hello, C:\\World!" in prompt
    assert "PRODUCT SOURCE TEXT" not in prompt


def test_a_cited_binding_repair_that_fails_with_no_product_is_kept(tmp_path):
    target_dir = _target(tmp_path)

    result = ac_repair.repair("Demo", target_dir, runner=_runner(_BINDING_REPAIR))

    assert [item.status for item in result.items] == ["repaired"]
    assert result.changed_files == ("FEATURE-Greeting.md",)
    repaired = _check(target_dir)
    assert repaired.check_id == "greets"
    assert repaired.binding
    status = current_status(read_acceptance_status(target_dir / "evidence"), repaired)
    assert status.status == STATUS_VALID
    # Repaired and binding: no longer DISPUTED work, so the gate clears.
    assert ac_repair.select_repairs(target_dir) == ()
    assert completion_check("Demo", target_dir).outcome == COMPLETE


def test_a_repair_that_passes_with_no_product_is_reverted_and_unfixable(tmp_path):
    target_dir = _target(tmp_path)

    result = ac_repair.repair("Demo", target_dir, runner=_runner(_PASSES_WITH_NOTHING))

    (item,) = result.items
    assert item.status == "unfixable"
    assert "PREBUILD_PASSES" in item.detail
    assert result.changed_files == ()
    original = _check(target_dir)
    assert original.code == _DISPUTED_CODE
    status = current_status(read_acceptance_status(target_dir / "evidence"), original)
    assert status.status == STATUS_UNFIXABLE
    # UNFIXABLE is terminal and clean: it stops holding the gate.
    assert ac_repair.select_repairs(target_dir) == ()
    assert completion_check("Demo", target_dir).outcome == COMPLETE


def test_a_repair_that_still_retypes_is_rejected(tmp_path):
    target_dir = _target(tmp_path)
    uncited = _BINDING_REPAIR.replace("Cite: sources/banner.txt:1\n", "")

    (item,) = ac_repair.repair("Demo", target_dir, runner=_runner(uncited)).items

    assert item.status == "unfixable"
    assert "re-types" in item.detail


def test_repair_impossible_records_unfixable(tmp_path):
    target_dir = _target(tmp_path)
    text = "REPAIR_IMPOSSIBLE: FEATURE-Greeting.md :: greets — no independent source\n"

    (item,) = ac_repair.repair("Demo", target_dir, runner=_runner(text)).items

    assert item.status == "unfixable"
    assert item.detail == "no independent source"


def test_a_failed_call_records_nothing(tmp_path):
    target_dir = _target(tmp_path)

    def run(prompt, working_directory, **kwargs):
        return _Result("", ok=False)

    result = ac_repair.repair("Demo", target_dir, runner=run)

    assert result.error
    assert read_acceptance_status(target_dir / "evidence") == {}


def test_nothing_selected_spends_nothing(tmp_path):
    target_dir = _target(tmp_path, outcome_binding=True)

    def run(*args, **kwargs):
        raise AssertionError("no call expected")

    assert ac_repair.repair("Demo", target_dir, runner=run).items == ()


def test_diagnose_apply_repairs_disputed_criteria_before_diagnosing(tmp_path, monkeypatch):
    import drydock.config as config
    import drydock.diagnose_command as command
    from drydock.build_plan import parse_build_plan
    from drydock.diagnose_console import Style

    workspace = tmp_path / "ws"
    (workspace / "logs").mkdir(parents=True)
    target_dir = _target(workspace / "targets")
    monkeypatch.setattr(config, "get_workspace", lambda: workspace)
    monkeypatch.setattr(config, "get_target_directory", lambda: workspace / "targets")
    monkeypatch.setattr(command, "_provider_unavailable", lambda llm=None: "")
    calls: list[str] = []
    printed: list[str] = []

    result = command.run(
        "Demo",
        mode="apply",
        runner=_runner(_BINDING_REPAIR, calls),
        out=printed.append,
        style=Style(width=1000),
    )

    output = "\n".join(printed)
    assert result.exit_code == 0
    assert len(calls) == 1
    assert "repaired (disputed)" in output
    assert "── Diagnosing " not in output
    # The repaired Blueprint resets its consumer so the next build runs the new criterion.
    plan = parse_build_plan(target_dir / "MANIFEST.md")
    assert plan.by_id()["greeting"].state == "pending"


def _diagnose(tmp_path, monkeypatch, *, confirm):
    import drydock.config as config
    import drydock.diagnose_command as command
    from drydock.diagnose_console import Style

    workspace = tmp_path / "ws"
    (workspace / "logs").mkdir(parents=True)
    target_dir = _target(workspace / "targets")
    monkeypatch.setattr(config, "get_workspace", lambda: workspace)
    monkeypatch.setattr(config, "get_target_directory", lambda: workspace / "targets")
    monkeypatch.setattr(command, "_provider_unavailable", lambda llm=None: "")
    printed: list[str] = []
    result = command.run(
        "Demo",
        mode="confirm",
        runner=_runner(_BINDING_REPAIR),
        out=printed.append,
        style=Style(width=1000),
        confirm=confirm,
    )
    return result, target_dir, "\n".join(printed)


def test_diagnose_confirm_mode_asks_before_keeping_a_repair(tmp_path, monkeypatch):
    questions: list[str] = []

    def confirm(question):
        questions.append(question)
        return True

    result, target_dir, output = _diagnose(tmp_path, monkeypatch, confirm=confirm)

    assert result.exit_code == 0
    (question,) = questions
    assert "FEATURE-Greeting.md [greets] (disputed)" in question
    assert "Cite: sources/banner.txt:1" in question
    assert "repaired (disputed)" in output
    assert _check(target_dir).binding


def test_a_declined_repair_leaves_the_criterion_selected(tmp_path, monkeypatch):
    result, target_dir, output = _diagnose(tmp_path, monkeypatch, confirm=lambda question: False)

    assert "declined" in output
    assert _check(target_dir).code == _DISPUTED_CODE
    assert read_acceptance_status(target_dir / "evidence") == {}
    assert [candidate.kind for candidate in ac_repair.select_repairs(target_dir)] == [
        ac_repair.KIND_DISPUTED
    ]


def test_repair_context_includes_selected_language_compact(tmp_path):
    from drydock.ac_repair import assemble
    from drydock.technology_stack import StackEntry, write

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    for language in ("python", "go"):
        write(tmp_path, [StackEntry("Selected", f"{language}.md")])
        assembly = assemble("Repair the criteria.", (), blueprint)
        assert f"{language}_compact.md" in [part.label for part in assembly.parts]
