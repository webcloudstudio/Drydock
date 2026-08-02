"""Acceptance-tool declarations, Commander authorization, and question projection."""

from __future__ import annotations

import ast
import importlib.metadata
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from drydock.acceptance import AcceptanceRequirement, ProgrammaticAcceptance
from drydock.dependency_gate import canonicalize_package_name
from drydock.plan_feedback import PlanningDecision, load_feedback
from drydock.questions import (
    MarkdownQuestion,
    append_question,
    parse_questions,
    replace_questions_section,
)
from drydock.target_environment import resolve_target_environment

_MISSING_MODULE_RE = re.compile(
    r"(?:ModuleNotFoundError|ImportError): No module named ['\"]([^'\"]+)"
)
_MISSING_EXECUTABLE_RE = re.compile(r"FileNotFoundError: .*?['\"]([^/'\"]+)['\"]")
_KNOWN_EXTERNAL_IMPORTS = frozenset({
    "fastapi",
    "httpx",
    "numpy",
    "pandas",
    "playwright",
    "pydantic",
    "pytest",
    "requests",
    "sqlalchemy",
    "starlette",
})


@dataclass(frozen=True)
class RequirementAuthorization:
    requirement: AcceptanceRequirement
    authorized: bool
    source: str = ""
    commander_text: str = ""


def _distribution_imports() -> frozenset[str]:
    try:
        return frozenset(importlib.metadata.packages_distributions())
    except Exception:  # pragma: no cover - damaged host metadata
        return frozenset()


