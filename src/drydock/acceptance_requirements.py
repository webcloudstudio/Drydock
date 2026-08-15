"""Acceptance-tool declarations, Commander authorization, and question projection."""

from __future__ import annotations

import ast
import importlib.metadata
import re
import shutil
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from drydock.acceptance import AcceptanceRequirement, ProgrammaticAcceptance
from drydock.decisions import Decision, load_decisions, write_decisions
from drydock.dependency_gate import canonicalize_package_name
from drydock.target_environment import resolve_target_environment

_MISSING_MODULE_RE = re.compile(
    r"(?:ModuleNotFoundError|ImportError): No module named ['\"]([^'\"]+)"
)
# The capture stays on the failing line. Without the newline exclusion a project-local
# executable — which contains a path separator and so cannot match — makes the engine
# backtrack past its own quotes and swallow the following traceback as a tool name.
_MISSING_EXECUTABLE_RE = re.compile(r"FileNotFoundError: .*?['\"]([^/'\"\n]+)['\"]")
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


@cache
def _distribution_map() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return installed import-to-distribution metadata once per process."""
    try:
        distributions = importlib.metadata.packages_distributions()
    except Exception:  # pragma: no cover - damaged host metadata
        return ()
    return tuple(sorted((name, tuple(packages)) for name, packages in distributions.items()))


def _distribution_imports() -> frozenset[str]:
    return frozenset(name for name, _packages in _distribution_map())


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
            # No baseline exemption list. Nothing here blocks, so there is nothing to exempt
            # from: reporting that a check shells out to ``sh`` is accurate and harmless, and
            # a frozenset someone must edit and re-release to unblock a build is exactly the
            # mechanism this stopped being.
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
    distributions = dict(_distribution_map())
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


def recommend_external_declarations(checks: tuple[ProgrammaticAcceptance, ...]) -> tuple[str, ...]:
    """Return advisory notes about external tooling a check uses without declaring.

    This replaces a gate that conflated two questions and only ever asked the harmless one. A
    tool that is present and undeclared costs nothing at run time: the check works. The
    declaration is still worth having — it belongs in Rigging or ``TECHNOLOGY_STACK.md``, where
    the Commander states it once for the whole project rather than per check — so the absence is
    reported as a recommendation and never stops planning.

    The authoring rule that makes this a rarity: an acceptance check is written in the project's
    own language and uses that language's libraries. Reaching for an external executable is the
    exception, and it belongs in Rigging when it is genuinely needed.
    """
    return tuple(
        f"{check.source} [{check.check_id}] uses undeclared {kind}={name}; "
        f"consider declaring it in Rigging or TECHNOLOGY_STACK.md"
        for check in checks
        for kind, name in undeclared_external_usage(check)
    )


def _manifest_packages(build_dir: Path) -> frozenset[str]:
    path = build_dir / "pyproject.toml"
    if not path.is_file():
        return frozenset()
    stat = path.stat()
    return _manifest_packages_file(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


@cache
def _manifest_packages_file(path: str, _mtime_ns: int, _size: int) -> frozenset[str]:
    try:
        doc = tomllib.loads(Path(path).read_text(encoding="utf-8"))
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


@cache
def _target_python_packages(build_dir: str) -> frozenset[str]:
    venv = Path(build_dir) / ".venv"
    candidates = [*venv.glob("lib/python*/site-packages"), venv / "Lib" / "site-packages"]
    names = []
    found_target_environment = False
    for root in candidates:
        if not root.is_dir():
            continue
        found_target_environment = True
        for distribution in importlib.metadata.distributions(path=[str(root)]):
            name = distribution.metadata.get("Name", "")
            if name:
                names.append(canonicalize_package_name(name))
    if not found_target_environment:
        environment = resolve_target_environment(Path(build_dir))
        if environment.interpreter is not None:
            for distribution in importlib.metadata.distributions():
                name = distribution.metadata.get("Name", "")
                if name:
                    names.append(canonicalize_package_name(name))
    return frozenset(names)


def invalidate_target_environment_inventory() -> None:
    """Discard Target package inventories after environment provisioning."""
    _target_python_packages.cache_clear()


def requirement_available(requirement: AcceptanceRequirement, build_dir: Path) -> bool:
    if requirement.kind == "executable":
        return shutil.which(requirement.name) is not None
    environment = resolve_target_environment(build_dir)
    if environment.interpreter is None:
        return False
    wanted = canonicalize_package_name(requirement.name)
    return wanted in _target_python_packages(str(build_dir.resolve()))


@cache
def _technology_stack_text(path: str, _mtime_ns: int, _size: int) -> str:
    return Path(path).read_text(encoding="utf-8").lower()


def _technology_stack_contains(path: Path, value: str) -> bool:
    stat = path.stat()
    return value.lower() in _technology_stack_text(
        str(path.resolve()), stat.st_mtime_ns, stat.st_size
    )


def _decision_authorizes(requirement: AcceptanceRequirement, decision: Decision) -> bool:
    answer = decision.answer.lower()
    if not any(word in answer for word in ("approve", "authorize", "allowed", "permit")):
        return False
    if "all test harness" in answer and requirement.scope == "test":
        return True
    corpus = f"{decision.title} {decision.description} {decision.answer}".lower()
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
    if stack.is_file() and _technology_stack_contains(stack, requirement.name):
        return RequirementAuthorization(requirement, True, "Commander technology stack")
    for decision in load_decisions(target_dir / "DECISIONS.json"):
        if not decision.archived and _decision_authorizes(requirement, decision):
            return RequirementAuthorization(
                requirement, True, f"Commander decision {decision.id}", decision.answer
            )
    if current_manifest_approved:
        return RequirementAuthorization(requirement, True, "current Manifest approval")
    return RequirementAuthorization(requirement, False)


def tooling_decision(
    check: ProgrammaticAcceptance,
    requirement: AcceptanceRequirement,
    *,
    origin: str,
    multiple: bool = False,
) -> Decision:
    suffix = (
        "" if not multiple else f"-{requirement.kind}-{canonicalize_package_name(requirement.name)}"
    )
    mechanism = (
        f"uv add {'--dev ' if requirement.scope == 'test' else ''}{requirement.name}"
        if requirement.kind == "python-package"
        else f"provision executable {requirement.name} outside Drydock"
    )
    return Decision(
        id=f"acceptance-{check.check_id}-tooling{suffix}",
        type="text",
        severity="blocking",
        origin=origin,
        blueprint=check.source,
        story=None,
        status="open",
        archived=False,
        title=f"Authorize {check.check_id} {requirement.scope} tooling",
        description=(
            f"Authorize {requirement.kind}={requirement.name} for {requirement.scope} scope. "
            f"Planned installation: {mechanism}. Affected acceptance check: "
            f"{check.source}#{check.check_id} ({check.intent})."
        ),
        options=(),
        system_choice="not authorized",
    )


def project_plan_requirement_decisions(
    blocks: dict[str, str], *, target_dir: Path, build_dir: Path
) -> tuple[Decision, ...]:
    """Return deterministic blocking decisions for unavailable tooling."""
    added: list[Decision] = []
    for source, text in tuple(blocks.items()):
        if not source.lower().endswith(".md"):
            continue
        from drydock.acceptance import parse_programmatic_acceptance_text

        checks = parse_programmatic_acceptance_text(text, source=source)
        for check in checks:
            missing = [
                requirement
                for requirement in check.requirements
                if not authorization_for(
                    requirement, target_dir=target_dir, build_dir=build_dir
                ).authorized
            ]
            for requirement in missing:
                decision = tooling_decision(
                    check, requirement, origin="plan", multiple=len(check.requirements) > 1
                )
                added.append(decision)
    return tuple(added)


def project_plan_requirement_questions(
    blocks: dict[str, str], *, target_dir: Path, build_dir: Path
) -> tuple[str, ...]:
    """Compatibility shim; acceptance authorization is persisted as decisions."""
    return tuple(
        item.id
        for item in project_plan_requirement_decisions(
            blocks, target_dir=target_dir, build_dir=build_dir
        )
    )


def record_requirement_decision(
    target_dir: Path,
    check: ProgrammaticAcceptance,
    requirement: AcceptanceRequirement,
    *,
    origin: str = "build",
    story: str | None = None,
) -> Decision:
    """Persist one unanswered acceptance authorization in DECISIONS.json."""
    item = tooling_decision(check, requirement, origin=origin)
    if story:
        item = Decision(**{**item.__dict__, "story": story})
    path = target_dir / "DECISIONS.json"
    prior = {record.id: record for record in load_decisions(path)}
    prior[item.id] = (
        item if item.id not in prior or not prior[item.id].is_human_authored else prior[item.id]
    )
    write_decisions(path, tuple(sorted(prior.values(), key=lambda record: record.id)))
    return prior[item.id]


def discover_missing_requirement(result_stderr: str) -> AcceptanceRequirement | None:
    if match := _MISSING_MODULE_RE.search(result_stderr):
        return AcceptanceRequirement("python-package", match.group(1).split(".", 1)[0], "test")
    if match := _MISSING_EXECUTABLE_RE.search(result_stderr):
        candidate = match.group(1)
        # Same rule ``visible_external_usage`` applies to declared commands: a path is the
        # artifact under construction, not external tooling somebody must authorize. A
        # pre-build acceptance observation is expected to miss ``./program``.
        if candidate.split() == [candidate] and not candidate.startswith((".", "/")):
            return AcceptanceRequirement("executable", candidate, "test")
    return None
