"""Blueprint-owned acceptance assertions for build verification."""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import os
import re
import shutil
import signal
import subprocess
import symtable
import sys
import tempfile
import tokenize
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path, PurePosixPath

from drydock.acceptance_protocol import (
    PROGRESS_BEGIN,
    PROGRESS_END,
    VALUES_BEGIN,
    VALUES_END,
)
from drydock.acceptance_taxonomy import load_acceptance_failure_taxonomy
from drydock.build_plan import BuildPlan, PlanBlock
from drydock.child_sandbox import child_limits, kill_process_group
from drydock.config import get_sandbox_mem_limit_mb
from drydock.paths import get_language_dir
from drydock.proof_integrity import analyze_proof
from drydock.target_environment import resolve_target_environment

SECTION_RE = re.compile(r"^## (?P<name>[^\n]+)\n", re.MULTILINE)
PYTHON_FENCE_RE = re.compile(r"```python\s*\n(?P<code>.*?)\n```", re.DOTALL)
HEADING_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$", re.MULTILINE)
REQUIRES_RE = re.compile(r"^Requires:\s*(?P<value>.+?)\s*$", re.MULTILINE | re.IGNORECASE)
#: The authored acceptance-criterion container. Every boundary is explicit: the id lives in the
#: delimiter rather than being slugified from a nearby heading, and the body runs verbatim to a
#: matching end marker. Nothing the criterion contains — a Markdown fence, a ``##`` line, a
#: ``Requires:`` line inside a string — can move a boundary, because no boundary is inferred.
#: Markup-processing targets make fence-bearing criteria ordinary rather than exotic.
AC_OPEN_RE = re.compile(r"^===[ \t]+AC[ \t]+(?P<id>[^\n=]+?)[ \t]*===[ \t]*$", re.MULTILINE)
AC_END_RE = re.compile(r"^===[ \t]+END[ \t]+AC[ \t]+(?P<id>[^\n=]+?)[ \t]*===[ \t]*$", re.MULTILINE)
#: An end marker the model wrote without its id (``=== END AC`` or ``=== END AC ===``). It closes
#: whichever criterion is open; it is never a valid terminator as written.
AC_BARE_END_RE = re.compile(r"^===[ \t]+END[ \t]+AC[ \t]*(?:===)?[ \t]*$", re.MULTILINE)
#: Leading ``Key: value`` metadata lines inside an AC block, terminated by the first blank line.
AC_META_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9 _-]*):[ \t]*(?P<value>.*?)[ \t]*$")


