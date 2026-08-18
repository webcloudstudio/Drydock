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
import re
import runpy
import sys
import traceback
from types import FrameType, ModuleType

#: Fences around the value block so the reader can lift it out of stderr and present it as its
#: own section rather than as noise in front of a traceback.
VALUES_BEGIN = "--- drydock: values at failure ---"
VALUES_END = "--- drydock: end values ---"
#: Fences around the machine-readable tally a harness-style criterion implies but does not print.
#: A criterion that drives a suite answers one yes/no question, so a run that fixes a hundred
#: cases and a run that fixes none report the same failure. The count that separates them is
#: sitting in the failing frame — in the parsed report, or in the output the criterion captured
#: — and is discarded with the frame unless it is lifted out here.
PROGRESS_BEGIN = "--- drydock: progress ---"
PROGRESS_END = "--- drydock: end progress ---"
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


#: Words a suite uses for each outcome, normalised to letters only. A harness names its buckets
#: in one of a handful of dialects; recognising the dialect is the whole trick, because the
#: numbers themselves are always plain integers.
_OUTCOME_WORDS: dict[str, tuple[str, ...]] = {
    "pass": ("pass", "passed", "passes", "passing", "ok", "success", "successes", "succeeded"),
    "fail": ("fail", "failed", "failures", "failure", "failing", "bad"),
    "error": ("error", "errors", "errored", "exception", "exceptions"),
    "skip": ("skip", "skipped", "skips", "skipping", "ignored", "xfail", "xfailed"),
}
_WORD_OUTCOME = {word: outcome for outcome, words in _OUTCOME_WORDS.items() for word in words}
#: Explicit population, when the harness states one instead of leaving it to be summed.
_TOTAL_WORDS = frozenset({"total", "totals", "count", "cases", "tests", "checks", "ran"})
#: ``22 passed`` / ``pass=22`` / ``"fail": 159`` — the three shapes a printed tally takes.
_TALLY_TOKEN_RE = re.compile(
    r"(?P<n1>\d+)\s+(?P<w1>[A-Za-z]+)|(?P<w2>[A-Za-z_]+)\s*[:=]\s*\"?(?P<n2>\d+)"
)
#: How much of a captured stream to scan. A suite prints its tally last, and a corpus dump in
#: front of it can be megabytes.
_TALLY_SCAN_TAIL = 20_000
#: How deep to look inside a parsed report for its summary. ``report["summary"]["pass"]`` is two.
_TALLY_MAX_DEPTH = 4


def _outcome_counts(pairs: list[tuple[str, int]]) -> dict[str, int] | None:
    """Fold ``(word, number)`` observations into a tally, or ``None`` when they are not one.

    A tally has to name a pass bucket and at least one way of not passing. One number beside the
    word ``ok`` is a log line, not a measurement, and inventing a total from it would report
    progress that was never measured.
    """
    counts: dict[str, int] = {}
    total: int | None = None
    for word, number in pairs:
        if (outcome := _WORD_OUTCOME.get(word)) is not None:
            counts.setdefault(outcome, number)
        elif word in _TOTAL_WORDS and total is None:
            total = number
    if "pass" not in counts or not ({"fail", "error"} & counts.keys()):
        return None
    summed = sum(counts.values())
    # Skipped cases stay in the population. A case that moves from skipped to passing must not
    # change the denominator, or the comparison between two attempts is refused as incomparable.
    counts["total"] = total if total is not None and total >= summed else summed
    return counts


def _dict_tally(value: object) -> dict[str, int] | None:
    """Read a tally out of a mapping such as ``{"pass": 123, "fail": 159}``."""
    if not isinstance(value, dict):
        return None
    pairs: list[tuple[str, int]] = []
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, int) or isinstance(item, bool):
            continue
        if item < 0:
            continue
        pairs.append(("".join(ch for ch in key if ch.isalpha()).lower(), item))
    return _outcome_counts(pairs)


def _text_tally(value: object) -> dict[str, int] | None:
    """Read a tally out of printed output such as ``22 passed, 260 failed``."""
    if not isinstance(value, str | bytes):
        return None
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    pairs = [
        (
            (match.group("w1") or match.group("w2")).strip("_").lower(),
            int(match.group("n1") or match.group("n2")),
        )
        for match in _TALLY_TOKEN_RE.finditer(text[-_TALLY_SCAN_TAIL:])
    ]
    return _outcome_counts(pairs)


def _values_to_search(frame: FrameType) -> list[tuple[str, object]]:
    """Frame locals first, then the globals the criterion bound itself."""
    named = list(frame.f_locals.items())
    seen = {name for name, _ in named}
    named += [
        (name, value)
        for name, value in frame.f_globals.items()
        if name not in seen and not name.startswith("__")
    ]
    return named


def _reachable(frame: FrameType) -> list[tuple[str, object]]:
    """Every value the criterion holds, breadth first, named by the path that reaches it.

    Only mappings and plain instance attributes are followed. A property is never read: this
    runs inside a process that has already failed, and re-entering the product's own code to
    fetch a number would risk a second failure on top of the one being reported.
    """
    pending = [(name, value, 0) for name, value in _values_to_search(frame)]
    found: list[tuple[str, object]] = []
    while pending:
        path, current, depth = pending.pop(0)
        found.append((path, current))
        if depth >= _TALLY_MAX_DEPTH or isinstance(current, str | bytes):
            continue
        if isinstance(current, dict):
            children = [(key, item) for key, item in current.items() if isinstance(key, str)]
        else:
            children = list(getattr(current, "__dict__", {}).items())
        pending += [(f"{path}.{key}", item, depth + 1) for key, item in children]
    return found


def tally_lines(frame: FrameType) -> list[str]:
    """The first tally discoverable in the failing frame, rendered for a machine to read.

    Structured values are searched before captured text: a parsed report states what the harness
    counted, whereas its printed output only describes it, and a corpus dump quotes both. The
    search stops at the first tally so the block names one measurement and the reading stays
    stable between attempts.
    """
    reachable = _reachable(frame)
    for read in (_dict_tally, _text_tally):
        for path, value in reachable:
            if (tally := read(value)) is not None:
                return [_render_tally(path, tally)]
    return []


def _render_tally(source: str, tally: dict[str, int]) -> str:
    counts = " ".join(
        f"{outcome}={tally[outcome]}"
        for outcome in ("pass", "fail", "error", "skip", "total")
        if outcome in tally
    )
    return f"cases: {counts} from={source}"


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
            for begin, lines, end in (
                (PROGRESS_BEGIN, tally_lines(deepest.tb_frame), PROGRESS_END),
                (VALUES_BEGIN, value_lines(deepest.tb_frame, deepest.tb_lineno), VALUES_END),
            ):
                if not lines:
                    continue
                print(begin, file=sys.stderr)
                for line in lines:
                    print(line, file=sys.stderr)
                print(end, file=sys.stderr)
        traceback.print_exception(type(exc), exc, tb or exc.__traceback__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
