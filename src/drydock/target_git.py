"""Target repository process contract.

Every git invocation against a Target Workspace goes through this module. Keeping process
execution in its own contract lets the lineage, refit, and import capabilities stay testable
without shelling out, and gives one place to enforce the rules a Target repository must obey:

- A Target may or may not have its own repository. ``init_target`` creates one only when the
  workspace is itself a repository that ignores ``targets/``, so every entry point here degrades
  to a no-op rather than raising when ``.git`` is absent.
- Failures are reported as ``None`` or an empty result, never as ``CalledProcessError`` escaping
  into a command. A missing or broken git installation must not abort an import.
- Drydock never pushes. Amending the tip commit is therefore safe: the commit being rewritten is
  local and unpublished by construction.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_TIMEOUT = 30


@dataclass(frozen=True)
class SourceVersion:
    """One recorded version of a source file in the Target repository."""

    commit: str
    date: str
    subject: str


def is_repo(target_dir: Path) -> bool:
    return (target_dir / ".git").exists()


def _run(target_dir: Path, *args: str, timeout: int = _TIMEOUT) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout


def head_commit(target_dir: Path) -> str | None:
    """Short sha of the Target's current tip, or ``None`` when there is no repository or commit."""
    if not is_repo(target_dir):
        return None
    code, out = _run(target_dir, "rev-parse", "--short", "HEAD")
    if code != 0 or not out.strip():
        return None
    return out.strip()


def commit_target(target_dir: Path, message: str) -> str | None:
    """Commit a Target repository when one exists; never commit the parent workspace.

    The commit stages every pending change in the Target, not only the files the calling command
    wrote, so the operation is announced explicitly with the file count and the resulting commit.
    Returns the new short sha, or ``None`` when nothing was committed.
    """
    if not is_repo(target_dir):
        return None
    code, out = _run(target_dir, "status", "--short")
    if code != 0 or not out.strip():
        return None
    pending = len([line for line in out.splitlines() if line.strip()])
    print(f"Git commit: {target_dir}")
    print(f'  git add -A && git commit -m "{message}"')
    print(f"  staging {pending} pending Target file(s), not only this command's output")
    if _run(target_dir, "add", "-A", timeout=15)[0] != 0:
        return None
    if _run(target_dir, "commit", "-m", message)[0] != 0:
        return None
    code, out = _run(target_dir, "log", "-1", "--format=%h %s")
    if code == 0 and out.strip():
        print(f"  → {out.strip()}")
    return head_commit(target_dir)


def amend_head(target_dir: Path, paths: Sequence[str]) -> bool:
    """Fold ``paths`` into the tip commit without changing its message.

    Used when a record can only be completed after the commit exists — the commit sha a version
    record needs is not known until the commit is made. Amending keeps one commit per import
    rather than emitting a second bookkeeping commit.
    """
    if not is_repo(target_dir) or not paths:
        return False
    if _run(target_dir, "add", "--", *paths, timeout=15)[0] != 0:
        return False
    return _run(target_dir, "commit", "--amend", "--no-edit")[0] == 0


def file_versions(target_dir: Path, rel_path: str) -> tuple[SourceVersion, ...]:
    """Every recorded version of ``rel_path``, oldest first.

    ``--follow`` tracks the file across renames. Order is the commit graph order produced by
    ``--reverse``, not author-date order; author dates can move backwards and are recorded as
    reported rather than re-sorted.
    """
    if not is_repo(target_dir):
        return ()
    code, out = _run(
        target_dir,
        "log",
        "--follow",
        "--reverse",
        "--format=%h%x09%ad%x09%s",
        "--date=short",
        "--",
        rel_path,
    )
    if code != 0:
        return ()
    versions: list[SourceVersion] = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].strip():
            versions.append(SourceVersion(parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return tuple(versions)


def show(target_dir: Path, commit: str, rel_path: str) -> str | None:
    """File content at ``commit``, or ``None`` when the path did not exist there."""
    if not is_repo(target_dir):
        return None
    code, out = _run(target_dir, "show", f"{commit}:{rel_path}")
    if code != 0:
        return None
    return out


def diff(target_dir: Path, base: str | None, rel_path: str) -> str:
    """Unified diff of ``rel_path`` between ``base`` and the working tree.

    With no ``base`` the whole file is the delta, so the file is rendered as an all-addition diff
    against the empty tree. That is the first-import case: nothing has consumed the file yet.
    """
    if not is_repo(target_dir):
        return ""
    args = ["diff", "--no-color"]
    if base:
        args.append(base)
    else:
        args.append("--no-index")
        args.extend(["--", "/dev/null", rel_path])
        return _run(target_dir, *args)[1]
    args.extend(["--", rel_path])
    return _run(target_dir, *args)[1]


def tracked_sources(target_dir: Path, sources_dir: str = "blueprint/sources") -> tuple[str, ...]:
    """Every source path git has ever recorded under ``sources_dir``, including deleted ones.

    A ``HEAD``-anchored listing would omit a source that was withdrawn upstream, and a withdrawn
    source still has lineage worth replaying. Selecting on the add filter over full history keeps
    those paths visible.
    """
    if not is_repo(target_dir):
        return ()
    code, out = _run(
        target_dir, "log", "--diff-filter=A", "--name-only", "--format=", "--", sources_dir
    )
    if code != 0:
        return ()
    seen: dict[str, None] = {}
    for line in out.splitlines():
        path = line.strip()
        if path.startswith(f"{sources_dir}/") and not any(
            part.startswith(".") for part in Path(path).parts
        ):
            seen.setdefault(path[len(sources_dir) + 1 :], None)
    return tuple(sorted(seen))