@contextlib.contextmanager
def captured_syntax_warnings() -> Iterator[list[warnings.WarningMessage]]:
    """Capture compile-time warnings from criterion text instead of printing them.

    A criterion is authored text that Drydock compiles on the operator's behalf, so a warning
    about it is Drydock's to report against the named criterion — not a bare
    ``<acceptance>:5: SyntaxWarning`` on stderr with nothing to attribute it to. The one that
    occurs in practice is a bare ``\\(`` in a non-raw string, which a jq or regex target writes
    constantly. Compile-time syntax warnings use a NULL registry, so they re-emit on every parse
    rather than deduplicating: left unfiltered one criterion produces one warning line per
    parsing pass, per plan attempt.

    The block wraps a single compile call, so nothing else can warn inside it. This path is
    single-threaded; ``catch_warnings`` mutates global filter state and must not be used where
    it is not.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SyntaxWarning)
        yield caught


TIMEOUT_SECONDS = 120
# A suite-bound check runs a complete conformance suite; a story timeout would kill it.
SUITE_TIMEOUT_SECONDS = 900
# The three outcomes an assertion can have. Only FAIL is evidence about the product: it means
# the check reached the code under test and the oracle was violated. UNVERIFIED means the check
# never got there — a missing path, a permission, an absent declared tool, a defective snippet.
# That is evidence about the kit, so it is counted separately, reported loudly, and never
# charged against the build.
OUTCOME_PASS = "PASS"
OUTCOME_FAIL = "FAIL"
OUTCOME_UNVERIFIED = "UNVERIFIED"
# A criterion that ran, reached the code under test, and missed its expectation — but whose
# expectation is one the author re-typed by hand rather than derived, so the miss is as likely to
# be the criterion's fault as the product's. Reported in full and never charged against the build.
OUTCOME_DISPUTED = "DISPUTED"
OUTCOMES = (OUTCOME_PASS, OUTCOME_FAIL, OUTCOME_UNVERIFIED, OUTCOME_DISPUTED)

# Category prefixes for a check that failed by exhausting a resource rather than by missing
# an expectation. Consumers use these to gate a repair pass on the resource fact.
MEMORY_FAILURE_PREFIX = "exhausted memory"
TIMEOUT_FAILURE_PREFIX = "timed out"
SKIPPED_FAILURE_PREFIX = "skipped acceptance"
UNVERIFIED_FAILURE_PREFIX = "unverified acceptance"
# A check that died inside its own snippet rather than inside the code under test. No
# implementation can turn it green, so a repair pass on it is wasted.
MALFORMED_FAILURE_PREFIX = "malformed check"
# A criterion whose verdict changed between two runs on an unchanged build tree. It disagrees
# with itself, so neither verdict is evidence about the product and no repair pass can settle it.
FLAKY_FAILURE_PREFIX = "flaky check"
# A criterion not run because its recorded status says it cannot measure the product.
EXCLUDED_FAILURE_PREFIX = "excluded check"

# A criterion importing a foundation package the build directory does not contain. The application
# it exercises is not built, so it is not run: the verdict is FAIL, stated in one line instead of a
# traceback from inside the application's own test machinery. Deliberately absent from
# TERMINAL_FAILURE_PREFIXES — building the package is exactly the work a build pass does.
UNBUILT_FOUNDATION_FAILURE_PREFIX = "foundation not built"

#: Every failure prefix that names a fault in the check rather than in the code under test. A
#: repair pass rewrites the implementation, never the criterion or the machine it runs on, so no
#: number of further passes can move any of these: each is a stop condition, and the repair loop
#: must not spend budget on it.
#:
#: The complement is deliberately small. A failure carrying *no* prefix is the only repairable
#: class: the check reached the code under test and the oracle was violated, which is exactly what
#: another informed pass can fix. Classification lives here, beside the prefixes it names, so a new
#: category cannot be added without deciding what the loop does with it.
TERMINAL_FAILURE_PREFIXES = (
    MEMORY_FAILURE_PREFIX,
    TIMEOUT_FAILURE_PREFIX,
    SKIPPED_FAILURE_PREFIX,
    UNVERIFIED_FAILURE_PREFIX,
    MALFORMED_FAILURE_PREFIX,
    FLAKY_FAILURE_PREFIX,
    EXCLUDED_FAILURE_PREFIX,
)


def is_terminal_check_failure(error: str | None) -> bool:
    """True when a failed check names a kit fault that no repair pass can turn green."""
    return bool(error) and error.startswith(TERMINAL_FAILURE_PREFIXES)


#: Enough of a runner's summary to show its tally without pasting a whole suite log. A check
#: prints its own account of what it observed before asserting, and that account is the reason
#: the assertion failed; a bounded tail carries it without turning a report into a log dump.
OBSERVED_OUTPUT_LINES = 12
#: Enough of the check's own stderr to carry the traceback that produced the verdict. The
#: summary line names the assertion; this names where it lives and what led to it, which is the
#: difference between "AssertionError" and a defect an operator can act on.
DIAGNOSTIC_OUTPUT_LINES = 20
#: How much of the criterion's own source a failure report quotes. A criterion is a short script,
#: so the whole of it is usually the right answer: the reader is being asked why an assertion
#: failed, and the assertion is one line of a program whose earlier lines built the values it
#: tested. Longer criteria are windowed around the failing line instead of dumped.
CODE_EXCERPT_LINES = 40
#: Lines kept either side of the failing line when a criterion is longer than the whole-source cap.
CODE_CONTEXT_LINES = 12
#: The value-capture harness, copied beside each criterion at run time.
_RUNNER_SOURCE = get_language_dir("python") / "acceptance" / "runner.py"
_EXCEPTION_TAIL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)\b")
#: A CPython traceback frame: ``  File "decoder-no-arguments.py", line 12, in <module>``.
_TRACEBACK_FRAME_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)')


def assertion_location(stderr: str) -> str:
    """``file:line`` of the deepest traceback frame, or ``""`` when there is no traceback.

    The deepest frame is the one that raised. For a check written as a flat script that is the
    failing ``assert`` itself, so the operator can open the criterion at the exact line rather
    than re-reading the whole snippet to guess which expectation was missed.
    """
    _, stderr = split_captured_values(stderr)
    frames = [
        match
        for match in (_TRACEBACK_FRAME_RE.match(line) for line in (stderr or "").splitlines())
        if match
    ]
    if not frames:
        return ""
    deepest = frames[-1]
    return f"{Path(deepest.group('file')).name}:{deepest.group('line')}"


def _split_fenced_block(text: str, begin: str, end: str) -> tuple[list[str], str]:
    """Lift one fenced harness block out of a stream, returning ``(lines, remaining)``."""
    if begin not in text:
        return [], text
    before, _, rest = text.partition(begin)
    block, _, after = rest.partition(end)
    lines = [line.rstrip() for line in block.splitlines() if line.strip()]
    remaining = (before + after.lstrip("\n")) if after else before
    return lines, remaining


def split_captured_progress(stderr: str) -> tuple[list[str], str]:
    """Separate the harness's tally block from the criterion's own stderr.

    Returns ``(tally_lines, remaining_stderr)``. The tally is how much of a suite passed, which
    is a measurement of the attempt rather than a diagnosis of the failure, so it is lifted out
    before the failure is rendered and read on its own.
    """
    return _split_fenced_block(stderr or "", PROGRESS_BEGIN, PROGRESS_END)


def split_captured_values(stderr: str) -> tuple[list[str], str]:
    """Separate the harness's value block from the criterion's own stderr.

    Returns ``(value_lines, remaining_stderr)``. The values are reported as their own section
    because they are the answer to the reader's question — what did the criterion actually
    observe — and burying them above a traceback puts the answer where nobody looks.
    """
    _, text = split_captured_progress(stderr or "")
    return _split_fenced_block(text, VALUES_BEGIN, VALUES_END)


#: The acceptance harness's own tally line: ``cases: pass=123 fail=159 error=0 total=282``.
_PROGRESS_TALLY_RE = re.compile(r"(?m)^cases:\s+(?P<counts>[a-z]+=\d+(?:\s+[a-z]+=\d+)*)")
_CASE_TALLY_RE = re.compile(
    r"(?m)(?P<passed>\d+)\s+passed,\s+"
    r"(?P<failed>\d+)\s+failed"
    r"(?:,\s+(?P<errored>\d+)\s+errored)?"
)


def case_tally(stdout: str, stderr: str) -> tuple[int, int] | None:
    """Return the ``passed/total`` subcase tally a scoped acceptance check reported, if any.

    Two sources, in order of authority. The acceptance harness lifts a tally out of the failing
    frame and prints it in a fenced block, which is exact and does not depend on the criterion
    choosing to print anything. Failing that, a criterion that printed its own ``N passed, M
    failed`` line is read directly. Shared by the build loop and ``score ac`` so a check that
    selected zero cases from its corpus is classified identically by both: neither can prove the
    story broken or correct, so it is not a failure.
    """
    if (match := _PROGRESS_TALLY_RE.search(stderr or "")) is not None:
        counts = dict(
            (name, int(number))
            for name, _, number in (pair.partition("=") for pair in match.group("counts").split())
        )
        if "pass" in counts:
            total = counts.get(
                "total",
                sum(counts[name] for name in ("pass", "fail", "error", "skip") if name in counts),
            )
            if total >= counts["pass"]:
                return counts["pass"], total
    matches = tuple(_CASE_TALLY_RE.finditer(f"{stdout}\n{stderr}"))
    if not matches:
        return None
    match = matches[-1]
    passed = int(match.group("passed"))
    failed = int(match.group("failed"))
    errored = int(match.group("errored") or 0)
    return passed, passed + failed + errored


def _assertion_line_number(stderr: str) -> int | None:
    """1-based line number of the deepest traceback frame, or ``None`` when there is no traceback."""
    _, stderr = split_captured_values(stderr)
    frames = [
        match
        for match in (_TRACEBACK_FRAME_RE.match(line) for line in (stderr or "").splitlines())
        if match
    ]
    return int(frames[-1].group("line")) if frames else None


def code_excerpt(code: str, *, focus_line: int | None = None, indent: str = "") -> list[str]:
    """Render a criterion's source with line numbers, marking the line that raised.

    A failure report that names an assertion without showing it makes the reader open the
    Blueprint to find out what was asserted. The code is the check; quoting it is what turns
    ``AssertionError`` into a statement about the product. The failing line carries a ``>``
    marker so it is findable without counting.
    """
    lines = (code or "").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []
    first, last = 1, len(lines)
    if len(lines) > CODE_EXCERPT_LINES and focus_line is not None:
        first = max(1, focus_line - CODE_CONTEXT_LINES)
        last = min(len(lines), focus_line + CODE_CONTEXT_LINES)
    elif len(lines) > CODE_EXCERPT_LINES:
        last = CODE_EXCERPT_LINES
    width = len(str(last))
    out: list[str] = []
    if first > 1:
        out.append(f"{indent}  ... {first - 1} earlier line(s)")
    for number in range(first, last + 1):
        mark = ">" if number == focus_line else " "
        out.append(f"{indent}{mark} {str(number).rjust(width)} | {lines[number - 1]}".rstrip())
    if last < len(lines):
        out.append(f"{indent}  ... {len(lines) - last} further line(s)")
    return out


def assertion_summary(stderr: str, error: str | None = None, *, override: str | None = None) -> str:
    """The concrete reason a programmatic check failed, in one line.

    A file-backed run's stderr carries the source line and the exception, so the failing
    assertion is recoverable: ``assert a + b == c`` → ``AssertionError``. Falls back to the
    check's own error (e.g. a timeout) when no traceback is present.

    A bare exception name is never returned alone. ``AssertionError`` on its own reads to every
    operator as an internal Drydock fault rather than as the product missing an expectation, so
    an exception with neither a message nor a recoverable source line is stated as what it is.

    ``override`` outranks the traceback. When the built code exhausted memory or ran past its
    budget, the bare ``MemoryError`` at the top of the stack names the symptom; the override
    names the defect, and that is what a repair pass has to act on.
    """
    if override:
        return override
    _, stderr = split_captured_values(stderr)
    lines = [line.rstrip() for line in (stderr or "").splitlines() if line.strip()]
    assertion = next(
        (line.strip() for line in reversed(lines) if line.strip().startswith("assert ")), ""
    )
    exception = next(
        (line.strip() for line in reversed(lines) if _EXCEPTION_TAIL_RE.match(line.strip())),
        "",
    )
    if assertion and exception:
        return f"{assertion} → {exception}"
    if assertion:
        return assertion
    if exception:
        # ``AssertionError`` with no message and no recoverable source line. Name the class of
        # failure instead of the exception, so the reader is not left holding a symbol.
        if ":" not in exception:
            return f"the check's expectation was not met ({exception}, no message)"
        return exception
    if error:
        return error
    return "failed with no diagnostic output"


def failure_detail(
    *,
    stderr: str,
    stdout: str,
    return_code: int | None = None,
    error: str | None = None,
    override: str | None = None,
    code: str = "",
    indent: str = "",
    full: bool = False,
) -> list[str]:
    """Render one failed check as a readable block: the assertion, the exit, what it observed.

    This is the whole diagnostic an operator needs at the point of failure. It is deliberately
    bounded: the summary line, where the assertion lives, the exit code, the exception, the tail
    of the check's own reported output, and the tail of its stderr. The full streams stay in the
    evidence file for the reader who wants them, or are shown here in full when ``full`` is set.

    The stderr tail is not redundant with the summary. A check that prints nothing before it
    asserts — the common shape for a boundary check — leaves ``observed output`` empty, and
    without the traceback the report states an ``AssertionError`` with no account of how it was
    reached. The traceback is that account, and it is on stderr.
    """
    tally, _ = split_captured_progress(stderr)
    values, stderr = split_captured_values(stderr)
    lines = [f"{indent}assertion: {assertion_summary(stderr, error, override=override)}"]
    # A suite-driving criterion fails identically whether one case is broken or every case is.
    # The tally is the difference, and the repair pass is shown it for the same reason the
    # operator is: it is the only statement of how far off the product actually is.
    lines.extend(f"{indent}{line}" for line in tally)
    location = assertion_location(stderr)
    if location:
        lines.append(f"{indent}raised at: {location}")
    if return_code is not None:
        lines.append(f"{indent}process exit code: {return_code}")
    exception = next(
        (
            line.strip()
            for line in reversed((stderr or "").splitlines())
            if _EXCEPTION_TAIL_RE.match(line.strip())
        ),
        "",
    )
    if exception and ":" in exception:
        lines.append(f"{indent}error: {exception}")
    # The values the criterion observed come before its source: they are the answer, and the
    # source is the context for the answer.
    if values:
        lines.append(f"{indent}values at failure:")
        lines.extend(f"{indent}{line}" for line in values)
    excerpt = code_excerpt(code, focus_line=_assertion_line_number(stderr), indent=f"{indent}  ")
    if excerpt:
        lines.append(f"{indent}criterion code:")
        lines.extend(excerpt)
    observed = [line.rstrip() for line in (stdout or "").splitlines() if line.strip()]
    if observed:
        shown = observed if full else observed[-OBSERVED_OUTPUT_LINES:]
        lines.append(f"{indent}observed output:")
        lines.extend(f"{indent}  {line}" for line in shown)
        if not full and len(observed) > len(shown):
            lines.append(
                f"{indent}  … {len(observed) - len(shown)} earlier line(s) omitted, --full for all"
            )
    diagnostic = [line.rstrip() for line in (stderr or "").splitlines() if line.strip()]
    if diagnostic:
        shown = diagnostic if full else diagnostic[-DIAGNOSTIC_OUTPUT_LINES:]
        lines.append(f"{indent}check stderr:")
        lines.extend(f"{indent}  {line}" for line in shown)
        if not full and len(diagnostic) > len(shown):
            lines.append(
                f"{indent}  … {len(diagnostic) - len(shown)} earlier line(s) omitted, --full for all"
            )
    return lines


_MEMORY_SIGNATURES = ("MemoryError", "Cannot allocate memory", "std::bad_alloc", "Killed")
# Exceptions that, when raised by the snippet's own frame, mean the snippet is defective:
# it reads a name it never bound or does not parse. Neither is a statement about the code
# under test.
#
# ``TypeError`` belongs here for the same reason, and it is the common case in practice: a criterion
# that passes a ``str`` to a binary-mode ``subprocess`` call, or calls an interface with the wrong
# argument shape, dies before the code under test does any work. A build is a search for pass/fail
# verdicts, not for exceptions in the harness, so a criterion that cannot execute never fails the
# build. The trade is deliberate and known: a ``TypeError`` that a correct implementation would have
# avoided — an interface returning ``None`` where the criterion expected a value — stops gating too.
# That case is visible as a reported defective criterion rather than silent, and the alternative
# spends the whole repair budget on a check no implementation can turn green.
# Exceptions that, raised in the snippet's own frame, mean the check never reached the code
# under test: the filesystem or the environment refused it. ``ConnectionError`` and friends are
# deliberately absent — a refused connection to the service under test is a product defect.
_MISSING_MODULE_RE = re.compile(
    r"(?:ModuleNotFoundError|ImportError): No module named ['\"]([^'\"]+)"
)
_TRACEBACK_FILE_RE = re.compile(r'^\s*File "([^"]+)", line ', re.MULTILINE)
_EXCEPTION_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\b:?(.*)$")
_FIXTURE_PATH_RE = re.compile(
    r"(?:Path|open)\(\s*[\"'](?P<path>(?:tests/)?[^\"']*fixture[^\"']*)[\"']"
)


def _timeout_output_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _resource_failure(return_code: int, stderr: str, limit_mb: int) -> str | None:
    """Classify a non-zero exit as resource exhaustion, or ``None`` when it is not.

    Distinguishes "the built code cannot run within its budget" from "the built code ran
    and missed an expectation". Only the former should tell a repair pass to fix an
    unbounded loop or allocation rather than adjust behavior.
    """
    if return_code == 0:
        return None
    oom_signalled = return_code == -signal.SIGKILL
    if oom_signalled or any(sig in stderr for sig in _MEMORY_SIGNATURES):
        bound = f"{limit_mb} MB" if limit_mb > 0 else "the available memory"
        return (
            f"{MEMORY_FAILURE_PREFIX}: the built code exceeded {bound} and was stopped by the "
            f"kernel. This is unbounded allocation or a non-terminating loop in the code under "
            f"test, not a missed expectation."
        )
    return None


def _timeout_failure_text(check: ProgrammaticAcceptance) -> str:
    """State what a timeout establishes, which is not the same for every criterion.

    A story check is bounded work the criterion itself defines, so overrunning its budget by an
    order of magnitude is good evidence of a loop that never exits. A suite-bound check hands its
    runtime to a staged runner over a whole corpus: there, "slow suite", "hung case", and "loaded
    host" produce the identical kill, and naming one of them invents a cause. The jq run of
    20260815.004309 was reported as a non-terminating loop in the product when the suite in fact
    completes in 50s. Say what was observed and let the repair pass reason from that.
    """
    budget = f"{TIMEOUT_FAILURE_PREFIX} after {check.timeout_seconds}s"
    if check.suite_bound:
        return (
            f"{budget}: the staged runner did not finish within its budget and was stopped by "
            f"the harness. The cause is not established — a hung case, a suite slower than its "
            f"budget, and a loaded host are indistinguishable here. This is not a missed "
            f"expectation."
        )
    return (
        f"{budget}: the built code did not terminate within its budget and was stopped by the "
        f"harness. Look first for a non-terminating loop or unbounded work in the code under "
        f"test. This is not a missed expectation."
    )


def _frame_in_build(frame: str, script_name: str, build_dir: Path) -> bool:
    """True when a traceback frame names a file inside the built tree."""
    path = Path(frame)
    if path.name == script_name:
        return False
    # A relative frame is relative to the acceptance cwd, which is the build directory.
    candidate = path if path.is_absolute() else build_dir / path
    try:
        resolved = candidate.resolve()
        root = build_dir.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _own_frame_exception(
    return_code: int,
    stderr: str,
    script_name: str,
    build_dir: Path | None = None,
) -> tuple[str, str] | None:
    """Return ``(exception, detail)`` when the check died in its own frame, else ``None``.

    Attribution is by traceback frame, not by exception type alone. The same exception means
    opposite things depending on where it was raised: inside the code under test it is a
    genuine red the build must drive green; inside the check's own frame it says the check
    never reached the code under test at all.

    The deepest frame is not always the check's own, even when the check is what is wrong. A
    criterion that calls ``subprocess.run`` with an ``int`` in its argv dies inside
    ``subprocess.py``, several stdlib frames below the check, without the built code running
    at all. Such a traceback is still the check's fault, so it qualifies when the check appears
    in the traceback and *no* frame belongs to the built tree. One build frame is enough to
    disqualify it: that means the product ran, and its failure is the build's to fix.
    """
    if return_code == 0:
        return None
    lines = [line for line in stderr.splitlines() if line.strip()]
    if not lines:
        return None
    match = _EXCEPTION_LINE_RE.match(lines[-1].strip())
    if match is None:
        return None
    frames = _TRACEBACK_FILE_RE.findall(stderr)
    if not frames:
        return None
    if Path(frames[-1]).name != script_name:
        if build_dir is None or not any(Path(frame).name == script_name for frame in frames):
            # The failure surfaced inside the code under test. That is the build's job to fix.
            return None
        if any(_frame_in_build(frame, script_name, build_dir) for frame in frames):
            return None
    return match.group(1).rsplit(".", 1)[-1], match.group(2).strip()


def _environment_failure(
    return_code: int,
    stderr: str,
    script_name: str,
    requirements: tuple[AcceptanceRequirement, ...] = (),
) -> str | None:
    """Classify a non-zero exit as a non-result, or ``None`` when it is a real verdict.

    An assertion that fails because it could not read a file, lacked a permission, or found a
    declared tool absent never exercised the code under test. It is not evidence that the
    implementation is wrong; it is evidence that the kit around the implementation is wrong.
    Only failures raised in the check's own top frame qualify — the same exception from inside
    the built code is a product defect and stays a FAIL. Attribution here is deliberately
    stricter than :func:`_malformed_failure`: a ``FileNotFoundError`` raised deep in the standard
    library is usually the *expected* red baseline, where the check reads a deliverable the build
    has not written yet, and classifying that as a kit fault would erase every red baseline.
    """
    attributed = _own_frame_exception(return_code, stderr, script_name)
    if attributed is None:
        return None
    exception, detail = attributed
    taxonomy = load_acceptance_failure_taxonomy()
    if exception in taxonomy.environment_exceptions:
        return (
            f"{UNVERIFIED_FAILURE_PREFIX}: the assertion raised {exception}"
            f"{f' ({detail})' if detail else ''} in its own frame, before reaching the code "
            f"under test. This is a fault in the acceptance kit or its environment, not a "
            f"defect in the build."
        )
    # A missing module is normally the expected red baseline, so it is a genuine FAIL. It is a
    # non-result only when the module is one the check *declared* it needs: the Commander
    # promised the tool and the environment did not supply it, so nothing was tested.
    declared = {
        item.name.lower().replace("-", "_")
        for item in requirements
        if item.kind == "python-package"
    }
    if declared and (match := _MISSING_MODULE_RE.search(stderr)):
        missing = match.group(1).split(".", 1)[0]
        if missing.lower().replace("-", "_") in declared:
            return (
                f"{UNVERIFIED_FAILURE_PREFIX}: declared python-package {missing!r} is absent "
                f"from the acceptance environment, so the assertion never ran. Provision the "
                f"declared dependency; this is not a defect in the build."
            )
    return None


def _malformed_failure(
    return_code: int, stderr: str, script_name: str, build_dir: Path | None = None
) -> str | None:
    """Classify a non-zero exit as a defective snippet, or ``None`` when it is not.

    ``NameError`` raised inside the code under test is a genuine red the build must drive
    green; the same exception raised in the check's own frame means the check reads a name
    nothing binds — most often a name a sibling check defined, which is not in scope because
    every check runs as its own script in its own process.
    """
    attributed = _own_frame_exception(return_code, stderr, script_name, build_dir)
    if attributed is None:
        return None
    exception, detail = attributed

    # ``ImportError`` is deliberately absent. A missing module is the *expected* red baseline
    # before the code under test is written, and nothing in the traceback distinguishes that
    # from a typo'd import. Classifying it would block builds that should proceed, so it is
    # left to the build.
    taxonomy = load_acceptance_failure_taxonomy()
    if exception in taxonomy.malformed_exceptions:
        return (
            f"{MALFORMED_FAILURE_PREFIX}: the assertion itself raised {exception}"
            f"{f' ({detail})' if detail else ''} in its own frame, before reaching the code "
            f"under test. No implementation can satisfy it. Each check runs as its own "
            f"script in its own process, so a name bound by another check is not in scope. "
            f"Repair the assertion in the Blueprint specification."
        )
    return None


def _missing_fixture_failure(
    return_code: int, stderr: str, code: str, build_dir: Path
) -> str | None:
    """Classify an acceptance that cannot run because its declared fixture is absent.

    A missing fixture is a defect in the generated acceptance setup, not evidence that the
    implementation failed. Keep this deliberately narrow: only a path containing ``fixture``
    that is referenced by the acceptance code, absent from the build directory, and named by
    a missing-file diagnostic is skipped. Other filesystem failures remain implementation
    failures.
    """
    if return_code == 0 or "No such file or directory" not in stderr:
        return None
    for match in _FIXTURE_PATH_RE.finditer(code):
        relative = match.group("path")
        candidate = Path(relative)
        if not candidate.is_absolute() and not (build_dir / candidate).exists():
            return (
                f"{SKIPPED_FAILURE_PREFIX}: acceptance references missing fixture "
                f"{relative!r}. The check is untested; provide the fixture or revise the "
                "acceptance before relying on its result."
            )
    return None


def _scrub_script_path(text: str, script: Path) -> str:
    """Replace the throwaway script's absolute path with its stable check name.

    The path is a per-run temporary directory; leaving it in evidence makes otherwise
    identical failures compare unequal across runs.
    """
    return text.replace(str(script), script.name)


@dataclass(frozen=True)
class AcceptanceRequirement:
    kind: str
    name: str
    scope: str


@dataclass(frozen=True)
class ProgrammaticAcceptance:
    check_id: str
    source: str
    intent: str
    code: str
    sea_trials: tuple[str, ...] = ()
    full_suite: bool = False
    requirements: tuple[AcceptanceRequirement, ...] = ()
    #: The story gate this criterion belongs to, from its ``Gate:`` declaration.  It is
    #: planning metadata, not Python source; execution is determined by the criterion body.
    gate: str = ""
    #: The character encoding this criterion deliberately exercises, from its ``Encoding:``
    #: declaration. Empty is the norm and means the criterion is ASCII, which is what the
    #: authoring gate enforces. A target whose specification genuinely states an encoding
    #: requirement declares it here and may then use non-ASCII test data.
    encoding: str = ""
    #: Literal flag(s) that make a staged corpus-selection runner list or count the cases its
    #: selector matched, with no candidate present, from this criterion's ``Probe:`` declaration.
    probe: str = ""
    #: How to read the probe's stdout: ``lines`` (one case per non-blank line) or ``summary`` (the
    #: count is parsed from the trailing non-blank line), from ``Probe Count:``.
    probe_count: str = ""
    #: Where the source material states this criterion's expected value, from its ``Cite:``
    #: declaration: ``sources/<file>:<line>`` or ``sources/<file>:<start>-<end>``.
    cite: str = ""
    #: The cited lines, resolved under the Blueprint's ``sources/`` when the criterion was parsed
    #: from a file. ``None`` when nothing is cited or the citation does not resolve.
    cited_text: str | None = None

    @property
    def timeout_seconds(self) -> int:
        """A suite-bound check runs a whole conformance suite, not a story unit test.

        The budget follows what the criterion does, not only what it declared. A criterion that
        executes a staged runner is suite-bound whether or not its author wrote ``Suite:``, and
        charging it the story budget kills a legitimate run partway and reports the corpse as a
        non-terminating loop in the product.
        """
        return SUITE_TIMEOUT_SECONDS if self.suite_bound else TIMEOUT_SECONDS

    @property
    def suite_bound(self) -> bool:
        """True when the verdict comes from a staged runner rather than from this criterion."""
        return self.full_suite or _invokes_staged_asset(self.code)

    @property
    def retyped_expectations(self) -> tuple[str, ...]:
        """Expected values this criterion re-typed instead of binding to its input.

        A re-typed string literal, an assembled string, or a reconstructed path, rendered as
        source text. A literal found verbatim in the cited source material is derived: the
        source is the authority, and copying it is not a second escaping decision.
        """
        found = retyped_expectations(self.code)
        if self.cited_text:
            found = tuple(value for value in found if value not in self.cited_text)
        return found

    @property
    def binding(self) -> bool:
        """True when a failure of this criterion is evidence about the product.

        A criterion binds when every expected value it asserts is one it could not have got
        wrong: a staged suite's exit status, a status code, a value read back from the input it
        supplied, or a contract token that carries nothing escapable. A criterion that re-typed
        its expected bytes by hand did the one thing that fails independently of the product, so
        it is graded and reported but never charged against the build.
        """
        return not self.retyped_expectations


@dataclass(frozen=True)
class AcceptanceRunResult:
    check_id: str
    source: str
    intent: str
    passed: bool
    return_code: int | None
    stdout: str
    stderr: str
    error: str | None = None
    skipped: bool = False
    interpreter: str = ""
    provisioning_result: str = "not requested"
    #: Whether a miss here is evidence about the product. False when the criterion re-typed its
    #: expected value rather than deriving it; see :attr:`ProgrammaticAcceptance.binding`.
    binding: bool = True

    @property
    def outcome(self) -> str:
        """PASS, FAIL, UNVERIFIED, or DISPUTED — the verdict for this assertion.

        ``skipped`` is the storage for UNVERIFIED so that every consumer written against the
        older two-valued model keeps excluding these results from the build's tally, which is
        exactly what UNVERIFIED requires.
        """
        if self.skipped:
            return OUTCOME_UNVERIFIED
        if self.passed:
            return OUTCOME_PASS
        return OUTCOME_FAIL if self.binding else OUTCOME_DISPUTED

    @property
    def unverified(self) -> bool:
        return self.outcome == OUTCOME_UNVERIFIED


@dataclass(frozen=True)
class AcceptanceObservation:
    check_id: str
    source: str
    intent: str
    passed: bool
    return_code: int | None
    stdout: str
    stderr: str
    error: str | None = None
    skipped: bool = False
    integrity_ok: bool = True
    integrity_reasons: tuple[str, ...] = ()

    @property
    def outcome(self) -> str:
        if self.skipped:
            return OUTCOME_UNVERIFIED
        return OUTCOME_PASS if self.passed else OUTCOME_FAIL

    @property
    def unverified(self) -> bool:
        return self.outcome == OUTCOME_UNVERIFIED

    @property
    def status(self) -> str:
        if self.skipped:
            return "unverified"
        if not self.passed:
            return "baseline-red"
        return "green" if self.integrity_ok else "green-vacuous"

    @property
    def weak(self) -> bool:
        return self.passed


@dataclass(frozen=True)
class OutcomeTally:
    """Counts of the three assertion outcomes, plus the defect attribution they imply."""

    passed: int = 0
    failed: int = 0
    unverified: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.unverified

    @property
    def product_defects(self) -> int:
        """Assertions that reached the code under test and found it wrong."""
        return self.failed

    @property
    def harness_defects(self) -> int:
        """Assertions that never reached the code under test."""
        return self.unverified

    def to_dict(self) -> dict[str, int]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "unverified": self.unverified,
            "total": self.total,
            "product_defects": self.product_defects,
            "harness_defects": self.harness_defects,
        }


def tally_outcomes(
    results: tuple[AcceptanceRunResult | AcceptanceObservation, ...],
) -> OutcomeTally:
    """Aggregate assertion outcomes so a run reports harness defects apart from product defects.

    Without this split, ``status: failed`` says only that something went wrong, and the two
    causes it conflates — Drydock produced a bad artifact, Drydock's checker rejected a good one
    — need opposite fixes.
    """
    counts = {outcome: 0 for outcome in OUTCOMES}
    for result in results:
        counts[result.outcome] += 1
    return OutcomeTally(
        passed=counts[OUTCOME_PASS],
        failed=counts[OUTCOME_FAIL],
        unverified=counts[OUTCOME_UNVERIFIED],
    )


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "acceptance"


def _sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("name").strip().lower()] = text[start:end].strip()
    return sections


def _last_heading(text: str) -> str | None:
    headings = list(HEADING_RE.finditer(text))
    if not headings:
        return None
    return headings[-1].group("title").strip()


def _intent(prefix: str, title: str | None) -> str:
    lines = []
    for raw in prefix.splitlines():
        line = raw.strip()
        if not line or line.startswith("###"):
            continue
        if re.match(r"(Sea Trials|Suite|Requires):", line, re.I):
            continue
        lines.append(line)
    if lines:
        return " ".join(lines)
    return title or "Programmatic acceptance assertion"


def _full_suite(prefix: str) -> bool:
    """Whether the assertion runs the whole test suite rather than a bounded story check.

    Story acceptance is bounded by default so an ordinary check cannot accidentally invoke the
    whole test suite. A suite-bound check declares ``Suite: full`` (a terminal verification story
    gating on the entire suite) or ``Suite: scoped`` (a feature story gating on the sections it
    owns); both get the suite execution budget.
    """
    return bool(re.search(r"^Suite:\s*(?:full|scoped)\s*$", prefix, re.MULTILINE | re.IGNORECASE))


def _sea_trials(prefix: str) -> tuple[str, ...]:
    match = re.search(r"^Sea Trials:\s*(.+?)\s*$", prefix, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ()
    return tuple(value.lower() for raw in match.group(1).split(",") if (value := raw.strip()))


def _requirements(prefix: str, *, source: str, check_id: str) -> tuple[AcceptanceRequirement, ...]:
    return _requirements_from_values(
        [match.group("value") for match in REQUIRES_RE.finditer(prefix)],
        source=source,
        check_id=check_id,
    )


def _requirements_from_values(
    values: Sequence[str], *, source: str, check_id: str
) -> tuple[AcceptanceRequirement, ...]:
    """Validate ``Requires:`` declarations however they were delimited.

    Both container formats converge here so the declaration rules have exactly one definition.
    """
    requirements: list[AcceptanceRequirement] = []
    for declaration in values:
        fields: dict[str, str] = {}
        for raw in declaration.split(";"):
            if "=" not in raw:
                raise ValueError(
                    f"{source} [{check_id}] malformed Requires declaration {declaration!r}"
                )
            key, field_value = raw.split("=", 1)
            fields[key.strip().lower()] = field_value.strip()
        kinds = [kind for kind in ("python-package", "executable") if kind in fields]
        if len(kinds) != 1 or set(fields) != {kinds[0], "scope"}:
            raise ValueError(
                f"{source} [{check_id}] Requires must declare exactly one of "
                "python-package/executable and scope"
            )
        scope = fields["scope"].lower()
        name = fields[kinds[0]]
        if scope not in {"runtime", "test"} or not name:
            raise ValueError(
                f"{source} [{check_id}] Requires scope must be runtime or test and name non-empty"
            )
        requirements.append(AcceptanceRequirement(kinds[0], name, scope))
    return tuple(requirements)


#: Metadata keys recognized inside an AC block. The set is closed on purpose: an unrecognized
#: ``Key: value`` line ends the metadata run and begins the code, so an annotated assignment such
#: as ``result: int = 5`` on the first code line cannot be mistaken for a declaration.
_AC_META_KEYS = frozenset({
    "intent",
    "suite",
    "requires",
    "sea trials",
    "gate",
    "encoding",
    "probe",
    "probe count",
    "cite",
})


def _parse_ac_block(body: str, *, check_id: str, source: str) -> ProgrammaticAcceptance:
    """Split one AC block into its declarations and its verbatim proof body.

    A blank line does not end the metadata run. The run ends at the first line that is not a
    recognized declaration, and only that line's content decides where the code begins. A blank
    line used to terminate the run, so an author who spaced ``Intent:`` away from ``Suite:`` and
    ``Requires:`` lost both declarations into the proof body: the criterion then reported a
    ``full`` suite as a story-scoped check, declared none of its tooling, and — because
    ``Suite: full`` and ``Gate: story-id`` are themselves valid Python annotations — and were
    reported as snippets reading undefined globals named after their own directives.
    """
    lines = body.splitlines()
    # The slice begins at the end of the opening marker's text, so the first element is that
    # line's terminator rather than content. Dropping it keeps the metadata run at the top.
    if lines and not lines[0].strip():
        lines = lines[1:]
    meta: dict[str, list[str]] = {}
    index = 0
    # Blank lines are consumed only when a declaration still follows them; the code must keep
    # any blank line that precedes its first statement, so the cursor advances to the declaration
    # rather than past the blanks.
    while index < len(lines):
        cursor = index
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines):
            break
        match = AC_META_RE.match(lines[cursor])
        if match is None or match.group("key").strip().lower() not in _AC_META_KEYS:
            break
        meta.setdefault(match.group("key").strip().lower(), []).append(match.group("value"))
        index = cursor + 1
    # The proof body is whatever follows, character for character. Only the trailing blank lines
    # the author left before the end marker are dropped.
    code = "\n".join(lines[index:]).strip("\n")
    intent = " ".join(value.strip() for value in meta.get("intent", ()) if value.strip())
    suite = " ".join(meta.get("suite", ())).strip().lower()
    sea_trials = tuple(
        value.lower()
        for raw in ",".join(meta.get("sea trials", ())).split(",")
        if (value := raw.strip())
    )
    return ProgrammaticAcceptance(
        check_id=check_id,
        source=source,
        intent=intent or check_id,
        code=code,
        sea_trials=sea_trials,
        full_suite=suite in {"full", "scoped"},
        requirements=_requirements_from_values(
            meta.get("requires", ()), source=source, check_id=check_id
        ),
        gate=" ".join(meta.get("gate", ())).strip(),
        encoding=" ".join(meta.get("encoding", ())).strip().lower(),
        probe=" ".join(meta.get("probe", ())).strip(),
        probe_count=" ".join(meta.get("probe count", ())).strip().lower(),
        cite=" ".join(meta.get("cite", ())).strip(),
    )


_CITE_RE = re.compile(r"(?P<path>sources/[^:]+):(?P<start>\d+)(?:-(?P<end>\d+))?\Z")


def resolve_citation(cite: str, blueprint_dir: Path) -> str | None:
    """Return the cited source text of a ``Cite:`` declaration, or ``None`` when it does not resolve.

    A citation names one line or an inclusive range of lines of a file under the Blueprint's
    ``sources/``. Anything outside ``sources/``, or past the end of the file, does not resolve.
    """
    match = _CITE_RE.match(cite.strip())
    if match is None:
        return None
    sources = (blueprint_dir / "sources").resolve()
    path = (blueprint_dir / match.group("path")).resolve()
    if not path.is_relative_to(sources) or not path.is_file():
        return None
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    try:
        # Line terminators are kept: an expected program output usually ends in one, and the
        # cited text must contain the literal exactly as the source states it.
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return None
    if start < 1 or end < start or end > len(lines):
        return None
    return "".join(lines[start - 1 : end])


def citation_defect(check: ProgrammaticAcceptance, blueprint_dir: Path) -> str | None:
    """Return why a criterion's ``Cite:`` does not support it, or ``None`` when it does.

    A citation exists to make a literal derived, so one that resolves to nothing, or to lines
    containing none of the criterion's expected literals, is a plan defect rather than a no-op.
    """
    if not check.cite:
        return None
    text = resolve_citation(check.cite, blueprint_dir)
    if text is None:
        return (
            f"Cite: {check.cite} does not resolve to lines of a file under sources/; "
            "cite sources/<file>:<line> or sources/<file>:<start>-<end>"
        )
    literals = retyped_expectations(check.code)
    if not any(value in text for value in literals):
        return (
            f"Cite: {check.cite} contains none of this criterion's expected literals verbatim; "
            "cite the lines that state the expected value"
        )
    return None


def _blueprint_root(path: Path) -> Path:
    """Return the Blueprint directory a criterion file belongs to: the nearest with ``sources/``."""
    for parent in path.parents:
        if (parent / "sources").is_dir():
            return parent
    return path.parent


def body_is_a_complete_cut(body: str) -> bool:
    """True when ``body`` can stand as a whole criterion, so a boundary may be inserted after it.

    An ``=== AC ... ===`` line only matches at column zero, so the sole way one lands inside a
    criterion rather than after it is inside a triple-quoted string. Tokenizing rather than
    compiling is deliberate: ``assert 1 ==`` is bad Python that still tokenizes, which is the
    point — the check only needs to rule out a cut landing mid-literal, not judge the Python.

    Only the proof body is tokenized. The leading ``Intent:`` declaration is prose, and an
    apostrophe in it (``the screen's inventory``) reads as an unterminated string literal, which
    refused every repair of a criterion whose intent used a possessive.
    """
    code = _parse_ac_block(body, check_id="", source="").code
    try:
        list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return False
    return True


def _markers_alternate(text: str) -> bool:
    """True when every acceptance marker in ``text`` opens, closes with its own id, and is unique.

    The structural half of :func:`parse_delimited_acceptance`, without the body parsing. A
    speculative boundary repair is accepted only when it produces this shape, so the repair can
    never hand Build a file that the real parser then rejects.
    """
    seen: set[str] = set()
    pending: str | None = None
    for _, kind, match in sorted(
        [(m.start(), "open", m) for m in AC_OPEN_RE.finditer(text)]
        + [(m.start(), "end", m) for m in AC_END_RE.finditer(text)],
        key=lambda item: item[0],
    ):
        ident = match.group("id").strip()
        if kind == "open":
            if pending is not None or ident in seen:
                return False
            seen.add(ident)
            pending = ident
            continue
        if pending != ident:
            return False
        pending = None
    return pending is None


def split_fused_acceptance_boundary(text: str) -> tuple[str, tuple[str, ...]] | None:
    """Split an ``=== AC <id> ===`` block whose closer names a different, never-opened id.

    The model sometimes fuses two criteria under one opener and closes the first with the
    *second* criterion's id, never emitting that second criterion's own opener — confirmed
    against a live plan run where every malformed Blueprint file showed exactly this shape, and
    where an LLM asked to repair it reliably renamed the wrong closer but never inserted the
    missing opener, failing identically on every attempt.

    The fusion chains. A live run emitted ``workflow-columns`` closed by
    ``workflow-production-terminal``, whose body was closed by ``workflow-catalog-boundary`` —
    each wrong closer opening the next criterion in turn. Every link is repaired, not just the
    first, because a chain is no more ambiguous than a single fusion: the walk carries the wrong
    id forward as the new pending opener, exactly as the model should have written it.

    Repaired only when unambiguous: the wrong id never opens anywhere in the text (so it cannot
    be a real, differently-placed criterion), the body being split off passes
    :func:`body_is_a_complete_cut`, and the repaired text alternates strictly. That last check is
    the guard — a speculative repair that leaves any block unclosed, stray, or duplicated is
    discarded whole and the hard error in :func:`parse_delimited_acceptance` stands.

    Returns ``(repaired_text, messages)`` when at least one boundary was inserted, else ``None``.
    Each message names the criterion id but not the file, so a caller with the filename can
    prefix it; one that has no file identity (a single already-loaded specification) can use a
    message as-is.
    """
    markers = sorted(
        [(match.start(), match.end(), "open", match) for match in AC_OPEN_RE.finditer(text)]
        + [(match.start(), match.end(), "end", match) for match in AC_END_RE.finditer(text)]
        + [(match.start(), match.end(), "bare", match) for match in AC_BARE_END_RE.finditer(text)],
        key=lambda item: item[0],
    )
    if not markers:
        return None
    open_ids = {m.group("id").strip() for _, _, kind, m in markers if kind == "open"}
    repairs: list[tuple[int, int, str]] = []
    messages: list[str] = []
    pending: tuple[str, int] | None = None
    for start, end, kind, match in markers:
        if kind == "bare":
            # The chain's last link is closed by an end marker with no id. Whatever is open is
            # the only thing it can close; with nothing open it is stray and left for the parser.
            if pending is not None:
                repairs.append((start, end, f"=== END AC {pending[0]} ==="))
                messages.append(f"[{pending[0]}]: '=== END AC' without an id closed it; id added")
                pending = None
            continue
        ident = match.group("id").strip()
        if kind == "open":
            pending = (ident, end)
            continue
        if pending is None or ident == pending[0]:
            pending = None
            continue
        if ident in open_ids:
            pending = None
            continue
        body = text[pending[1] : start]
        if not body_is_a_complete_cut(body):
            pending = None
            continue
        repairs.append((start, end, f"=== END AC {pending[0]} ===\n=== AC {ident} ===\n"))
        messages.append(
            f"[{pending[0]}]: '=== END AC {ident} ===' closed the wrong criterion; "
            f"boundary inserted between {pending[0]} and {ident}"
        )
        pending = (ident, end)
    if not repairs:
        return None
    repaired = text
    for start, end, replacement in sorted(repairs, key=lambda item: item[0], reverse=True):
        repaired = repaired[:start] + replacement + repaired[end:]
    if not _markers_alternate(repaired):
        return None
    return repaired, tuple(messages)


def parse_delimited_acceptance(text: str, *, source: str) -> tuple[ProgrammaticAcceptance, ...]:
    """Return every ``=== AC <id> ===`` criterion in ``text``, or ``()`` when the file uses none.

    Markers are read as one flat sequence in document order and must alternate strictly. An
    unterminated block, an end marker naming a different id, a stray end marker, and a duplicate
    id are all hard errors. The previous format degraded silently in exactly these cases: a
    truncated criterion produced an unparseable fragment that graded UNVERIFIED and cost the
    story nothing, so the gate disappeared without anyone being told.

    Blocks are found document-wide rather than inside a ``## Programmatic Acceptance`` section,
    because a ``##`` line inside a proof body would otherwise close that section early.
    """
    markers = sorted(
        [(match.start(), "open", match) for match in AC_OPEN_RE.finditer(text)]
        + [(match.start(), "end", match) for match in AC_END_RE.finditer(text)],
        key=lambda item: item[0],
    )
    if not markers:
        return ()
    checks: list[ProgrammaticAcceptance] = []
    seen: set[str] = set()
    pending: tuple[str, int] | None = None
    for _, kind, match in markers:
        ident = match.group("id").strip()
        if kind == "open":
            if pending is not None:
                raise ValueError(
                    f"{source} [{pending[0]}] acceptance block is never closed: found "
                    f"'=== AC {ident} ===' before '=== END AC {pending[0]} ==='"
                )
            if ident in seen:
                raise ValueError(f"{source} [{ident}] duplicate acceptance criterion id")
            seen.add(ident)
            pending = (ident, match.end())
            continue
        if pending is None:
            raise ValueError(
                f"{source} [{ident}] '=== END AC {ident} ===' has no matching opening block"
            )
        if ident != pending[0]:
            raise ValueError(
                f"{source} [{pending[0]}] acceptance block closes with a different id: "
                f"expected '=== END AC {pending[0]} ===', found '=== END AC {ident} ==='"
            )
        checks.append(
            _parse_ac_block(text[pending[1] : match.start()], check_id=ident, source=source)
        )
        pending = None
    if pending is not None:
        raise ValueError(
            f"{source} [{pending[0]}] acceptance block is never closed: "
            f"'=== END AC {pending[0]} ===' is missing"
        )
    return tuple(checks)


#: A string expectation an author cannot mis-escape: printable ASCII text, lines, and tabs. A
#: deterministic known answer — a CSV report, a status line, a quoted message — is the point of a
#: criterion, not a re-typed value. A backslash is the one character whose meaning depends on
#: how many layers have escaped it (a Windows path, a TOML literal), so it is excluded except in
#: ``\"``, an escaped quote, which every layer reads alike. A carriage return is excluded because
#: CRLF against LF is an escaping decision. Revised 2026-10-21 from identifier-shaped tokens only;
#: LayersTesting ``20261021.195808`` demoted seven known-answer criteria to non-binding.
#:
#: ``\Z`` rather than ``$``: ``$`` also matches before a trailing newline.
_PLAIN_TEXT_RE = re.compile(r'(?:[\t\n\x20-\x5b\x5d-\x7e]|\\")*\Z')

#: The path prefix that marks a staged, externally authored asset. A criterion whose verdict is
#: such a runner's exit status did not invent its oracle.
_STAGED_PREFIX = "sources/"


#: The process-launching callables whose arguments name the thing actually being executed. A
#: staged path anywhere else in a criterion — read, stat-ed, opened — is not an invocation.
_RUNNER_NAMES = frozenset({
    "run",
    "call",
    "check_call",
    "check_output",
    "Popen",
    "system",
    "getoutput",
    "getstatusoutput",
})


def _invokes_staged_asset(code: str) -> bool:
    """True when the criterion executes something staged under ``sources/``.

    Mentioning a staged path is not executing one: ``Path("sources/spec.txt").is_file()`` is an
    ordinary bounded assertion, while ``subprocess.run(["sh", "sources/full_test.sh"])`` hands the
    verdict to a runner whose runtime this criterion does not control. Only the second earns the
    suite budget, so the staged path must appear in the arguments of a process launch.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except SyntaxError:
        # Not parseable is a separate, already-reported fact. Nothing to classify.
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _RUNNER_NAMES:
            continue
        for argument in ast.walk(node):
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                if _STAGED_PREFIX in argument.value:
                    return True
    return False


def _is_escapable(value: str) -> bool:
    """True when stating this literal requires escaping decisions that can disagree."""
    return not _PLAIN_TEXT_RE.match(value)


def _supplied_literals(tree: ast.AST) -> frozenset[str]:
    """Return every string literal bound to a name or passed as input by the criterion.

    A literal the criterion itself supplies is not a re-typed expectation: asserting the value
    that went in came back out is the round trip, and it cannot disagree with itself.
    """
    supplied: set[str] = set()
    for node in ast.walk(tree):
        # Bound to a name: `raw = "C:\\Users\\nodejs"` then asserted against `raw` later, or
        # asserted against the same literal, are the same claim.
        if isinstance(node, ast.Assign):
            for value in ast.walk(node.value):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    supplied.add(value.value)
        # Passed as input to the code under test: `input=source`, `json={"title": "Dune"}`,
        # `subprocess.run([...])`. Whatever went in may be asserted on the way out.
        elif isinstance(node, ast.Call):
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                for value in ast.walk(argument):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        supplied.add(value.value)
    return frozenset(supplied)


def _supplied_expressions(tree: ast.AST) -> frozenset[str]:
    """Return the structural dump of every expression bound to a name or passed as input.

    An assembled string that is itself the input — built once, fed in, asserted on the way out —
    is the round trip, exactly as a supplied literal is.
    """
    supplied: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            supplied.add(ast.dump(node.value))
        elif isinstance(node, ast.Call):
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                supplied.add(ast.dump(argument))
    return frozenset(supplied)


def _is_reconstructed_path(node: ast.AST) -> bool:
    """True for ``a / b [/ c ...]`` — a path rebuilt with the pathlib join operator.

    Path equality is sensitive to normalization a hand-assembled join does not control:
    ``.resolve()`` against a relative join, a trailing slash, a symlink. Comparing one against a
    path the code under test computed independently is the structural analogue of a re-typed
    string literal — two spellings of "the same" value that can disagree with each other while
    both are correct.
    """
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)


