"""Compare a criterion's expected exit status with the staged harness's expectation.

The failure this exists for. LayersTesting ``20261020.183046``: three criteria asserted
``cli_runner("load", "categories", "sources/seed_categories.csv")[0] == 1`` while the user's own
``sources/run.sh`` line ``check B2 0 load categories "$SEED/seed_categories.csv"`` expects ``0``.
All three agreed with each other, so no comparison inside the plan could see it. A correct loader
failed them on every build.

Deterministic and conservative. A harness line is read only when, after shell tokenization, an
integer token is followed by exactly the criterion's arguments (optionally after one program
token), with file arguments compared by name. A harness written in any other shape yields
nothing and is never misread.

Only a call that passes a staged source file is compared, because its outcome is fixed by that
file. A call addressing state is not: the LayersTesting harness expects ``txn delete 1`` to exit
``3`` because, at that point in its sequence, the delete would leave a negative balance, while a
criterion deleting its own fresh transaction correctly expects ``0`` (run ``20261020.191708``).
Only the first call of each command in a criterion is compared, and only when no harness line
expects the criterion's value: a second load of the same file is a duplicate.
"""

from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

#: The CLI test helper the ``cli`` stack publishes (``Rigging/stack/cli.md``).
RUNNER_NAME = "cli_runner"

#: A token that ends the command and starts a redirection, pipe, or list operator.
_OPERATOR = re.compile(r"^(\d*[<>]|[|&;])")


@dataclass(frozen=True)
class HarnessExpectation:
    """One staged harness line: the arguments it runs and the exit it expects."""

    argv: tuple[str, ...]
    exit_code: int
    source: str
    line: int


@dataclass(frozen=True)
class Harness:
    """The staged harness lines and the names of the staged files they may load."""

    expectations: tuple[HarnessExpectation, ...]
    staged_files: frozenset[str]


@dataclass(frozen=True)
class CriterionCall:
    """One ``cli_runner(<literals>)[0] == <int>`` assertion in a criterion."""

    argv: tuple[str, ...]
    exit_code: int
    line: int


def _normalized(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Compare a path argument by file name: ``$SEED/x.csv`` and ``sources/x.csv`` are one file."""
    return tuple(PurePosixPath(arg).name if "/" in arg else arg for arg in argv)


def _line_tokens(line: str) -> list[str]:
    try:
        tokens = shlex.split(line, comments=True)
    except ValueError:
        return []
    for index, token in enumerate(tokens):
        if _OPERATOR.match(token):
            return tokens[:index]
    return tokens


def load_harness(sources_dir: Path) -> Harness:
    """Every ``<int> <args...>`` line in the staged shell harnesses under ``sources_dir``.

    Each candidate keeps every integer position, because the arguments are not known until a
    criterion asks; :func:`contradictions` matches them exactly.
    """
    found: list[HarnessExpectation] = []
    if not sources_dir.is_dir():
        return Harness((), frozenset())
    staged = frozenset(path.name for path in sources_dir.rglob("*") if path.is_file())
    for path in sorted(sources_dir.rglob("*.sh")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        name = path.relative_to(sources_dir).as_posix()
        for number, line in enumerate(text.splitlines(), 1):
            tokens = _line_tokens(line)
            for index, token in enumerate(tokens[:-1]):
                if token.isdigit() and int(token) <= 255:
                    found.append(
                        HarnessExpectation(tuple(tokens[index + 1 :]), int(token), name, number)
                    )
    return Harness(tuple(found), staged)


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Top-level ``name = "literal"`` bindings, so ``cli_runner("account", "add", account)`` reads."""
    bound: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            bound[node.targets[0].id] = node.value.value
    return bound


def _runner_call(node: ast.expr) -> ast.Call | None:
    """``cli_runner(...)[0]``, or ``None``."""
    if not (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == 0
        and isinstance(node.value, ast.Call)
    ):
        return None
    func = node.value.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return node.value if name == RUNNER_NAME else None


def criterion_calls(code: str) -> list[CriterionCall]:
    """Every ``cli_runner(<literal args>)[0] == <int>`` in source order; anything else is skipped."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    bound = _string_constants(tree)
    calls: list[CriterionCall] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and isinstance(node.comparators[0], ast.Constant)
            and type(node.comparators[0].value) is int
        ):
            continue
        call = _runner_call(node.left)
        if call is None or call.keywords:
            continue
        argv: list[str] = []
        for arg in call.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                argv.append(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in bound:
                argv.append(bound[arg.id])
            else:
                break
        else:
            calls.append(CriterionCall(tuple(argv), node.comparators[0].value, node.lineno))
    return sorted(calls, key=lambda call: call.line)


def contradictions(code: str, harness: Harness) -> list[tuple[CriterionCall, HarnessExpectation]]:
    """The first call of each file-loading command whose exit no matching harness line expects."""
    if not harness.expectations:
        return []
    found: list[tuple[CriterionCall, HarnessExpectation]] = []
    seen: set[tuple[str, ...]] = set()
    for call in criterion_calls(code):
        key = _normalized(call.argv)
        if not harness.staged_files & set(key) or key in seen:
            continue
        seen.add(key)
        matches = [
            expectation
            for expectation in harness.expectations
            if key in {_normalized(expectation.argv), _normalized(expectation.argv[1:])}
        ]
        if matches and all(match.exit_code != call.exit_code for match in matches):
            found.append((call, matches[0]))
    return found


__all__ = [
    "CriterionCall",
    "Harness",
    "HarnessExpectation",
    "contradictions",
    "criterion_calls",
    "load_harness",
]
