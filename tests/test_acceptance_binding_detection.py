"""Binding detection: assembled expectations are not derived; a cited source literal is."""

from drydock.acceptance import (
    citation_defect,
    parse_programmatic_acceptance,
    resolve_citation,
    retyped_expectations,
)
from drydock.plan_verify import verify

# --- T13a: assembled expectations ------------------------------------------------------------


def test_an_f_string_expectation_is_not_derived():
    assert retyped_expectations('assert out == f"total: {n}"\n')


def test_a_concatenated_expectation_is_not_derived():
    assert retyped_expectations('assert out == "total: " + str(n)\n')


def test_percent_and_format_expectations_are_not_derived():
    assert retyped_expectations('assert out == "total: %d" % n\n')
    assert retyped_expectations('assert out == "total: {}".format(n)\n')


def test_numeric_arithmetic_is_not_an_assembled_string():
    assert retyped_expectations("assert total == a + b\n") == ()


def test_an_assembled_string_supplied_as_input_is_the_round_trip():
    code = 'out = echo(f"hi {name}")\nassert out == f"hi {name}"\n'
    assert retyped_expectations(code) == ()


# --- T13b: cited literals --------------------------------------------------------------------

_CITED = """# FEATURE: Cited

## Programmatic Acceptance

=== AC banner ===
Intent: The banner matches the source.
Cite: sources/spec.txt:2

assert render() == "<b>Welcome</b>"
=== END AC banner ===
"""


def _blueprint(tmp_path, spec: str, source: str = "Title\n<b>Welcome</b>\n"):
    blueprint = tmp_path / "targets" / "Demo" / "blueprint"
    (blueprint / "sources").mkdir(parents=True)
    (blueprint / "sources" / "spec.txt").write_text(source, encoding="utf-8")
    (blueprint / "FEATURE_Cited.md").write_text(spec, encoding="utf-8")
    return blueprint


def test_a_citation_resolves_one_line_or_a_range(tmp_path):
    blueprint = _blueprint(tmp_path, _CITED)
    assert resolve_citation("sources/spec.txt:2", blueprint) == "<b>Welcome</b>"
    assert resolve_citation("sources/spec.txt:1-2", blueprint) == "Title\n<b>Welcome</b>"
    assert resolve_citation("sources/spec.txt:9", blueprint) is None
    assert resolve_citation("sources/../FEATURE_Cited.md:1", blueprint) is None
    assert resolve_citation("FEATURE_Cited.md:1", blueprint) is None


def test_a_cited_literal_is_derived(tmp_path):
    blueprint = _blueprint(tmp_path, _CITED)
    (check,) = parse_programmatic_acceptance(blueprint / "FEATURE_Cited.md")
    assert check.cite == "sources/spec.txt:2"
    assert check.binding
    assert citation_defect(check, blueprint) is None


def test_an_uncited_literal_is_still_retyped(tmp_path):
    blueprint = _blueprint(tmp_path, _CITED.replace("Cite: sources/spec.txt:2\n", ""))
    (check,) = parse_programmatic_acceptance(blueprint / "FEATURE_Cited.md")
    assert not check.binding


def test_a_citation_that_does_not_match_is_a_plan_defect(tmp_path):
    _blueprint(tmp_path, _CITED, source="Title\n<i>Hello</i>\n")
    result = verify("Demo", tmp_path / "targets" / "Demo")
    (defect,) = result.defects
    assert defect.kind == "bad-citation"
    assert "none of this criterion's expected literals" in defect.detail


def test_a_citation_that_does_not_resolve_is_a_plan_defect(tmp_path):
    _blueprint(tmp_path, _CITED.replace("spec.txt:2", "missing.txt:2"))
    result = verify("Demo", tmp_path / "targets" / "Demo")
    (defect,) = result.defects
    assert defect.kind == "bad-citation"
