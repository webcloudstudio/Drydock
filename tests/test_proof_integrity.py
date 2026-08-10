"""Tests for deterministic proof-integrity analysis."""

from __future__ import annotations

from drydock.proof_integrity import (
    analyze_invocation,
    analyze_literals,
    analyze_proof,
    analyze_structure,
    analyze_swallowed_output,
)


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


# --- Structural defects -----------------------------------------------------
#
# Each check runs as its own script in its own process. A snippet that reads a name a sibling
# check bound dies with NameError on every run, so it is unsatisfiable by construction — the
# same category as a mis-authored literal, and it must be caught before the build spends a pass.


def test_name_carried_over_from_a_sibling_check_is_flagged():
    defects = analyze_structure("assert result.returncode == 0")
    assert len(defects) == 1
    assert defects[0].kind == "undefined-name"
    assert defects[0].detail == "result"
    assert "its own process" in defects[0].message


def test_self_contained_snippet_is_clean():
    code = (
        "import subprocess\n"
        "result = subprocess.run(['true'], capture_output=True)\n"
        "print(result.stdout)\n"
        "assert result.returncode == 0\n"
    )
    assert analyze_structure(code) == ()


def test_builtins_are_not_reported_as_undefined():
    assert analyze_structure("assert len(open('f').read()) > 0") == ()


def test_imported_name_is_bound():
    assert analyze_structure("from app import create_app\nassert create_app()") == ()


def test_aliased_import_is_bound():
    assert analyze_structure("import subprocess as sp\nassert sp.run(['true'])") == ()


def test_comprehension_and_loop_targets_are_bound():
    code = "rows = [1, 2]\nassert [n for n in rows]\nfor row in rows:\n    assert row\n"
    assert analyze_structure(code) == ()


def test_with_and_except_targets_are_bound():
    code = (
        "try:\n"
        "    with open('f') as handle:\n"
        "        assert handle.read()\n"
        "except OSError as exc:\n"
        "    raise AssertionError(str(exc))\n"
    )
    assert analyze_structure(code) == ()


def test_function_arguments_are_bound():
    code = "def render(markdown):\n    return markdown\n\nassert render('a') == 'a'\n"
    assert analyze_structure(code) == ()


def test_star_import_suppresses_the_analysis():
    # A star import can supply anything, so the analysis cannot stay sound. Defer to runtime.
    assert analyze_structure("from app import *\nassert create_app()") == ()


def test_dynamic_binding_suppresses_the_analysis():
    assert analyze_structure("exec('x = 1')\nassert x == 1") == ()


def test_unparseable_snippet_is_flagged_as_a_syntax_error():
    defects = analyze_structure("assert result.returncode ==\n")
    assert len(defects) == 1
    assert defects[0].kind == "syntax-error"
    assert "not valid Python" in defects[0].message


def test_each_undefined_name_is_reported_once():
    defects = analyze_structure("assert result.a == 0\nassert result.b == 0")
    assert len(defects) == 1


# --- Swallowed diagnostics --------------------------------------------------
#
# Capturing a runner's output and asserting only on the exit code destroys the tally and the
# failing cases — the only evidence that explains the failure to an operator or a repair pass.


def test_captured_output_that_is_never_printed_is_flagged():
    code = (
        "import subprocess\n"
        "result = subprocess.run(['suite'], capture_output=True, text=True)\n"
        "assert result.returncode == 0\n"
    )
    defects = analyze_swallowed_output(code)
    assert len(defects) == 1
    assert defects[0].call == "subprocess.run"
    assert "never prints it" in defects[0].message


def test_captured_output_that_is_printed_is_clean():
    code = (
        "import subprocess\n"
        "result = subprocess.run(['suite'], capture_output=True, text=True)\n"
        "print(result.stdout)\n"
        "assert result.returncode == 0\n"
    )
    assert analyze_swallowed_output(code) == ()


def test_captured_output_that_is_asserted_on_is_clean():
    # The assertion names the captured stream, so the failure still reports what the command
    # produced. Only an exit-code-only check discards the evidence.
    code = (
        "import json\n"
        "import subprocess\n"
        "result = subprocess.run(['decoder'], capture_output=True, text=True)\n"
        "assert result.returncode == 0\n"
        "assert json.loads(result.stdout) == {'a': 1}\n"
    )
    assert analyze_swallowed_output(code) == ()


def test_uncaptured_subprocess_is_clean():
    # Without capture the runner's output already reaches the check's own streams.
    code = "import subprocess\nassert subprocess.run(['suite']).returncode == 0\n"
    assert analyze_swallowed_output(code) == ()


def test_in_process_check_is_not_flagged():
    code = (
        "from app import create_app\nassert create_app().test_client().get('/').status_code == 200"
    )
    assert analyze_swallowed_output(code) == ()


# --- Malformed subprocess invocation -----------------------------------------
#
# An invocation whose arguments cannot launch the command grades a different process than the
# one under test. No implementation can move it, so it must be caught before a build spends a
# repair budget on it.


def test_argument_list_with_shell_true_is_flagged():
    code = (
        "import subprocess\n"
        "result = subprocess.run(\n"
        "    ['PYTHONPATH=sources', 'python3', 'suite.py', '--number', '1'],\n"
        "    shell=True, capture_output=True, text=True,\n"
        ")\n"
        "print(result.stdout)\n"
        "assert '1 passed' in result.stdout\n"
    )
    defects = analyze_invocation(code)
    assert len(defects) == 1
    assert defects[0].kind == "shell-with-argv"
    assert defects[0].call == "subprocess.run"
    assert "PYTHONPATH=sources" in defects[0].message


def test_environment_assignment_as_executable_is_flagged():
    code = "import subprocess\nsubprocess.run(['PYTHONPATH=sources', 'python3', 'suite.py'])\n"
    defects = analyze_invocation(code)
    assert len(defects) == 1
    assert defects[0].kind == "env-assignment-argv"
    assert "env={**os.environ, ...}" in defects[0].message


def test_unsplit_command_string_without_shell_is_flagged():
    code = "import subprocess\nsubprocess.run('python3 suite.py --number 1', capture_output=True)\n"
    defects = analyze_invocation(code)
    assert len(defects) == 1
    assert defects[0].kind == "unsplit-command"


def test_correct_argument_list_is_clean():
    code = (
        "import os\n"
        "import subprocess\n"
        "result = subprocess.run(\n"
        "    ['python3', 'suite.py', '--number', '1'],\n"
        "    env={**os.environ, 'PYTHONPATH': 'sources'}, capture_output=True, text=True,\n"
        ")\n"
        "print(result.stdout)\n"
        "assert '1 passed' in result.stdout\n"
    )
    assert analyze_invocation(code) == ()


def test_shell_command_string_is_clean():
    # A single command string is exactly what shell=True expects.
    code = "import subprocess\nsubprocess.run('PYTHONPATH=sources python3 suite.py', shell=True)\n"
    assert analyze_invocation(code) == ()


def test_single_token_command_string_is_clean():
    code = "import subprocess\nsubprocess.run('suite', capture_output=True)\n"
    assert analyze_invocation(code) == ()


def test_dynamic_arguments_are_not_analyzed():
    # The argument shape is undecidable, so the analysis stays silent rather than guess.
    code = "import subprocess\ncmd = build_cmd()\nsubprocess.run(cmd, shell=use_shell)\n"
    assert analyze_invocation(code) == ()
