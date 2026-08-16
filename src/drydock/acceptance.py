"""Blueprint-owned acceptance assertions for build verification."""

from __future__ import annotations

import ast
import builtins
import json
import os
import re
import shutil
import signal
import subprocess
import symtable
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from drydock.acceptance_runner import VALUES_BEGIN, VALUES_END
from drydock.acceptance_taxonomy import load_acceptance_failure_taxonomy
from drydock.build_plan import BuildPlan, PlanBlock
from drydock.child_sandbox import child_limits, kill_process_group
from drydock.config import get_sandbox_mem_limit_mb
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
#: Leading ``Key: value`` metadata lines inside an AC block, terminated by the first blank line.
AC_META_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9 _-]*):[ \t]*(?P<value>.*?)[ \t]*$")
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
_RUNNER_SOURCE = Path(__file__).with_name("acceptance_runner.py")
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


def split_captured_values(stderr: str) -> tuple[list[str], str]:
    """Separate the harness's value block from the criterion's own stderr.

    Returns ``(value_lines, remaining_stderr)``. The values are reported as their own section
    because they are the answer to the reader's question — what did the criterion actually
    observe — and burying them above a traceback puts the answer where nobody looks.
    """
    text = stderr or ""
    if VALUES_BEGIN not in text:
        return [], text
    before, _, rest = text.partition(VALUES_BEGIN)
    block, _, after = rest.partition(VALUES_END)
    values = [line.rstrip() for line in block.splitlines() if line.strip()]
    remaining = (before + after.lstrip("\n")) if after else before
    return values, remaining


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
) -> list[str]:
    """Render one failed check as a readable block: the assertion, the exit, what it observed.

    This is the whole diagnostic an operator needs at the point of failure. It is deliberately
    bounded: the summary line, where the assertion lives, the exit code, the exception, the tail
    of the check's own reported output, and the tail of its stderr. The full streams stay in the
    evidence file for the reader who wants them.

    The stderr tail is not redundant with the summary. A check that prints nothing before it
    asserts — the common shape for a boundary check — leaves ``observed output`` empty, and
    without the traceback the report states an ``AssertionError`` with no account of how it was
    reached. The traceback is that account, and it is on stderr.
    """
    values, stderr = split_captured_values(stderr)
    lines = [f"{indent}assertion: {assertion_summary(stderr, error, override=override)}"]
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
        lines.append(f"{indent}observed output:")
        lines.extend(f"{indent}  {line}" for line in observed[-OBSERVED_OUTPUT_LINES:])
    diagnostic = [line.rstrip() for line in (stderr or "").splitlines() if line.strip()]
    if diagnostic:
        lines.append(f"{indent}check stderr:")
        lines.extend(f"{indent}  {line}" for line in diagnostic[-DIAGNOSTIC_OUTPUT_LINES:])
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
    #: The character encoding this criterion deliberately exercises, from its ``Encoding:``
    #: declaration. Empty is the norm and means the criterion is ASCII, which is what the
    #: authoring gate enforces. A target whose specification genuinely states an encoding
    #: requirement declares it here and may then use non-ASCII test data.
    encoding: str = ""

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
        """Expected string literals this criterion re-typed instead of binding to its input."""
        return retyped_expectations(self.code)

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
_AC_META_KEYS = frozenset({"intent", "suite", "requires", "sea trials", "encoding"})


def _parse_ac_block(body: str, *, check_id: str, source: str) -> ProgrammaticAcceptance:
    """Split one AC block into its declarations and its verbatim proof body."""
    lines = body.splitlines()
    # The slice begins at the end of the opening marker's text, so the first element is that
    # line's terminator rather than content. Dropping it keeps the metadata run at the top.
    if lines and not lines[0].strip():
        lines = lines[1:]
    meta: dict[str, list[str]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            break
        match = AC_META_RE.match(line)
        if match is None or match.group("key").strip().lower() not in _AC_META_KEYS:
            break
        meta.setdefault(match.group("key").strip().lower(), []).append(match.group("value"))
        index += 1
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
        encoding=" ".join(meta.get("encoding", ())).strip().lower(),
    )


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


#: A string expectation an author cannot mis-escape: an identifier-shaped ASCII token. ``"string"``,
#: ``"integer"``, ``"application/json"``, and ``"POST"`` are read off a declared interface and carry
#: nothing to escape. Markup, whitespace, backslashes, quotes, and control characters are excluded:
#: each has to be escaped correctly twice — once building the input, once stating the expectation —
#: and that is the assertion class that fails independently of the product.
#:
#: ``\Z`` rather than ``$``: ``$`` also matches before a trailing newline, which would admit exactly
#: the rendered-output literals this is meant to exclude.
_CONTRACT_TOKEN_RE = re.compile(r"[A-Za-z0-9_./+-]*\Z")

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
    return not value.isascii() or not _CONTRACT_TOKEN_RE.match(value)


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


