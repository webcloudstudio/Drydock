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
