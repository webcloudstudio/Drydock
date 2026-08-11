"""Blueprint-owned acceptance assertions for build verification."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from drydock.build_plan import BuildPlan, PlanBlock
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
TIMEOUT_SECONDS = 60
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
OUTCOMES = (OUTCOME_PASS, OUTCOME_FAIL, OUTCOME_UNVERIFIED)

# Category prefixes for a check that failed by exhausting a resource rather than by missing
# an expectation. Consumers use these to gate a repair pass on the resource fact.
MEMORY_FAILURE_PREFIX = "exhausted memory"
TIMEOUT_FAILURE_PREFIX = "timed out"
SKIPPED_FAILURE_PREFIX = "skipped acceptance"
UNVERIFIED_FAILURE_PREFIX = "unverified acceptance"
# A check that died inside its own snippet rather than inside the code under test. No
# implementation can turn it green, so a repair pass on it is wasted.
MALFORMED_FAILURE_PREFIX = "malformed check"
_MEMORY_SIGNATURES = ("MemoryError", "Cannot allocate memory", "std::bad_alloc", "Killed")
# Exceptions that, when raised by the snippet's own frame, mean the snippet is defective:
# it reads a name it never bound or does not parse. Neither is a statement about the code
# under test.
_MALFORMED_EXCEPTIONS = frozenset({
    "NameError",
    "UnboundLocalError",
    "SyntaxError",
    "IndentationError",
    "TabError",
})
# Exceptions that, raised in the snippet's own frame, mean the check never reached the code
# under test: the filesystem or the environment refused it. ``ConnectionError`` and friends are
# deliberately absent — a refused connection to the service under test is a product defect.
_ENVIRONMENT_EXCEPTIONS = frozenset({
    "FileNotFoundError",
    "IsADirectoryError",
    "NotADirectoryError",
    "PermissionError",
})
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


def _child_limits(limit_mb: int) -> Callable[[], None] | None:
    """A ``preexec_fn`` capping the child's address space, or ``None`` when unavailable.

    ``RLIMIT_AS`` is inherited across ``fork``/``exec``, so the bound also covers every
    process the check spawns — the runner, the built program under it, and so on. That is
    the point: the runaway is never the acceptance snippet itself, it is the built code the
    snippet invokes.
    """
    if limit_mb <= 0 or os.name != "posix":
        return None
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return None

    ceiling = limit_mb * 1024 * 1024

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
        # A multi-GB core dump from a bounded runaway helps nobody and costs the disk.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    """Kill the check's whole process group, not just the process Drydock started.

    A check that shells out leaves grandchildren. Killing only the direct child orphans
    them, and a runaway grandchild then survives the timeout that was meant to stop it.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        process.kill()


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


def _own_frame_exception(return_code: int, stderr: str, script_name: str) -> tuple[str, str] | None:
    """Return ``(exception, detail)`` when the check died in its own frame, else ``None``.

    Attribution is by traceback frame, not by exception type alone. The same exception means
    opposite things depending on where it was raised: inside the code under test it is a
    genuine red the build must drive green; inside the check's own frame it says the check
    never reached the code under test at all.
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
    if not frames or Path(frames[-1]).name != script_name:
        # The failure surfaced inside the code under test. That is the build's job to fix.
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
    Only failures raised in the check's own frame qualify — the same exception from inside the
    built code is a product defect and stays a FAIL.
    """
    attributed = _own_frame_exception(return_code, stderr, script_name)
    if attributed is None:
        return None
    exception, detail = attributed
    if exception in _ENVIRONMENT_EXCEPTIONS:
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


def _malformed_failure(return_code: int, stderr: str, script_name: str) -> str | None:
    """Classify a non-zero exit as a defective snippet, or ``None`` when it is not.

    ``NameError`` raised inside the code under test is a genuine red the build must drive
    green; the same exception raised in the check's own frame means the check reads a name
    nothing binds — most often a name a sibling check defined, which is not in scope because
    every check runs as its own script in its own process.
    """
    attributed = _own_frame_exception(return_code, stderr, script_name)
    if attributed is None:
        return None
    exception, detail = attributed

    # ``ImportError`` is deliberately absent. A missing module is the *expected* red baseline
    # before the code under test is written, and nothing in the traceback distinguishes that
    # from a typo'd import. Classifying it would block builds that should proceed, so it is
    # left to the build.
    if exception in _MALFORMED_EXCEPTIONS:
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

    @property
    def timeout_seconds(self) -> int:
        """A suite-bound check runs a whole conformance suite, not a story unit test."""
        return SUITE_TIMEOUT_SECONDS if self.full_suite else TIMEOUT_SECONDS


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

    @property
    def outcome(self) -> str:
        """PASS, FAIL, or UNVERIFIED — the three-valued verdict for this assertion.

        ``skipped`` is the storage for UNVERIFIED so that every consumer written against the
        older two-valued model keeps excluding these results from the build's tally, which is
        exactly what UNVERIFIED requires.
        """
        if self.skipped:
            return OUTCOME_UNVERIFIED
        return OUTCOME_PASS if self.passed else OUTCOME_FAIL

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
_AC_META_KEYS = frozenset({"intent", "suite", "requires", "sea trials"})


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
class DroppedAcceptance:
    """One acceptance criterion a static analyzer believes cannot pass, as authored."""

    check_id: str
    reason: str