def _comparison_expectations(tree: ast.AST) -> tuple[ast.Constant, ...]:
    """Return the string constants asserted as expected values by an ``==`` comparison."""
    found: list[ast.Constant] = []
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
    return tuple(found)


@cache
def retyped_expectations(code: str) -> tuple[str, ...]:
    """Return expected string literals the criterion re-typed rather than bound to its input.

    This is the whole of the authoring rule, and it is a whitelist over a decidable property
    rather than a catalogue of observed failures. An expected value is legal when it is a status
    code, a value read back from the input the criterion supplied, or a contract token carrying
    nothing escapable. It is illegal when the author typed the expected bytes a second time,
    because that is the one assertion that can be wrong while the product is right.

    The case this exists for, from a real run::

        source = 'raw = \\'C:\\\\\\\\Users\\\\\\\\nodejs\\'\\n'
        assert decoded["raw"]["value"] == r"C:\\Users\\nodejs"

    A TOML literal string preserves its backslashes, so the expectation was wrong and the decoder
    was right. Binding the value to a name and using it on both sides removes the second escaping
    decision, and with it the entire failure class.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Not parseable is a separate, already-reported fact. Nothing to classify.
        return ()
    supplied = _supplied_literals(tree)
    offending = [
        node.value
        for node in _comparison_expectations(tree)
        if _is_escapable(node.value) and node.value not in supplied
    ]
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
    return parse_programmatic_acceptance_text(
        source.read_text(encoding="utf-8"), source=source.name
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
        compile(code, "<acceptance>", "exec")
    except SyntaxError as exc:
        where = f" (line {exc.lineno})" if exc.lineno else ""
        return f"criterion is not valid Python: {exc.msg}{where}"
    except ValueError as exc:
        # Source containing a null byte raises ValueError rather than SyntaxError.
        return f"criterion is not valid Python: {exc}"
    return None


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


#: Where a build records criteria that were already green at their block's baseline — before that
#: block's code existed. Two different situations produce it: a criterion that exercises nothing
#: (a suite selector matching no cases exits zero), and a deliverable that legitimately already
#: existed. Only the baseline can observe either, and only the build takes a baseline, so the fact
#: is written here for ``drydock score ac`` to report. It is reported, never gated: the two causes
#: are indistinguishable from the baseline alone, and failing the second would break correct
#: builds. A missing file simply means no baseline has been recorded yet.
PREPASSED_ACCEPTANCE_EVIDENCE = "prepassed-acceptance.json"


def record_prepassed_acceptance(evidence_dir: Path, check_ids: Iterable[str]) -> None:
    """Merge ``check_ids`` into the target's record of criteria green before their block built."""
    incoming = set(check_ids)
    if not incoming:
        return
    known = set(read_prepassed_acceptance(evidence_dir)) | incoming
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / PREPASSED_ACCEPTANCE_EVIDENCE).write_text(
        json.dumps({"prepassed": sorted(known)}, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def read_prepassed_acceptance(evidence_dir: Path) -> frozenset[str]:
    """Return criterion ids a build found green at baseline, or an empty set."""
    try:
        payload = json.loads(
            (evidence_dir / PREPASSED_ACCEPTANCE_EVIDENCE).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return frozenset()
    entries = payload.get("prepassed") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(str(entry) for entry in entries)


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
    block: PlanBlock, blueprint_dir: Path
) -> tuple[ProgrammaticAcceptance, ...]:
    """Load programmatic assertions from the Blueprint files a step implements."""
    checks: list[ProgrammaticAcceptance] = []
    for name in block.fields.get("implements", ()):
        if not isinstance(name, str):
            continue
        path = blueprint_dir / name
        if path.is_file():
            checks.extend(parse_programmatic_acceptance(path))
    return tuple(checks)


def all_programmatic_acceptance(
    plan: BuildPlan, blueprint_dir: Path
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
            for check in parse_programmatic_acceptance(path):
                key = (check.source, check.check_id)
                if key in seen:
                    continue
                seen.add(key)
                checks.append(check)
    return tuple(checks)


def run_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
    strict_target: bool = False,
) -> tuple[AcceptanceRunResult, ...]:
    """Execute Python acceptance snippets from the build directory."""
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
    limit_mb = get_sandbox_mem_limit_mb()
    preexec = child_limits(limit_mb)
    for check in checks:
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
                continue
            return_code = process.returncode
            scrubbed = _scrub_script_path(stderr, script)
            verdict = (
                _resource_failure(return_code, stderr, limit_mb)
                or _environment_failure(return_code, scrubbed, script.name, check.requirements)
                or _malformed_failure(return_code, scrubbed, script.name, build_dir)
                or _missing_fixture_failure(return_code, scrubbed, check.code, build_dir)
            )
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
    return tuple(results)


def observe_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
    strict_target: bool = False,
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
