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

    kind: str  # shell-with-argv | env-assignment-argv | unsplit-command
    call: str
    detail: str

    @property
    def message(self) -> str:
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


def _invocation_defect(node: ast.Call) -> InvocationDefect | None:
    if _call_name(node) not in _INVOKING_CALLS or not node.args:
        return None
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
