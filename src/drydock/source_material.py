"""Immutable imported source-material discovery and prompt rendering.

The source material is deliberately read-only.  It records every regular file
beneath ``blueprint/sources`` so Analyze can account for heterogeneous imports
without asking an author to rename, classify, or normalize them first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drydock.source_files import iter_source_files

_MAX_FILE_CHARS = 48_000
_CHUNK_CHARS = 12_000
#: Minification is a *line-structure* property: a generated file packs its content into one or a few
#: enormous lines. Both thresholds must hold — the file carries a machine-scale line, and that line
#: is most of the file — so ordinary prose never qualifies however long its longest sentence runs.
_MINIFIED_MIN_CHARS = 2_000
_MINIFIED_LINE_CHARS = 2_000
_MINIFIED_LINE_SHARE = 0.5
#: Kinds whose text is always injected. Prose is the material an author imports to *be read*: a
#: specification is where stories come from, so its content is never withheld on formatting grounds.
#: A large prose file is chunked, never summarized. Withholding applies only to code and data
#: artifacts, where a build output carries no design intent worth the tokens.
_PROSE_KINDS = frozenset({"markdown", "text"})
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


def is_generated_or_minified(text: str) -> bool:
    """Whether a file's content is machine-packed rather than human line-structured.

    A generated or minified file holds its content in one or a few enormous lines: the longest line
    is itself machine-scale *and* accounts for most of the file. Aggregate newline density cannot
    make this call — hand-written Markdown that wraps at 120 columns has a newline every ~50
    characters, which is indistinguishable by ratio alone from genuinely minified output, and
    misclassifying it silently drops the file's text from every prompt that cites it.
    """
    if len(text) <= _MINIFIED_MIN_CHARS:
        return False
    longest = max((len(line) for line in text.splitlines()), default=0)
    return longest >= _MINIFIED_LINE_CHARS and longest >= _MINIFIED_LINE_SHARE * len(text)


def split_prompt_chunks(text: str) -> tuple[str, ...]:
    """Split ``text`` into ``_CHUNK_CHARS``-bounded chunks on existing line boundaries."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if current and size + len(line) > _CHUNK_CHARS:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append("".join(current))
    return tuple(chunks)


@dataclass(frozen=True)
class SourceMaterialFile:
    path: Path
    relative_path: str
    kind: str
    disposition: str
    reason: str
    text: str | None = None
    fence: str = "text"

    @property
    def prompt_chunks(self) -> tuple[str, ...]:
        """Split the file into bounded chunks that never cut a line in half.

        A chunk boundary is a formatting decision imposed on someone else's file, so it has to
        fall where the file already has one. Slicing on a raw character offset lands mid-line
        roughly every time, and each severed line reaches the model as two unrelated lines in two
        separately fenced blocks — a specification whose indentation, fence lengths, and trailing
        spaces are normative arrives describing a different language than the one on disk.

        A single line longer than the budget is emitted whole rather than broken; exceeding the
        chunk size costs tokens, whereas splitting the line costs correctness.
        """
        if self.text is None:
            return ()
        return split_prompt_chunks(self.text)


def discover_source_material(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[SourceMaterialFile]:
    """Discover all non-excluded regular imported files in stable path order."""
    sources = blueprint_dir / "sources"
    if not sources.is_dir():
        return []
    result: list[SourceMaterialFile] = []
    for path in sorted(iter_source_files(sources), key=lambda item: item.as_posix()):
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
                SourceMaterialFile(path, relative, "unreadable", "skipped", str(exc), fence=fence)
            )
            continue
        if b"\0" in raw:
            result.append(
                SourceMaterialFile(
                    path, relative, "binary", "skipped", "binary content", fence=fence
                )
            )
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            result.append(
                SourceMaterialFile(
                    path, relative, "binary", "skipped", "non-UTF-8 content", fence=fence
                )
            )
            continue
        if kind not in _PROSE_KINDS and is_generated_or_minified(text):
            result.append(
                SourceMaterialFile(
                    path, relative, kind, "summarized", "likely generated or minified", fence=fence
                )
            )
        elif len(text) > _MAX_FILE_CHARS:
            result.append(
                SourceMaterialFile(
                    path,
                    relative,
                    kind,
                    "chunked",
                    f"split into {len(split_prompt_chunks(text))} bounded chunks",
                    text,
                    fence,
                )
            )
        else:
            result.append(
                SourceMaterialFile(path, relative, kind, "analyzed", "readable UTF-8", text, fence)
            )
    return result


def withheld_content_warning(source_material: list[SourceMaterialFile]) -> str | None:
    """Report imported files whose content was not injected, or ``None`` when every file was read.

    An author imports a file to have it read. When Drydock declines to read one, that decision has
    to be visible at the moment it is made: a file silently classified as unreadable produces an
    analysis with a hole in it, and the hole surfaces much later as a missing story or an
    unsatisfiable citation.
    """
    withheld = [entry for entry in source_material if entry.text is None]
    if not withheld:
        return None
    return "Imported source content was not read: " + ", ".join(
        f"{entry.relative_path} ({entry.reason})" for entry in withheld
    )


def inventory_markdown(source_material: list[SourceMaterialFile]) -> str:
    """Render deterministic coverage evidence for ANALYSIS.md."""
    lines = [
        "## Source Inventory",
        "",
        "| Path | Content kind | Disposition | Reason |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{entry.relative_path}` | {entry.kind} | {entry.disposition} | {entry.reason} |"
        for entry in source_material
    )
    if not source_material:
        lines.append("| _None_ | _None_ | skipped | No imported source files found. |")
    return "\n".join(lines)
