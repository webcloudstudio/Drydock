"""Tests for deterministic proof-integrity analysis."""

from __future__ import annotations

from drydock.proof_integrity import (
    analyze_invocation,
    analyze_literals,
    analyze_output_assertions,
    analyze_proof,
    analyze_shell_escapes,
    analyze_staged_invocation,
    analyze_structure,
    analyze_swallowed_output,
    staged_script_requirements,
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


# --- Assertions on captured output text -------------------------------------------------

# The defect that failed a working TOML decoder four times: ``toml-test`` prints
# "invalid tests: 96 passed,  0 failed" on a clean run, so the forbidden word is always there.
_TALLY_ASSERTION = """
import subprocess

result = subprocess.run(["sh", "run_conformance.sh"], capture_output=True, text=True)
print(result.stdout)
assert result.returncode == 0
assert "failed" not in result.stdout.lower()
"""


def test_forbidding_a_tally_word_is_fatal():
    defects = analyze_output_assertions(_TALLY_ASSERTION)
    assert len(defects) == 1
    assert defects[0].fatal
    assert defects[0].kind == "tally-vocabulary"
    assert defects[0].literal == "failed"
    assert "tally" in defects[0].message


def test_forbidding_skipped_is_fatal():
    # A scoped conformance run reports "skipped tests: 774" on success.
    (defect,) = analyze_output_assertions(
        'assert result.returncode == 0\nassert "skipped" not in result.stdout.lower()'
    )
    assert defect.fatal
    assert defect.literal == "skipped"


def test_redundant_substring_beside_exit_gate_is_advisory():
    (defect,) = analyze_output_assertions(
        'assert result.returncode == 0\nassert "Traceback" not in result.stdout'
    )
    assert not defect.fatal
    assert defect.kind == "redundant-substring"


def test_substring_tracked_through_a_binding():
    (defect,) = analyze_output_assertions(
        'out = result.stdout\nassert result.returncode == 0\nassert "Traceback" not in out'
    )
    assert defect.literal == "Traceback"


def test_substring_without_an_exit_gate_is_left_alone():
    # The substring check is the only verdict the proof has; removing it leaves nothing.
    assert analyze_output_assertions('assert "Traceback" not in result.stdout') == ()


def test_assertion_on_non_stream_text_is_ignored():
    assert (
        analyze_output_assertions('text = Path("out.json").read_text()\nassert "error" not in text')
        == ()
    )


def test_positive_membership_assertion_is_ignored():
    # Requiring an ordinary word to be present is a satisfiable expectation about the program's
    # own output, not a model of the runner's summary formatting.
    assert (
        analyze_output_assertions(
            'assert result.returncode == 0\nassert "All tests passed" in result.stdout'
        )
        == ()
    )


# The Toml conformance case. toml-test prints "valid tests: 205 passed,  0 failed" — the count
# is a property of the installed suite and the columns are aligned, so a literal carrying both
# is false on correct code for two independent reasons.
_HARDCODED_TALLY_ASSERTION = """
import subprocess

result = subprocess.run(["sh", "full_test.sh"], capture_output=True, text=True)
print(result.stdout)
assert result.returncode == 0
assert "valid tests: 210 passed, 0 failed" in result.stdout
"""


def test_requiring_a_hardcoded_tally_is_fatal():
    (defect,) = analyze_output_assertions(_HARDCODED_TALLY_ASSERTION)
    assert defect.fatal
    assert defect.kind == "hardcoded-tally"
    assert defect.literal == "valid tests: 210 passed, 0 failed"
    assert "column-align" in defect.message


def test_hardcoded_tally_in_noun_colon_count_form_is_fatal():
    (defect,) = analyze_output_assertions(
        'assert result.returncode == 0\nassert "failures: 0" in result.stdout'
    )
    assert defect.kind == "hardcoded-tally"


def test_hardcoded_tally_tracked_through_a_stdout_binding():
    (defect,) = analyze_output_assertions(
        'out = result.stdout\nassert "709 tests" in out',
    )
    assert defect.kind == "hardcoded-tally"


def test_hardcoded_tally_on_stderr_is_not_reported():
    # Only a runner's stdout summary carries the formatting hazard.
    assert analyze_output_assertions('assert "210 passed" in result.stderr') == ()


def test_whitespace_tolerant_regex_on_a_tally_is_not_reported():
    # The prescribed repair: match the shape, not the literal.
    assert (
        analyze_output_assertions(
            "import re\n"
            "assert result.returncode == 0\n"
            'assert re.search(r"valid tests:\\s+\\d+ passed,\\s+0 failed", result.stdout)'
        )
        == ()
    )


# The Toml conformance case, one repair later. Rewriting the pinned literal as a regex moved the
# assertion into a call the literal rules cannot see, and the criterion grew two nouns toml-test
# never prints on a clean run: it emits "skipped tests: N" only when it skipped something, and no
# error tally at all.
_SPECULATIVE_TALLY_ASSERTION = """
import re
import subprocess

result = subprocess.run(["sh", "sources/full_test.sh"], capture_output=True, text=True)
print(result.stdout)
assert result.returncode == 0
assert re.search(r"\\b0\\s+failed\\b", result.stdout)
assert re.search(r"\\b0\\s+errors?\\b", result.stdout, re.IGNORECASE)
assert re.search(r"\\b0\\s+skipped\\b", result.stdout, re.IGNORECASE)
"""


def test_requiring_a_tally_of_errors_or_skips_by_regex_is_fatal():
    defects = analyze_output_assertions(_SPECULATIVE_TALLY_ASSERTION)
    assert [d.kind for d in defects] == ["speculative-tally", "speculative-tally"]
    assert all(d.fatal for d in defects)
    # The failure count is the documented form and survives; only the speculative nouns are cited.
    assert [d.literal for d in defects] == [r"\b0\s+errors?\b", r"\b0\s+skipped\b"]
    assert "exit status" in defects[0].message


def test_pinned_count_in_a_regex_is_a_hardcoded_tally():
    # The regex form does not launder a case count the installed suite owns.
    (defect,) = analyze_output_assertions(
        "import re\n"
        "assert result.returncode == 0\n"
        'assert re.search(r"\\b205\\s+passed\\b", result.stdout)'
    )
    assert defect.kind == "hardcoded-tally"
    assert defect.fatal


def test_speculative_tally_without_an_exit_assertion_is_not_reported():
    # With no exit-status gate the regex is the proof's only verdict; removing it leaves nothing.
    assert (
        analyze_output_assertions(
            'import re\nassert re.search(r"\\b0\\s+errors\\b", result.stdout)'
        )
        == ()
    )


def test_speculative_tally_on_stderr_is_not_reported():
    assert (
        analyze_output_assertions(
            "import re\n"
            "assert result.returncode == 0\n"
            'assert re.search(r"\\b0\\s+errors\\b", result.stderr)'
        )
        == ()
    )


def test_forbidding_a_nonzero_tally_by_regex_is_not_reported():
    # A negated match forbids a pattern rather than requiring one, and pins no count.
    assert (
        analyze_output_assertions(
            "import re\n"
            "assert result.returncode == 0\n"
            'assert not re.search(r"[1-9]\\d*\\s+errors", result.stdout)'
        )
        == ()
    )


def test_unparseable_code_is_not_reported():
    assert analyze_output_assertions("def broken(:") == ()


def test_duplicate_literals_report_once():
    defects = analyze_output_assertions(
        'assert "failed" not in result.stdout.lower()\nassert "failed" not in result.stderr.lower()'
    )
    assert len(defects) == 1


def test_tally_word_on_stderr_is_not_fatal():
    # A command that succeeds writes nothing to stderr, so forbidding a word there is an
    # ordinary satisfiable check — the tally reasoning applies only to a runner's stdout.
    (defect,) = analyze_output_assertions(
        'assert result.returncode == 0\nassert "error" not in result.stderr.lower()'
    )
    assert not defect.fatal
    assert defect.kind == "redundant-substring"


def test_a_stderr_binding_does_not_inherit_stdout_reasoning():
    (defect,) = analyze_output_assertions(
        'err = result.stderr\nassert result.returncode == 0\nassert "failed" not in err'
    )
    assert not defect.fatal


def test_a_stdout_binding_stays_fatal():
    (defect,) = analyze_output_assertions(
        'out = result.stdout\nassert result.returncode == 0\nassert "failed" not in out'
    )
    assert defect.fatal


# --- Environment replacement -------------------------------------------------
#
# Every snippet below is the shape a real plan emitted against the TOML conformance
# harness. Each failed a full build pass before it was caught statically.


def test_env_dict_without_environ_is_a_defect():
    (defect,) = analyze_invocation(
        'subprocess.run(["sh", "sources/run.sh"], env={"DECODER": "./decoder"})'
    )
    assert defect.kind == "env-replaces-environ"
    assert "**os.environ" in defect.message
    assert "PATH" in defect.message


def test_env_dict_extending_environ_is_accepted():
    assert (
        analyze_invocation(
            'subprocess.run(["sh", "sources/run.sh"], env={**os.environ, "DECODER": "./d"})'
        )
        == ()
    )


def test_env_naming_path_explicitly_is_still_a_replacement():
    # Supplying PATH does not make the replacement safe: HOME, TMPDIR, and the toolchain's
    # own cache variables are gone too, and no plan-time author can enumerate them.
    (defect,) = analyze_invocation(
        'subprocess.run(["go", "build"], env={"DECODER": "./d", "PATH": "/usr/bin"})'
    )
    assert defect.kind == "env-replaces-environ"


def test_computed_environment_is_left_alone():
    # ``os.environ.copy()`` is not a dict literal. Deciding it would need value tracking this
    # analysis deliberately does not do, and the runtime gate still covers it.
    assert analyze_invocation('subprocess.run(["sh", "x.sh"], env=os.environ.copy())') == ()
    assert analyze_invocation('subprocess.run(["sh", "x.sh"], env=environment)') == ()


def test_no_env_keyword_is_not_a_replacement():
    assert analyze_invocation('subprocess.run(["sh", "sources/run.sh"])') == ()


# --- Shell escape handling ---------------------------------------------------


def test_printf_percent_s_with_escapes_is_a_defect():
    (defect,) = analyze_shell_escapes(
        r"""subprocess.run(["sh", "-c", "printf '%s' '[a.b]\\nvalue = 1\\n' | ./decoder"])"""
    )
    assert defect.fmt == "%s"
    assert "verbatim" in defect.message


def test_printf_percent_b_expands_and_is_accepted():
    assert (
        analyze_shell_escapes(
            r"""subprocess.run(["sh", "-c", "printf '%b' '[a.b]\\nvalue = 1\\n' | ./decoder"])"""
        )
        == ()
    )


def test_printf_escape_inside_the_format_is_accepted():
    # printf always expands escapes written into the format itself.
    assert analyze_shell_escapes(r"""subprocess.run(["sh", "-c", "printf 'a\\nb'"])""") == ()


def test_printf_without_escapes_is_accepted():
    assert (
        analyze_shell_escapes("""subprocess.run(["sh", "-c", "printf '%s' 'plain' | ./d"])""") == ()
    )


# --- Staged harness environment contract -------------------------------------

_HARNESS = """#!/bin/sh
set -u

if [ -z "${DECODER:-}" ]; then
    echo "error: DECODER is not set; give the command that runs your decoder." >&2
    exit 2
fi

if [ -n "${TOML_TEST:-}" ] && [ -x "${TOML_TEST}" ]; then
    HARNESS="${TOML_TEST}"
fi
"""


def _staged(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "run_conformance.sh").write_text(_HARNESS, encoding="utf-8")
    return sources


def test_required_variable_is_read_from_the_staged_script(tmp_path):
    # Only the guarded-and-exiting variable is required. ``TOML_TEST`` selects a default and
    # is documented as optional, so it must not be demanded.
    assert staged_script_requirements(_staged(tmp_path) / "run_conformance.sh") == ("DECODER",)


def test_staged_call_missing_the_required_variable_is_a_defect(tmp_path):
    (defect,) = analyze_staged_invocation(
        'subprocess.run(["sh", "sources/run_conformance.sh", "-run", "valid/key*"])',
        sources_dir=_staged(tmp_path),
    )
    assert defect.script == "run_conformance.sh"
    assert defect.variable == "DECODER"
    assert "grades the script's own precondition" in defect.message


def test_staged_call_supplying_the_variable_is_accepted(tmp_path):
    assert (
        analyze_staged_invocation(
            'subprocess.run(["sh", "sources/run_conformance.sh"],'
            ' env={**os.environ, "DECODER": "./d"})',
            sources_dir=_staged(tmp_path),
        )
        == ()
    )


def test_a_shell_assignment_supplies_the_variable(tmp_path):
    assert (
        analyze_staged_invocation(
            'subprocess.run(["sh", "-c", "DECODER=./d sh sources/run_conformance.sh"])',
            sources_dir=_staged(tmp_path),
        )
        == ()
    )


def test_an_unreadable_staged_script_reports_nothing(tmp_path):
    # The asset may not be staged yet at the moment of analysis. Silence beats a false defect.
    assert (
        analyze_staged_invocation(
            'subprocess.run(["sh", "sources/absent.sh"])', sources_dir=tmp_path / "sources"
        )
        == ()
    )


def test_no_sources_directory_disables_the_check():
    assert (
        analyze_staged_invocation(
            'subprocess.run(["sh", "sources/run_conformance.sh"])', sources_dir=None
        )
        == ()
    )
