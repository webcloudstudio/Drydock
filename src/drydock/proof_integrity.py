"""Deterministic integrity analysis of Programmatic Acceptance proof code.

A proof that cannot fail proves nothing: an empty body, an assertion on a constant, or a
self-comparison passes at build time while verifying no behavior. Drydock's scoring already
discounts model judgment; trusting a vacuous deterministic proof at face value is the same
mistake in the other direction. This module flags such proofs by static AST analysis so the
scorer can demote them to "no proof" rather than count them as verification.

The analysis is conservative by design: it only reports a proof as vacuous when it is confident
the code carries no effective failure path. A proof it cannot parse is not demoted — the runtime
execution remains the real gate, and a broken proof fails there.
"""

from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass
from pathlib import Path

# Call targets that raise on failure and therefore constitute a real check even without a bare
# ``assert``/``raise``. Matched against the final attribute or bare name of a call.
_CHECKER_NAMES = frozenset({
    "fail",
    "expect",
    "check",
    "ensure",
    "verify",
    "require",
    "raise_for_status",
})
_CHECKER_PREFIXES = ("assert",)


@dataclass(frozen=True)
class ProofIntegrity:
    """Verdict for one proof body. ``ok`` is False when the proof cannot meaningfully fail."""

    ok: bool
    reasons: tuple[str, ...] = ()


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_checker_call(node: ast.Call) -> bool:
    name = _call_name(node)
    if name in _CHECKER_NAMES or name.startswith(_CHECKER_PREFIXES):
        return True
    # ``subprocess.run(..., check=True)`` raises CalledProcessError on failure.
    return any(
        kw.arg == "check" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in node.keywords
    )


def _is_meaningful_exit(node: ast.Call) -> bool:
    name = _call_name(node)
    if name not in {"exit", "_exit"}:
        return False
    if not node.args:
        return False
    arg = node.args[0]
    # exit()/exit(0)/exit(None) all signal success; anything else can fail the run.
    if isinstance(arg, ast.Constant):
        return arg.value not in (0, None, False)
    return True


def _tautological_compare(node: ast.Compare) -> bool:
    """True for a comparison that is constant by construction, e.g. ``x == x`` or ``a is a``."""
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    if not isinstance(node.ops[0], (ast.Eq, ast.Is, ast.GtE, ast.LtE)):
        return False
    return ast.dump(node.left) == ast.dump(node.comparators[0])


def _vacuous_assert_reason(node: ast.Assert) -> str | None:
    """Return why an assert is vacuously true, or None if it can genuinely fail."""
    test = node.test
    if isinstance(test, ast.Constant):
        if bool(test.value):
            return f"assertion on constant literal {test.value!r} is always true"
        return None  # ``assert False`` always fails — a real (if blunt) gate.
    if isinstance(test, (ast.Tuple, ast.List)) and test.elts:
        return "assertion on a non-empty collection literal is always true"
    if isinstance(test, ast.Compare) and _tautological_compare(test):
        return "tautological self-comparison is always true"
    return None


def analyze_proof(code: str) -> ProofIntegrity:
    """Judge whether a Programmatic Acceptance proof body can meaningfully fail."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Unparseable code is not vacuous; it fails loudly when executed. Do not demote it.
        return ProofIntegrity(True)

    asserts: list[ast.Assert] = []
    has_meaningful = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            asserts.append(node)
        elif isinstance(node, ast.Raise):
            has_meaningful = True
        elif isinstance(node, ast.Call):
            if _is_checker_call(node) or _is_meaningful_exit(node):
                has_meaningful = True

    vacuous_reasons = [
        reason for node in asserts if (reason := _vacuous_assert_reason(node)) is not None
    ]
    effective_asserts = len(asserts) - len(vacuous_reasons)

    if has_meaningful or effective_asserts > 0:
        return ProofIntegrity(True)

    if asserts:
        # Every assertion present is vacuous and nothing else can fail.
        return ProofIntegrity(False, tuple(dict.fromkeys(vacuous_reasons)))
    return ProofIntegrity(False, ("proof contains no assertion, raise, or failing exit",))


# --- Literal defects -------------------------------------------------------------------
#
# A proof can be perfectly non-vacuous and still be unsatisfiable, because its *expectation*
# is mis-authored. The dominant instance is a raw string literal carrying an escape sequence
# the author meant as a control character: ``r"...\n"`` is backslash-n, not a newline, so no
# conforming implementation can ever satisfy the assertion. The build then burns a full LLM
# cycle failing to make correct code pass a check that cannot pass. Catch it before the build.

_RAW_PREFIX_RE = re.compile(r"""^[a-zA-Z]*[rR][a-zA-Z]*["']""")
# Only sequences whose intended meaning is unambiguously a control character. ``\t`` is
# excluded: a literal tab is visually indistinguishable in source, so raw ``\t`` is often
# deliberate.
_CONTROL_ESCAPE_RE = re.compile(r"\\[nr]")
# Callables whose string argument is a pattern, where a raw escape is the correct authoring.
_PATTERN_CALLS = frozenset({
    "compile",
    "match",
    "fullmatch",
    "search",
    "sub",
    "subn",
    "split",
    "findall",
    "finditer",
})


