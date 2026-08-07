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

from drydock.errors import SpecificationError

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
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    output = completed.stdout if completed.stdout.strip() else completed.stderr
    return completed.returncode, output


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
    wrote. Success is reported in one line. A Git failure aborts the calling command rather than
    allowing it to report success without the required checkpoint. Returns the new short sha, or
    ``None`` when nothing was committed.
    """
    if not is_repo(target_dir):
        return None
    code, out = _run(target_dir, "status", "--short")
    if code != 0:
        raise SpecificationError(f"Cannot inspect Target Git status: {out.strip() or 'git failed'}")
    if not out.strip():
        return None
    pending = len([line for line in out.splitlines() if line.strip()])
    code, out = _run(target_dir, "add", "-A", timeout=15)
    if code != 0:
        raise SpecificationError(
            f"Cannot stage Target Git checkpoint: {out.strip() or 'git failed'}"
        )
    code, out = _run(target_dir, "commit", "-m", message)
    if code != 0:
        raise SpecificationError(
            f"Cannot commit Target Git checkpoint: {out.strip() or 'git failed'}"
        )
    code, out = _run(target_dir, "log", "-1", "--format=%h %s")
    if code != 0 or not out.strip():
        raise SpecificationError(
            f"Cannot verify Target Git checkpoint: {out.strip() or 'git failed'}"
        )
    commit = head_commit(target_dir)
    if commit is None:
        raise SpecificationError("Cannot resolve Target Git checkpoint after commit")
    print(f"Git checkpoint: {out.strip()} ({pending} pending Target file(s))")
    return commit


def commit_paths(target_dir: Path, paths: Sequence[str], message: str) -> str | None:
    """Commit only ``paths``, quietly, and return the resulting sha.

    A lineage record names the commit that introduced a source version, so that commit has to
    exist before the record can be written — and it must stay reachable afterwards. Amending it
    to fold the record in would orphan the very sha the record points at, so the stamp lands as
    its own small follow-up commit instead.
    """
    if not is_repo(target_dir) or not paths:
        return None
    if _run(target_dir, "add", "--", *paths, timeout=15)[0] != 0:
        return None
    code, _ = _run(target_dir, "diff", "--cached", "--quiet", "--", *paths)
    if code == 0:
        return None
    if _run(target_dir, "commit", "-m", message, "--", *paths)[0] != 0:
        return None
    return head_commit(target_dir)


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
