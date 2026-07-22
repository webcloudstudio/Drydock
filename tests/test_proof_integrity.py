"""Tests for deterministic proof-integrity analysis."""

from __future__ import annotations

from drydock.proof_integrity import analyze_literals, analyze_proof


def test_real_assertion_is_ok():
    result = analyze_proof('assert Path("marker.txt").read_text() == "built"')
    assert result.ok
    assert result.reasons == ()


def test_assert_true_is_flagged():
    result = analyze_proof("assert True")
    assert not result.ok
    assert "constant literal" in result.reasons[0]


def test_assert_constant_int_is_flagged():
    assert not analyze_proof("assert 1").ok


def test_assert_nonempty_tuple_is_flagged():
    result = analyze_proof("assert (1, 2)")
    assert not result.ok
    assert "collection literal" in result.reasons[0]


def test_tautological_self_comparison_is_flagged():
    result = analyze_proof("x = compute()\nassert x == x")
    assert not result.ok
    assert "self-comparison" in result.reasons[0]


def test_assert_false_is_not_flagged():
    # ``assert False`` always fails — a real gate, not a vacuous pass.
    assert analyze_proof("assert False").ok


def test_empty_body_is_flagged():
    result = analyze_proof('x = 1\nprint("done")')
    assert not result.ok
    assert "no assertion" in result.reasons[0]


def test_docstring_only_is_flagged():
    assert not analyze_proof('"""a proof"""').ok


def test_raise_is_ok():
    assert analyze_proof("if not ready():\n    raise SystemExit('missing')").ok


def test_nonzero_exit_is_ok():
    assert analyze_proof("import sys\nif bad():\n    sys.exit(1)").ok


def test_zero_exit_alone_is_flagged():
    assert not analyze_proof("import sys\nsys.exit(0)").ok


def test_checker_call_is_ok():
    assert analyze_proof("resp = get()\nresp.raise_for_status()").ok


def test_subprocess_check_true_is_ok():
    code = "import subprocess\nsubprocess.run(['true'], check=True)"
    assert analyze_proof(code).ok


def test_real_assert_alongside_vacuous_is_ok():
    # One genuine assertion redeems a sloppy ``assert True`` beside it.
    code = "assert True\nassert value() == 5"
    assert analyze_proof(code).ok


def test_unparseable_is_not_demoted():
    result = analyze_proof("this is not python !!!")
    assert result.ok


def test_vacuous_reasons_are_deduplicated():
    result = analyze_proof("assert True\nassert True")
    assert not result.ok
    assert len(result.reasons) == 1


# --- analyze_literals -------------------------------------------------------


def test_raw_literal_newline_is_reported():
    code = 'assert convert(r"\\*literal\\*\\n") == "<p>*literal*</p>\\n"'
    defects = analyze_literals(code)
    assert len(defects) == 1
    assert defects[0].sequence == "\\n"
    assert "cannot" in defects[0].message


def test_normal_literal_newline_is_clean():
    assert analyze_literals('assert convert("a\\n") == "<p>a</p>\\n"') == ()


def test_escaped_backslash_in_normal_literal_is_clean():
    # ``"\\\\n"`` is a deliberate literal backslash-n and is the sanctioned spelling.
    assert analyze_literals('assert render("\\\\n") == "\\\\n"') == ()


def test_raw_literal_without_control_escape_is_clean():
    assert analyze_literals('assert convert(r"\\*a\\*") == "<p>*a*</p>"') == ()


def test_regex_pattern_argument_is_exempt():
    code = 'import re\nassert re.search(r"a\\nb", text)'
    assert analyze_literals(code) == ()


def test_unparseable_code_reports_nothing():
    assert analyze_literals("this is not python !!!") == ()


def test_repeated_defect_is_reported_once():
    code = 'assert f(r"a\\n")\nassert g(r"a\\n")'
    assert len(analyze_literals(code)) == 1
