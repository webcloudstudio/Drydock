"""Language resources resolve in prompts and execute real native tests."""

import shutil

import pytest

from drydock.acceptance import ProgrammaticAcceptance, run_programmatic_acceptance
from drydock.paths import get_language_dir
from drydock.plan_stack import resolve_stack_file
from drydock.rigging_contract import contract_for
from drydock.technology_stack import rigging_names


@pytest.mark.parametrize("language", ["python", "go"])
def test_language_resolves_from_bundle(language):
    path = get_language_dir(language) / f"{language}.md"
    assert resolve_stack_file(f"{language}.md").path == path
    assert contract_for(f"{language}.md").kind == "language"
    assert f"{language}.md" in rigging_names()


@pytest.mark.skipif(shutil.which("go") is None, reason="Go toolchain required")
@pytest.mark.parametrize(
    "test,status",
    [("TestPass", "pass"), ("TestFail", "fail"), ("TestSkip", "skip"), ("TestAbsent", "not-run")],
)
def test_go_native_results_flow_through_acceptance(tmp_path, monkeypatch, test, status):
    monkeypatch.setenv("GOCACHE", "/tmp/drydock-go-cache")
    (tmp_path / "go.mod").write_text("module example.test/criteria\n\ngo 1.22\n")
    (tmp_path / "sample_test.go").write_text("""package criteria
import "testing"
func TestPass(t *testing.T) {}
func TestFail(t *testing.T) { t.Fatal("observed failure") }
func TestSkip(t *testing.T) { t.Skip("unavailable") }
""")
    code = (
        f'from drydock_go import run_test\nr = run_test("./", "{test}")\n'
        f'assert r.status == "{status}", (r.status, r.stderr, r.stdout)\n'
        f"assert r.passed == {status == 'pass'}\n"
    )
    check = ProgrammaticAcceptance(
        check_id="native-go",
        source="FEATURE.md",
        intent="Observe native test result",
        code=code,
        full_suite=True,
    )
    (result,) = run_programmatic_acceptance(
        (check,), build_dir=tmp_path, target_dir=tmp_path, blueprint_dir=tmp_path
    )
    assert result.passed == (status == "pass"), (result.error, result.stderr)
    assert result.skipped == (status in {"skip", "not-run"})
    if status != "pass":
        assert status in result.error


@pytest.mark.skipif(shutil.which("go") is None, reason="Go toolchain required")
def test_go_compile_error_remains_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("GOCACHE", "/tmp/drydock-go-cache")
    (tmp_path / "go.mod").write_text("module example.test/broken\n\ngo 1.22\n")
    (tmp_path / "broken_test.go").write_text("package broken\nthis does not compile\n")
    code = (
        'from drydock_go import run_test\nr = run_test("./", "TestBroken")\n'
        'assert not r.passed\nassert r.status == "execution-error", r\n'
    )
    check = ProgrammaticAcceptance("compile-error", "FEATURE.md", "Observe compilation error", code)
    (result,) = run_programmatic_acceptance(
        (check,), build_dir=tmp_path, target_dir=tmp_path, blueprint_dir=tmp_path
    )
    assert not result.passed
    assert "execution-error" in result.error


def test_unavailable_native_tool_is_unverified(tmp_path):
    check = ProgrammaticAcceptance(
        "no-go",
        "FEATURE.md",
        "Native tool availability",
        """
from unittest.mock import patch
from drydock_go import run_test
with patch("drydock_go.subprocess.run", side_effect=FileNotFoundError("go unavailable")):
    result = run_test("./", "TestExample")
assert not result.passed
""",
    )
    (result,) = run_programmatic_acceptance(
        (check,), build_dir=tmp_path, target_dir=tmp_path, blueprint_dir=tmp_path
    )
    assert result.skipped and not result.passed
    assert "unavailable" in result.error
