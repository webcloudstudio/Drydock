"""Planning contracts exercised through temporary Targets; no provider or benchmark access."""

from dataclasses import replace

import pytest

from drydock.acceptance import selection_probe_reason
from drydock.plan_graph import compute_plan, interface_dependency_defects
from drydock.plan_repair import repair
from drydock.plan_verify import Defect, VerifyResult, recovery_commands, render, verify
from drydock.planning_session import CriteriaDefect, _validate_plan_output, create_plan
from tests.test_acceptance import _json_probe
from tests.test_plan_graph import story
from tests.test_planning_session import (
    FakeRun,
    _arch_block,
    _declaration_block,
    _llm_output,
    _make_target,
    _parse_blocks,
    _sequence_runner,
)


def probe_feature(check):
    return (
        "# FEATURE: Scoped transformation\n\n"
        "| Field | Value |\n|---|---|\n"
        "| Version | 20261026 V1 |\n| Description | Transform selected records. |\n\n"
        "## Programmatic Acceptance\n\n"
        "=== AC scoped ===\nIntent: Transform the selected corpus.\nSuite: scoped\n"
        f"Probe: {check.probe}\nProbe Count: {check.probe_count}\n\n"
        f"{check.code}\n=== END AC scoped ===\n\n"
        "## User Acceptance\n\n- None.\n\n## Guardrails\n\n- Preserve the corpus.\n"
    )


@pytest.mark.parametrize(
    "expression, expected",
    [
        ('f"{os.getcwd()}/missing-product"', "unresolved-probe-arguments"),
        ("f\"{__import__('os').getcwd()}/missing-product\"", "unresolved-probe-arguments"),
        ('os.path.abspath("missing-product")', None),
        ("'./missing-product'", None),
    ],
)
def test_authoring_and_verification_share_probe_contract(tmp_path, expression, expected):
    target = _make_target(tmp_path)
    blueprint = target / "blueprint"
    check = _json_probe(blueprint / "sources")
    check = replace(
        check,
        code="import os\n"
        + check.code
        .replace("'./missing-product'", expression)
        .replace('"runner.py"', '"sources/runner.py"')
        .replace("'corpus.json'", "'sources/corpus.json'"),
    )
    blocks = _parse_blocks(_llm_output())
    blocks["FEATURE-Status.md"] = probe_feature(check)
    result = selection_probe_reason(check, blueprint_dir=blueprint)
    assert (result[0] if result else None) == expected
    if expected:
        with pytest.raises(CriteriaDefect) as raised:
            _validate_plan_output(dict(blocks), blueprint, FakeRun(text=""))
        assert (expected, "FEATURE-Status.md", "scoped") in [
            (kind, d.source, d.check_id) for kind, d in raised.value.defects
        ]
    else:
        _validate_plan_output(dict(blocks), blueprint, FakeRun(text=""))
    for name, text in blocks.items():
        (target / name if name == "MANIFEST.md" else blueprint / name).write_text(text)
    verdict = verify("Example", target)
    assert [d.kind for d in verdict.defects] == ([expected] if expected else [])


@pytest.mark.parametrize("failure", ["missing", "protocol", "empty"])
def test_authoring_checks_probe_declarations_and_selection(tmp_path, failure):
    target = _make_target(tmp_path)
    blueprint = target / "blueprint"
    check = _json_probe(blueprint / "sources", pattern="missing" if failure == "empty" else "Lists")
    check = replace(
        check,
        code=check.code.replace('"runner.py"', '"sources/runner.py"').replace(
            "'corpus.json'", "'sources/corpus.json'"
        ),
    )
    check = replace(
        check,
        probe="" if failure == "missing" else check.probe,
        probe_count="lines" if failure == "protocol" else check.probe_count,
    )
    expected = {
        "missing": "missing-selection-probe",
        "protocol": "probe-failed",
        "empty": "empty-selection",
    }[failure]
    blocks = _parse_blocks(_llm_output())
    blocks["FEATURE-Status.md"] = probe_feature(check)
    with pytest.raises(CriteriaDefect) as raised:
        _validate_plan_output(blocks, blueprint, FakeRun(text=""))
    assert expected in [kind for kind, _ in raised.value.defects]


@pytest.mark.parametrize("corrected", [True, False])
def test_complete_plan_reauthors_probe_before_persisting_and_can_repeat(tmp_path, corrected):
    target = _make_target(tmp_path)
    blueprint = target / "blueprint"
    check = _json_probe(blueprint / "sources")
    check = replace(
        check,
        code=check.code.replace('"runner.py"', '"sources/runner.py"').replace(
            "'corpus.json'", "'sources/corpus.json'"
        ),
    )
    good = probe_feature(check)
    bad = good.replace("'./missing-product'", "f\"{__import__('os').getcwd()}/missing-product\"")
    (blueprint / "sources/unrelated.txt").write_text("UNRELATED CONTEXT MUST STAY OUT")

    def artifact(body):
        return f"=== BEGIN ARTIFACT FEATURE-Status.md ===\n{body}\n=== END ARTIFACT ===\n"

    runner = _sequence_runner(
        _declaration_block(), _arch_block() + artifact(bad), artifact(good if corrected else bad)
    )
    result = create_plan(
        "Example",
        "Example",
        tmp_path,
        runner=runner,
        allow_diagnostic_recovery=True,
        continue_attempts=1,
    )
    assert len(runner.calls) == 3
    assert (
        "unresolved-probe-arguments" in runner.calls[-1]
        or "cannot be statically resolved" in runner.calls[-1]
    )
    assert "parser.add_argument('--dump-tests'" in runner.calls[-1]
    assert "UNRELATED CONTEXT MUST STAY OUT" not in runner.calls[-1]
    if not corrected:
        assert "getcwd" in (blueprint / "FEATURE-Status.md").read_text()
        assert result.unbuildable
        errors = (target / "ERRORS.md").read_text()
        assert "Run: drydock plan Example" in errors
        assert "Run: drydock plan repair Example" not in errors
        return
    assert "getcwd" not in (blueprint / "FEATURE-Status.md").read_text()
    assert not result.unbuildable
    assert verify("Example", target).ok
    # Replanning already valid inputs must not add a model repair or invalidate the plan.
    again = _sequence_runner(_declaration_block(), _arch_block() + artifact(good))
    second = create_plan("Example", "Example", tmp_path, runner=again, overwrite=True)
    assert not second.unbuildable
    assert len(again.calls) == 2
    assert verify("Example", target).ok


