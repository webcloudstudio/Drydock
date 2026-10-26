"""Resolve literal CLI calls for comparison with declared story interfaces.

Only syntax is inspected: criterion code is never executed. Unknown arguments remain unknown,
so an unresolved invocation cannot become a guessed dependency.
"""

from __future__ import annotations

import ast


def cli_arguments(code: str) -> tuple[tuple[str | None, ...], ...]:
    """Literal runner arguments, including local forwarding helpers and literal loops.

    Follow local helper parameters and ``*args`` without interpreting expressions, subprocesses,
    imports, or return values. A recursion guard bounds recursive helpers. Rebound helper names
    and runner names are excluded rather than assigning them an interface they may not call.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    rebound = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    }
    functions = {name: node for name, node in functions.items() if name not in rebound}
    found: list[tuple[str | None, ...]] = []

    def value(node, env):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, (ast.List, ast.Tuple)):
            return tuple(value(item, env) for item in node.elts)
        return None

    def arguments(node, env):
        args = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                expanded = value(arg.value, env)
                if not isinstance(expanded, tuple):
                    return None
                args.extend(expanded)
            else:
                args.append(value(arg, env))
        return args

    def calls(node, env, active):
        if isinstance(node, ast.Assert) and negative_assertion(node.test):
            return
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else ""
            runner = name == "cli_runner" or (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"drydock_go", "drydock_cli"}
                and node.func.attr == "cli_runner"
            )
            args = arguments(node, env)
            if runner and "cli_runner" not in rebound and args is not None:
                found.append(tuple(arg if isinstance(arg, str) else None for arg in args))
            elif name in functions and name not in active and args is not None:
                function = functions[name]
                if not function.decorator_list:
                    params = [*function.args.posonlyargs, *function.args.args]
                    local = dict(env)
                    local.update({param.arg: None for param in params})
                    local.update({param.arg: arg for param, arg in zip(params, args)})
                    for keyword in node.keywords:
                        if keyword.arg:
                            local[keyword.arg] = value(keyword.value, env)
                    if function.args.vararg:
                        local[function.args.vararg.arg] = tuple(args[len(params) :])
                    statements(function.body, local, active | {name})
        for child in ast.iter_child_nodes(node):
            calls(child, env, active)

    def statements(body, env, active):
        negative_names = {
            node.test.left.id
            for node in body
            if isinstance(node, ast.Assert)
            and negative_assertion(node.test)
            and isinstance(node.test.left, ast.Name)
        }
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.For):
                choices = value(node.iter, env)
                if isinstance(node.target, ast.Name) and isinstance(choices, tuple):
                    for choice in choices:
                        statements(node.body, {**env, node.target.id: choice}, active)
                else:
                    local = dict(env)
                    for item in ast.walk(node.target):
                        if isinstance(item, ast.Name):
                            local[item.id] = None
                    statements(node.body, local, active)
                statements(node.orelse, dict(env), active)
                # A loop can run zero or several times; its final bindings are unknown.
                env.update({
                    item.id: None
                    for item in ast.walk(node)
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)
                })
            elif isinstance(node, ast.With):
                statements(node.body, env, active)
            elif isinstance(node, (ast.If, ast.While, ast.Try, ast.Match)):
                # Branch-dependent bindings cannot establish literal arguments.
                assigned = {
                    item.id
                    for item in ast.walk(node)
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)
                }
                local = {**env, **dict.fromkeys(assigned)}
                calls(node, local, active)
                env.update(dict.fromkeys(assigned))
            else:
                targets = node.targets if isinstance(node, ast.Assign) else ()
                exit_names = {
                    target.id if isinstance(target, ast.Name) else target.elts[0].id
                    for target in targets
                    if isinstance(target, ast.Name)
                    or (
                        isinstance(target, (ast.Tuple, ast.List))
                        and target.elts
                        and isinstance(target.elts[0], ast.Name)
                    )
                }
                if not exit_names & negative_names:
                    calls(node, env, active)
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            env[target.id] = value(node.value, env)
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                    if isinstance(node.target, ast.Name):
                        env[node.target.id] = None

    def negative_assertion(test):
        return (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.comparators[0], ast.Constant)
            and type(test.comparators[0].value) is int
            and test.comparators[0].value != 0
        )

    statements(tree.body, {}, set())
    return tuple(dict.fromkeys(found))
