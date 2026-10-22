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
import csv
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

#: The CLI test helper the ``cli`` stack publishes (``Rigging/stack/cli.md``) and the Go
#: acceptance helper ships (``Rigging/languages/go/acceptance/drydock_go.py``).
RUNNER_NAME = "cli_runner"

#: ``go run <pkg>`` as a shell string; a pinned tool (``go run tool@v1``) is not the application.
_GO_RUN_TEXT = re.compile(r"^\s*go\s+run\s+(?:-\S+\s+)*(?P<target>\S+)")

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
    #: The key (first) column of each staged CSV's data rows, by file name.
    staged_values: dict[str, frozenset[str]] = field(default_factory=dict)


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
    values = {path.name: _csv_values(path) for path in sorted(sources_dir.rglob("*.csv"))}
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
    return Harness(tuple(found), staged, {name: v for name, v in values.items() if v})


def _csv_values(path: Path) -> frozenset[str]:
    """Each data row's key (first column) when it names something: amounts and dates do not."""
    try:
        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    except (OSError, UnicodeDecodeError, csv.Error):
        return frozenset()
    return frozenset(row[0] for row in rows[1:] if row and any(char.isalpha() for char in row[0]))


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


def _is_runner(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)) == RUNNER_NAME


def _statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """Statements in source order, descending into ``with``/``for``/``if``/``try`` bodies."""
    flat: list[ast.stmt] = []
    for node in body:
        flat.append(node)
        for name in ("body", "orelse", "finalbody"):
            flat.extend(_statements(getattr(node, name, []) or []))
        for handler in getattr(node, "handlers", []) or []:
            flat.extend(_statements(handler.body))
    return flat


def _exit_name(target: ast.expr) -> str | None:
    """The name a ``cli_runner`` result's exit status is bound to, or ``None`` when discarded."""
    if isinstance(target, ast.Name):
        return None if target.id == "_" else target.id
    if isinstance(target, ast.Tuple) and target.elts and isinstance(target.elts[0], ast.Name):
        return None if target.elts[0].id == "_" else target.elts[0].id
    return None


@dataclass(frozen=True)
class _CheckedCall:
    """One ``cli_runner`` call, and the exit status an ``assert`` holds it to, if any."""

    call: ast.Call
    checked: bool
    exit_code: int | None


def _asserted_exit(test: ast.expr, name: str | None, call: ast.Call | None) -> int | None:
    """The integer an ``assert`` compares the exit status to: ``code == 3`` or ``cli_runner()[0] == 3``."""
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and isinstance(test.comparators[0], ast.Constant)
        and type(test.comparators[0].value) is int
    ):
        return None
    left = test.left
    if name is not None and isinstance(left, ast.Name) and left.id == name:
        return test.comparators[0].value
    if call is not None and _runner_call(left) is call:
        return test.comparators[0].value
    return None


def _checked_calls(tree: ast.Module) -> list[_CheckedCall]:
    """Every ``cli_runner`` call in source order, with whether an ``assert`` reads its exit.

    A call is checked when it sits inside an ``assert``, or when its result is bound and the name
    holding the exit status is read by an ``assert`` before it is rebound.
    """
    results: list[_CheckedCall] = []
    pending: dict[str, ast.Call] = {}
    for node in _statements(tree.body):
        if isinstance(node, ast.Assert):
            read = {name.id for name in ast.walk(node.test) if isinstance(name, ast.Name)}
            for name in sorted(read & pending.keys()):
                call = pending.pop(name)
                results.append(_CheckedCall(call, True, _asserted_exit(node.test, name, None)))
            for call in (call for call in ast.walk(node.test) if _is_runner(call)):
                results.append(_CheckedCall(call, True, _asserted_exit(node.test, None, call)))
            continue
        if isinstance(node, (ast.With, ast.For, ast.AsyncWith, ast.AsyncFor)):
            # Only the header belongs to this statement; the body is visited in turn.
            header = [*getattr(node, "items", []), getattr(node, "iter", None)]
            calls = [c for item in header if item is not None for c in ast.walk(item)]
        elif isinstance(node, (ast.If, ast.While, ast.Try)):
            calls = []
        else:
            calls = list(ast.walk(node))
        calls = [call for call in calls if _is_runner(call)]
        if not calls:
            continue
        name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and len(calls) == 1:
            if _is_runner(node.value):
                name = _exit_name(node.targets[0])
        if name is None:
            results.extend(_CheckedCall(call, False, None) for call in calls)
            continue
        if name in pending:
            results.append(_CheckedCall(pending.pop(name), False, None))
        pending[name] = calls[0]
    results.extend(_CheckedCall(call, False, None) for call in pending.values())
    return sorted(results, key=lambda item: (item.call.lineno, item.call.col_offset))


def unchecked_calls(code: str) -> list[int]:
    """Lines of ``cli_runner`` calls whose exit status no ``assert`` reads.

    LayersTesting ``20261021.195808``: two unasserted setup calls failed silently, and the
    criterion went on to test an account that did not exist.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return sorted({item.call.lineno for item in _checked_calls(tree) if not item.checked})


def go_run_calls(code: str) -> list[int]:
    """Lines that launch the application through ``go run``.

    CsvStat ``20261022.203215``: criteria ran ``["go", "run", "./cmd/csvstat", ...]`` and asserted
    usage exit ``2``. ``go run`` reports every non-zero program exit as ``1``, so a correct parser
    failed them on every build, and an asserted exit ``1`` passed whatever the program did.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            words = [
                item.value
                for item in node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if words[:2] == ["go", "run"]:
                targets = [word for word in words[2:] if not word.startswith("-")]
                if not targets or "@" not in targets[0]:
                    lines.add(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (match := _GO_RUN_TEXT.match(node.value)) and "@" not in match["target"]:
                lines.add(node.lineno)
    return sorted(lines)


def unloaded_staged_values(code: str, harness: Harness) -> list[tuple[str, str]]:
    """``(key, file)`` for a staged record a criterion expects a refusal about but never loads.

    LayersTesting ``20261021.195808``: ``account delete DRAWER1`` asserted exit 3 (in use), but
    ``DRAWER1`` exists only in ``sources/seed_accounts.csv``, which the criterion never loads; the
    product correctly answered 4 (absent). Only a staged key column counts, and only when the
    first call addressing it expects a non-zero exit: a criterion that creates a key itself
    expects success, and a deliberately absent key is in no key column.
    """
    if not harness.staged_values:
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    bound = _string_constants(tree)
    constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    named = {file for file in harness.staged_values if any(file in text for text in constants)}
    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    for item in _checked_calls(tree):
        for arg in item.call.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                value = arg.value
            elif isinstance(arg, ast.Name) and arg.id in bound:
                value = bound[arg.id]
            else:
                continue
            if value in seen:
                continue
            seen.add(value)
            sources = sorted(f for f, keys in harness.staged_values.items() if value in keys)
            if sources and not named & set(sources) and item.exit_code not in (None, 0):
                found.append((value, sources[0]))
    return found


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
    "unchecked_calls",
    "unloaded_staged_values",
]
