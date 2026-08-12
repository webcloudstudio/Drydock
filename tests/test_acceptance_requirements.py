"""Commander-authorized Programmatic Acceptance tooling contracts."""

from __future__ import annotations

from drydock import acceptance_requirements, target_environment
from drydock.acceptance import (
    AcceptanceRequirement,
    parse_programmatic_acceptance_text,
)
from drydock.acceptance_requirements import (
    authorization_for,
    discover_missing_requirement,
    project_plan_requirement_decisions,
    recommend_external_declarations,
    undeclared_external_usage,
)
from drydock.decisions import Decision, write_decisions


def _spec(requires: str, code: str) -> str:
    return f"""# FEATURE: Health

| Field | Value |
|---|---|
| Type | FEATURE |

## Programmatic Acceptance

### health-route
{requires}

The health route responds successfully.

```python
{code}
```

## User Acceptance

- None.
"""


# The declaration gate is retired. It asked whether the model had written a ``Requires:`` line
# beside a check, never whether the tool was installed, so a check that ran perfectly failed
# planning over a missing declaration. Undeclared usage is now a recommendation.


def test_undeclared_usage_is_recommended_never_a_planning_failure():
    check = parse_programmatic_acceptance_text(
        _spec(
            "Requires: python-package=fastapi; scope=test",
            "from fastapi.testclient import TestClient\nassert TestClient",
        ),
        source="FEATURE-Health.md",
    )[0]

    assert ("python-package", "httpx") in undeclared_external_usage(check)
    notes = recommend_external_declarations((check,))
    assert any("undeclared python-package=httpx" in note for note in notes)
    assert all("TECHNOLOGY_STACK.md" in note for note in notes)


def test_a_baseline_executable_needs_no_exemption_list():
    """``sh`` is reported like anything else, because reporting it blocks nothing.

    The old gate needed a hard-coded exemption for ``sh``/``bash``/``python3`` precisely
    because it blocked. Nothing blocks now, so nothing needs exempting.
    """
    check = parse_programmatic_acceptance_text(
        _spec(
            "",
            'import subprocess\nsubprocess.run(["sh", "-c", "true"], check=True)',
        ),
        source="FEATURE-Health.md",
    )[0]

    assert ("executable", "sh") in undeclared_external_usage(check)
    assert recommend_external_declarations((check,))


def test_an_undeclared_executable_is_reported_without_stopping_the_plan():
    check = parse_programmatic_acceptance_text(
        _spec(
            "",
            'import subprocess\nsubprocess.run(["toml-test", "--version"], check=True)',
        ),
        source="FEATURE-Health.md",
    )[0]

    assert ("executable", "toml-test") in undeclared_external_usage(check)
    assert any(
        "undeclared executable=toml-test" in note
        for note in recommend_external_declarations((check,))
    )


def test_distribution_metadata_is_discovered_once_per_process(monkeypatch):
    calls = 0

    def packages_distributions():
        nonlocal calls
        calls += 1
        return {"external_import": ["external-package"]}

    monkeypatch.setattr(
        acceptance_requirements.importlib.metadata,
        "packages_distributions",
        packages_distributions,
    )
    acceptance_requirements._distribution_map.cache_clear()
    check = parse_programmatic_acceptance_text(
        _spec(
            "Requires: python-package=external-package; scope=test",
            "import external_import\nassert external_import",
        ),
        source="FEATURE-Health.md",
    )[0]

    try:
        recommend_external_declarations((check,))
        recommend_external_declarations((check,))
    finally:
        acceptance_requirements._distribution_map.cache_clear()

    assert calls == 1


def test_target_package_inventory_is_reused_until_invalidated(tmp_path, monkeypatch):
    class Distribution:
        metadata = {"Name": "httpx"}

    calls = 0

    def distributions(*, path):
        nonlocal calls
        calls += 1
        assert path
        return (Distribution(),)

    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    site_packages = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    monkeypatch.setattr(acceptance_requirements.importlib.metadata, "distributions", distributions)
    acceptance_requirements.invalidate_target_environment_inventory()
    requirement = AcceptanceRequirement("python-package", "httpx", "test")

    try:
        assert acceptance_requirements.requirement_available(requirement, tmp_path)
        assert acceptance_requirements.requirement_available(requirement, tmp_path)
        assert calls == 1

        acceptance_requirements.invalidate_target_environment_inventory()
        assert acceptance_requirements.requirement_available(requirement, tmp_path)
        assert calls == 2
    finally:
        acceptance_requirements.invalidate_target_environment_inventory()