def unsatisfiable_defects(code: str, *, sources_dir: Path | None = None) -> tuple[str, ...]:
    """Return every reason ``code`` can never pass, whatever the implementation does.

    ``sources_dir`` is the staged-asset directory the proof runs against. When given, the
    analysis also reads the assets the proof invokes and checks their declared preconditions;
    without it that class of defect is simply not reported.
    """
    from drydock.proof_integrity import (
        analyze_invocation,
        analyze_literals,
        analyze_output_assertions,
        analyze_shell_escapes,
        analyze_staged_invocation,
        analyze_structure,
    )

    messages = [
        defect.message
        for analyze in (
            analyze_literals,
            analyze_structure,
            analyze_invocation,
            analyze_shell_escapes,
        )
        for defect in analyze(code)
    ]
    # Only the fatal output assertions belong here. A merely redundant substring check still
    # passes when the code is correct, so it is a warning, not grounds for dropping the check.
    messages.extend(defect.message for defect in analyze_output_assertions(code) if defect.fatal)
    messages.extend(
        defect.message for defect in analyze_staged_invocation(code, sources_dir=sources_dir)
    )
    return tuple(messages)


def flag_unsatisfiable_acceptance(
    text: str, *, source: str, sources_dir: Path | None = None
) -> tuple[DroppedAcceptance, ...]:
    """Report acceptance criteria a static analyzer believes cannot pass. Never edits the spec.

    These analyzers are the real prize of the work that produced them: each is a tested
    description of one way a model writes a broken assertion. As *gates* they fight the model
    after the fact and accumulate false positives — the space of bad assertions is not
    enumerable, every analyzer carries its own false-positive rate against legitimate snippets,
    and two were retracted after they started failing fixtures that had passed for weeks.

    So the knowledge is kept and the enforcement is dropped. A finding here is a warning that
    may cost marks, never a removal and never a hard gate. The runtime classifier is what
    protects the build now: a snippet that truly dies in its own frame reports UNVERIFIED and is
    not charged against the build, and it does so from what actually happened rather than from a
    prediction about what would.
    """
    checks = parse_programmatic_acceptance_text(text, source=source)
    return tuple(
        DroppedAcceptance(check_id=check.check_id, reason=defects[0])
        for check in checks
        if (defects := unsatisfiable_defects(check.code, sources_dir=sources_dir))
    )


def syntax_defect(code: str) -> str | None:
    """Return why ``code`` is not Python at all, or ``None`` when it compiles.

    This is deliberately not one of the ``unsatisfiable_defects`` heuristics, and it is gated
    where those are only reported. Those analyzers *predict* that a well-formed assertion cannot
    pass, which is a judgment with a false-positive rate — two were retracted for exactly that.
    Compiling is not a prediction. A criterion that does not parse cannot execute under any
    implementation, so it verifies nothing, and no correct build can change that.

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


@dataclass(frozen=True)
class QuarantinedAcceptance:
    """One acceptance criterion a static analyzer flagged as unable to pass, as authored."""

    check_id: str
    source: str
    reason: str

    @property
    def rendered(self) -> str:
        return f"{self.source} [{self.check_id}]: {self.reason}"


def flag_unsatisfiable(
    checks: tuple[ProgrammaticAcceptance, ...], *, sources_dir: Path | None = None
) -> tuple[QuarantinedAcceptance, ...]:
    """Report criteria a static analyzer believes cannot pass, without excluding any of them.

    Excluding a criterion from grading on a static prediction is enforcement, and enforcement
    is what these analyzers are no longer for. A criterion that genuinely dies in its own frame
    now settles as UNVERIFIED at run time on the evidence of the traceback, which costs the
    build nothing and does not depend on an analyzer being right in advance.
    """
    return tuple(
        QuarantinedAcceptance(check_id=check.check_id, source=check.source, reason=defects[0])
        for check in checks
        if (defects := unsatisfiable_defects(check.code, sources_dir=sources_dir))
    )


def malformed_criteria(
    checks: tuple[ProgrammaticAcceptance, ...],
) -> tuple[QuarantinedAcceptance, ...]:
    """Return every criterion that does not compile. A hard authoring defect, not a warning."""
    return tuple(
        QuarantinedAcceptance(check_id=check.check_id, source=check.source, reason=reason)
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
    preexec = _child_limits(limit_mb)
    for check in checks:
        # Run from a real file, never ``python -c``: a ``-c`` traceback reports
        # ``File "<string>", line N`` with no source text, so a failing assertion names
        # neither the assertion nor the expectation it asserted. Written to a file, the
        # traceback carries the offending line and the failure is diagnosable in one pass.
        with tempfile.TemporaryDirectory(prefix="drydock-acceptance-") as tmp:
            script = Path(tmp) / f"{check.check_id or 'acceptance'}.py"
            script.write_text(check.code + "\n", encoding="utf-8")
            # Own session so the timeout can reap the whole tree, and a bounded address
            # space so a runaway is stopped by the kernel long before the timeout.
            process = subprocess.Popen(
                [str(environment.interpreter), str(script)],
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
                _kill_process_group(process)
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
                        error=(
                            f"{TIMEOUT_FAILURE_PREFIX} after {check.timeout_seconds}s: the built "
                            f"code did not terminate within its budget. This is a "
                            f"non-terminating loop or unbounded work in the code under test, "
                            f"not a missed expectation."
                        ),
                        interpreter=str(environment.interpreter),
                        provisioning_result=environment.provisioning_result,
                    )
                )
                continue
            return_code = process.returncode
            scrubbed = _scrub_script_path(stderr, script)
            verdict = (
                _resource_failure(return_code, stderr, limit_mb)
                or _environment_failure(return_code, scrubbed, script.name, check.requirements)
                or _malformed_failure(return_code, scrubbed, script.name)
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
