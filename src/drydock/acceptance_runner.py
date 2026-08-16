"""The harness a Programmatic Acceptance criterion is executed through.

A criterion is a short script that acts on the built product and asserts on what it read back.
When the assertion fails, CPython reports the source line and the exception name and nothing
else: ``assert result.returncode != 0`` → ``AssertionError``. The values the criterion actually
observed — the return code that was zero, the payload the command printed — are live in the
failing frame at that instant and are then discarded, so the report restates the assertion
three times and never says what happened.

This module runs the criterion unchanged and, when it raises, prints the operands of the failing
line before the traceback. The criterion file is still the file that executes, so line numbers,
the traceback text, and every downstream classifier that reads them are unaffected.

It is executed as ``<interpreter> acceptance_runner.py <criterion.py>`` and deliberately imports
nothing from Drydock: it runs under the *Target's* interpreter, which has no reason to be able
to import this package.
"""

from __future__ import annotations

import ast
import linecache
import runpy
import sys
import traceback
from types import FrameType, ModuleType

#: Fences around the value block so the reader can lift it out of stderr and present it as its
#: own section rather than as noise in front of a traceback.
VALUES_BEGIN = "--- drydock: values at failure ---"
VALUES_END = "--- drydock: end values ---"
#: A value is quoted to diagnose a failure, not to dump a corpus. A staged suite's captured
#: output can be megabytes; the head of it still identifies what went wrong.
VALUE_REPR_LIMIT = 400
#: Names quoted from one failing line. A line with more operands than this is not a line whose
#: values a reader is going to read.
VALUE_NAME_LIMIT = 8


def _statement_names(path: str, lineno: int) -> list[str]:
    """Names appearing in the statement at ``lineno``, in source order, without duplicates.

    Parsing the whole file and selecting the enclosing statement catches an assertion spread
    across several lines, where reading only ``lineno`` would quote one fragment of it.
    """
    try:
        source = "".join(linecache.getlines(path))
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return []
    best: ast.stmt | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        if node.lineno <= lineno <= end:
            if best is None or node.lineno > best.lineno:
                best = node
    if best is None:
        return []
    names: list[str] = []
    for node in ast.walk(best):
        # Only the base name of an attribute or subscript chain. Re-evaluating
        # ``result.returncode`` here would run arbitrary property code inside a process that has
        # already failed; ``result``'s own repr carries the same fact without executing anything.
        if isinstance(node, ast.Name) and node.id not in names:
            names.append(node.id)
    return names


def _quotable(value: object) -> bool:
    """False for things whose repr says nothing about why the assertion failed."""
    if isinstance(value, ModuleType) or callable(value):
        return False
    return not isinstance(value, type)


def _render(value: object) -> str:
    try:
        text = repr(value)
    except Exception as exc:  # a broken __repr__ is not a reason to lose the whole block
        return f"<unreprable {type(value).__name__}: {exc!r}>"
    text = text.replace("\r\n", "\n")
    if len(text) > VALUE_REPR_LIMIT:
        text = text[:VALUE_REPR_LIMIT] + f"… (+{len(text) - VALUE_REPR_LIMIT} chars)"
    return text


def value_lines(frame: FrameType, lineno: int) -> list[str]:
    """The operands of the failing line, rendered one per entry."""
    lines: list[str] = []
    for name in _statement_names(frame.f_code.co_filename, lineno):
        if name in frame.f_locals:
            value = frame.f_locals[name]
        elif name in frame.f_globals:
            value = frame.f_globals[name]
        else:
            continue
        if not _quotable(value):
            continue
        rendered = _render(value).replace("\n", "\n    ")
        lines.append(f"  {name} = {rendered}")
        if len(lines) >= VALUE_NAME_LIMIT:
            break
    return lines


def _criterion_traceback(exc: BaseException, path: str):
    """The traceback with this harness's own frames removed.

    A reader diagnosing a product defect must not be shown ``runpy`` internals, and the
    classifiers that decide whether a criterion was malformed read the same text.
    """
    tb = exc.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename != path:
        tb = tb.tb_next
    return tb


def main(argv: list[str]) -> int:
    path = argv[1]
    sys.argv = argv[1:]
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    except BaseException as exc:  # noqa: BLE001 — the criterion's failure is the product's news
        tb = _criterion_traceback(exc, path)
        deepest = tb
        while deepest is not None and deepest.tb_next is not None:
            deepest = deepest.tb_next
        if deepest is not None:
            lines = value_lines(deepest.tb_frame, deepest.tb_lineno)
            if lines:
                print(VALUES_BEGIN, file=sys.stderr)
                for line in lines:
                    print(line, file=sys.stderr)
                print(VALUES_END, file=sys.stderr)
        traceback.print_exception(type(exc), exc, tb or exc.__traceback__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