def test_interface_dependencies_are_transitive_and_do_not_serialize_independent_work():
    declared = [
        story("cli", provides=("executable",)),
        story("parse", depends=("cli",), provides=("records",), consumes=("executable",)),
        story("validate", depends=("parse",)),
        story("render", depends=("validate",), consumes=("records", "external input")),
        story("independent", depends=("cli",), consumes=("executable",)),
    ]
    assert not interface_dependency_defects(declared)
    computed = compute_plan(
        declared, min_savings=1, block_size_fn=lambda members: 100 + len(members)
    )
    assert not computed.fatal
    by_id = {s.story_id: s for s in computed.stories}
    assert by_id["parse"].block == by_id["independent"].block
    assert by_id["parse"].block < by_id["validate"].block < by_id["render"].block
    broken = [replace(s, depends=("cli",)) if s.story_id == "render" else s for s in declared]
    assert [d.code for d in interface_dependency_defects(broken)] == ["interface-dependency"]
    assert compute_plan(broken).fatal


def test_interface_provider_alternatives_self_use_and_cycles():
    declared = [
        story("a", provides=("data",), consumes=("data",)),
        story("b", provides=("data",)),
        story("c", depends=("b",), consumes=("data",)),
    ]
    assert not interface_dependency_defects(declared)
    cyclic = [replace(declared[0], depends=("c",)), replace(declared[2], depends=("a",))]
    assert "cycle" in [d.code for d in compute_plan(cyclic).fatal]


@pytest.mark.parametrize(
    "kind",
    [
        "unresolved-probe-arguments",
        "acceptance-order",
        "persistence-order",
        "interface-dependency",
        "ordered-oracle",
        "process-readiness",
        "criteria-missing",
        "operation-untested",
        "database-contract",
    ],
)
def test_authoring_faults_recommend_replanning_without_mechanical_repair(tmp_path, kind):
    result = VerifyResult(
        "Example", tmp_path, defects=(Defect("FEATURE-X.md", "x", kind, "cause"),)
    )
    assert recovery_commands(result) == ("drydock plan Example",)
    assert "Run: drydock plan repair" not in render(result)


def test_mixed_faults_retain_both_recovery_paths(tmp_path):
    result = VerifyResult(
        "Example",
        tmp_path,
        defects=(
            Defect("FEATURE-X.md", "x", "syntax", "missing colon"),
            Defect("FEATURE-Y.md", "y", "unresolved-probe-arguments", "dynamic argument"),
        ),
    )
    assert recovery_commands(result) == ("drydock plan repair Example", "drydock plan Example")


def test_existing_manifest_interface_fault_routes_to_authoring_without_model_call(tmp_path):
    target = tmp_path / "Example"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    for filename in ("FEATURE-Input.md", "FEATURE-Output.md"):
        (blueprint / filename).write_text(
            "# FEATURE: Example\n\n## Programmatic Acceptance\n\n"
            "=== AC interface ===\nIntent: Public interface works.\n"
            "import json\nassert json.loads('[1]') == [1]\n=== END AC interface ===\n"
        )
    manifest = (
        "# MANIFEST: Example\nstate: draft\n\n"
        "## story 1: Read input\nid: read\ntype: service\nphase: 1\nblock: 1\n"
        "implements: FEATURE-Input.md\nprovides: parsed records\nacceptance: yes\nstate: pending\n\n"
        "## story 2: Write output\nid: write\ntype: service\nphase: 1\nblock: 1\n"
        "implements: FEATURE-Output.md\nconsumes: parsed records\nacceptance: yes\nstate: pending\n"
    )
    (target / "MANIFEST.md").write_text(manifest)
    result = verify("Example", target)
    assert [d.kind for d in result.defects] == ["interface-dependency"]

    def forbidden(*args, **kwargs):
        pytest.fail("an interface dependency needs source-aware topology authoring")

    fixed = repair("Example", target, runner=forbidden)
    assert not fixed.ok
    assert not fixed.files_changed
    assert (target / "MANIFEST.md").read_text() == manifest
    (target / "MANIFEST.md").write_text(
        manifest.replace("consumes: parsed records", "depends: read\nconsumes: parsed records")
    )
    assert verify("Example", target).ok