def _is_string_piece(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (
        isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _is_assembled_string(node: ast.AST) -> bool:
    """True for an expected string built in the criterion rather than typed or read back.

    An f-string, a ``+`` concatenation with a string piece, ``"..." % args``, or
    ``"...".format(...)`` states expected bytes exactly as a literal does, with extra steps.
    """
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return any(
                _is_string_piece(side) or _is_assembled_string(side)
                for side in (node.left, node.right)
            )
        if isinstance(node.op, ast.Mod):
            return _is_string_piece(node.left)
        return False
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and _is_string_piece(node.func.value)
    )


def _is_computed_attribute(node: ast.AST) -> bool:
    """True for ``name.attr`` (or a chain of them) — a value read off an object, not typed here."""
    return isinstance(node, ast.Attribute)


def _comparison_expectations(tree: ast.AST) -> tuple[ast.expr, ...]:
    """Return the expected-value expressions asserted by an ``==``/``!=`` comparison.

    Two shapes qualify: a string constant, and a path rebuilt with ``/`` and compared against a
    value read off another object (``module.CORPUS == sources / "jq.test"``) — the reconstruction
    is retyped by structure rather than by bytes.
    """
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        for inner in ast.walk(node.test):
            if not isinstance(inner, ast.Compare):
                continue
            # Only equality states "the value is exactly this". Membership, identity, and
            # ordering are structural claims that carry no re-typed bytes.
            for operator, comparator in zip(inner.ops, inner.comparators, strict=True):
                if not isinstance(operator, (ast.Eq, ast.NotEq)):
                    continue
                for side in (inner.left, comparator):
                    if isinstance(side, ast.Constant) and isinstance(side.value, str):
                        found.append(side)
                    elif _is_assembled_string(side):
                        found.append(side)
                if _is_reconstructed_path(inner.left) and _is_computed_attribute(comparator):
                    found.append(inner.left)
                elif _is_reconstructed_path(comparator) and _is_computed_attribute(inner.left):
                    found.append(comparator)
    return tuple(found)


@cache
def retyped_expectations(code: str) -> tuple[str, ...]:
    """Return expected values the criterion re-typed rather than bound to its input.

    This is the whole of the authoring rule, and it is a whitelist over a decidable property
    rather than a catalogue of observed failures. An expected value is legal when it is a status
    code, a value read back from the input the criterion supplied, or a contract token carrying
    nothing escapable. It is illegal when the author typed the expected bytes a second time,
    because that is the one assertion that can be wrong while the product is right — and illegal
    in the same way when the author rebuilt a path expected to equal one the code under test
    computes itself, since the two constructions are not guaranteed to normalize alike.

    The case this exists for, from a real run::

        source = 'raw = \\'C:\\\\\\\\Users\\\\\\\\nodejs\\'\\n'
        assert decoded["raw"]["value"] == r"C:\\Users\\nodejs"

    A TOML literal string preserves its backslashes, so the expectation was wrong and the decoder
    was right. Binding the value to a name and using it on both sides removes the second escaping
    decision, and with it the entire failure class.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except SyntaxError:
        # Not parseable is a separate, already-reported fact. Nothing to classify.
        return ()
    supplied = _supplied_literals(tree)
    supplied_expressions = _supplied_expressions(tree)
    offending: list[str] = []
    for node in _comparison_expectations(tree):
        if isinstance(node, ast.Constant):
            if _is_escapable(node.value) and node.value not in supplied:
                offending.append(node.value)
        elif ast.dump(node) not in supplied_expressions:
            offending.append(ast.unparse(node))
    return tuple(dict.fromkeys(offending))


def parse_programmatic_acceptance(path: Path) -> tuple[ProgrammaticAcceptance, ...]:
    """Return Python acceptance snippets from one Blueprint spec file."""
    stat = path.stat()
    return _parse_programmatic_acceptance_file(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


@cache
def _parse_programmatic_acceptance_file(
    path: str, _mtime_ns: int, _size: int
) -> tuple[ProgrammaticAcceptance, ...]:
    source = Path(path)
    checks = parse_programmatic_acceptance_text(
        source.read_text(encoding="utf-8"), source=source.name
    )
    if not any(check.cite for check in checks):
        return checks
    blueprint_dir = _blueprint_root(source)
    return tuple(
        replace(check, cited_text=resolve_citation(check.cite, blueprint_dir))
        if check.cite
        else check
        for check in checks
    )


def parse_programmatic_acceptance_text(
    text: str, *, source: str
) -> tuple[ProgrammaticAcceptance, ...]:
    """Return Python acceptance snippets from in-memory Blueprint text.

    The delimited ``=== AC <id> ===`` container is the authored form and is tried first. The
    Markdown-fence form is retained for Blueprints not yet migrated; it infers every boundary and
    so cannot survive a proof body that contains a fence, a ``##`` line, or a ``###`` line.
    """
    delimited = parse_delimited_acceptance(text, source=source)
    if delimited:
        return delimited

    section = _sections(text).get("programmatic acceptance", "")
    if not section or section.strip() == "- None.":
        return ()

    checks: list[ProgrammaticAcceptance] = []
    previous_end = 0
    for index, match in enumerate(PYTHON_FENCE_RE.finditer(section), start=1):
        prefix = section[previous_end : match.start()]
        title = _last_heading(prefix)
        check_id = _slugify(title or f"{Path(source).stem}-{index}")
        code = match.group("code").strip()
        checks.append(
            ProgrammaticAcceptance(
                check_id=check_id,
                source=source,
                intent=_intent(prefix, title),
                code=code,
                sea_trials=_sea_trials(prefix),
                full_suite=_full_suite(prefix),
                requirements=_requirements(prefix, source=source, check_id=check_id),
            )
        )
        previous_end = match.end()
    return tuple(checks)


def unreadable_acceptance_warning(source: str, exc: Exception) -> str:
    """The one wording every surface uses when a spec's criteria could not be read."""
    return (
        f"{source}: acceptance criteria could not be read and are not graded "
        f"— {exc}. Repair the Blueprint specification."
    )


def acceptance_checks_from_text(
    text: str, *, source: str, defects: list[str] | None
) -> tuple[ProgrammaticAcceptance, ...]:
    """Parse criteria from spec text, degrading an unreadable container to a reported defect.

    A malformed acceptance container is an authoring defect in one file. Raising here costs the
    caller everything it was doing — at plan time, an entire generated plan — over a criterion
    that gates nothing either way. So the file simply carries no criteria and the fact is
    reported instead.

    ``defects`` is required rather than defaulted because dropping criteria silently is the one
    outcome that must not be reachable by omission: unreported, the gap looks like a spec with
    no acceptance and nobody ever fixes it. Pass a list to collect the warning, or ``None`` only
    where the same file is already reported by another pass.
    """
    try:
        return parse_programmatic_acceptance_text(text, source=source)
    except ValueError as exc:
        if defects is not None:
            defects.append(unreadable_acceptance_warning(source, exc))
        return ()


def acceptance_checks_from_file(
    path: Path, *, defects: list[str] | None
) -> tuple[ProgrammaticAcceptance, ...]:
    """File-reading form of :func:`acceptance_checks_from_text`; same contract for ``defects``."""
    try:
        return parse_programmatic_acceptance(path)
    except ValueError as exc:
        if defects is not None:
            defects.append(unreadable_acceptance_warning(path.name, exc))
        return ()


#: An ``assert <expr>.status_code <op> <codes>`` line, with the accepted codes as written. Both the
#: membership form (``in {200, 404}``, and the tuple and list spellings) and the equality form
#: (``== 200``) are read, because the defect is about which codes a criterion admits, not how the
#: author spelled the admission.
_STATUS_ASSERT_RE = re.compile(
    r"^[ \t]*assert\b[^\n]*?\.status_code\s*(?:in\s*[\[({]\s*(?P<set>[^\])}]*)\s*[\])}]"
    r"|==\s*(?P<one>\d{3}))",
    re.MULTILINE,
)


def accepted_status_codes(code: str) -> tuple[tuple[str, frozenset[int]], ...]:
    """Return each status assertion in ``code`` as its source line and the codes it admits."""
    found: list[tuple[str, frozenset[int]]] = []
    for match in _STATUS_ASSERT_RE.finditer(code):
        if match.group("one") is not None:
            codes = {int(match.group("one"))}
        else:
            codes = {int(item) for item in re.findall(r"\d{3}", match.group("set") or "")}
        if codes:
            found.append((match.group(0).strip(), frozenset(codes)))
    return tuple(found)


def weak_status_assertion(codes: frozenset[int]) -> str:
    """Return why an accepted-status set asserts nothing, or ``""`` when it is determinate.

    A criterion states one expectation. ``404`` means the endpoint is not there, so admitting it
    beside any other code makes the criterion true of an application that implements nothing —
    which is how a real run produced 37 criteria that an empty FastAPI app satisfies. Asserted
    alone it is the opposite: a deliberate negative probe, and one of the stronger checks there is.

    A stub is not the problem and is not caught here. A stub answers, and a criterion that pins
    the status it answers with is a real test of a real contract.
    """
    if len(codes) < 2:
        return ""
    if 404 in codes:
        return (
            f"accepts {sorted(codes)}: 404 means the endpoint is absent, so this passes against "
            "an application that implements nothing. Assert 404 alone for a negative probe, or "
            "assert the status the implementation answers with."
        )
    if any(200 <= code < 300 for code in codes) and any(code >= 500 for code in codes):
        return (
            f"accepts {sorted(codes)}: success and server failure are both admitted, so the "
            "criterion holds whatever the implementation does."
        )
    return ""


def weak_acceptance_defects(
    checks: Iterable[ProgrammaticAcceptance],
) -> tuple[MalformedAcceptance, ...]:
    """Return every criterion whose status assertion admits contradictory outcomes."""
    defects: list[MalformedAcceptance] = []
    for check in checks:
        for line, codes in accepted_status_codes(check.code):
            reason = weak_status_assertion(codes)
            if reason:
                defects.append(
                    MalformedAcceptance(
                        check_id=check.check_id,
                        source=check.source,
                        reason=f"{reason} ({line})",
                    )
                )
                break
    return tuple(defects)


@dataclass(frozen=True)
class MalformedAcceptance:
    """One acceptance criterion that does not compile, and so can never execute."""

    check_id: str
    source: str
    reason: str

    @property
    def rendered(self) -> str:
        return f"{self.source} [{self.check_id}]: {self.reason}"


def syntax_defect(code: str) -> str | None:
    """Return why ``code`` is not Python at all, or ``None`` when it compiles.

    This is the one authoring fact that still gates, and it gates because it is a fact rather
    than a prediction. The analyzers that were deleted around it *predicted* that a well-formed
    assertion could not pass, which is a judgment with a false-positive rate. Compiling is not a
    judgment: a criterion that does not parse cannot execute under any implementation, so it
    verifies nothing, and no correct build can change that.

    Left ungated it is worse than useless: the fragment raises ``SyntaxError`` in its own frame,
    which the runtime classifier reads as a malformed check, which settles UNVERIFIED and costs
    the story nothing. The criterion stops gating and the story closes green.
    """
    try:
        with captured_syntax_warnings():
            compile(code, "<acceptance>", "exec")
    except SyntaxError as exc:
        where = f" (line {exc.lineno})" if exc.lineno else ""
        return f"criterion is not valid Python: {exc.msg}{where}"
    except ValueError as exc:
        # Source containing a null byte raises ValueError rather than SyntaxError.
        return f"criterion is not valid Python: {exc}"
    return None


#: ``re.<attr>(pattern, ...)`` forms whose first argument is a pattern, not already-compiled.
_REGEX_PATTERN_CALLS = frozenset({
    "compile",
    "match",
    "fullmatch",
    "search",
    "split",
    "sub",
    "subn",
    "findall",
    "finditer",
})


def regex_defects(code: str) -> tuple[str, ...]:
    """Return why each statically-known ``re`` pattern literal in ``code`` fails to compile.

    A pattern built entirely from literals is a fact about the file, exactly like
    :func:`syntax_defect`: ``re.compile`` either accepts it or it does not, independent of what
    the code under test does. Left undetected it is worse than a normal failure — the criterion
    raises ``re.error`` before any assertion runs, so it fails identically on every build attempt
    and the repair loop spends its whole budget rediscovering a fault no code change can fix. The
    real case this exists for: ``r'^(\\\\.|\\\\[|\\\\{...)'`` — the raw string escapes the
    backslash, not the bracket it precedes, so the pattern opens a character class it never
    closes.

    Only patterns Drydock can resolve without executing the criterion are checked: a string
    literal passed directly to ``re.compile``/``re.match``/etc., or a plain module-level
    assignment (``NAME = "pattern"``) later passed by name. A pattern assembled at runtime —
    formatting, concatenation with a non-literal, a value passed into a function — is out of
    reach for static analysis and is left on the same footing as any other correctness fault,
    to fail at build time on its own evidence.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        # Not parseable is a separate, already-reported fact.
        return ()

    literals: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            literals[node.targets[0].id] = node.value.value

    defects: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
            and func.attr in _REGEX_PATTERN_CALLS
        ):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        pattern: str | None = None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            pattern = arg.value
        elif isinstance(arg, ast.Name) and arg.id in literals:
            pattern = literals[arg.id]
        if pattern is None:
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            defects.append(f"line {node.lineno}: pattern {pattern!r} does not compile: {exc}")
    return tuple(defects)


#: Callables whose first positional argument names a path on disk. Matched on the terminal name,
#: so ``open``, ``io.open``, ``Path``, ``pathlib.Path`` and ``os.path.exists`` are all covered.
_PATH_ARGUMENT_NAMES = frozenset({
    "open",
    "Path",
    "PosixPath",
    "exists",
    "isfile",
    "isdir",
    "getsize",
    "stat",
})


def _opened_path_literals(tree: ast.Module) -> tuple[tuple[int, str], ...]:
    """Return ``(line, literal)`` for every statically-known path a criterion opens or stats."""
    strings = _module_string_literals(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _PATH_ARGUMENT_NAMES:
            continue
        if (literal := _literal_string(node.args[0], strings)) is not None:
            found.append((node.lineno, literal))
    return tuple(found)


def blueprint_read_defects(code: str, blueprint_dir: Path) -> tuple[str, ...]:
    """Return the Blueprint documents a criterion opens, which the build directory never holds.

    Acceptance runs with the build directory as its working directory, and the Blueprint is an
    *input* to the build: nothing copies ``ARCHITECTURE.md`` next to the code written from it. A
    criterion reading one raises ``FileNotFoundError`` in its own frame on every run, so no
    implementation and no repair pass can turn it green — it is a test that cannot run, detected
    here rather than paid for a block at a time.

    The reading is also worthless where it succeeds. A Blueprint document is the statement of
    intent the story implements, so grepping it for the words it was written with asserts that the
    specification contains itself. It passes against an empty build directory.

    Staged assets under ``sources/`` are excluded: the Analysis marks those for copying into the
    build, so a criterion invoking one names a path that will exist.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        # Not parseable is a separate, already-reported fact.
        return ()

    defects: list[str] = []
    for line, literal in _opened_path_literals(tree):
        relative = literal.removeprefix("./")
        if PurePosixPath(relative).is_absolute() or relative.startswith(_STAGED_PREFIX):
            continue
        relative = relative.removeprefix("blueprint/")
        if relative.startswith(_STAGED_PREFIX) or not (blueprint_dir / relative).is_file():
            continue
        defects.append(
            f"line {line}: reads {relative}, a Blueprint document the build directory never "
            "holds; assert against the code the story builds, not the specification it builds from"
        )
    return tuple(defects)


def imported_modules(code: str) -> tuple[tuple[int, str, tuple[str, ...]], ...]:
    """Return ``(line, module, imported names)`` for every import in a criterion.

    ``import a.b`` yields ``(line, "a.b", ())``; ``from a import x, y`` yields
    ``(line, "a", ("x", "y"))``. A relative import yields its module with the leading dots
    dropped, because a criterion runs as a top-level script and has no package to be relative to.

    The judgment lives in ``rigging_contract.import_defects``; this function only reads the text.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return ()

    found: list[tuple[int, str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((
                node.lineno,
                node.module or "",
                tuple(alias.name for alias in node.names),
            ))
    return tuple(sorted(found))


def staged_regex_defects(code: str, source_root: Path) -> tuple[str, ...]:
    """Return invalid regex arguments passed to a statically-known staged Python runner.

    A staged runner option is checked only when that runner's AST proves the option reaches
    ``re.compile``. Literal command vectors are facts; dynamic commands remain runtime evidence.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return ()

    strings = _module_string_literals(tree)
    vectors = _module_string_vectors(tree, strings)
    defects: list[str] = []
    for node in ast.walk(tree):
        if not _is_subprocess_call(node):
            continue
        command = _call_command_vector(node, strings, vectors)
        if command is None:
            continue
        source = _staged_python_argument(command, source_root)
        if source is None:
            continue
        regex_options = _runner_regex_options(source)
        for option, pattern in _option_values(command).items():
            if option not in regex_options:
                continue
            try:
                re.compile(pattern)
            except re.error as exc:
                defects.append(
                    f"line {node.lineno}: {source.relative_to(source_root.resolve()).as_posix()} "
                    f"{option} pattern {pattern!r} does not compile: {exc}"
                )
    return tuple(defects)


def _module_string_literals(tree: ast.Module) -> dict[str, str]:
    return {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _literal_string(value: ast.expr, strings: dict[str, str]) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.Name):
        return strings.get(value.id)
    return None


def _string_vector(value: ast.expr, strings: dict[str, str]) -> tuple[str | None, ...] | None:
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    return tuple(_literal_string(item, strings) for item in value.elts)


def _module_string_vectors(
    tree: ast.Module, strings: dict[str, str]
) -> dict[str, tuple[str | None, ...]]:
    vectors: dict[str, tuple[str | None, ...]] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        if (vector := _string_vector(node.value, strings)) is not None:
            vectors[node.targets[0].id] = vector
    return vectors


def _is_subprocess_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr in {"run", "call", "check_call", "check_output", "Popen"}
    )