def test_uv_provisioning_invalidates_target_package_inventory(tmp_path, monkeypatch):
    class Distribution:
        metadata = {"Name": "httpx"}

    provisioned = False

    def distributions(*, path):
        assert path
        return (Distribution(),) if provisioned else ()

    def run(*args, **kwargs):
        nonlocal provisioned
        provisioned = True
        return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "uv.lock").touch()
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    (tmp_path / ".venv" / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
    monkeypatch.setattr(acceptance_requirements.importlib.metadata, "distributions", distributions)
    monkeypatch.setattr(target_environment.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(target_environment.subprocess, "run", run)
    acceptance_requirements.invalidate_target_environment_inventory()
    requirement = AcceptanceRequirement("python-package", "httpx", "test")

    try:
        assert not acceptance_requirements.requirement_available(requirement, tmp_path)
        result = target_environment.provision_uv_environment(tmp_path)
        assert result.interpreter == interpreter
        assert acceptance_requirements.requirement_available(requirement, tmp_path)
    finally:
        acceptance_requirements.invalidate_target_environment_inventory()


def _authorize(target, answer: str) -> None:
    """Persist an answered Commander authorization decision in DECISIONS.json."""
    write_decisions(
        target / "DECISIONS.json",
        (
            Decision(
                id="acceptance-health-route-tooling",
                type="text",
                severity="blocking",
                origin="plan",
                blueprint="FEATURE-Health.md",
                story=None,
                status="answered",
                archived=False,
                title="Authorize health-route test tooling",
                description=(
                    "Authorize python-package=httpx for test scope. Affected acceptance check: "
                    "FEATURE-Health.md#health-route."
                ),
                options=(),
                system_choice="not authorized",
                override_text=answer,
            ),
        ),
    )


def test_plan_projects_a_blocking_tooling_decision(tmp_path):
    target = tmp_path / "Demo"
    target.mkdir()
    blocks = {
        "FEATURE-Health.md": _spec(
            "Requires: python-package=httpx; scope=test", "import httpx\nassert httpx"
        )
    }

    decisions = project_plan_requirement_decisions(
        blocks, target_dir=target, build_dir=tmp_path / "build"
    )

    decision = decisions[0]
    assert decision.id == "acceptance-health-route-tooling"
    assert decision.blueprint == "FEATURE-Health.md"
    assert decision.origin == "plan"
    assert decision.severity == "blocking"
    assert "python-package=httpx" in decision.description
    assert "uv add --dev httpx" in decision.description


def test_broad_commander_test_harness_guidance_authorizes_later_tools(tmp_path):
    target = tmp_path / "Demo"
    target.mkdir()
    _authorize(target, "Approve all test harnesses")

    auth = authorization_for(
        AcceptanceRequirement("python-package", "playwright", "test"),
        target_dir=target,
        build_dir=tmp_path / "build",
    )

    assert auth.authorized
    assert auth.commander_text == "Approve all test harnesses"


def test_broad_test_guidance_does_not_authorize_runtime_scope(tmp_path):
    target = tmp_path / "Demo"
    target.mkdir()
    _authorize(target, "Approve all test harnesses")

    auth = authorization_for(
        AcceptanceRequirement("python-package", "httpx", "runtime"),
        target_dir=target,
        build_dir=tmp_path / "build",
    )

    assert not auth.authorized


def test_narrow_commander_answer_authorizes_only_named_tool_and_scope(tmp_path):
    target = tmp_path / "Demo"
    target.mkdir()
    _authorize(target, "Approve httpx for test scope only")

    httpx = authorization_for(
        AcceptanceRequirement("python-package", "httpx", "test"),
        target_dir=target,
        build_dir=tmp_path / "build",
    )
    playwright = authorization_for(
        AcceptanceRequirement("python-package", "playwright", "test"),
        target_dir=target,
        build_dir=tmp_path / "build",
    )
    runtime = authorization_for(
        AcceptanceRequirement("python-package", "httpx", "runtime"),
        target_dir=target,
        build_dir=tmp_path / "build",
    )

    assert httpx.authorized
    assert not playwright.authorized
    assert not runtime.authorized


# A pre-build acceptance observation runs before the code exists, so a missing project-local
# executable is the expected RED result — never an external tool the Commander must authorize.

_PROJECT_LOCAL_STDERR = """Traceback (most recent call last):
  File "spec_tests.py", line 44, in do_test
    p1 = Popen(prog.split(), stdout=PIPE, stdin=PIPE, stderr=PIPE)
FileNotFoundError: [Errno 2] No such file or directory: './program'

Traceback (most recent call last):
  File "block-quotes-basic.py", line 10, in <module>
    assert result.returncode == 0
AssertionError
"""


def test_a_project_local_executable_is_never_an_authorization_requirement():
    assert discover_missing_requirement(_PROJECT_LOCAL_STDERR) is None


def test_an_absolute_path_executable_is_never_an_authorization_requirement():
    stderr = "FileNotFoundError: [Errno 2] No such file or directory: '/opt/build/program'\n"

    assert discover_missing_requirement(stderr) is None


def test_a_genuinely_missing_external_tool_is_still_discovered():
    stderr = "FileNotFoundError: [Errno 2] No such file or directory: 'psql'\n"

    assert discover_missing_requirement(stderr) == AcceptanceRequirement(
        "executable", "psql", "test"
    )


def test_executable_discovery_never_captures_a_following_traceback():
    requirement = discover_missing_requirement(
        "FileNotFoundError: [Errno 2] No such file or directory: './program'\n"
        "\n"
        'Traceback (most recent call last):\n  File "check.py", line 1, in <module>\n'
    )

    assert requirement is None


def test_a_missing_module_is_still_discovered_as_a_package():
    stderr = "ModuleNotFoundError: No module named 'httpx.compat'\n"

    assert discover_missing_requirement(stderr) == AcceptanceRequirement(
        "python-package", "httpx", "test"
    )
