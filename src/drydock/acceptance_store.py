"""Reject acceptance code that replaces or reprovisions the application store."""

from __future__ import annotations

import ast

_STORE_KEYS = {"DATABASE_PATH", "DATABASE_URL"}
_PROCESS_LAUNCHERS = {
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "os.system",
    "os.popen",
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
}
_PROCESS_LAUNCHER_PREFIXES = ("os.exec", "os.spawn", "os.posix_spawn")


def store_setup_defects(code: str) -> tuple[str, ...]:
    """Recognize concrete environment mutations and schema calls, not arbitrary prose."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ()  # the syntax validator owns this defect
    aliases = {"os": "os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + "." + item.name

    def name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return name(node.value) + "." + node.attr
        return ""

    def key(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in _STORE_KEYS
        )

    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if name(node.value) == "os.environ" and key(node.slice):
                found.add("criterion changes the configured database; use the provisioned store")
        if isinstance(node, ast.Call):
            called = name(node.func)
            if (
                called
                in {
                    "os.putenv",
                    "os.unsetenv",
                    "os.environ.setdefault",
                    "os.environ.pop",
                    "os.environ.__setitem__",
                    "os.environ.__delitem__",
                }
                and node.args
                and key(node.args[0])
            ):
                found.add("criterion changes the configured database; use the provisioned store")
            if called == "os.environ.update":
                keys = [kw.arg for kw in node.keywords]
                for arg in node.args:
                    if isinstance(arg, ast.Dict):
                        keys.extend(k.value for k in arg.keys if isinstance(k, ast.Constant))
                if any(k in _STORE_KEYS for k in keys):
                    found.add(
                        "criterion changes the configured database; use the provisioned store"
                    )
            if (
                called == "sqlite3.connect"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in {":memory:", ""}
            ):
                found.add(
                    "criterion opens a private in-memory database that holds no schema; use "
                    "`with db_session() as db:` on the provisioned store"
                )
            if called.rsplit(".", 1)[-1] in {"execute_script", "executescript", "ApplySchema"}:
                found.add("criterion applies schema; only the DATABASE step provisions persistence")
            if called in {
                "persistence.testing.db_session",
                "persistence.testing.committed_session",
            } and (node.args or node.keywords):
                found.add(
                    "persistence fixtures take their store from configuration; do not supply a criterion DSN"
                )
    # The harness rolls back one transaction per criterion process. A launched process opens its
    # own connection, so it cannot see the criterion's setup, and the criterion cannot see it.
    opens_store = any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            module.split(".", 1)[0] == "persistence"
            for module in (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [item.name for item in node.names]
            )
        )
        for node in ast.walk(tree)
    )
    launches = any(
        isinstance(node, ast.Call)
        and (
            (called := name(node.func)) in _PROCESS_LAUNCHERS
            or called.startswith(_PROCESS_LAUNCHER_PREFIXES)
        )
        for node in ast.walk(tree)
    )
    if opens_store and launches:
        found.add(
            "criterion launches a process and opens the store; a launched process cannot see the "
            "criterion's rolled-back transaction, so exercise stored behavior in-process through "
            "`web_client()` or `cli_runner()`, or drop the store setup"
        )
    return tuple(sorted(found))
