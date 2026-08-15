"""Repository ownership and checkpoints for independent UAT kits."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from drydock.errors import SpecificationError

_TIMEOUT = 60


def _run(kit_root: Path, *args: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=kit_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    output = completed.stdout if completed.stdout.strip() else completed.stderr
    return completed.returncode, output.strip()


def ensure_kit_repository(kit_root: Path) -> bool:
    """Initialize the directly owned ``uat/<Kit>`` repository when absent."""
    if (kit_root / ".git").is_dir():
        return False
    code, output = _run(kit_root, "init", "-q")
    if code != 0 or not (kit_root / ".git").is_dir():
        raise SpecificationError(
            f"Cannot initialize UAT kit repository {kit_root}: {output or 'git failed'}"
        )
    print(f"UAT kit - initialized {kit_root.name}")
    return True


def remove_run_repositories(kit_root: Path) -> tuple[Path, ...]:
    """Remove Git control stores below generated ``runs/`` before the kit is staged."""
    runs_root = kit_root / "runs"
    if not runs_root.is_dir():
        return ()
    removed: list[Path] = []
    for git_path in sorted(runs_root.rglob(".git"), key=lambda path: len(path.parts), reverse=True):
        if git_path.is_symlink() or git_path.is_file():
            git_path.unlink()
        elif git_path.is_dir():
            shutil.rmtree(git_path)
        else:
            continue
        removed.append(git_path)
    return tuple(removed)


def _remove_run_gitlinks(kit_root: Path) -> None:
    """Clear stale embedded-repository index entries so their files can replace them."""
    code, output = _run(kit_root, "ls-files", "--stage", "runs/")
    if code != 0:
        raise SpecificationError(
            f"Cannot inspect UAT kit index {kit_root}: {output or 'git failed'}"
        )
    for line in output.splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) != 4 or fields[0] != "160000":
            continue
        path = fields[3]
        code, detail = _run(kit_root, "rm", "--cached", "--force", "--", path)
        if code != 0:
            raise SpecificationError(
                f"Cannot remove UAT run gitlink {kit_root / path}: {detail or 'git failed'}"
            )


def checkpoint_kit_repository(kit_root: Path, message: str = "Complete drydock uat") -> str | None:
    """Flatten generated repositories, stage the whole kit, and commit pending changes."""
    ensure_kit_repository(kit_root)
    remove_run_repositories(kit_root)
    _remove_run_gitlinks(kit_root)
    code, output = _run(kit_root, "add", "--all")
    if code != 0:
        raise SpecificationError(f"Cannot stage UAT kit {kit_root}: {output or 'git failed'}")
    code, output = _run(kit_root, "diff", "--cached", "--quiet")
    if code == 0:
        return None
    if code != 1:
        raise SpecificationError(f"Cannot inspect UAT kit {kit_root}: {output or 'git failed'}")
    code, output = _run(kit_root, "commit", "-m", message)
    if code != 0:
        raise SpecificationError(f"Cannot commit UAT kit {kit_root}: {output or 'git failed'}")
    code, output = _run(kit_root, "rev-parse", "--short", "HEAD")
    if code != 0 or not output:
        raise SpecificationError(f"Cannot resolve UAT kit commit for {kit_root}")
    print(f"UAT kit - committed {kit_root.name} ({output})")
    return output


def ensure_kit_repositories(kit_roots: Sequence[Path]) -> None:
    for kit_root in kit_roots:
        ensure_kit_repository(kit_root)


def checkpoint_kit_repositories(kit_roots: Sequence[Path]) -> None:
    for kit_root in kit_roots:
        checkpoint_kit_repository(kit_root)
