"""Immutable imported-source corpus discovery and prompt rendering.

The corpus is deliberately read-only.  It records every regular file beneath
``blueprint/sources`` so Analyze can account for heterogeneous imports without
asking an author to rename, classify, or normalize them first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MAX_FILE_CHARS = 48_000
_CHUNK_CHARS = 12_000
_FENCES = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "bash",
    ".sql": "sql",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".java": "java",
    ".md": "markdown",
    ".txt": "text",
}


@dataclass(frozen=True)
class CorpusFile:
    path: Path
    relative_path: str
    kind: str
    disposition: str
    reason: str
    text: str | None = None
    fence: str = "text"

    @property
    def prompt_chunks(self) -> tuple[str, ...]:
        if self.text is None:
            return ()
        return tuple(
            self.text[index : index + _CHUNK_CHARS]
            for index in range(0, len(self.text), _CHUNK_CHARS)
        )


def discover_corpus(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[CorpusFile]:
    """Discover all non-excluded regular imported files in stable path order."""
    sources = blueprint_dir / "sources"
    if not sources.is_dir():
        return []
    result: list[CorpusFile] = []
    for path in sorted(
        (item for item in sources.rglob("*") if item.is_file()), key=lambda item: item.as_posix()
    ):
        if path.name in excluded_filenames:
            continue
        relative = path.relative_to(blueprint_dir).as_posix()
        fence = _FENCES.get(path.suffix.lower(), "text")
        kind = (
            "markdown" if path.suffix.lower() == ".md" else ("code" if fence != "text" else "text")
        )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            result.append(
                CorpusFile(path, relative, "unreadable", "skipped", str(exc), fence=fence)
            )
            continue
        if b"\0" in raw:
            result.append(
                CorpusFile(path, relative, "binary", "skipped", "binary content", fence=fence)
            )
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            result.append(
                CorpusFile(path, relative, "binary", "skipped", "non-UTF-8 content", fence=fence)
            )
            continue
        compact = text.replace("\n", "")
        if len(text) > 2_000 and len(compact) / max(len(text), 1) > 0.98:
            result.append(
                CorpusFile(
                    path, relative, kind, "summarized", "likely generated or minified", fence=fence
                )
            )
        elif len(text) > _MAX_FILE_CHARS:
            result.append(
                CorpusFile(
                    path,
                    relative,
                    kind,
                    "chunked",
                    f"split into {len(text) // _CHUNK_CHARS + 1} bounded chunks",
                    text,
                    fence,
                )
            )
        else:
            result.append(
                CorpusFile(path, relative, kind, "analyzed", "readable UTF-8", text, fence)
            )
    return result


def inventory_markdown(corpus: list[CorpusFile]) -> str:
    """Render deterministic coverage evidence for ANALYSIS.md."""
    lines = [
        "## Source Inventory",
        "",
        "| Path | Content kind | Disposition | Reason |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{entry.relative_path}` | {entry.kind} | {entry.disposition} | {entry.reason} |"
        for entry in corpus
    )
    if not corpus:
        lines.append("| _None_ | _None_ | skipped | No imported source files found. |")
    return "\n".join(lines)
