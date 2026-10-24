"""Output cleanup preserves bodies and refuses ambiguous wrappers."""

import pytest

from drydock.output_format import clean_output, parse_json_output

ARTIFACT = "=== BEGIN ARTIFACT A.md ===\n# A\nKeep this narration.\n=== END ARTIFACT ===\n"


def test_artifact_cleanup_preserves_body_and_reports_all_wrappers():
    result = clean_output("Here it is.\n" + ARTIFACT + "Done.\n", "artifacts")
    assert result.text == ARTIFACT
    assert result.removed == ("Here it is.\n", "Done.\n")
    assert result.defect is None
    assert clean_output(result.text, "artifacts").text == result.text


@pytest.mark.parametrize(
    "text",
    [
        "# Missing artifact\n" + ARTIFACT,
        "=== END ARTIFACT ===\n" + ARTIFACT,
        ARTIFACT + ARTIFACT,
        ARTIFACT.replace("=== END ARTIFACT ===", ""),
        ARTIFACT.replace("=== END ARTIFACT ===", "=== END B.md ==="),
        "one\ntwo\nthree\nfour\n" + ARTIFACT,
    ],
)
def test_ambiguous_artifacts_are_preserved_for_existing_repair(text):
    result = clean_output(text, "artifacts")
    assert result.text == text
    assert result.defect
    assert not result.removed


def test_nested_acceptance_blocks_are_not_envelope_boundaries():
    text = ARTIFACT.replace("# A", "# A\n=== AC one ===\nassert True\n=== END AC one ===")
    assert clean_output("Here it is.\n" + text, "artifacts").text == text


@pytest.mark.parametrize(
    "text",
    [
        '{"message": "Keep this string."}',
        'Here it is.\n{"message": "Keep this string."}\nDone.',
        'Here it is.\n```json\n{"message": "Keep this string."}\n```\nDone.',
    ],
)
def test_json_cleanup_preserves_strings(text):
    assert parse_json_output(text) == {"message": "Keep this string."}


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1, "a": 2}',
        '{"a": {"b": 1, "b": 2}}',
        '{"a": NaN}',
        '{"a": 1}\n{"b": 2}',
        '# Heading\n{"a": 1}',
        '```json\n{"a": 1}',
        '{"a":',
        '{"a": 1}\n- Lost content',
        'one\ntwo\nthree\nfour\n{"a": 1}',
    ],
)
def test_invalid_json_or_ambiguous_wrapper_is_rejected(text):
    assert clean_output(text, "json").text == text
    with pytest.raises(ValueError):
        parse_json_output(text)


@pytest.mark.parametrize("suffix", ['"extra"', "42", "true", "null", "[1]"])
def test_second_json_value_is_not_narration(suffix):
    with pytest.raises(ValueError):
        parse_json_output('{"a": 1}\n' + suffix)


def test_json_arrays_and_fences_are_idempotent():
    result = clean_output('```json\n[1, {"a": 2}]\n```', "json")
    assert result.removed == ("JSON code fence",)
    assert parse_json_output(result.text) == [1, {"a": 2}]
    assert clean_output(result.text, "json").text == result.text


def test_malformed_second_json_string_is_not_narration():
    with pytest.raises(ValueError):
        parse_json_output('{"a": 1}\n"unterminated')


@pytest.mark.parametrize("ending", ["", "\n", "\r\n\r\n", "  \n\n"])
def test_final_invariant_close_is_repaired_without_changing_body(ending):
    body = "=== BEGIN ARTIFACT A.md ===\n# A\n=== AC one ===\nassert True\n=== END AC one ===\n"
    original = body + "=== END ARTIFACT" + ending
    result = clean_output(original, "artifacts")
    assert result.text == body + "=== END ARTIFACT ===" + ending
    assert result.defect is None
    assert result.repaired == (
        "A.md: completed final `=== END ARTIFACT` as `=== END ARTIFACT ===`",
    )
    assert not clean_output(result.text, "artifacts").repaired


def test_final_close_repair_preserves_preceding_completed_artifacts():
    final = "=== BEGIN ARTIFACT B.md ===\n# B\n=== END ARTIFACT"
    result = clean_output("Here it is.\n" + ARTIFACT + final, "artifacts")
    assert result.text == ARTIFACT + final + " ==="
    assert result.removed == ("Here it is.\n",)
    assert result.repaired[0].startswith("B.md:")


@pytest.mark.parametrize(
    "text",
    [
        "=== END ARTIFACT",
        ARTIFACT + "=== END ARTIFACT",
        ARTIFACT + ARTIFACT.replace("=== END ARTIFACT ===", "=== END ARTIFACT"),
        "=== BEGIN ARTIFACT B.md ===\n"
        + ARTIFACT.replace("=== END ARTIFACT ===", "=== END ARTIFACT"),
        ARTIFACT.replace("=== END ARTIFACT ===", "=== END ARTIFACT\nMore content."),
        ARTIFACT.replace(
            "=== END ARTIFACT ===", "=== END ARTIFACT\nMore content.\n=== END ARTIFACT"
        ),
        ARTIFACT.replace("=== END ARTIFACT ===", "=== END ARTIFACT =="),
        ARTIFACT.replace("=== END ARTIFACT ===", "=== END ARTIFACT A.md"),
        ARTIFACT.replace("=== END ARTIFACT ===", "# unfinished body"),
        "# lost content\n" + ARTIFACT.replace("=== END ARTIFACT ===", "=== END ARTIFACT"),
        "=== END B.md ===\n" + ARTIFACT.replace("=== END ARTIFACT ===", "=== END ARTIFACT"),
    ],
)
def test_final_close_repair_refuses_ambiguous_or_truncated_output(text):
    result = clean_output(text, "artifacts")
    assert result.text == text
    assert result.defect
    assert not result.repaired
    assert not result.removed
