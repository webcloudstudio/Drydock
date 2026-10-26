"""Plan-selected fixtures and decimal oracles, using synthetic criteria and no published UAT data."""

from drydock.plan_verify import verify

_PREFIX = "# FEATURE: Convert\n\n## Programmatic Acceptance\n\n=== AC {id} ===\n"
_SUFFIX = "\n=== END AC {id} ===\n\n## User Acceptance\n\n- None.\n"


def _verify_one(tmp_path, check_id, body):
    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "FEATURE-Convert.md").write_text(
        _PREFIX.format(id=check_id) + body + _SUFFIX.format(id=check_id)
    )
    return verify("Demo", tmp_path)


def test_plan_selected_decimal_text_fixtures_need_no_source_provenance(tmp_path):
    # LayersTesting csv-format-cents-values: none of these literals appear in source material.
    body = """Intent: Format integer cents as decimal text with exactly two fractional digits.
from csv_output import format_cents
cases = [(0, "0.00"), (5, "0.05"), (-5, "-0.05"), (-1250, "-12.50"), (1250, "12.50"),
         (500000, "5000.00"), (123456789, "1234567.89")]
for cents, expected in cases:
    assert format_cents(cents) == expected
"""
    result = _verify_one(tmp_path, "csv-format-cents-values", body)
    assert result.ok
    assert not any("provenance" in warning for warning in result.warnings)
    text = (tmp_path / "blueprint" / "FEATURE-Convert.md").read_text()
    assert '(123456789, "1234567.89")' in text


def test_plan_selected_division_example_needs_no_source_provenance(tmp_path):
    body = """Intent: Return the quotient for a nonzero denominator; 6 / 3 must equal 2.
from calculator import divide
assert divide(6, 3) == 2
"""
    result = _verify_one(tmp_path, "divide-quotient", body)
    assert result.ok
    assert not result.warnings


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
    assert result.nothing_to_repair
    assert not result.files_changed
    assert path.read_text() == original


def test_generated_plan_does_not_reauthor_an_unknown_decimal_expectation(tmp_path):
    from drydock.planning_session import _validate_plan_output
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
    original = blocks["FEATURE-Status.md"]
    _validate_plan_output(blocks, blueprint, FakeRun(text=_llm_output(manifest)))
    assert blocks["FEATURE-Status.md"] == original


def test_reemitted_artifact_with_missing_decimal_imports_is_rejected_before_write(tmp_path):
    import pytest

    from drydock.planning_session import CriteriaDefect, _validate_plan_output
    from tests.test_planning_session import _SPEC_HEADER, FakeRun, _llm_output, _manifest

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": "# FEATURE: Status\n\n## Programmatic Acceptance\n\n"
        "=== AC arithmetic ===\nfrom app import value\n"
        'expected = Decimal("1").quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)\n'
        "assert value == expected\n=== END AC arithmetic ===\n",
        "MANIFEST.md": manifest,
    }
    with pytest.raises(CriteriaDefect) as raised:
        _validate_plan_output(blocks, blueprint, FakeRun(text=_llm_output(manifest)))
    undefined = [defect.reason for kind, defect in raised.value.defects if kind == "undefined-name"]
    assert len(undefined) == 1
    assert "Decimal" in undefined[0] and "ROUND_HALF_EVEN" in undefined[0]
    assert not list(blueprint.iterdir())


def test_artifact_repair_instructions_require_self_contained_imports_and_complete_closes():
    from drydock.planning_session import _artifact_repair_assembly

    prompt = _artifact_repair_assembly(
        names=("FEATURE-Status.md",),
        blocks={"FEATURE-Status.md": "# FEATURE: Status"},
        defect="missing import",
        pass_number=1,
    ).rendered_text
    assert "isolated script" in prompt
    assert "Decimal and rounding constants" in prompt
    assert "count opening and closing artifact lines" in prompt
    assert "including all trailing equals signs" in prompt
