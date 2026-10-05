"""Git checkpoints and committed file deltas for build execution evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.paths import get_rigging_root


def git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SpecificationError(f"Build Git checkpoint failed in {root}: {exc}") from exc
    if result.returncode:
        raise SpecificationError(f"Build Git checkpoint failed in {root}: {result.stderr.strip()}")
    return result.stdout


def prepare(root: Path) -> None:
    """Use an explicit repository at the build/Target root, never a parent checkout."""
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        git(root, "init", "-q")
    if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root.resolve():
        raise SpecificationError(f"Build repository must be rooted at {root}")
    if git(root, "ls-files", "-u").strip():
        raise SpecificationError(f"Build repository has unresolved merges: {root}")
    # Apply the distributed ignore contract locally, preserving an authored .gitignore.
    exclude = Path(git(root, "rev-parse", "--git-path", "info/exclude").strip())
    if not exclude.is_absolute():
        exclude = root / exclude
    marker = "# Drydock build checkpoint exclusions"
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if marker not in current:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(
            current
            + "\n"
            + marker
            + "\n"
            + (get_rigging_root() / "gitignore").read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def head(root: Path) -> str | None:
    # An initialized repository can have an unborn branch.
    return git(root, "rev-parse", "--revs-only", "HEAD").strip() or None


def checkpoint(root: Path, message: str) -> str | None:
    git(root, "add", "-A", "--", ".")
    if not git(root, "diff", "--cached", "--name-only", "-z"):
        return None
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def changes(root: Path, before: str | None, after: str | None) -> list[dict[str, str]]:
    if after is None or after == before:
        return []
    args = (
        ("diff", before, after)
        if before
        else (
            "diff-tree",
            "--root",
            "--no-commit-id",
            "-r",
            after,
        )
    )
    fields = git(root, *args, "--name-status", "-z", "-M", "--").split("\0")
    result = []
    index = 0
    while index < len(fields) and fields[index]:
        status, path = fields[index : index + 2]
        index += 2
        change = {"status": status, "path": path}
        if status.startswith(("R", "C")):
            change["old_path"] = path
            change["path"] = fields[index]
            index += 1
        result.append(change)
    return result
