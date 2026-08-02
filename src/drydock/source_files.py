"""Shared enumeration of imported source files.

Every command that reads ``blueprint/sources/`` uses this so they can never disagree about what
was imported. Hidden entries — any path component beginning with ``.`` — are never authored
specification: they are Drydock's own bookkeeping (``.drydock-import``, ``.drydock-compass``),
version-control skeletons (``.gitkeep``, ``.git/``), or tool droppings that arrived with the
import. Reading them costs prompt tokens and produces findings about files no author wrote.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def is_hidden(path: Path, root: Path) -> bool:
    """Whether ``path`` is hidden relative to ``root``, including under a hidden directory."""
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield every visible regular file beneath ``root`` in arbitrary order.

    A missing directory yields nothing; callers that require imported sources raise their own
    error. Order is the caller's concern — each reader sorts by the key its output contract needs.
    """
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file() and not is_hidden(path, root):
            yield path
