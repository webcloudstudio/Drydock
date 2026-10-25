"""Decimal oracle provenance, using synthetic criteria and no published UAT data."""

from dataclasses import replace

from drydock.acceptance import ProgrammaticAcceptance
from drydock.acceptance_oracle import decimal_expectation_defects
from drydock.plan_verify import verify


def _check(code):
    return ProgrammaticAcceptance("conversion", "FEATURE-Convert.md", "Convert", code)


def test_guessed_decimal_answers_are_refused_but_derived_or_cited_answers_are_allowed():
    check = _check(
        'amount = "2.00"\nassert body["amount"] == "2.00"\nassert body["result"] == "10.00"'
    )
    reasons = decimal_expectation_defects(check)
    assert len(reasons) == 1
    assert "10.00" in reasons[0]
    assert not decimal_expectation_defects(replace(check, cited_text="Expected: 10.00"))
    assert not decimal_expectation_defects(
        _check('assert body["result"] == f"{expected:.2f}"\nassert response.status_code == 200')
    )
    assert not decimal_expectation_defects(_check('assert body["version"] == "1.2.3"'))


def test_verify_rejects_guessed_decimal_and_accepts_source_derived_oracle(tmp_path):
    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    path = blueprint / "FEATURE-Convert.md"
    prefix = "# FEATURE: Convert\n\n## Programmatic Acceptance\n\n=== AC conversion ===\n"
    code = """from decimal import Decimal, ROUND_HALF_EVEN
from app import convert
amount, source_rate, target_rate = "2.00", "2", "5"
body = convert(amount, source_rate, target_rate)
"""
    suffix = "\n=== END AC conversion ===\n\n## User Acceptance\n\n- None.\n"
    path.write_text(prefix + code + 'assert body["result"] == "10.00"' + suffix)
    result = verify("Demo", tmp_path)
    assert any(defect.kind == "decimal-oracle" for defect in result.defects)
    oracle = """expected = (Decimal(amount) * Decimal(target_rate) / Decimal(source_rate)).quantize(
    Decimal("0.01"), rounding=ROUND_HALF_EVEN)
assert body["result"] == f"{expected:.2f}"
"""
    path.write_text(prefix + code + oracle + suffix)
    assert not any(defect.kind == "decimal-oracle" for defect in verify("Demo", tmp_path).defects)


def test_verify_resolves_citation_for_known_decimal_answer(tmp_path):
    blueprint = tmp_path / "blueprint"
    (blueprint / "sources").mkdir(parents=True)
    (blueprint / "sources" / "brief.md").write_text("The known answer is 5.00.\n")
    (blueprint / "FEATURE-Convert.md").write_text(
        "# FEATURE: Convert\n\n## Programmatic Acceptance\n\n=== AC conversion ===\n"
        'Cite: sources/brief.md:1\n\nfrom app import result\nassert result == "5.00"\n'
        "=== END AC conversion ===\n"
    )
    assert not any(defect.kind == "decimal-oracle" for defect in verify("Demo", tmp_path).defects)


def test_plan_repair_does_not_guess_oracles_or_spend_a_model_call(tmp_path):
    from drydock.plan_repair import repair

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    path = blueprint / "FEATURE-Convert.md"
    original = (
        "# FEATURE: Convert\n\n## Programmatic Acceptance\n\n=== AC conversion ===\n"
        'from app import result\nassert result == "10.00"\n=== END AC conversion ===\n'
    )
    path.write_text(original)

    def runner(*args, **kwargs):
        raise AssertionError("Mechanical repair must not invent a numeric oracle")

    result = repair("Demo", tmp_path, runner=runner)
    assert not result.ok
    assert not result.files_changed
    assert path.read_text() == original


def test_generated_plan_routes_decimal_expectation_to_artifact_repair(tmp_path):
    import pytest

    from drydock.planning_session import CriteriaDefect, _validate_plan_output
    from tests.test_planning_session import _SPEC_HEADER, FakeRun, _llm_output, _manifest

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
        '=== AC conversion ===\nfrom app import result\nassert result == "10.00"\n'
        "=== END AC conversion ===\n",
        "MANIFEST.md": manifest,
    }
    with pytest.raises(CriteriaDefect) as raised:
        _validate_plan_output(blocks, blueprint, FakeRun(text=_llm_output(manifest)))
    assert any(kind == "decimal-oracle" for kind, defect in raised.value.defects)