@dataclass(frozen=True)
class LiteralDefect:
    """One mis-authored string literal in a proof body."""

    literal: str
    sequence: str

    @property
    def message(self) -> str:
        return (
            f"raw string literal {self.literal} contains {self.sequence}, which is a "
            f"backslash followed by a letter, not a control character — the assertion cannot "
            f"pass. Write the control character in a normal string "
            f'(for example "line\\n"), or "\\\\n" when a literal backslash is intended.'
        )


def _pattern_literals(tree: ast.AST) -> set[int]:
    """Node ids of string literals passed positionally to a regex-style callable."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in _PATTERN_CALLS:
            for arg in node.args:
                exempt.add(id(arg))
    return exempt


def analyze_literals(code: str) -> tuple[LiteralDefect, ...]:
    """Report string literals in a proof body that make it unsatisfiable by construction."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()

    exempt = _pattern_literals(tree)
    defects: list[LiteralDefect] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in exempt:
            continue
        segment = ast.get_source_segment(code, node)
        if not segment or not _RAW_PREFIX_RE.match(segment):
            continue
        match = _CONTROL_ESCAPE_RE.search(segment)
        if match is None:
            continue
        key = (segment, match.group(0))
        if key in seen:
            continue
        seen.add(key)
        defects.append(LiteralDefect(literal=segment, sequence=match.group(0)))
    return tuple(defects)


# --- Structural defects ----------------------------------------------------------------
#
# Each Programmatic Acceptance snippet executes as its own script in its own process; sibling
# checks in the same specification share no state. A snippet that reads a name another snippet
# bound therefore dies with ``NameError`` on every run, before the code under test is even
# reached. That is not a red baseline the build can drive green — no implementation satisfies
# it — so the build must reject it rather than spend an LLM cycle on it.

_ALWAYS_DEFINED = frozenset({
    "__file__",
    "__name__",
    "__doc__",
    "__builtins__",
    "__spec__",
    "__package__",
    "__loader__",
})
# Names these calls can introduce that static analysis cannot see. Their presence makes the
# undefined-name analysis unsound, so the snippet is left to the runtime gate instead.
_DYNAMIC_BINDERS = frozenset({"exec", "eval", "globals", "locals", "vars"})


@dataclass(frozen=True)
class StructuralDefect:
    """One defect that makes a proof fail for a reason unrelated to the code under test."""

    kind: str
    detail: str

    @property
    def message(self) -> str:
        if self.kind == "syntax-error":
            return (
                f"the snippet is not valid Python ({self.detail}) — it fails to parse before "
                f"the code under test runs. Repair the snippet."
            )
        return (
            f"name '{self.detail}' is read but never defined in this snippet — it raises "
            f"NameError on every run and no implementation can satisfy it. Each check runs as "
            f"its own script in its own process, so a name bound by another check in the same "
            f"file is not in scope here. Define it in this snippet."
        )


class _BindingCollector(ast.NodeVisitor):
    """Collect every name a snippet binds, flattening all scopes.

    Scopes are deliberately flattened: a name bound anywhere in the snippet counts as defined
    everywhere. That under-reports (a genuine scope error is missed) but never over-reports,
    which is the right bias for a gate that blocks a build.
    """

    def __init__(self) -> None:
        self.bound: set[str] = set()
        self.dynamic = False

    def _bind_target(self, node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                self.bound.add(child.id)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)
        elif node.id in _DYNAMIC_BINDERS:
            self.dynamic = True
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.bound.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                # A star import can supply anything; the analysis cannot stay sound.
                self.dynamic = True
                continue
            self.bound.add(alias.asname or alias.name)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        name = getattr(node, "name", None)
        if name:
            self.bound.add(name)
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.bound.add(arg.arg)
        for optional in (args.vararg, args.kwarg):
            if optional is not None:
                self.bound.add(optional.arg)
        self.generic_visit(node)

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function
    visit_Lambda = _visit_function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bound.add(node.name)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.bound.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.bound.update(node.names)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.bound.add(node.rest)
        self.generic_visit(node)

    def visit_withitem(self, node: ast.withitem) -> None:
        if node.optional_vars is not None:
            self._bind_target(node.optional_vars)
        self.generic_visit(node)


