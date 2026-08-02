"""Commander-authorized Programmatic Acceptance tooling contracts."""

from __future__ import annotations

import pytest

from drydock.acceptance import (
    AcceptanceRequirement,
    parse_programmatic_acceptance_text,
)
from drydock.acceptance_requirements import (
    authorization_for,
    project_plan_requirement_questions,
    undeclared_external_usage,
    validate_declared_external_usage,
)
from drydock.plan_feedback import harvest_answered_questions
from drydock.questions import answer_question, parse_questions


def _spec(requires: str, code: str) -> str:
    return f"""# FEATURE: Health

| Field | Value |
|---|---|
| Type | FEATURE |

## Questions

- None.

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


def test_fastapi_test_client_requires_declared_httpx():
    check = parse_programmatic_acceptance_text(
        _spec(
            "Requires: python-package=fastapi; scope=test",
            "from fastapi.testclient import TestClient\nassert TestClient",
        ),
        source="FEATURE-Health.md",
    )[0]

    assert ("python-package", "httpx") in undeclared_external_usage(check)
    with pytest.raises(ValueError, match="undeclared python-package=httpx"):
        validate_declared_external_usage((check,))


def test_plan_projects_canonical_story_local_tooling_question(tmp_path):
    target = tmp_path / "Demo"
    target.mkdir()
    blocks = {
        "FEATURE-Health.md": _spec(
            "Requires: python-package=httpx; scope=test", "import httpx\nassert httpx"
        )
    }

    added = project_plan_requirement_questions(
        blocks, target_dir=target, build_dir=tmp_path / "build"
    )
    question = parse_questions(blocks["FEATURE-Health.md"])[0]

    assert added == ("FEATURE-Health.md#Q-health-route-tooling",)
    assert question.origin == "plan"
    assert question.severity == "blocking"
    assert "python-package=httpx" in question.question
    assert "uv add --dev httpx" in question.question


def test_broad_commander_test_harness_guidance_authorizes_later_tools(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    path = blueprint / "FEATURE-Health.md"
    blocks = {
        path.name: _spec("Requires: python-package=httpx; scope=test", "import httpx\nassert httpx")
    }
    project_plan_requirement_questions(blocks, target_dir=target, build_dir=tmp_path / "build")
    path.write_text(blocks[path.name], encoding="utf-8")
    answer_question(path, "Q-health-route-tooling", "Approve all test harnesses")
    harvested = harvest_answered_questions(target)

    auth = authorization_for(
        AcceptanceRequirement("python-package", "playwright", "test"),
        target_dir=target,
        build_dir=tmp_path / "build",
    )

    assert harvested[0].answer == "Approve all test harnesses"
    assert auth.authorized
    assert auth.commander_text == "Approve all test harnesses"


def test_broad_test_guidance_does_not_authorize_runtime_scope(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    path = blueprint / "FEATURE-Health.md"
    text = _spec("Requires: python-package=httpx; scope=test", "assert True")
    blocks = {path.name: text}
    project_plan_requirement_questions(blocks, target_dir=target, build_dir=tmp_path / "build")
    path.write_text(blocks[path.name], encoding="utf-8")
    answer_question(path, "Q-health-route-tooling", "Approve all test harnesses")
    harvest_answered_questions(target)

    auth = authorization_for(
        AcceptanceRequirement("python-package", "httpx", "runtime"),
        target_dir=target,
        build_dir=tmp_path / "build",
    )

    assert not auth.authorized


def test_narrow_commander_answer_authorizes_only_named_tool_and_scope(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    path = blueprint / "FEATURE-Health.md"
    blocks = {
        path.name: _spec("Requires: python-package=httpx; scope=test", "import httpx\nassert httpx")
    }
    project_plan_requirement_questions(blocks, target_dir=target, build_dir=tmp_path / "build")
    path.write_text(blocks[path.name], encoding="utf-8")
    answer_question(
        path,
        "Q-health-route-tooling",
        "Approve httpx for test scope only",
    )

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
