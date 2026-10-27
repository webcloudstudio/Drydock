"""AC intent metadata: verbatim declarations, authoring enforcement and repair-prompt transport."""

import pytest

from drydock.acceptance import AcceptanceRunResult, parse_programmatic_acceptance_text
from drydock.build_run import _REPAIR_FEEDBACK_CAP, _render_repair_feedback

# Quotes, an apostrophe, a leading-decimal literal, repeated declarations and odd spacing.
INTENT_LINES = (
    'Intent: Preserve supplied text exactly; ".005" is a Plan-selected example.',
    "Intent:   The store's round trip must not reformat 'text'  -  spacing kept.",
)
BLOCK = (
    "=== AC text-round-trip ===\n"
    + "\n".join(INTENT_LINES)
    + '\n\nfrom text_store import round_trip\nassert round_trip(".005") == ".005"\n'
    "=== END AC text-round-trip ===\n"
)
SPEC = (
    "# FEATURE: Text\n\n## Programmatic Acceptance\n\n"
    + BLOCK
    + "\n## User Acceptance\n\n- None.\n"
)
NO_INTENT = SPEC.replace("\n".join(INTENT_LINES) + "\n", "")


def _check(text=SPEC):
    (check,) = parse_programmatic_acceptance_text(text, source="FEATURE-Text.md")
    return check


def test_intent_lines_are_kept_verbatim_and_in_order():
    check = _check()
    assert check.intent_lines == INTENT_LINES
    assert check.declares_intent
    # The normalized form still joins declarations for summaries.
    assert check.intent.startswith("Preserve supplied text exactly")


@pytest.mark.parametrize("meta", ["", "Intent:\n", "Intent:   \n"])
def test_missing_or_blank_intent_is_not_declared_despite_id_fallback(meta):
    check = _check(SPEC.replace("\n".join(INTENT_LINES) + "\n", meta))
    assert check.intent == "text-round-trip"
    assert not check.declares_intent


def _failed(check, stderr="AssertionError"):
    return AcceptanceRunResult(
        check_id=check.check_id,
        source=check.source,
        intent=check.intent,
        intent_lines=check.intent_lines,
        passed=False,
        return_code=1,
        stdout="",
        stderr=stderr,
    )


class _Unit:
    name = "Text"
    block_id = "text"


def test_build_repair_feedback_quotes_intent_verbatim_and_forbids_rewriting_expectations():
    text = _render_repair_feedback(_Unit(), (_failed(_check()),), None, (), {})
    for line in INTENT_LINES:
        assert f"  {line}\n" in text
    assert "does not\nauthorize changing an expected result" in text
    assert "AC_BROKEN" in text


def test_build_repair_feedback_keeps_intent_when_diagnostics_are_truncated():
    huge = "x" * (_REPAIR_FEEDBACK_CAP * 2)
    text = _render_repair_feedback(_Unit(), (_failed(_check(), stderr=huge),), None, (), {})
    assert "(feedback truncated)" in text
    for line in INTENT_LINES:
        assert line in text


def test_build_repair_feedback_never_substitutes_the_id_for_missing_intent():
    text = _render_repair_feedback(_Unit(), (_failed(_check(NO_INTENT)),), None, (), {})
    assert "### Criterion intent" not in text


def test_plan_repair_block_carries_intent_lines_verbatim():
    from drydock.plan_repair import _block_bodies, _defect_part
    from drydock.plan_verify import Defect

    body = _block_bodies(SPEC)["text-round-trip"]
    rendered = _defect_part(
        Defect("FEATURE-Text.md", "text-round-trip", "undefined-name", "detail"), body
    ).text
    for line in INTENT_LINES:
        assert line in rendered


def test_ac_repair_prompt_carries_intent_lines_verbatim(tmp_path):
    from drydock.ac_repair import RepairCandidate, assemble

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "FEATURE-Text.md").write_text(SPEC, encoding="utf-8")
    candidate = RepairCandidate(_check(), "mechanical", "fault")
    rendered = assemble("Repair it.", (candidate,), blueprint).rendered_text
    for line in INTENT_LINES:
        assert line in rendered


def _validate(spec_text, tmp_path):
    from drydock.planning_session import _validate_plan_output
    from tests.test_planning_session import _SPEC_HEADER, FakeRun, _llm_output, _manifest

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": spec_text,
        "MANIFEST.md": manifest,
    }
    return _validate_plan_output(blocks, blueprint, FakeRun(text=_llm_output(manifest)))


DIVISION = (
    "# FEATURE: Status\n\n## Programmatic Acceptance\n\n=== AC divide-quotient ===\n"
    "{meta}from app import divide\nassert divide(6, 3) == 2\n=== END AC divide-quotient ===\n"
)


@pytest.mark.parametrize("meta", ["", "Intent:\n"])
def test_authoring_routes_missing_intent_to_bounded_correction(meta, tmp_path):
    from drydock.planning_session import CriteriaDefect

    with pytest.raises(CriteriaDefect) as raised:
        _validate(DIVISION.format(meta=meta), tmp_path)
    kinds = [(kind, defect.check_id) for kind, defect in raised.value.defects]
    assert ("missing-intent", "divide-quotient") in kinds


def test_authoring_admits_declared_intent_with_plan_selected_fixtures(tmp_path):
    meta = "Intent: Return the quotient for a nonzero denominator; 6 / 3 must equal 2.\n"
    _validate(DIVISION.format(meta=meta), tmp_path)


def test_existing_criterion_without_intent_still_verifies(tmp_path):
    from drydock.plan_verify import verify

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "FEATURE-Status.md").write_text(
        DIVISION.format(meta="") + "\n## User Acceptance\n\n- None.\n"
    )
    result = verify("Demo", tmp_path)
    assert result.ok
    assert not any(defect.kind == "missing-intent" for defect in result.defects)