def analyze_structure(code: str) -> tuple[StructuralDefect, ...]:
    """Report defects that make a proof fail before it can exercise the code under test."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        detail = exc.msg or "invalid syntax"
        if exc.lineno:
            detail = f"{detail} at line {exc.lineno}"
        return (StructuralDefect(kind="syntax-error", detail=detail),)

    collector = _BindingCollector()
    collector.visit(tree)
    if collector.dynamic:
        return ()

    known = collector.bound | _ALWAYS_DEFINED | set(dir(builtins))
    undefined: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if node.id in known or node.id in undefined:
            continue
        undefined.append(node.id)
    return tuple(StructuralDefect(kind="undefined-name", detail=name) for name in undefined)


# --- Swallowed diagnostics -------------------------------------------------------------
#
# A check that shells out to a test runner and captures its output, then asserts on the exit
# code without echoing what it captured, destroys the only evidence that explains the failure.
# The traceback then carries the assertion and nothing else: no tally, no failing case names.
# The check still gates correctly, but neither the operator nor the repair pass can see why it
# failed. Flag it so the author prints the captured streams before asserting.

_CAPTURING_CALLS = frozenset({"run", "check_output", "Popen", "communicate", "getoutput"})
_ECHO_CALLS = frozenset({"print", "write", "writelines"})
_CAPTURED_STREAMS = frozenset({"stdout", "stderr", "output"})


@dataclass(frozen=True)
class SwallowedOutputDefect:
    """A proof that captures a subprocess's output and never echoes it."""

    call: str

    @property
    def message(self) -> str:
        return (
            f"captures subprocess output ({self.call}) but never prints it, so a failure "
            f"reports only the assertion — not the runner's tally or its failing cases. Print "
            f"the captured stdout and stderr before asserting."
        )


def _captures_output(node: ast.Call) -> bool:
    if _call_name(node) not in _CAPTURING_CALLS:
        return False
    for keyword in node.keywords:
        if keyword.arg == "capture_output" and isinstance(keyword.value, ast.Constant):
            if keyword.value.value is True:
                return True
        if keyword.arg in {"stdout", "stderr"}:
            return True
    return _call_name(node) == "check_output"


# --- Malformed subprocess invocation ---------------------------------------------------
#
# ``subprocess.run(["A=1", "prog", "arg"], shell=True)`` does not run ``prog``. On POSIX,
# ``shell=True`` executes only element 0 as the command string and binds the rest to ``$0, $1,
# …``. When element 0 is a bare ``NAME=value`` the shell performs an assignment, exits 0, and
# writes nothing — so a return-code assertion passes and an output assertion fails, for a
# reason no implementation can influence. The mirror defect, a whitespace-bearing command
# string without ``shell=True``, dies with FileNotFoundError in its own frame. Both make the
# check unsatisfiable by construction, so they are caught before a build spends a pass on them.

_INVOKING_CALLS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class InvocationDefect:
    """A subprocess invocation whose arguments cannot launch the command as written."""

    kind: str  # shell-with-argv | env-assignment-argv | unsplit-command | env-replaces-environ
    call: str
    detail: str

    @property
    def message(self) -> str:
        if self.kind == "env-replaces-environ":
            return (
                f"{self.call} passes env={self.detail} without **os.environ, which replaces the "
                "whole environment rather than adding to it. The child then runs with no PATH, "
                "so every command it names — including the interpreter it shells out to — fails "
                "to resolve, whatever the implementation does. Write "
                "env={**os.environ, ...}."
            )
        if self.kind == "shell-with-argv":
            return (
                f"{self.call} passes an argument list with shell=True, so POSIX executes only "
                f"{self.detail!r} and binds the remaining elements to $0, $1, … — the intended "
                "command never runs. Drop shell=True, or pass one command string."
            )
        if self.kind == "env-assignment-argv":
            return (
                f"{self.call} passes {self.detail!r} as the executable. An environment "
                "assignment is not a program; the assignment must move to "
                "env={**os.environ, ...} or into a shell command string."
            )
        return (
            f"{self.call} passes the command string {self.detail!r} without shell=True, so the "
            "whole string is treated as one executable name and the call raises "
            "FileNotFoundError. Split it into an argument list, or set shell=True."
        )


