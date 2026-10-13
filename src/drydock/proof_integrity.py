"""Deterministic integrity analysis of Programmatic Acceptance proof code.

A proof that cannot fail proves nothing: an empty body, an assertion on a constant, or a
self-comparison passes at build time while verifying no behavior. Drydock's scoring already
discounts model judgment; trusting a vacuous deterministic proof at face value is the same
mistake in the other direction. This module flags such proofs by static AST analysis so the
scorer can demote them to "no proof" rather than count them as verification.

The analysis is conservative by design: it only reports a proof as vacuous when it is confident
the code carries no effective failure path. A proof it cannot parse is not demoted — the runtime
execution remains the real gate, and a broken proof fails there.

This module once carried six further analyzers, each predicting from a proof's text that it would
fail: mis-authored literals, unbound names, shell escapes, swallowed output, runner-tally
vocabulary, staged-script invocation. They were an unbounded blacklist grown one observed failure
at a time, every entry with its own false-positive rate, and they were the mechanism by which
fixtures that had passed for weeks began to fail. They are gone. What replaces them is the
authoring rule in :func:`drydock.acceptance.retyped_expectations` — a whitelist of oracles whose
expected value cannot be invented — and the runtime verdict, which observes rather than predicts.

Vacuity analysis survives because it is the opposite kind of claim. Predicting a criterion will
fail assigns blame to the product on a guess, and a wrong guess fails a correct build. Detecting
that a criterion passed without exercising anything only withholds credit, so a wrong guess costs
a criterion its PASS and never fails anything. Only the second is safe to keep.
"""

from __future__ import annotations

import ast
import warnings
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


#: Exception types whose handler, when it does not re-raise, swallows a failing assertion.
_SWALLOWING_TYPES = frozenset({"AssertionError", "Exception", "BaseException"})

_UNREACHABLE = "assertion is unreachable"
_SWALLOWED = "assertion failure is swallowed by an exception handler"


def _type_names(node: ast.expr | None) -> set[str]:
    if node is None:
        return {"BaseException"}
    if isinstance(node, ast.Tuple):
        return {name for item in node.elts for name in _type_names(item)}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Name):
        return {node.id}
    return set()


def _swallows(handler: ast.ExceptHandler) -> bool:
    """True when a handler catches assertion failures and never re-raises."""
    if not _type_names(handler.type) & _SWALLOWING_TYPES:
        return False
    return not any(isinstance(node, ast.Raise) for stmt in handler.body for node in ast.walk(stmt))


def _suppresses(item: ast.withitem) -> bool:
    """True for ``with suppress(AssertionError):`` or an equally broad suppression."""
    call = item.context_expr
    return (
        isinstance(call, ast.Call)
        and _call_name(call) == "suppress"
        and any(_type_names(arg) & _SWALLOWING_TYPES for arg in call.args)
    )


def _carries_failure(stmts: list[ast.stmt]) -> bool:
    return any(
        isinstance(node, (ast.Assert, ast.Raise))
        or (isinstance(node, ast.Call) and (_is_checker_call(node) or _is_meaningful_exit(node)))
        for stmt in stmts
        for node in ast.walk(stmt)
    )


def _skip(stmts: list[ast.stmt], reason: str, dead: list[str]) -> None:
    if _carries_failure(stmts):
        dead.append(reason)


def _live_block(stmts: list[ast.stmt], dead: list[str]):
    """Yield every node that can execute with its failure observed, in statement order.

    Only constructs whose outcome is decided by the source text are pruned: a constant branch,
    code after an unconditional jump, and a body whose assertion failure a handler swallows.
    Anything undetermined is treated as live, so the analysis can withhold credit but never
    invent a failure path.
    """
    for index, stmt in enumerate(stmts):
        yield from _live_stmt(stmt, dead)
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            _skip(stmts[index + 1 :], _UNREACHABLE, dead)
            return


def _live_stmt(stmt: ast.stmt, dead: list[str]):
    if isinstance(stmt, (ast.If, ast.While)):
        yield stmt
        yield from ast.walk(stmt.test)
        truth = bool(stmt.test.value) if isinstance(stmt.test, ast.Constant) else None
        if truth is False:
            _skip(stmt.body, _UNREACHABLE, dead)
        else:
            yield from _live_block(stmt.body, dead)
        if truth is True:
            _skip(stmt.orelse, _UNREACHABLE, dead)
        else:
            yield from _live_block(stmt.orelse, dead)
        return
    if isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
        yield stmt
        if any(_swallows(handler) for handler in stmt.handlers):
            _skip(stmt.body, _SWALLOWED, dead)
        else:
            yield from _live_block(stmt.body, dead)
        for handler in stmt.handlers:
            yield handler
            yield from _live_block(handler.body, dead)
        yield from _live_block(stmt.orelse, dead)
        yield from _live_block(stmt.finalbody, dead)
        return
    if isinstance(stmt, (ast.With, ast.AsyncWith)) and any(_suppresses(i) for i in stmt.items):
        yield stmt
        for item in stmt.items:
            yield from ast.walk(item)
        _skip(stmt.body, _SWALLOWED, dead)
        return
    yield stmt
    for value in ast.iter_child_nodes(stmt):
        if isinstance(value, (ast.stmt, ast.match_case)):
            continue
        yield from ast.walk(value)
    for field in ("body", "orelse", "finalbody"):
        block = getattr(stmt, field, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            yield from _live_block(block, dead)
    for case in getattr(stmt, "cases", ()):
        yield from ast.walk(case.pattern)
        if case.guard is not None:
            yield from ast.walk(case.guard)
        yield from _live_block(case.body, dead)


def analyze_proof(code: str) -> ProofIntegrity:
    """Judge whether a Programmatic Acceptance proof body can meaningfully fail."""
    try:
        # A criterion's escape-sequence warnings are reported against the named criterion by
        # ``acceptance.escape_defects``; this module must not repeat them on stderr. Suppressed
        # locally rather than through ``acceptance.captured_syntax_warnings`` because
        # ``acceptance`` imports this module.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(code)
    except SyntaxError:
        # Unparseable code is not vacuous; it fails loudly when executed. Do not demote it.
        return ProofIntegrity(True)

    asserts: list[ast.Assert] = []
    has_meaningful = False
    dead: list[str] = []
    for node in _live_block(tree.body, dead):
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

    if asserts or dead:
        # Every assertion that can run is vacuous, and the rest cannot run or cannot fail.
        return ProofIntegrity(False, tuple(dict.fromkeys(vacuous_reasons + dead)))
    return ProofIntegrity(False, ("proof contains no assertion, raise, or failing exit",))