def _call_command_vector(
    node: ast.Call,
    strings: dict[str, str],
    vectors: dict[str, tuple[str | None, ...]],
) -> tuple[str | None, ...] | None:
    value = (
        node.args[0]
        if node.args
        else next((keyword.value for keyword in node.keywords if keyword.arg == "args"), None)
    )
    if isinstance(value, ast.Name):
        return vectors.get(value.id)
    return _string_vector(value, strings) if value is not None else None


def _staged_python_argument(command: tuple[str | None, ...], source_root: Path) -> Path | None:
    root = source_root.resolve()
    for value in command:
        if value is None or not value.endswith(".py"):
            continue
        candidate = (root / value).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _option_values(command: tuple[str | None, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for index, value in enumerate(command):
        if value is None or not value.startswith("-"):
            continue
        if "=" in value:
            option, pattern = value.split("=", 1)
            values[option] = pattern
        elif index + 1 < len(command) and (pattern := command[index + 1]) is not None:
            values[value] = pattern
    return values


def _runner_regex_options(source: Path) -> frozenset[str]:
    """Return runner options whose parsed values are proven inputs to ``re.compile``."""
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return frozenset()
    regex_destinations = {
        node.args[0].attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
        and node.func.attr == "compile"
        and node.args
        and isinstance(node.args[0], ast.Attribute)
        and isinstance(node.args[0].value, ast.Name)
    }
    options: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        names = [
            arg.value
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        ]
        destination = next(
            (
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "dest"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ),
            next(
                (name.lstrip("-").replace("-", "_") for name in names if name.startswith("--")), ""
            ),
        )
        if destination in regex_destinations:
            options.update(name for name in names if name.startswith("-"))
    return frozenset(options)


#: A ``Probe:`` flag token is a plain CLI literal — never a shell fragment. Anything outside this
#: set is rejected before a probe is ever executed.
_SAFE_PROBE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./=-]+$")
#: Recognized ``Probe Count:`` protocols: one case per non-blank stdout line, or a count parsed
#: from the trailing non-blank line.
_PROBE_COUNT_MODES = frozenset({"lines", "summary"})
#: The trailing-line form a ``summary``-mode runner is expected to print, e.g. ``27 cases, 2
#: excluded``. Only the leading integer is read; the rest is the runner's own words.
_PROBE_SUMMARY_RE = re.compile(r"^(?P<count>\d+)\s+\S")
#: Wall-clock budget for a selection probe. It lists or counts cases; it never runs them.
_PROBE_TIMEOUT_SECONDS = 30


def _recognized_staged_calls(
    code: str, source_root: Path
) -> list[tuple[Path, tuple[str | None, ...], int, int]]:
    """Every ``subprocess`` call whose literal command vector names a staged ``.py`` runner.

    Returns ``(runner_path, command, runner_index, node.lineno)`` per call, reusing the same
    static recognition :func:`staged_regex_defects` uses. ``command`` may still contain ``None``
    at positions other than the runner itself (a dynamic interpreter path, for instance) — only
    the runner argument is required to be literal.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    strings = _module_string_literals(tree)
    vectors = _module_string_vectors(tree, strings)
    root = source_root.resolve()
    calls: list[tuple[Path, tuple[str | None, ...], int, int]] = []
    for node in ast.walk(tree):
        if not _is_subprocess_call(node):
            continue
        command = _call_command_vector(node, strings, vectors)
        if command is None:
            continue
        source = _staged_python_argument(command, source_root)
        if source is None:
            continue
        index = next(
            i
            for i, value in enumerate(command)
            if value is not None and (root / value).resolve() == source
        )
        calls.append((source, command, index, node.lineno))
    return calls


def selector_recognition(code: str, source_root: Path) -> tuple[str, str, str, int] | None:
    """Return ``(runner_relpath, option, value, lineno)`` for the first statically-known staged
    corpus-selector call in ``code``, or ``None`` when no such call is recognized.

    A selector is any literal ``-``-prefixed option paired with a literal value in a fully
    resolvable staged-runner command. Drydock cannot know a staged runner's own flag semantics, so
    every such pair is treated as selection-shaped and made to prove it selects something.
    """
    for source, command, _index, lineno in _recognized_staged_calls(code, source_root):
        options = _option_values(command)
        if not options:
            continue
        option, value = next(iter(options.items()))
        return (source.relative_to(source_root.resolve()).as_posix(), option, value, lineno)
    return None


def dynamic_selector_advisory(check: ProgrammaticAcceptance, *, blueprint_dir: Path) -> str | None:
    """Advisory when a staged runner is invoked with a selector built at runtime.

    The recognition that feeds :func:`selection_probe_reason` requires a literal option/value
    pair to construct a probe from. A selector assembled from a variable is out of that reach —
    real evidence, not a prediction — so it is reported rather than gated; :mod:`build_run`'s
    zero-case handling still guards it when the build actually runs.
    """
    for source, command, index, lineno in _recognized_staged_calls(check.code, blueprint_dir):
        if _option_values(command):
            continue
        if any(value is None for value in command[index + 1 :]):
            relpath = source.relative_to(blueprint_dir.resolve()).as_posix()
            return (
                f"line {lineno}: {relpath} is invoked with a selector Drydock cannot statically "
                "resolve, so its selection cannot be proven non-empty before build"
            )
    return None


def selection_probe_reason(
    check: ProgrammaticAcceptance, *, blueprint_dir: Path
) -> tuple[str, str] | None:
    """Judge whether a recognized staged-runner selector is proven to select at least one case.

    Returns ``(kind, reason)`` for one of four hard defects, or ``None`` when no selector is
    recognized or the declared probe proves a non-empty selection:

    - ``missing-selection-probe`` — a selector is recognized and no ``Probe:`` is declared.
    - ``invalid-selection-probe`` — ``Probe:``/``Probe Count:`` is malformed; nothing executes.
    - ``probe-failed`` — the probe ran and exited nonzero, timed out, or its declared count
      protocol did not hold. A failed probe is never read as "zero selected".
    - ``empty-selection`` — the probe ran cleanly and counted zero cases.
    """
    recognized = selector_recognition(check.code, blueprint_dir)
    if recognized is None:
        return None
    runner, option, value, lineno = recognized
    where = f"line {lineno}: {runner} {option} {value!r} selects a subset of a staged corpus"

    if not check.probe:
        return (
            "missing-selection-probe",
            f"{where} with no declared Probe: to prove the selection is non-empty before build",
        )

    probe_flags = check.probe.split()
    if not probe_flags or any(_SAFE_PROBE_TOKEN_RE.match(flag) is None for flag in probe_flags):
        return (
            "invalid-selection-probe",
            f"{where}: Probe: {check.probe!r} is empty or not a plain flag literal",
        )
    if check.probe_count not in _PROBE_COUNT_MODES:
        return (
            "invalid-selection-probe",
            f"{where}: Probe Count: {check.probe_count!r} must be 'lines' or 'summary'",
        )

    argv = [sys.executable, str(blueprint_dir.resolve() / runner), option, value, *probe_flags]
    try:
        result = subprocess.run(
            argv,
            cwd=blueprint_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={"PATH": os.environ.get("PATH", "")},
            timeout=_PROBE_TIMEOUT_SECONDS,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ("probe-failed", f"{where}: probe could not run: {exc}")

    if result.returncode != 0:
        stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
        detail = stderr_lines[-1] if stderr_lines else f"exit {result.returncode}"
        return ("probe-failed", f"{where}: probe exited {result.returncode}: {detail}")

    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    if check.probe_count == "lines":
        count = len(stdout_lines)
    else:
        match = _PROBE_SUMMARY_RE.match(stdout_lines[-1]) if stdout_lines else None
        if match is None:
            return (
                "probe-failed",
                f"{where}: probe output does not match the declared 'summary' protocol",
            )
        count = int(match.group("count"))

    if count == 0:
        return ("empty-selection", f"{where}: probe selected 0 cases")
    return None


def escape_defects(code: str) -> tuple[str, ...]:
    """Return the compiler's escape-sequence advisories for one criterion.

    This reports rather than gates, and the distinction is the whole point. ``'"value=\\(.)"'``
    is what a jq target's interpolation test looks like, and CPython preserves the bytes it
    describes, so the criterion runs and proves what it claims. Two things are nonetheless worth
    telling the author: the escape is not the one they wrote — it survives by a rule that is
    scheduled to become a hard ``SyntaxError`` — and a literal carrying a backslash also fails
    ``_is_escapable``, which silently drops the criterion's ``binding`` flag.

    The fix is a raw string or a doubled backslash, and it is the author's to make. Rewriting
    the literal here would change what a proof asserts, which is not a thing to do quietly.
    """
    try:
        with captured_syntax_warnings() as caught:
            compile(code, "<acceptance>", "exec")
    except (SyntaxError, ValueError):
        # Not compilable at all is a separate, already-reported fact.
        return ()
    return tuple(
        f"line {entry.lineno}: {entry.message}"
        for entry in caught
        if issubclass(entry.category, SyntaxWarning)
    )


_IMPLICIT_SCRIPT_GLOBALS = frozenset({
    "__builtins__",
    "__cached__",
    "__file__",
    "__loader__",
    "__name__",
    "__package__",
    "__spec__",
})


def unresolved_globals(code: str) -> tuple[str, ...]:
    """Return names read by a standalone assertion but never imported or assigned.

    Acceptance criteria execute as isolated scripts. A global supplied by another criterion or
    by the process invoking Drydock therefore does not exist. Python's symbol table handles nested
    scopes and comprehensions without guessing from source text; builtins and interpreter-provided
    script globals remain valid.
    """
    try:
        with captured_syntax_warnings():
            root = symtable.symtable(code, "<acceptance>", "exec")
    except (SyntaxError, ValueError):
        return ()
    module_bindings = {
        symbol.get_name()
        for symbol in root.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }
    available = module_bindings | frozenset(dir(builtins)) | _IMPLICIT_SCRIPT_GLOBALS
    unresolved: set[str] = set()

    def inspect(table: symtable.SymbolTable) -> None:
        for symbol in table.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in available:
                unresolved.add(symbol.get_name())
        for child in table.get_children():
            inspect(child)

    inspect(root)
    return tuple(sorted(unresolved))


#: Calls that run a program and hand its output back as a value rather than to the console.
_CAPTURING_CALLS = frozenset({"run", "check_output", "getoutput", "getstatusoutput", "Popen"})


def captures_without_reporting(code: str) -> bool:
    """True when a criterion runs a program, captures its output, and reports none of it.

    A criterion in this shape answers one bit. Whatever the program printed — the suite tally,
    the failing cases, the diagnostic that explains the exit code — is bound to a variable and
    then thrown away, so the failure is reported as a bare assertion and two attempts that
    differ by a hundred passing cases are indistinguishable. The acceptance harness recovers
    what it can from the failing frame; printing is how the criterion states it outright.
    """
    try:
        with captured_syntax_warnings():
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    captures = False
    reports = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        if name == "print":
            reports = True
        elif name in _CAPTURING_CALLS:
            captures = True
    return captures and not reports


def malformed_criteria(
    checks: tuple[ProgrammaticAcceptance, ...],
) -> tuple[MalformedAcceptance, ...]:
    """Return every criterion that does not compile. A hard authoring defect, not a warning."""
    return tuple(
        MalformedAcceptance(check_id=check.check_id, source=check.source, reason=reason)
        for check in checks
        if (reason := syntax_defect(check.code)) is not None
    )


def programmatic_acceptance_for_step(
    block: PlanBlock, blueprint_dir: Path, *, defects: list[str] | None
) -> tuple[ProgrammaticAcceptance, ...]:
    """Load programmatic assertions from the Blueprint files a step implements.

    See :func:`acceptance_checks_from_text` for the ``defects`` contract.
    """
    checks: list[ProgrammaticAcceptance] = []
    for name in block.fields.get("implements", ()):
        if not isinstance(name, str):
            continue
        path = blueprint_dir / name
        if path.is_file():
            checks.extend(acceptance_checks_from_file(path, defects=defects))
    return tuple(checks)


def all_programmatic_acceptance(
    plan: BuildPlan, blueprint_dir: Path, *, defects: list[str] | None
) -> tuple[ProgrammaticAcceptance, ...]:
    """Every Blueprint assertion the plan implements, deduped by ``(source, check_id)``.

    This is the projection source for ``SOUNDINGS.md``: one entry per individual Programmatic
    Acceptance assertion across the Blueprint spec files the plan's stories implement.
    """
    checks: list[ProgrammaticAcceptance] = []
    seen: set[tuple[str, str]] = set()
    for block in plan.blocks:
        if block.block_type != "story":
            continue
        for name in block.fields.get("implements", ()):
            if not isinstance(name, str):
                continue
            path = blueprint_dir / name
            if not path.is_file():
                continue
            for check in acceptance_checks_from_file(path, defects=defects):
                key = (check.source, check.check_id)
                if key in seen:
                    continue
                seen.add(key)
                checks.append(check)
    return tuple(checks)


def _foundation_packages() -> dict[str, str]:
    """Return ``{package: "the <kind> foundation (<file>)"}`` for every published foundation."""
    from drydock.rigging_contract import published_packages

    try:
        published = published_packages()
    except (OSError, ValueError):
        return {}
    return {
        package: f"the {contracts[0].kind} foundation ({', '.join(c.filename for c in contracts)})"
        for package, contracts in published.items()
    }


def _unbuilt_foundation_failure(
    code: str, build_dir: Path, packages: Mapping[str, str]
) -> str | None:
    """Return the failure for a criterion whose foundation package is absent, else ``None``.

    Decided before the criterion runs. ``from app_server.testing import web_client`` against a
    build directory with no ``app_server/`` can only raise ``ModuleNotFoundError``, and a
    criterion that runs the application's pytest suite would fail inside pytest's collection
    instead — neither says what is wrong as plainly as naming the package that was never built.
    """
    missing: list[str] = []
    for _line, module, _names in imported_modules(code):
        root = module.split(".", 1)[0]
        if root not in packages or root in missing:
            continue
        if (build_dir / root).is_dir() or (build_dir / f"{root}.py").is_file():
            continue
        missing.append(root)
    if not missing:
        return None
    return (
        f"{UNBUILT_FOUNDATION_FAILURE_PREFIX}: "
        + "; ".join(
            f"`{root}` is the package {packages[root]} builds, and the build directory has no "
            f"`{root}/`"
            for root in missing
        )
        + ". The criterion exercises the built application, so it was not run."
    )


def run_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
    strict_target: bool = False,
    on_item: Callable[[ProgrammaticAcceptance, int, int, bool], None] | None = None,
) -> tuple[AcceptanceRunResult, ...]:
    """Execute Python acceptance snippets from the build directory.

    ``on_item`` fires once per check, after it finishes, with whether it passed — a check
    announced before it runs cannot yet be marked, and a live progress line that cannot say
    pass or fail is not worth the line.
    """
    results: list[AcceptanceRunResult] = []
    environment = resolve_target_environment(build_dir)
    if environment.interpreter is None:
        # No interpreter means not one assertion ran. That is a fault in the kit, so every
        # check is UNVERIFIED rather than a fleet of product failures.
        return tuple(
            AcceptanceRunResult(
                check_id=check.check_id,
                source=check.source,
                intent=check.intent,
                passed=False,
                return_code=None,
                stdout="",
                stderr="",
                error=(
                    f"{UNVERIFIED_FAILURE_PREFIX}: acceptance environment unavailable: "
                    f"{environment.detail}"
                ),
                skipped=True,
                provisioning_result=environment.provisioning_result,
                binding=check.binding,
            )
            for check in checks
        )
    pythonpath = os.pathsep.join(
        part
        for part in (
            str(build_dir),
            "" if strict_target else os.environ.get("PYTHONPATH", ""),
        )
        if part
    )
    env = {
        **os.environ,
        "DRYDOCK_BUILD_DIR": str(build_dir),
        "DRYDOCK_TARGET_DIR": str(target_dir),
        "DRYDOCK_BLUEPRINT_DIR": str(blueprint_dir),
        "PYTHONPATH": pythonpath,
    }
    from drydock.database_apply import apply_schema

    application = apply_schema(build_dir, env=env, verify_only=True)
    if application is not None and not application.applied:
        return tuple(
            AcceptanceRunResult(
                check_id=check.check_id,
                source=check.source,
                intent=check.intent,
                passed=False,
                return_code=1,
                stdout="",
                stderr=application.detail,
                error="persistence verification failed: " + application.detail,
                binding=check.binding,
            )
            for check in checks
        )
    limit_mb = get_sandbox_mem_limit_mb()
    preexec = child_limits(limit_mb)
    packages = _foundation_packages()
    for index, check in enumerate(checks, start=1):
        if unbuilt := _unbuilt_foundation_failure(check.code, build_dir, packages):
            results.append(
                AcceptanceRunResult(
                    check_id=check.check_id,
                    source=check.source,
                    intent=check.intent,
                    passed=False,
                    return_code=None,
                    stdout="",
                    stderr="",
                    error=unbuilt,
                    interpreter=str(environment.interpreter),
                    provisioning_result=environment.provisioning_result,
                    # The miss is a fact about the build, not about a re-typed expectation.
                    binding=True,
                )
            )
            if on_item is not None:
                on_item(check, index, len(checks), False)
            continue
        # Run from a real file, never ``python -c``: a ``-c`` traceback reports
        # ``File "<string>", line N`` with no source text, so a failing assertion names
        # neither the assertion nor the expectation it asserted. Written to a file, the
        # traceback carries the offending line and the failure is diagnosable in one pass.
        with tempfile.TemporaryDirectory(prefix="drydock-acceptance-") as tmp:
            script = Path(tmp) / f"{check.check_id or 'acceptance'}.py"
            script.write_text(check.code + "\n", encoding="utf-8")
            # The criterion runs through the value-capture harness rather than directly, so a
            # failed assertion reports the values it observed and not only its own source line.
            # The harness is copied beside the criterion because it executes under the Target's
            # interpreter, which cannot be assumed able to import Drydock.
            runner = Path(tmp) / "_drydock_acceptance_runner.py"
            shutil.copyfile(_RUNNER_SOURCE, runner)
            # The Go bridge remains usable from the existing Python AC container.
            shutil.copyfile(
                get_language_dir("go") / "acceptance" / "drydock_go.py",
                Path(tmp) / "drydock_go.py",
            )
            # Own session so the timeout can reap the whole tree, and a bounded address
            # space so a runaway is stopped by the kernel long before the timeout.
            process = subprocess.Popen(
                [str(environment.interpreter), str(runner), str(script)],
                cwd=build_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=os.name == "posix",
                preexec_fn=preexec,
            )
            try:
                stdout, stderr = process.communicate(timeout=check.timeout_seconds)
            except subprocess.TimeoutExpired:
                kill_process_group(process)
                stdout, stderr = process.communicate()
                results.append(
                    AcceptanceRunResult(
                        check_id=check.check_id,
                        source=check.source,
                        intent=check.intent,
                        passed=False,
                        return_code=None,
                        stdout=_timeout_output_text(stdout),
                        stderr=_scrub_script_path(_timeout_output_text(stderr), script),
                        error=_timeout_failure_text(check),
                        interpreter=str(environment.interpreter),
                        provisioning_result=environment.provisioning_result,
                        binding=check.binding,
                    )
                )
                if on_item is not None:
                    on_item(check, index, len(checks), False)
                continue
            return_code = process.returncode
            scrubbed = _scrub_script_path(stderr, script)
            verdict = (
                _resource_failure(return_code, stderr, limit_mb)
                or _environment_failure(return_code, scrubbed, script.name, check.requirements)
                or _malformed_failure(return_code, scrubbed, script.name, build_dir)
                or _missing_fixture_failure(return_code, scrubbed, check.code, build_dir)
            )
            native_statuses = re.findall(
                r'^DRYDOCK_NATIVE_RESULT=\{"status": "([^"\n]+)"\}', stderr, re.MULTILINE
            )
            native_failure = next(
                (status for status in native_statuses if status in {"fail", "execution-error"}),
                None,
            ) or next((status for status in native_statuses if status != "pass"), None)
            if native_failure:
                return_code = return_code or 1
                prefix = (
                    UNVERIFIED_FAILURE_PREFIX
                    if native_failure in {"skip", "not-run", "unavailable"}
                    else "native acceptance"
                )
                verdict = f"{prefix}: {native_failure}"
            # A malformed snippet, a missing fixture, and an environment fault all mean the
            # same thing: the code under test was never exercised. None is charged to the build.
            skipped = bool(
                verdict
                and verdict.startswith((
                    SKIPPED_FAILURE_PREFIX,
                    UNVERIFIED_FAILURE_PREFIX,
                    MALFORMED_FAILURE_PREFIX,
                ))
            )
        results.append(
            AcceptanceRunResult(
                check_id=check.check_id,
                source=check.source,
                intent=check.intent,
                passed=return_code == 0,
                return_code=return_code,
                stdout=stdout,
                stderr=scrubbed,
                error=verdict,
                skipped=skipped,
                interpreter=str(environment.interpreter),
                provisioning_result=environment.provisioning_result,
                binding=check.binding,
            )
        )
        if on_item is not None:
            on_item(check, index, len(checks), return_code == 0)
    return tuple(results)


def observe_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
    strict_target: bool = False,
    on_item: Callable[[ProgrammaticAcceptance, int, int, bool], None] | None = None,
) -> tuple[AcceptanceObservation, ...]:
    """Execute checks and annotate whether a passing proof is integrity-valid or vacuous."""
    if not checks:
        return ()
    runtime = run_programmatic_acceptance(
        checks,
        build_dir=build_dir,
        target_dir=target_dir,
        blueprint_dir=blueprint_dir,
        strict_target=strict_target,
        on_item=on_item,
    )
    observations: list[AcceptanceObservation] = []
    for check, result in zip(checks, runtime, strict=True):
        integrity = analyze_proof(check.code)
        observations.append(
            AcceptanceObservation(
                check_id=result.check_id,
                source=result.source,
                intent=result.intent,
                passed=result.passed,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                error=result.error,
                skipped=result.skipped,
                integrity_ok=integrity.ok,
                integrity_reasons=integrity.reasons,
            )
        )
    return tuple(observations)