def _shell_keyword(node: ast.Call) -> bool | None:
    """Return the literal value of the ``shell`` keyword, or ``None`` when it is not literal."""
    for keyword in node.keywords:
        if keyword.arg != "shell":
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool):
            return keyword.value.value
        return None
    return False


def _invocation_label(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return _call_name(node)


def _env_dict(node: ast.Call) -> ast.Dict | None:
    """Return the call's ``env=`` argument when it is a dict literal, else ``None``.

    Anything that is not a literal — ``os.environ.copy()``, a name bound earlier, a ``dict(...)``
    call, a ``|`` merge — is left alone. Those forms usually do carry the inherited environment,
    and deciding otherwise would need value tracking this analysis deliberately does not do.
    """
    for keyword in node.keywords:
        if keyword.arg == "env":
            return keyword.value if isinstance(keyword.value, ast.Dict) else None
    return None


def _env_replacement_defect(node: ast.Call) -> InvocationDefect | None:
    """Report an ``env=`` dict literal that replaces the environment instead of extending it.

    ``env={"DECODER": "./decoder"}`` is the single most common way an otherwise correct proof
    becomes unsatisfiable: the child loses ``PATH``, so the harness it invokes cannot be found
    and the exit status reports a missing tool rather than the behavior under test. A literal
    carrying no ``**`` unpacking supplies the entire environment by definition, so the judgement
    needs no value tracking.
    """
    env = _env_dict(node)
    if env is None:
        return None
    # ``None`` in ``keys`` is how ``**expr`` appears in a dict literal. Any unpacking at all is
    # taken as the inherited environment: ``{**os.environ}``, ``{**base}``, ``{**e.copy()}``.
    if any(key is None for key in env.keys):
        return None
    shown = ", ".join(
        (repr(key.value) if isinstance(key, ast.Constant) else "…") + ": …" for key in env.keys
    )
    return InvocationDefect(
        kind="env-replaces-environ",
        call=_invocation_label(node),
        detail="{" + shown + "}",
    )


def _invocation_defect(node: ast.Call) -> InvocationDefect | None:
    if _call_name(node) not in _INVOKING_CALLS or not node.args:
        return None
    replaced = _env_replacement_defect(node)
    if replaced is not None:
        return replaced
    shell = _shell_keyword(node)
    if shell is None:
        # A non-literal ``shell=`` value leaves the argument shape undecidable. Stay silent,
        # matching the dynamic-code escape the structural analysis already takes.
        return None
    argv = node.args[0]
    label = _invocation_label(node)
    if isinstance(argv, (ast.List, ast.Tuple)):
        if shell:
            head = argv.elts[0] if argv.elts else None
            shown = head.value if isinstance(head, ast.Constant) else "<first element>"
            return InvocationDefect(kind="shell-with-argv", call=label, detail=str(shown))
        head = argv.elts[0] if argv.elts else None
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            if _ENV_ASSIGNMENT_RE.match(head.value):
                return InvocationDefect(kind="env-assignment-argv", call=label, detail=head.value)
        return None
    if isinstance(argv, ast.Constant) and isinstance(argv.value, str) and not shell:
        if argv.value.strip() and len(argv.value.split()) > 1:
            return InvocationDefect(kind="unsplit-command", call=label, detail=argv.value)
    return None


def analyze_invocation(code: str) -> tuple[InvocationDefect, ...]:
    """Report subprocess invocations that cannot launch the command their arguments name."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()

    defects: list[InvocationDefect] = []
    seen: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        defect = _invocation_defect(node)
        if defect is None:
            continue
        key = (defect.kind, defect.call, defect.detail)
        if key in seen:
            continue
        seen.add(key)
        defects.append(defect)
    return tuple(defects)


# --- Shell escape handling -------------------------------------------------------------
#
# A proof that feeds input to the program under test through ``sh -c`` has to get the shell's
# own quoting right before the program sees anything. ``printf '%s' 'a\nb'`` does not emit a
# newline: ``%s`` copies its argument verbatim, so the program receives a literal backslash
# followed by ``n``. Where the program is a parser, it correctly rejects that as malformed and
# the proof reads the rejection as a defect in the implementation. No implementation can pass,
# because the input it is graded on is not the input the author wrote.

_PRINTF_RE = re.compile(r"""printf\s+(?P<q>['"])(?P<fmt>.*?)(?P=q)(?P<args>[^;|&]*)""")
_SHELL_ESCAPE_RE = re.compile(r"\\[nrt]")


@dataclass(frozen=True)
class ShellEscapeDefect:
    """A shell command whose escape sequences are never interpreted."""

    command: str
    fmt: str

    @property
    def message(self) -> str:
        return (
            f"the shell command uses printf {self.fmt!r} with arguments containing backslash "
            "escapes, and that format copies its argument verbatim — the escapes reach the "
            "program as a literal backslash and letter, not as control characters. The program "
            "is then graded on input the author never wrote, so no implementation can pass. "
            "Use printf '%b', embed a real newline, or pass the input through "
            "subprocess input= instead of a shell."
        )


def analyze_shell_escapes(code: str) -> tuple[ShellEscapeDefect, ...]:
    """Report shell commands whose backslash escapes are copied verbatim rather than expanded."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()

    defects: list[ShellEscapeDefect] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for match in _PRINTF_RE.finditer(node.value):
            fmt = match.group("fmt")
            # ``%b`` is the format that expands escapes in its argument, and an escape written
            # into the format itself is expanded there. Neither is a defect.
            if "%b" in fmt:
                continue
            if not _SHELL_ESCAPE_RE.search(match.group("args")):
                continue
            key = (node.value, fmt)
            if key in seen:
                continue
            seen.add(key)
            defects.append(ShellEscapeDefect(command=node.value, fmt=fmt))
    return tuple(defects)


def analyze_swallowed_output(code: str) -> tuple[SwallowedOutputDefect, ...]:
    """Report proofs that capture a subprocess's output and discard it on failure."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()

    capturing = [
        node for node in ast.walk(tree) if isinstance(node, ast.Call) and _captures_output(node)
    ]
    if not capturing:
        return ()
    echoes = any(
        isinstance(node, ast.Call) and _call_name(node) in _ECHO_CALLS for node in ast.walk(tree)
    )
    if echoes:
        return ()
    # A check that asserts on the captured streams names the evidence in its own assertion, so
    # the failure still reports what the command produced. Only a check that captures the output
    # and reads nothing but the exit code destroys the diagnostics.
    reads_streams = any(
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and node.attr in _CAPTURED_STREAMS
        for node in ast.walk(tree)
    )
    if reads_streams:
        return ()
    first = capturing[0]
    func = first.func
    label = (
        f"{func.value.id}.{func.attr}"
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
        else _call_name(first)
    )
    return (SwallowedOutputDefect(call=label),)


# --- Assertions on captured output text ------------------------------------------------
#
# A criterion that shells out to a test runner already has a verdict: the runner's exit status.
# An assertion layered on top of it, forbidding a word in the runner's stdout, is the author's
# model of an output format they may never have run. When that model is wrong the criterion is
# false on correct code, and no implementation can move it — the build spends its whole repair
# budget proving that.
#
# The failure is not hypothetical or rare. Test runners print their tally in the form
# ``N passed, M failed``, so the words ``failed``, ``error``, ``skipped`` and ``warning`` appear
# in the summary of a completely clean run. ``assert "failed" not in result.stdout.lower()`` is
# therefore unsatisfiable against every runner that reports a count of failures, which is most
# of them. Forbidding one of those words is treated as a defect; forbidding any other literal
# alongside an exit-status assertion is advisory, because the exit status is already the gate.

# Words that appear in a passing runner's own summary line. Forbidding one of these in captured
# output asserts that a successful run stays silent about its counters, which it does not.
_TALLY_VOCABULARY = frozenset({
    "fail",
    "failed",
    "failure",
    "failures",
    "error",
    "errors",
    "skip",
    "skipped",
    "warning",
    "warnings",
})
_STREAM_ATTRS = frozenset({"stdout", "stderr", "output"})
# A runner prints its summary to stdout. The same word on stderr carries no such guarantee —
# a command that succeeds usually writes nothing there — so a stderr assertion is satisfiable
# and must not be treated as a defect.
_TALLY_STREAMS = frozenset({"stdout", "output"})

# The mirror image of the vocabulary rule. Requiring a *specific* tally to appear in captured
# output pins two things the author does not own: the case count, which belongs to whatever
# suite version the harness installs, and the whitespace, because runners column-align their
# columns (``valid tests: 205 passed,  0 failed`` carries two spaces before the zero). Either
# drifts and the criterion is false on correct code, with no implementation able to move it.
_TALLY_NOUNS = r"(?:passed|failed|failures?|errors?|skipped|ok|tests?|cases?|examples?|assertions?)"
_HARDCODED_TALLY_RE = re.compile(
    rf"\b\d+\s+{_TALLY_NOUNS}\b|\b{_TALLY_NOUNS}\s*[:=]\s*\d+", re.IGNORECASE
)

# Rewriting the pinned literal as a whitespace-tolerant regular expression — the remedy this
# module recommends — moves the assertion out of an ``in`` comparison and into a ``re.search``
# call, where none of the rules above can see it. Two defects survive that move.
#
# The first is the count. ``re.search(r"\b205\s+passed\b", ...)`` pins the installed suite's case
# count exactly as the literal form did. A *zero* count is different in kind: "no failures" is the
# specification's own claim about correct code, not a number the suite owns, which is why
# ``\b0\s+failed\b`` is the documented form.
#
# The second is the noun. A runner is only reliably observed to report passes and failures.
# ``errors``, ``skipped`` and ``warnings`` are per-runner vocabulary, and a runner that has none
# of them commonly prints no such line at all — toml-test emits ``skipped tests: N`` only when it
# skipped something, and never emits an error tally. Requiring ``0 errors`` in captured output
# therefore asserts that the runner uses a vocabulary it may not have, and no implementation can
# supply it. The exit status already carries the verdict, so where the proof gates on it these
# assertions can only subtract; without it, the regex is the proof's only gate and is left alone.
_REGEX_SEARCH_NAMES = frozenset({"search", "match", "fullmatch", "findall", "finditer"})
#
# These two match against the *pattern source*, not against runner output, so a digit may be
# preceded by the regex escape that introduces it (``\b0``) and the separator may be written as
# ``\s+``. Anchor on "not part of a longer number" rather than on a word boundary.
_PINNED_COUNT_RE = re.compile(
    rf"(?<!\d)(?!0(?![0-9]))\d+(?:\\s[*+]|\s)*{_TALLY_NOUNS}\b", re.IGNORECASE
)
_SPECULATIVE_TALLY_RE = re.compile(
    r"(?<!\d)\d+(?:\\s[*+]|\s)*(errors|error|skipped|skips|skip|warnings|warning)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class OutputAssertionDefect:
    """An assertion constraining a literal in a command's captured output."""

    kind: str  # tally-vocabulary | hardcoded-tally | speculative-tally | redundant-substring
    literal: str
    fatal: bool

    @property
    def message(self) -> str:
        if self.kind == "speculative-tally":
            return (
                f"requires the pattern {self.literal!r} to match captured output, which asserts "
                f"the runner reports a count of errors, skips or warnings. Only passes and "
                f"failures are reliably tallied; a runner with none of the others commonly prints "
                f"no such line at all, so the pattern is false on correct code and no "
                f"implementation can move it. The exit status already gates the run — assert on "
                f"it, and verify at most the failure count."
            )
        if self.kind == "hardcoded-tally":
            return (
                f"asserts the exact tally {self.literal!r} appears in captured output. The count "
                f"belongs to the installed suite, not to the specification, and runners "
                f'column-align their tallies ("205 passed,  0 failed" carries two spaces), so '
                f"the literal is false on correct code as soon as either drifts and no "
                f"implementation can move it. Gate on the exit status, or match with a regular "
                f"expression that tolerates whitespace and asserts the failure count is zero."
            )
        if self.kind == "tally-vocabulary":
            return (
                f"asserts {self.literal!r} never appears in captured output, but a test runner "
                f'prints its tally ("N passed, M failed") on a clean run, so the word is present '
                f"when the run succeeds. The assertion is false on correct code and no "
                f"implementation can move it. Gate on the exit status instead, or match a "
                f"nonzero count."
            )
        return (
            f"asserts {self.literal!r} never appears in captured output alongside an exit-status "
            f"assertion. The exit status is already the verdict; a substring check models an "
            f"output format the author may not have observed. Drop it, or verify it against a "
            f"captured sample of the command's real output."
        )


def _streams_read(node: ast.AST, bindings: dict[str, frozenset[str]]) -> frozenset[str]:
    """Which subprocess result streams ``node`` reads, directly or through a binding."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in _STREAM_ATTRS:
            found.add(child.attr)
        elif isinstance(child, ast.Name) and child.id in bindings:
            found |= bindings[child.id]
    return frozenset(found)


def _reads_captured_stream(node: ast.AST, bindings: dict[str, frozenset[str]]) -> bool:
    """True when ``node`` reads a subprocess result stream, directly or through a binding."""
    return bool(_streams_read(node, bindings))


def _stream_bindings(tree: ast.AST) -> dict[str, frozenset[str]]:
    """Names bound to captured streams, so ``out = result.stdout`` is tracked through ``out``.

    The mapped value keeps *which* streams the name carries: a stderr binding must not inherit
    the stdout tally reasoning.
    """
    bindings: dict[str, frozenset[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        streams = _streams_read(node.value, bindings)
        if not streams:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = bindings.get(target.id, frozenset()) | streams
    return bindings


def _regex_pattern_against_stream(
    node: ast.AST, bindings: dict[str, frozenset[str]]
) -> tuple[str, frozenset[str]] | None:
    """The literal pattern and streams of a ``re.search``-family call reading captured output.

    Returns ``None`` for anything else, including a computed (non-literal) pattern, which this
    module does not reason about.
    """
    if not isinstance(node, ast.Call) or _call_name(node) not in _REGEX_SEARCH_NAMES:
        return None
    if len(node.args) < 2:
        return None
    pattern = node.args[0]
    if not isinstance(pattern, ast.Constant) or not isinstance(pattern.value, str):
        return None
    streams = _streams_read(node.args[1], bindings)
    if not streams:
        return None
    return pattern.value, streams


def _asserts_exit_status(tree: ast.AST) -> bool:
    """True when the proof already gates on a return code."""
    return any(
        isinstance(node, ast.Attribute) and node.attr in {"returncode", "exit_code", "status"}
        for node in ast.walk(tree)
    )


def analyze_output_assertions(code: str) -> tuple[OutputAssertionDefect, ...]:
    """Flag assertions that constrain a literal in a command's captured output.

    Fatal for a word a passing runner prints anyway, and for a required literal carrying a
    hardcoded tally the runner's own formatting and suite version control; advisory when the
    proof already asserts on the exit status and the substring check is therefore redundant
    speculation.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()
    captured_names = _stream_bindings(tree)
    has_exit_assert = _asserts_exit_status(tree)
    defects: list[OutputAssertionDefect] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        # A regex form of the same claim. Only a required match is analysed: a negated one
        # (``assert not re.search(...)``) forbids a pattern, which the vocabulary rule below
        # already reasons about in its literal form and which carries no count to pin.
        negated = any(isinstance(child, ast.Not) for child in ast.walk(node.test))
        for call in () if negated else ast.walk(node.test):
            found = _regex_pattern_against_stream(call, captured_names)
            if found is None:
                continue
            pattern, streams = found
            if not (streams & _TALLY_STREAMS):
                continue
            if _PINNED_COUNT_RE.search(pattern):
                kind = "hardcoded-tally"
            elif has_exit_assert and _SPECULATIVE_TALLY_RE.search(pattern):
                kind = "speculative-tally"
            else:
                continue
            if (kind, pattern) in seen:
                continue
            seen.add((kind, pattern))
            defects.append(OutputAssertionDefect(kind=kind, literal=pattern, fatal=True))
        if not isinstance(node.test, ast.Compare):
            continue
        compare = node.test
        if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.NotIn | ast.In):
            continue
        if not isinstance(compare.left, ast.Constant) or not isinstance(compare.left.value, str):
            continue
        streams = _streams_read(compare.comparators[0], captured_names)
        if not streams:
            continue
        literal = compare.left.value
        if isinstance(compare.ops[0], ast.In):
            # A required literal is only a defect when it pins a tally. Any other required
            # substring is an ordinary, satisfiable expectation about the program's own output.
            if not (streams & _TALLY_STREAMS) or not _HARDCODED_TALLY_RE.search(literal):
                continue
            key = ("hardcoded-tally", literal)
            if key in seen:
                continue
            seen.add(key)
            defects.append(
                OutputAssertionDefect(kind="hardcoded-tally", literal=literal, fatal=True)
            )
            continue
        # Fatal only where a runner actually prints its tally. The same word forbidden on
        # stderr is an ordinary, satisfiable check on a command that succeeds silently.
        fatal = bool(streams & _TALLY_STREAMS) and literal.strip().lower() in _TALLY_VOCABULARY
        if not fatal and not has_exit_assert:
            # No exit-status gate: the substring check is the only verdict the proof has.
            # Removing it would leave nothing, so it is not redundant and not reported.
            continue
        kind = "tally-vocabulary" if fatal else "redundant-substring"
        if (kind, literal) in seen:
            continue
        seen.add((kind, literal))
        defects.append(OutputAssertionDefect(kind=kind, literal=literal, fatal=fatal))
    return tuple(defects)


# --- Staged harness environment contract -----------------------------------------------
#
# A staged asset is imported read-only and restored before grading, so a proof that invokes one
# has to satisfy the asset's own interface. Where the asset opens with a guard — ``[ -z
# "${DECODER:-}" ] && exit`` — that variable is not advice, it is a precondition the script
# enforces before it does any work. A proof that omits it grades the guard, not the program:
# the exit status reports a missing variable on every run, at every level of implementation
# quality. The requirement is read from the staged script itself rather than configured here,
# so the rule holds for any harness the Analysis stages, not one project's.

_STAGED_SCRIPT_RE = re.compile(r"sources/(?P<name>[\w.@-]+\.(?:sh|bash|py))\b")
_SHELL_GUARD_RE = re.compile(
    r"""\[\s*-z\s+"?\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}"?\s*\]"""
    r"""|\[\s*-z\s+"?\$(?P<bare>[A-Za-z_][A-Za-z0-9_]*)"?\s*\]"""
)
_SHELL_ASSIGNMENT_RE = re.compile(r"(?:^|[\s;&|])(?P<name>[A-Za-z_][A-Za-z0-9_]*)=")
#: Lines a guard may span before its ``exit`` for the guard to still count as fatal.
_GUARD_WINDOW = 6


@dataclass(frozen=True)
class StagedInvocationDefect:
    """A proof that invokes a staged asset without the environment that asset requires."""

    script: str
    variable: str

    @property
    def message(self) -> str:
        return (
            f"invokes the staged asset sources/{self.script} without setting {self.variable}, "
            f"which that script requires and exits on when unset. The proof then grades the "
            f"script's own precondition rather than the program under test, and fails "
            f"identically whatever the implementation does. Supply it with "
            f"env={{**os.environ, {self.variable!r}: ...}}."
        )


def staged_script_requirements(script: Path) -> tuple[str, ...]:
    """Return the environment variables ``script`` refuses to run without.

    A variable counts only when its unset-guard is followed closely by an ``exit``: a guard that
    merely selects a default is a documented fallback, not a precondition.
    """
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    lines = text.splitlines()
    required: list[str] = []
    for index, line in enumerate(lines):
        match = _SHELL_GUARD_RE.search(line)
        if match is None:
            continue
        name = match.group("braced") or match.group("bare")
        if name in required:
            continue
        window = "\n".join(lines[index : index + _GUARD_WINDOW])
        if re.search(r"\bexit\b", window):
            required.append(name)
    return tuple(required)


def _supplied_variables(node: ast.Call) -> frozenset[str] | None:
    """Names the call adds to the child environment, or ``None`` when that cannot be decided."""
    supplied: set[str] = set()
    for keyword in node.keywords:
        if keyword.arg != "env":
            continue
        if not isinstance(keyword.value, ast.Dict):
            return None  # a computed environment; the analysis declines to guess
        for key in keyword.value.keys:
            if key is None:
                continue  # ``**expr`` may carry anything, but never the guarded variable alone
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                return None
            supplied.add(key.value)
    # ``sh -c "DECODER=./x sources/run.sh"`` supplies it inside the command string instead.
    for arg in ast.walk(node):
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            supplied.update(
                match.group("name") for match in _SHELL_ASSIGNMENT_RE.finditer(arg.value)
            )
    return frozenset(supplied)


def _invoked_staged_scripts(node: ast.Call) -> tuple[str, ...]:
    names: list[str] = []
    for arg in ast.walk(node):
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            continue
        for match in _STAGED_SCRIPT_RE.finditer(arg.value):
            name = match.group("name")
            if name not in names:
                names.append(name)
    return tuple(names)


def analyze_staged_invocation(
    code: str, *, sources_dir: Path | None
) -> tuple[StagedInvocationDefect, ...]:
    """Report proofs that invoke a staged asset without the environment it requires."""
    if sources_dir is None:
        return ()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()

    defects: list[StagedInvocationDefect] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in _INVOKING_CALLS:
            continue
        scripts = _invoked_staged_scripts(node)
        if not scripts:
            continue
        supplied = _supplied_variables(node)
        if supplied is None:
            continue
        for script in scripts:
            for variable in staged_script_requirements(sources_dir / script):
                if variable in supplied or (script, variable) in seen:
                    continue
                seen.add((script, variable))
                defects.append(StagedInvocationDefect(script=script, variable=variable))
    return tuple(defects)