def visible_external_usage(code: str) -> tuple[tuple[str, str], ...]:
    """Return visible third-party imports and literal subprocess executables."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()
    distribution_imports = _distribution_imports()
    usage: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        module = ""
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in distribution_imports or root in _KNOWN_EXTERNAL_IMPORTS:
                    usage.append(("python-package", root))
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module.split(".", 1)[0]
            if module in distribution_imports or module in _KNOWN_EXTERNAL_IMPORTS:
                usage.append(("python-package", module))
            if node.module in {"fastapi.testclient", "starlette.testclient"}:
                usage.append(("python-package", "httpx"))
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        is_subprocess = (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "subprocess"
            and function.attr in {"run", "Popen", "call", "check_call", "check_output"}
        )
        if not is_subprocess:
            continue
        command = node.args[0]
        first = (
            command.elts[0]
            if isinstance(command, (ast.List, ast.Tuple)) and command.elts
            else command
        )
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            executable = first.value.strip().split()[0]
            if executable and not executable.startswith((".", "/")):
                usage.append(("executable", executable))
    return tuple(dict.fromkeys(usage))


def undeclared_external_usage(check: ProgrammaticAcceptance) -> tuple[tuple[str, str], ...]:
    declared = {
        (
            item.kind,
            canonicalize_package_name(item.name) if item.kind == "python-package" else item.name,
        )
        for item in check.requirements
    }
    missing = []
    distributions = importlib.metadata.packages_distributions()
    for kind, name in visible_external_usage(check.code):
        normalized = canonicalize_package_name(name) if kind == "python-package" else name
        aliases = {normalized}
        if kind == "python-package":
            aliases.update(
                canonicalize_package_name(distribution)
                for distribution in distributions.get(name, ())
            )
        if not any((kind, alias) in declared for alias in aliases):
            missing.append((kind, name))
    return tuple(missing)


def validate_declared_external_usage(checks: tuple[ProgrammaticAcceptance, ...]) -> None:
    defects = [
        f"{check.source} [{check.check_id}] uses undeclared {kind}={name}"
        for check in checks
        for kind, name in undeclared_external_usage(check)
    ]
    if defects:
        raise ValueError(
            "Programmatic Acceptance has undeclared external tooling:\n  " + "\n  ".join(defects)
        )


def _manifest_packages(build_dir: Path) -> frozenset[str]:
    path = build_dir / "pyproject.toml"
    if not path.is_file():
        return frozenset()
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return frozenset()
    project = doc.get("project", {})
    values = list(project.get("dependencies", [])) if isinstance(project, dict) else []
    optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                values.extend(group)
    names = []
    for value in values:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", str(value))
        if match:
            names.append(canonicalize_package_name(match.group(1)))
    return frozenset(names)


def requirement_available(requirement: AcceptanceRequirement, build_dir: Path) -> bool:
    if requirement.kind == "executable":
        return shutil.which(requirement.name) is not None
    environment = resolve_target_environment(build_dir)
    if environment.interpreter is None:
        return False
    venv = build_dir / ".venv"
    candidates = [*venv.glob("lib/python*/site-packages"), venv / "Lib" / "site-packages"]
    wanted = canonicalize_package_name(requirement.name)
    for root in candidates:
        if not root.is_dir():
            continue
        for distribution in importlib.metadata.distributions(path=[str(root)]):
            name = distribution.metadata.get("Name", "")
            if name and canonicalize_package_name(name) == wanted:
                return True
    return False


def _decision_authorizes(requirement: AcceptanceRequirement, decision: PlanningDecision) -> bool:
    answer = decision.answer.lower()
    if not any(word in answer for word in ("approve", "authorize", "allowed", "permit")):
        return False
    if "all test harness" in answer and requirement.scope == "test":
        return True
    corpus = f"{decision.subject} {decision.question} {decision.answer}".lower()
    return requirement.name.lower() in corpus and requirement.scope in corpus


def authorization_for(
    requirement: AcceptanceRequirement,
    *,
    target_dir: Path,
    build_dir: Path,
    current_manifest_approved: bool = False,
) -> RequirementAuthorization:
    if requirement_available(requirement, build_dir):
        return RequirementAuthorization(requirement, True, "existing Target environment/manifest")
    if requirement.kind == "python-package" and canonicalize_package_name(
        requirement.name
    ) in _manifest_packages(build_dir):
        return RequirementAuthorization(requirement, True, "existing Target dependency manifest")
    stack = target_dir / "TECHNOLOGY_STACK.md"
    if stack.is_file() and requirement.name.lower() in stack.read_text(encoding="utf-8").lower():
        return RequirementAuthorization(requirement, True, "Commander technology stack")
    for decision in load_feedback(target_dir):
        if decision.status == "active" and _decision_authorizes(requirement, decision):
            return RequirementAuthorization(
                requirement, True, f"Commander guidance {decision.decision_id}", decision.answer
            )
    if current_manifest_approved:
        return RequirementAuthorization(requirement, True, "current Manifest approval")
    return RequirementAuthorization(requirement, False)


def tooling_question(
    check: ProgrammaticAcceptance,
    requirement: AcceptanceRequirement,
    *,
    origin: str,
    multiple: bool = False,
) -> MarkdownQuestion:
    suffix = (
        "" if not multiple else f"-{requirement.kind}-{canonicalize_package_name(requirement.name)}"
    )
    mechanism = (
        f"uv add {'--dev ' if requirement.scope == 'test' else ''}{requirement.name}"
        if requirement.kind == "python-package"
        else f"provision executable {requirement.name} outside Drydock"
    )
    return MarkdownQuestion(
        question_id=f"Q-{check.check_id}-tooling{suffix}",
        name=f"Authorize {check.check_id} {requirement.scope} tooling",
        origin=origin,
        severity="blocking",
        status="open",
        question=(
            f"Authorize `{requirement.kind}={requirement.name}` for {requirement.scope} scope. "
            f"Purpose: execute `{check.check_id}` ({check.intent}). Planned installation: "
            f"`{mechanism}`. Affected acceptance criterion: `{check.source}#{check.check_id}`."
        ),
        answer="",
    )


def append_requirement_question(
    blueprint_path: Path,
    check: ProgrammaticAcceptance,
    requirement: AcceptanceRequirement,
    *,
    origin: str,
) -> bool:
    existing = parse_questions(
        blueprint_path.read_text(encoding="utf-8"), source=str(blueprint_path)
    )
    base = tooling_question(check, requirement, origin=origin)
    multiple = any(item.question_id == base.question_id for item in existing)
    return append_question(
        blueprint_path,
        tooling_question(check, requirement, origin=origin, multiple=multiple),
    )


def project_plan_requirement_questions(
    blocks: dict[str, str], *, target_dir: Path, build_dir: Path
) -> tuple[str, ...]:
    """Add deterministic Plan-origin gates for unavailable, unauthorized requirements."""
    added: list[str] = []
    for source, text in tuple(blocks.items()):
        if not source.lower().endswith(".md") or "## Questions" not in text:
            continue
        from drydock.acceptance import parse_programmatic_acceptance_text

        checks = parse_programmatic_acceptance_text(text, source=source)
        questions = list(parse_questions(text, source=source))
        known = {item.question_id for item in questions}
        for check in checks:
            missing = [
                requirement
                for requirement in check.requirements
                if not authorization_for(
                    requirement, target_dir=target_dir, build_dir=build_dir
                ).authorized
            ]
            for requirement in missing:
                question = tooling_question(
                    check, requirement, origin="plan", multiple=len(check.requirements) > 1
                )
                if question.question_id in known:
                    continue
                questions.append(question)
                known.add(question.question_id)
                added.append(f"{source}#{question.question_id}")
        if questions != list(parse_questions(text, source=source)):
            blocks[source] = replace_questions_section(text, tuple(questions))
    return tuple(added)


def discover_missing_requirement(result_stderr: str) -> AcceptanceRequirement | None:
    if match := _MISSING_MODULE_RE.search(result_stderr):
        return AcceptanceRequirement("python-package", match.group(1).split(".", 1)[0], "test")
    if match := _MISSING_EXECUTABLE_RE.search(result_stderr):
        return AcceptanceRequirement("executable", match.group(1), "test")
    return None
