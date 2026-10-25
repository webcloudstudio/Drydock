"""Static authoring checks for decimal expectations; never execute criterion code."""

from __future__ import annotations

import ast
import re

from drydock.acceptance import (
    ProgrammaticAcceptance,
    _comparison_expectations,
    _supplied_literals,
)


def decimal_expectation_defects(check: ProgrammaticAcceptance) -> tuple[str, ...]:
    """Require an input or source for a literal formatted decimal expectation.

    This checks the provenance of the oracle, not the correctness of arbitrary arithmetic.
    Derived expressions remain the author's responsibility. Integer counts/statuses and
    nonnumeric contract tokens retain their existing rules.
    """
    try:
        tree = ast.parse(check.code)
    except SyntaxError:
        return ()
    supplied = _supplied_literals(tree)
    values = dict.fromkeys(
        node.value
        for node in _comparison_expectations(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"[+-]?\d+\.\d+", node.value)
        and node.value not in supplied
        and node.value not in (check.cited_text or "")
    )
    return tuple(
        f"decimal expectation {value!r} has no input or cited source; derive the expected "
        "value from fixture inputs using the source formula and explicit rounding, or cite "
        "the source's exact known answer"
        for value in values
    )
