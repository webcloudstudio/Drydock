"""Import existing source code into a Drydock Blueprint via LLM decomposition.

The LLM only emits text; this module writes Blueprint files deterministically from the parsed
output, so execution carries no file-write permissions and tests inject a fake runner.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from drydock.errors import LlmError, SpecificationError
from drydock.init_specification import _ROOT_TEMPLATES, init_specification
from drydock.llm import run_prompt
from drydock.prompts import load_prompt

PROMPT_NAME = "import_source"

# Blueprint filename convention: allow FEATURE-Name.md, SCREEN-Name.md, etc.
_SAFE_FILENAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_\-]*\.md$")
# XML output block: <file path="FILENAME">content</file>
_FILE_BLOCK_RE = re.compile(r'<file\s+path="([^"]+)">(.*?)</file>', re.DOTALL)
# Files that belong at the Target root, not inside blueprint/
_ROOT_TEMPLATE_NAMES = frozenset(_ROOT_TEMPLATES)

# Stack detection markers (V1 decompose.sh pattern)
_STACK_MARKERS: list[tuple[str, str]] = [
    ("requirements.txt", "Python"),
    ("package.json", "Node.js"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
]
_CONTENT_MARKERS: list[tuple[str, str, str]] = [
    # (filename_glob, content_substring, stack_label)
    ("requirements.txt", "flask", "Flask"),
    ("requirements.txt", "django", "Django"),
    ("requirements.txt", "fastapi", "FastAPI"),
]
_BOOTSTRAP_PATTERNS: tuple[str, ...] = ("templates/", "static/")
_SQLITE_SUFFIXES: tuple[str, ...] = (".db", ".sqlite", ".sqlite3")

_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {"venv", ".venv", "env", "__pycache__", "node_modules", ".git", "dist", "build"}
)
_SOURCE_EXTENSIONS: tuple[str, ...] = (
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb",
    ".java", ".cpp", ".c", ".h",
)
_CONFIG_NAMES: tuple[str, ...] = (
    "requirements.txt", "package.json", "Cargo.toml", "go.mod",
    "Dockerfile", ".env.example", "config.py", "settings.py", "AGENTS.md",
)
_TEMPLATE_EXTENSIONS: tuple[str, ...] = (".html", ".jinja", ".jinja2")
_SCHEMA_EXTENSIONS: tuple[str, ...] = (".sql",)
_SCHEMA_NAMES: tuple[str, ...] = ("schema.py",)


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...
    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]


@dataclass(frozen=True)
class ImportSourceResult:
    blueprint: str
    target: str
    blueprint_dir: Path
    source: Path
    files_written: tuple[str, ...]
    execution_id: str


def _detect_stack(source: Path) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label not in seen:
            hints.append(label)
            seen.add(label)

    for filename, label in _STACK_MARKERS:
        if (source / filename).is_file():
            add(label)

    for filename, substring, label in _CONTENT_MARKERS:
        candidate = source / filename
        if candidate.is_file():
            try:
                if substring in candidate.read_text(encoding="utf-8", errors="replace").lower():
                    add(label)
            except OSError:
                pass

    # Bootstrap detection
    for pattern in _BOOTSTRAP_PATTERNS:
        try:
            for p in (source / pattern.rstrip("/")).rglob("*"):
                if p.is_file():
                    try:
                        text = p.read_text(encoding="utf-8", errors="replace").lower()
                        if "bootstrap" in text:
                            add("Bootstrap")
                            break
                    except OSError:
                        continue
        except (OSError, StopIteration):
            pass

    # SQLite detection
    try:
        for p in source.rglob("*"):
            if p.suffix.lower() in _SQLITE_SUFFIXES:
                add("SQLite")
                break
    except OSError:
        pass

    return hints


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDE_DIRS for part in path.parts)


def _cap_lines(text: str, path: Path, max_lines: int = 200) -> str:
    lines = text.splitlines()
    total = len(lines)
    if total <= max_lines:
        return text
    preview = "\n".join(lines[:max_lines])
    return f"{preview}\n... ({total} lines total, showing first {max_lines})"


def _collect_source_files(source: Path) -> list[tuple[str, str]]:
    """Return (label, content) pairs for significant source files."""
    items: list[tuple[str, str]] = []

    def add_file(label: str, path: Path, max_lines: int = 200) -> None:
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            items.append((label, _cap_lines(text, path, max_lines)))
        except OSError:
            pass

    # Key config files first
    for name in _CONFIG_NAMES:
        add_file(name, source / name)

    # Source code files (top 20, excluded dirs)
    source_files: list[Path] = []
    try:
        for p in sorted(source.rglob("*")):
            if p.is_file() and p.suffix in _SOURCE_EXTENSIONS and not _is_excluded(p.relative_to(source)):
                source_files.append(p)
                if len(source_files) >= 20:
                    break
    except OSError:
        pass
    for p in source_files:
        rel = p.relative_to(source)
        if p.name not in _CONFIG_NAMES:
            add_file(str(rel), p)

    # Template files (top 20)
    templates: list[Path] = []
    try:
        for p in sorted(source.rglob("*")):
            if p.is_file() and p.suffix in _TEMPLATE_EXTENSIONS and not _is_excluded(p.relative_to(source)):
                templates.append(p)
                if len(templates) >= 20:
                    break
    except OSError:
        pass
    for p in templates:
        add_file(str(p.relative_to(source)), p, max_lines=80)

    # SQL / schema files
    schemas: list[Path] = []
    try:
        for p in sorted(source.rglob("*")):
            if p.is_file() and (p.suffix in _SCHEMA_EXTENSIONS or p.name in _SCHEMA_NAMES) and not _is_excluded(p.relative_to(source)):
                schemas.append(p)
                if len(schemas) >= 5:
                    break
    except OSError:
        pass
    for p in schemas:
        add_file(str(p.relative_to(source)), p)

    return items


def _directory_tree(source: Path, max_depth: int = 3, max_lines: int = 100) -> str:
    lines: list[str] = []
    try:
        for p in sorted(source.rglob("*")):
            rel = p.relative_to(source)
            if len(rel.parts) > max_depth:
                continue
            if _is_excluded(rel):
                continue
            lines.append(str(rel) + ("/" if p.is_dir() else ""))
            if len(lines) >= max_lines:
                lines.append("... (truncated)")
                break
    except OSError:
        pass
    return "\n".join(lines)


def _assemble_prompt(
    prompt_body: str,
    project_name: str,
    stack_hints: list[str],
    source: Path,
    source_files: list[tuple[str, str]],
) -> str:
    tree = _directory_tree(source)
    stack_str = ", ".join(stack_hints) if stack_hints else "Unknown"

    file_sections: list[str] = []
    for label, content in source_files:
        file_sections.append(f"### {label}\n```\n{content}\n```")
    files_block = "\n\n".join(file_sections)

    source_content = f"### Directory Structure\n```\n{tree}\n```\n\n{files_block}"

    return (
        prompt_body.replace("{{PROJECT_NAME}}", project_name)
        .replace("{{STACK_HINTS}}", stack_str)
        .replace("{{SOURCE_CONTENT}}", source_content)
    )


def _validate_filename(name: str) -> bool:
    """True if name is a safe Blueprint filename with no traversal."""
    if ".." in name or "/" in name or "\\" in name:
        return False
    return bool(_SAFE_FILENAME_RE.match(name))


def parse_file_blocks(text: str) -> dict[str, str]:
    """Extract ``<file path="NAME">content</file>`` blocks from LLM output."""
    result: dict[str, str] = {}
    for match in _FILE_BLOCK_RE.finditer(text):
        name = match.group(1).strip()
        content = match.group(2).strip()
        if not _validate_filename(name):
            continue
        result[name] = content
    return result


def import_source(
    blueprint: str,
    target: str,
    source: Path,
    target_directory: Path,
    *,
    runner: RunnerFn = run_prompt,
) -> ImportSourceResult:
    """Reverse-engineer source code into a Drydock Blueprint using an LLM."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SpecificationError(f"Import source must be a directory for --format source: {source}")

    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    init_specification(blueprint, target_dir, update=True)

    prompt = load_prompt(PROMPT_NAME)
    stack_hints = _detect_stack(source)
    source_files = _collect_source_files(source)
    full_prompt = _assemble_prompt(prompt.body, blueprint, stack_hints, source, source_files)

    result = runner(
        full_prompt,
        blueprint_dir,
        command_name=PROMPT_NAME,
        parameters={"blueprint": blueprint, "target": target, "source": str(source)},
    )

    if not result.ok:
        raise LlmError(
            f"LLM execution failed for import_source; execution_id={result.execution_id}"
        )

    files = parse_file_blocks(result.text)
    if not files:
        raise SpecificationError(
            "LLM output contained no <file path=\"...\"> blocks; "
            "cannot write Blueprint files."
        )

    written: list[str] = []
    for name, content in files.items():
        dest = (target_dir if name in _ROOT_TEMPLATE_NAMES else blueprint_dir) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content + "\n", encoding="utf-8", newline="\n")
        written.append(name)

    return ImportSourceResult(
        blueprint=blueprint,
        target=target,
        blueprint_dir=blueprint_dir,
        source=source,
        files_written=tuple(sorted(written)),
        execution_id=result.execution_id,
    )
