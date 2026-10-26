"""Narrow static oracle and readiness checks; never execute criterion code."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping

from drydock.acceptance import (
    ProgrammaticAcceptance,
    _comparison_expectations,
    _supplied_literals,
)


def decimal_provenance_advisories(check: ProgrammaticAcceptance) -> tuple[str, ...]:
    """Report unrecognized provenance without judging or rewriting the expected value.

    A decimal can occur inside a serialized fixture rather than as a separate AST literal.
    Exact tokens in supplied text suppress this advisory; that is not proof of correctness.
    Failure to recognize input is uncertainty, never evidence for a new formula or rounding.
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
        and not any(
            re.search(r"(?<![\w.+-])" + re.escape(node.value) + r"(?![\w.])", text)
            for text in supplied
        )
        and node.value not in (check.cited_text or "")
    )
    return tuple(
        f"decimal expectation {value!r}: provenance unknown to static analysis; review against "
        "the source contract if needed; this is not a defect and does not authorize changing "
        "the value, precision or rounding"
        for value in values
    )


def _fixture_value(
    node: ast.AST, bindings: Mapping[str, ast.AST], seen: frozenset[str] = frozenset()
):
    """Resolve only literal fixture data; never execute criterion expressions."""
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _fixture_value(bindings[node.id], bindings, seen | {node.id})
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [_fixture_value(item, bindings, seen) for item in node.elts]
        return tuple(values) if isinstance(node, ast.Tuple) else values
    if isinstance(node, ast.Subscript):
        value = _fixture_value(node.value, bindings, seen)
        index = ast.literal_eval(node.slice)
        if isinstance(value, (tuple, list)) and isinstance(index, int):
            return value[index]
        raise ValueError("not a literal fixture index")
    return ast.literal_eval(node)


def ordered_expectation_defects(
    check: ProgrammaticAcceptance, database_text: str
) -> tuple[str, ...]:
    """Reject statically resolvable row expectations contradicting a declared list Order.

    The supported form is a projection of a bound repository list result compared with literal
    fixture rows. Arbitrary expressions, helper calls and runtime sort keys remain unjudged.
    """
    from drydock.database_contract import parse_database_contract, sqlite_schema_tables
    from drydock.errors import SpecificationError

    if not database_text:
        return ()
    try:
        contract = parse_database_contract(database_text)
        column_types = {
            (table.name, column.name): column.sql_type
            for table in sqlite_schema_tables(database_text)
            for column in table.columns
        }
        tree = ast.parse(check.code)
    except (SpecificationError, SyntaxError):
        return ()
    stores = [
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    ]
    statements = list(tree.body)
    for statement in statements:
        if isinstance(statement, ast.With):
            statements.extend(statement.body)
    bindings = {
        node.targets[0].id: node.value
        for node in statements
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and stores.count(node.targets[0].id) == 1
    }
    # Do not treat a literal assignment as a constant after an observable mutation.
    mutated = {
        node.func.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    } | {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.value, ast.Name)
    }
    for name in mutated:
        bindings.pop(name, None)
    orders = {
        pattern.repository_operation: pattern.order
        for pattern in contract.patterns
        if pattern.order
    }
    reasons: list[str] = []
    for assertion in (node for node in tree.body if isinstance(node, ast.Assert)):
        comparison = assertion.test
        if (
            not isinstance(comparison, ast.Compare)
            or len(comparison.ops) != 1
            or not isinstance(comparison.ops[0], ast.Eq)
        ):
            continue
        projection = comparison.left
        if not isinstance(projection, ast.ListComp) or len(projection.generators) != 1:
            continue
        generator = projection.generators[0]
        if not isinstance(generator.iter, ast.Name) or not isinstance(generator.target, ast.Name):
            continue
        call = bindings.get(generator.iter.id)
        if (
            not isinstance(call, ast.Call)
            or not isinstance(call.func, ast.Attribute)
            or not isinstance(call.func.value, ast.Attribute)
        ):
            continue
        operation = f"{call.func.value.attr}.{call.func.attr}"
        order = orders.get(operation, ())
        if not order or not isinstance(projection.elt, (ast.Tuple, ast.List)):
            continue
        fields = projection.elt.elts
        if not all(
            isinstance(field, ast.Attribute)
            and isinstance(field.value, ast.Name)
            and field.value.id == generator.target.id
            for field in fields
        ):
            continue
        columns = [field.attr for field in fields]
        if any(column not in columns for column, _ in order):
            continue
        try:
            expected = _fixture_value(comparison.comparators[0], bindings)
            if not isinstance(expected, (list, tuple)) or not all(
                isinstance(row, (list, tuple)) and len(row) == len(columns) for row in expected
            ):
                continue
            sorted_rows = list(expected)
            for column, direction in reversed(order):
                position = columns.index(column)
                sql_type = column_types.get((operation.split(".")[0], column), "")
                values = [row[position] for row in expected]
                if sql_type == "TEXT" or sql_type.startswith("VARCHAR("):
                    if not all(isinstance(value, str) for value in values):
                        raise ValueError("unknown text projection conversion")
                elif sql_type in {"INTEGER", "NUMERIC", "REAL"}:
                    if not all(type(value) in {int, float} for value in values):
                        raise ValueError("unknown numeric projection conversion")
                else:
                    raise ValueError("unknown column ordering")
                sorted_rows.sort(key=lambda row: row[position], reverse=direction == "desc")
        except (ValueError, TypeError, IndexError, KeyError, RecursionError):
            continue
        if list(expected) != sorted_rows:
            declaration = ", ".join(f"{column} {direction}" for column, direction in order)
            reasons.append(
                f"expected rows contradict {operation} Order ({declaration}); derive ordered expectations from fixture inputs using the declared keys"
            )
    return tuple(dict.fromkeys(reasons))


def process_readiness_defect(code: str) -> str | None:
    """Recognize a spawn followed only by an immediate liveness assertion."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for index, statement in enumerate(tree.body):
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
        ):
            continue
        call = statement.value
        if (
            not isinstance(call, ast.Call)
            or not isinstance(call.func, ast.Attribute)
            or not isinstance(call.func.value, ast.Name)
            or call.func.value.id != "subprocess"
            or call.func.attr != "Popen"
        ):
            continue
        if index + 1 >= len(tree.body) or not isinstance(tree.body[index + 1], ast.Try):
            continue
        body = tree.body[index + 1].body
        if len(body) != 1 or not isinstance(body[0], ast.Assert):
            continue
        test = body[0].test
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], ast.Is)
            or not isinstance(test.comparators[0], ast.Constant)
            or test.comparators[0].value is not None
        ):
            continue
        poll = test.left
        if (
            isinstance(poll, ast.Call)
            and isinstance(poll.func, ast.Attribute)
            and isinstance(poll.func.value, ast.Name)
            and poll.func.value.id == statement.targets[0].id
            and poll.func.attr == "poll"
        ):
            return "an immediate Popen.poll() is None proves only spawning; use a bounded readiness probe of the required endpoint or port, retain diagnostics, and terminate the process in finally"
    return None
