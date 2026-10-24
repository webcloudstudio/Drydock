"""Binding detection: assembled expectations are not derived; a cited source literal is."""

import pytest

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


def test_a_declared_csv_header_or_row_is_a_contract_token():
    # Regression shape from LayersTesting 20261020.161323: twelve report criteria were reported
    # non-binding only because their source-declared CSV lines contain commas.
    code = (
        'assert rows[0] == "account,name,transactions,balance"\n'
        'assert rows[-1] == "TOTAL,,0,0.00"\n'
    )
    assert retyped_expectations(code) == ()


def test_plain_text_binds_and_backslashes_do_not():
    """2026-10-21: a deterministic known answer binds; only a backslash other than ``\\"``, a
    carriage return, or non-ASCII text still marks a re-typed value."""
    assert not retyped_expectations('assert out == "a, b"\n')
    assert not retyped_expectations('assert out == "a,b\\n"\n')
    assert not retyped_expectations('assert out == "say \\"hi\\""\n')
    assert not retyped_expectations('assert out == \'{"a": "say \\\\"hi\\\\""}\'\n')
    assert retyped_expectations('assert out == r"C:\\Users,x"\n')
    assert retyped_expectations('assert out == "a\\r\\n"\n')
    assert retyped_expectations('assert out == "caf\\u00e9"\n')


def test_an_assembled_string_supplied_as_input_is_the_round_trip():
    code = 'out = echo(f"hi {name}")\nassert out == f"hi {name}"\n'
    assert retyped_expectations(code) == ()


# --- T13b: cited literals --------------------------------------------------------------------

_CITED = """# FEATURE: Cited

## Programmatic Acceptance

=== AC banner ===
Intent: The banner matches the source.
Cite: sources/spec.txt:2

assert render() == r"C:\\Users\\Welcome"
=== END AC banner ===
"""


def _blueprint(tmp_path, spec: str, source: str = "Title\nC:\\Users\\Welcome\n"):
    blueprint = tmp_path / "targets" / "Demo" / "blueprint"
    (blueprint / "sources").mkdir(parents=True)
    (blueprint / "sources" / "spec.txt").write_text(source, encoding="utf-8")
    (blueprint / "FEATURE_Cited.md").write_text(spec, encoding="utf-8")
    return blueprint


def test_a_citation_resolves_one_line_or_a_range(tmp_path):
    blueprint = _blueprint(tmp_path, _CITED)
    assert resolve_citation("sources/spec.txt:2", blueprint) == "C:\\Users\\Welcome\n"
    assert resolve_citation("sources/spec.txt:1-2", blueprint) == "Title\nC:\\Users\\Welcome\n"
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


@pytest.mark.parametrize("code", ["assert code == 0", 'assert out == "group,size,path"'])
def test_resolving_citations_on_already_binding_expectations_are_valid(tmp_path, code):
    from dataclasses import replace

    blueprint = _blueprint(tmp_path, _CITED)
    (check,) = parse_programmatic_acceptance(blueprint / "FEATURE_Cited.md")
    check = replace(check, code=code)
    assert retyped_expectations(code) == ()
    assert citation_defect(check, blueprint) is None
    assert citation_defect(replace(check, cite="sources/spec.txt:999"), blueprint)


@pytest.mark.parametrize("code", ["code = 0\nassert code == 0", 'out = "ok"\nassert out == "ok"'])
def test_plan_verify_cli_accepts_cited_binding_expectations(
    tmp_path, monkeypatch, isolated_config, code
):
    from tests.test_cli import run_cli

    spec = (
        "# FEATURE: Cited\n\n## Programmatic Acceptance\n\n"
        "=== AC success ===\nIntent: Returns success.\nCite: sources/spec.txt:1\n\n"
        + code
        + "\n=== END AC success ===\n"
    )
    _blueprint(tmp_path, spec, source="Success returns 0 and writes ok.\n")
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    rc, out, err = run_cli("plan", "verify", "Demo")
    assert rc == 0, err
    assert "every one can run" in out
