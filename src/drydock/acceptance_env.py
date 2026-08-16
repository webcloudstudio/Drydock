"""Acceptance criteria that invoke a staged asset without the environment it requires.

A staged asset is imported, hash-verified, and restored before grading, so its interface is not
negotiable: an assertion either calls it the way the asset documents or the asset refuses to run.
When it refuses it exits on its own usage code, which is not the verdict the criterion asserts —
``assert result.returncode == 0`` is then false at every level of implementation quality, and no
build can move it. The criterion is unsatisfiable in exactly the sense a criterion that does not
compile is unsatisfiable, and it is detected the same way: by reading the file, never by predicting
whether an expectation is correct.

Detection is deliberately asymmetric. A missed defect costs one build block; a false positive
raises a blocking decision against a sound story, so every signal here requires the asset to say
plainly that it needs the variable, and any call whose environment cannot be read statically is
treated as satisfied.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from drydock.acceptance import MalformedAcceptance, ProgrammaticAcceptance
from drydock.source_roles import BUILD_ASSET_DIR

#: Variables the ambient environment already carries. An asset that names one is describing the
#: shell it runs in, not declaring a parameter its caller must supply.
AMBIENT_ENV_NAMES = frozenset({
    "CI",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "PWD",
    "PYTHONHASHSEED",
    "PYTHONPATH",
    "SHELL",
    "TERM",
    "TMPDIR",
    "USER",
    "VIRTUAL_ENV",
})

_NAME = r"[A-Z][A-Z0-9_]{1,63}"

#: "error: JQ is not set", "TOOL must be set", "RUNNER is required".
_STATED_REQUIRED = re.compile(rf"\b({_NAME})\b\s+(?:is|must)\s+(?:not\s+set|be\s+set|required)")

#: An ``Environment:`` block entry whose description says the variable is required.
_ENV_SECTION = re.compile(r"^\s*Environment:\s*$", re.M)
_ENV_ENTRY = re.compile(rf"^\s+({_NAME})\s{{2,}}(?P<detail>.+)$")

#: A documented invocation that assigns the variable in front of the asset's own command line.
_USAGE_ASSIGNMENT = re.compile(rf"^\s*(?:\$\s*)?({_NAME})=\S*\s+(?P<rest>.+)$", re.M)

#: subprocess entry points whose first positional argument is the command.
_SUBPROCESS_CALLS = frozenset({"run", "call", "check_call", "check_output", "Popen"})

#: Assets large enough that scanning is pointless — a corpus or a manual, never an interface.
_MAX_ASSET_BYTES = 400_000


def read_staged_assets(blueprint_dir: Path) -> dict[str, str]:
    """Return build-relative staged asset paths mapped to their text.

    Imported sources are the immutable copy under ``blueprint/sources/``; the build directory
    holds the same bytes at the same relative path, which is the path a criterion writes. A file
    that is not text is not an interface and is skipped.
    """
    sources = blueprint_dir / BUILD_ASSET_DIR
    if not sources.is_dir():
        return {}
    assets: dict[str, str] = {}
    for path in sorted(sources.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(sources).as_posix()
        assets[f"{BUILD_ASSET_DIR}/{relative}"] = text
    return assets


def required_env_names(asset_text: str, asset_name: str = "") -> frozenset[str]:
    """Return the variables ``asset_text`` declares its caller must supply.

    Three signals, each requiring the asset to state the requirement rather than merely mention
    the name: an explicit "is not set" / "must be set" / "is required" sentence, an ``Environment:``
    entry whose description says required, and a documented usage line that assigns the variable
    in front of a command naming the asset itself. The last qualifier is what keeps a wrapper
    honest: ``full_test.sh`` sets ``JQ`` for the runner it calls, which makes ``JQ`` a requirement
    of the runner and not of the wrapper.
    """
    if len(asset_text) > _MAX_ASSET_BYTES:
        return frozenset()
    names: set[str] = set()
    names.update(match.group(1) for match in _STATED_REQUIRED.finditer(asset_text))

    for section in _ENV_SECTION.finditer(asset_text):
        for line in asset_text[section.end() :].splitlines()[1:]:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            entry = _ENV_ENTRY.match(line)
            if entry and "required" in entry.group("detail").lower():
                names.add(entry.group(1))

    stem = PurePosixPath(asset_name).name
    if stem:
        for match in _USAGE_ASSIGNMENT.finditer(asset_text):
            if stem in match.group("rest"):
                names.add(match.group(1))

    return frozenset(names) - AMBIENT_ENV_NAMES


def _argv_strings(node: ast.AST) -> tuple[str, ...]:
    """Return the literal strings in a command argument, list or bare string alike."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.List | ast.Tuple):
        return tuple(
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    return ()


def _is_subprocess_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in _SUBPROCESS_CALLS
    return isinstance(func, ast.Name) and func.id in _SUBPROCESS_CALLS


def _supplied_names(node: ast.Call) -> frozenset[str] | None:
    """Names the call supplies through ``env=``, or ``None`` when it cannot be read.

    An unreadable environment — a variable, a comprehension, a call — is reported as satisfying
    everything. The alternative is a blocking decision raised on a criterion nobody can see is
    wrong from the source alone.
    """
    for keyword in node.keywords:
        if keyword.arg != "env":
            continue
        if not isinstance(keyword.value, ast.Dict):
            return None
        return frozenset(
            key.value
            for key in keyword.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        )
    return frozenset()


def _environ_assignments(tree: ast.AST) -> frozenset[str]:
    """Names the snippet writes into its own process environment before calling out."""
    names: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                names.add(target.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"setdefault", "update", "putenv"}
        ):
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    names.add(argument.value)
                names.update(
                    key.value
                    for key in getattr(argument, "keys", [])
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
    return frozenset(names)


def _matching_asset(argument: str, assets: Mapping[str, str]) -> str | None:
    """Return the staged asset ``argument`` names, or ``None``.

    Matching is on the build-relative path or its trailing components, because a criterion runs
    from the build directory and writes the path the way the asset is staged.
    """
    candidate = PurePosixPath(argument.strip())
    for relative in assets:
        staged = PurePosixPath(relative)
        if candidate == staged or candidate.name == staged.name:
            return relative
    return None


def missing_env_names(code: str, assets: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Return ``(asset, variable)`` pairs the snippet fails to supply.

    ``assets`` maps a build-relative staged path to that asset's text. Code that does not parse
    is not this pass's defect — ``syntax_defect`` already owns it — so it yields nothing.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()
    preset = _environ_assignments(tree)
    missing: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_subprocess_call(node):
            continue
        if not node.args:
            continue
        supplied = _supplied_names(node)
        if supplied is None:
            continue
        for argument in _argv_strings(node.args[0]):
            relative = _matching_asset(argument, assets)
            if relative is None:
                continue
            for name in sorted(required_env_names(assets[relative], relative)):
                if name in supplied or name in preset or (relative, name) in seen:
                    continue
                seen.add((relative, name))
                missing.append((relative, name))
    return tuple(missing)


def staged_asset_env_defects(
    checks: tuple[ProgrammaticAcceptance, ...],
    assets: Mapping[str, str],
) -> tuple[MalformedAcceptance, ...]:
    """Return every criterion that calls a staged asset without a variable the asset requires."""
    if not assets:
        return ()
    defects: list[MalformedAcceptance] = []
    for check in checks:
        for relative, name in missing_env_names(check.code, assets):
            defects.append(
                MalformedAcceptance(
                    check_id=check.check_id,
                    source=check.source,
                    reason=(
                        f"invokes staged asset {relative} without {name}, which that asset "
                        f"declares required; supply it as env={{**os.environ, {name!r}: ...}}"
                    ),
                )
            )
    return tuple(defects)
