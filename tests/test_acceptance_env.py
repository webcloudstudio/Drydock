"""Acceptance criteria that call a staged asset without the environment it requires."""

from __future__ import annotations

import textwrap

from drydock.acceptance import parse_programmatic_acceptance_text
from drydock.acceptance_env import (
    missing_env_names,
    read_staged_assets,
    required_env_names,
    staged_asset_env_defects,
)

# The jq conformance runner, reduced to the three things that make ``JQ`` a caller obligation.
RUNNER = '''#!/usr/bin/env python3
"""Run the upstream jq conformance corpus against a candidate implementation.

Usage:
    JQ=./jq python3 sources/run_conformance.py                     # full corpus
    JQ=./jq python3 sources/run_conformance.py --select 'reduce'   # one construct

Environment:
    JQ         command that runs the candidate. Required -- this harness is language-neutral
               and deliberately has no default implementation language.

Exit codes:
    0   every case that ran passed
    2   the harness could not run: bad usage, missing corpus, or a stale exclusion
"""
if not os.environ.get("JQ"):
    sys.exit("error: JQ is not set; give the command that runs your implementation")
'''

# The wrapper supplies ``JQ`` to the runner it calls. It requires nothing from its own caller.
WRAPPER = """#!/bin/sh
set -eu
if [ ! -x ./jq ]; then
    echo "error: no executable ./jq at the application root." >&2
    exit 1
fi
JQ="$PWD/jq" exec python3 sources/run_conformance.py
"""

ASSETS = {
    "sources/run_conformance.py": RUNNER,
    "sources/full_test.sh": WRAPPER,
}


def _code(body: str) -> str:
    return textwrap.dedent(body).strip() + "\n"


def test_a_runner_that_states_the_variable_is_required_declares_it():
    assert required_env_names(RUNNER, "sources/run_conformance.py") == frozenset({"JQ"})


def test_a_wrapper_that_supplies_the_variable_does_not_declare_it():
    """``full_test.sh`` sets ``JQ`` for the runner; that is the runner's requirement, not its own."""
    assert required_env_names(WRAPPER, "sources/full_test.sh") == frozenset()


def test_ambient_variables_are_never_a_caller_obligation():
    text = "Environment:\n    PATH       search path. Required\n"
    assert required_env_names(text, "sources/tool.sh") == frozenset()


def test_the_run_that_failed_is_detected():
    """Verbatim from the jq UAT run 20260816.202001, FEATURE-Formats.md."""
    code = _code("""
        import subprocess

        result = subprocess.run(
            ["python3", "sources/run_conformance.py", "--select", r"@|interpolation"],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        print(result.stderr)
        assert result.returncode == 0
    """)
    assert missing_env_names(code, ASSETS) == (("sources/run_conformance.py", "JQ"),)


def test_supplying_the_variable_clears_the_defect():
    code = _code("""
        import os
        import subprocess

        result = subprocess.run(
            ["python3", "sources/run_conformance.py"],
            capture_output=True,
            text=True,
            env={**os.environ, "JQ": f"{os.getcwd()}/jq"},
        )
        assert result.returncode == 0
    """)
    assert missing_env_names(code, ASSETS) == ()


def test_setting_the_variable_in_the_process_environment_clears_the_defect():
    code = _code("""
        import os
        import subprocess

        os.environ["JQ"] = os.getcwd() + "/jq"
        result = subprocess.run(["python3", "sources/run_conformance.py"], capture_output=True)
        assert result.returncode == 0
    """)
    assert missing_env_names(code, ASSETS) == ()


def test_calling_the_wrapper_is_not_a_defect():
    code = _code("""
        import subprocess

        result = subprocess.run(["sh", "sources/full_test.sh"], capture_output=True, text=True)
        assert result.returncode == 0
    """)
    assert missing_env_names(code, ASSETS) == ()


def test_an_unreadable_environment_is_treated_as_satisfied():
    """A computed ``env=`` cannot be read statically, and a guess would block a sound story."""
    code = _code("""
        import os
        import subprocess

        environment = dict(os.environ, JQ="./jq")
        result = subprocess.run(["python3", "sources/run_conformance.py"], env=environment)
        assert result.returncode == 0
    """)
    assert missing_env_names(code, ASSETS) == ()


def test_a_criterion_that_does_not_compile_is_not_this_passes_defect():
    assert missing_env_names("assert 1 ==", ASSETS) == ()


def test_a_project_with_no_staged_assets_reports_nothing():
    code = _code("""
        import subprocess

        result = subprocess.run(["python3", "sources/run_conformance.py"])
        assert result.returncode == 0
    """)
    assert missing_env_names(code, {}) == ()


def test_defects_name_the_criterion_the_asset_and_the_variable():
    spec = (
        "# FEATURE: Formats\n\n## Programmatic Acceptance\n\n"
        "=== AC formats-suite ===\nIntent: The slice passes.\n\n"
        "import subprocess\n"
        'result = subprocess.run(["python3", "sources/run_conformance.py"], capture_output=True)\n'
        "assert result.returncode == 0\n"
        "=== END AC formats-suite ===\n"
    )
    checks = parse_programmatic_acceptance_text(spec, source="FEATURE-Formats.md")

    defects = staged_asset_env_defects(checks, ASSETS)

    assert len(defects) == 1
    assert defects[0].check_id == "formats-suite"
    assert defects[0].source == "FEATURE-Formats.md"
    assert "sources/run_conformance.py" in defects[0].reason
    assert "JQ" in defects[0].reason


def test_staged_assets_are_read_from_the_blueprint_source_tree(tmp_path):
    sources = tmp_path / "sources"
    (sources / "nested").mkdir(parents=True)
    (sources / "run_conformance.py").write_text(RUNNER, encoding="utf-8")
    (sources / "nested" / "corpus.bin").write_bytes(b"\xff\xfe\x00")

    assets = read_staged_assets(tmp_path)

    assert "sources/run_conformance.py" in assets
    assert "sources/nested/corpus.bin" not in assets


def test_no_source_tree_reads_as_no_assets(tmp_path):
    assert read_staged_assets(tmp_path) == {}
