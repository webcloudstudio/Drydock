"""Shared HTML report rendering for Drydock receipts.

Both ``drydock uat --report`` and ``drydock score report`` publish the same kind of document:
a self-contained page that inventories a directory of evidence, links every artifact through a
styled viewer, and stamps a verdict the recorded exit codes support. This module owns everything
those two reports have in common — page chrome, inventory trees, artifact viewers, receipt
tables, and path portability. It knows nothing about what a run means.

Rendering is deterministic and reads only what is already on disk, so a report can be rebuilt
for an old run without re-executing it.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import shutil
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from drydock.markdown_render import render_markdown

# Interpreter and tooling caches are regenerated on demand, differ between machines, and
# make a checked-in receipt noisy. They are removed before the kit is inventoried.
PRUNED_DIRECTORIES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"})


_INDEX_NAME = "index.html"

_SUMS_NAME = "SHA256SUMS"

_IGNORE_NAME = ".gitignore"

# Generated at the top of a kit and rewritten on every rebuild, so they are never inventoried:
# a checksum of a file that the next rebuild replaces is a checksum that fails verification.
_KIT_OUTPUTS = frozenset({_INDEX_NAME, _SUMS_NAME, _IGNORE_NAME, "README.md"})


_MAX_EXCERPT_BYTES = 16_384


@dataclass(frozen=True)
class FileRecord:
    """One inventoried file, addressed relative to the directory that owns the kit."""

    path: str
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class ArtifactGroup:
    """A named section of the inventory, rendered as one table in the receipt."""

    name: str
    description: str
    files: tuple[FileRecord, ...]

    @property
    def total_bytes(self) -> int:
        return sum(record.bytes for record in self.files)


def prune_generated(root: Path) -> int:
    """Delete regenerable interpreter caches under ``root`` and report how many were removed."""
    removed = 0
    if not root.is_dir():
        return removed
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and path.name in PRUNED_DIRECTORIES:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def _hash_file(path: Path, base: Path) -> FileRecord:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return FileRecord(path.relative_to(base).as_posix(), size, digest.hexdigest())


def _is_hidden(relative: Path) -> bool:
    """Is any component of ``relative`` a dot entry or a tooling cache?

    A repository's own bookkeeping — ``.git`` above all — has no evidentiary value, and
    hashing its internals bloats the checksum file with thousands of lines nobody reads.
    """
    return any(
        part.startswith(".") or part in PRUNED_DIRECTORIES for part in relative.parts[:-1]
    ) or relative.parts[-1].startswith(".")


def _iter_files(
    root: Path, base: Path, *, skip: Iterable[Path] = (), hidden: bool = True
) -> Iterator[FileRecord]:
    if not root.is_dir():
        return
    # ``root`` is resolved once and every walked path is already absolute beneath it, so a
    # skipped directory is recognised by prefix. Resolving each ancestor of each file instead
    # costs one ``realpath`` per directory component per file, which on a network or DrvFs mount
    # turns a kit rebuild into tens of thousands of syscalls.
    resolved_root = root.resolve()
    skipped = {path.resolve() for path in skip}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        # A kit accounts for a dot entry by naming it withheld, so it inventories one; a
        # receipt simply has no use for a repository's own bookkeeping and drops it.
        if not hidden and _is_hidden(path.relative_to(root)):
            continue
        if skipped:
            walked = resolved_root / path.relative_to(root)
            if any(parent in skipped for parent in walked.parents):
                continue
        if path.parent == base and path.name in _KIT_OUTPUTS:
            continue
        yield _hash_file(path, base)


def _write_sums(base: Path, groups: Sequence[ArtifactGroup]) -> None:
    """Seal a published report: one ``sha256  path`` line per inventoried file.

    Written last, once every other file is final, so ``sha256sum -c`` run from inside the
    directory verifies the document a reader was handed.
    """
    lines = [f"{record.sha256}  {record.path}" for group in groups for record in group.files]
    (base / _SUMS_NAME).write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def _portable(value: object, base: Path) -> object:
    """Rewrite absolute paths under ``base`` as relative ones, recursively."""
    prefix = f"{base}/"
    windows_prefix = str(base).replace("/", "\\") + "\\"
    if isinstance(value, str):
        if value in (str(base), str(base).replace("/", "\\")):
            return "."
        for candidate in (prefix, windows_prefix):
            if value.startswith(candidate):
                return value[len(candidate) :].replace("\\", "/")
        return value
    if isinstance(value, dict):
        return {key: _portable(item, base) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable(item, base) for item in value]
    return value


def _make_portable(path: Path, base: Path) -> None:
    """Strip the generating machine's absolute paths out of a report Drydock authored."""
    if not path.is_file():
        return
    if path.suffix == ".json":
        payload = _read_json(path)
        if payload is None:
            return
        path.write_text(
            json.dumps(_portable(payload, base), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return
    text = path.read_text(encoding="utf-8")
    replaced = text.replace(f"{base}/", "").replace(str(base), ".")
    if replaced != text:
        path.write_text(replaced, encoding="utf-8")


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _relative(value: object, base: Path) -> str:
    """Render a recorded path relative to ``base`` so the kit stays portable."""
    text = str(value or "")
    if not text:
        return ""
    path = Path(text)
    # Report entry points normally pass an absolute root, but direct rebuilds and callers using a
    # project-relative UAT root are valid too. Recorded execution artifacts are absolute, so try
    # both forms before preserving a genuinely external path.
    for candidate in (base, base.resolve()):
        try:
            return path.relative_to(candidate).as_posix()
        except ValueError:
            continue
    # A case-insensitive filesystem lets a run record ``uat/Commonmark`` for a directory named
    # ``CommonMark``: the same file, spelled the way the operator typed it. Matching exactly would
    # call that path external and publish an absolute link nobody else can open, so the spellings
    # are compared case-blind and the recorded remainder is kept.
    for candidate in (base, base.resolve()):
        prefix = candidate.as_posix().rstrip("/") + "/"
        recorded = path.as_posix()
        if recorded[: len(prefix)].lower() == prefix.lower():
            return recorded[len(prefix) :]
    return text


def _tail(path: Path, limit: int = _MAX_EXCERPT_BYTES) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace").strip()


def _llm_calls(
    records_path: Path, base: Path, redirect: Mapping[str, str] | None = None
) -> tuple[dict[str, object], ...]:
    """Summarize each recorded LLM execution for the receipt's call table.

    ``redirect`` remaps an artifact the run recorded under the workspace onto the canonical
    copy the receipt actually publishes. The run writes these records pointing at its own
    working tree, so without the remap every prompt, output, and transcript link in the table
    addresses a file the kit withheld.
    """
    from drydock.llm_usage import normalize_tokens, read_records

    # Only entries with a replacement redirect. A withheld path that maps to nothing was not
    # part of the build record, so it keeps its recorded name rather than becoming an empty link.
    moved = {source: target for source, target in (redirect or {}).items() if target}

    def _artifact(value: object) -> str:
        relative = _relative(value, base)
        return moved.get(relative, relative)

    records, _ = read_records(records_path)
    calls: list[dict[str, object]] = []
    for record in records:
        job = record.get("job") if isinstance(record.get("job"), dict) else {}
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), dict) else {}
        total, cached, output = normalize_tokens(str(job.get("llm") or ""), stats)
        prompt_artifact = artifacts.get("prompt")
        llm_log_artifact = artifacts.get("llm_log")
        # Runs created during the telemetry migration may have written the sibling .llm.log
        # before execution records started naming it. Derive that conventional sibling; renderers
        # still verify that the file exists before linking it.
        if not llm_log_artifact and str(prompt_artifact or "").endswith(".prompt.md"):
            llm_log_artifact = str(prompt_artifact)[: -len(".prompt.md")] + ".llm.log"
        calls.append({
            "execution_id": str(record.get("execution_id") or ""),
            "command": str(job.get("command_name") or ""),
            "provider": str(job.get("llm") or ""),
            "model": str(job.get("model") or ""),
            "status": str(record.get("status") or ""),
            "returncode": result.get("returncode"),
            "elapsed_ms": stats.get("elapsed_ms") or 0,
            "input_tokens": total,
            "cached_input_tokens": cached,
            "output_tokens": output,
            "prompt": _artifact(prompt_artifact),
            "output": _artifact(artifacts.get("output")),
            "raw": _artifact(artifacts.get("raw")),
            "llm_log": _artifact(llm_log_artifact),
        })
    return tuple(calls)


# ── rendering ────────────────────────────────────────────────────────────────────────


_STYLE = """
:root {
  --paper: #ffffff; --ink: #14171a; --muted: #5b616a; --rule: #c9c9c3; --hard: #14171a;
  --pass: #16663a; --fail: #a3170f; --warn: #8a5a00; --tint: #f7f7f4;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 1.75rem 1rem 3rem; background: var(--paper); color: var(--ink);
  font: 13.5px/1.62 "Courier New", Courier, ui-monospace, SFMono-Regular, monospace;
}
main { max-width: 1080px; margin: 0 auto; }
a { color: var(--ink); text-underline-offset: 2px; }
a:hover { color: var(--pass); }
code, pre, .mono { font-family: inherit; }
code { background: var(--tint); padding: 0 .25em; }
pre {
  background: var(--tint); border: 1px solid var(--rule); padding: .8rem .9rem;
  overflow-x: auto; font-size: .84rem; margin: 0 0 1rem; white-space: pre-wrap; word-break: break-word;
}

/* ── letterhead ─────────────────────────────────────────────── */
.letterhead {
  display: flex; align-items: flex-start; gap: 1.5rem; flex-wrap: wrap;
  border-bottom: 3px double var(--hard); padding-bottom: 1rem; margin-bottom: 1rem;
}
.letterhead .logo { width: 190px; max-width: 42vw; height: auto; flex: 0 0 auto; }
.letterhead .wordmark { font-size: 1.7rem; font-weight: 700; letter-spacing: .12em; color: var(--pass); }
.ident { flex: 1 1 18rem; min-width: 15rem; }
.kind { text-transform: uppercase; letter-spacing: .22em; font-size: .72rem; color: var(--muted); }
h1 { font-size: 1.32rem; font-weight: 700; letter-spacing: .04em; margin: .3rem 0 .25rem; text-transform: uppercase; }
.docline { color: var(--muted); font-size: .82rem; word-break: break-all; }

/* ── rubber stamp ───────────────────────────────────────────── */
.stamp {
  flex: 0 0 auto; align-self: center; text-align: center; padding: .45rem 1.1rem .55rem;
  border: 3px solid currentColor; outline: 1px solid currentColor; outline-offset: 3px;
  transform: rotate(-7deg); opacity: .88; letter-spacing: .16em; font-weight: 700;
  text-transform: uppercase; line-height: 1.2;
}
.stamp .mark { display: block; font-size: 1.55rem; }
.stamp .sub { display: block; font-size: .62rem; letter-spacing: .18em; margin-top: .2rem; }
.stamp.pass { color: var(--pass); }
.stamp.fail { color: var(--fail); }
.stamp.warn { color: var(--warn); }

/* ── verdict and metadata ───────────────────────────────────── */
.verdict { margin: 0 0 1rem; font-size: .95rem; }
.verdict .state { font-weight: 700; letter-spacing: .08em; }
.verdict.pass .state { color: var(--pass); }
.verdict.fail .state { color: var(--fail); }
.verdict .detail { color: var(--ink); margin-top: .3rem; font-size: .86rem; }
dl.meta {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(23rem, 1fr));
  gap: .15rem 2rem; margin: 0 0 1.25rem; border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule); padding: .6rem 0; font-size: .82rem;
}
dl.meta > div { display: flex; gap: .6rem; }
dl.meta dt { color: var(--muted); text-transform: uppercase; letter-spacing: .08em; flex: 0 0 7rem; }
dl.meta dd { margin: 0; overflow-wrap: anywhere; }

/* ── tabs ───────────────────────────────────────────────────── */
nav.tabs { display: flex; flex-wrap: wrap; gap: .25rem; border-bottom: 1px solid var(--hard); margin-bottom: 1.25rem; }
nav.tabs button {
  font: inherit; font-size: .8rem; text-transform: uppercase; letter-spacing: .12em;
  background: var(--tint); color: var(--muted); cursor: pointer; padding: .4rem 1rem;
  border: 1px solid var(--rule); border-bottom: none; margin-bottom: -1px;
}
nav.tabs button[aria-selected="true"] {
  background: var(--paper); color: var(--ink); font-weight: 700;
  border-color: var(--hard); border-bottom: 1px solid var(--paper);
}
.panel { display: none; }
.panel.active { display: block; }
h2 { font-size: .9rem; margin: 1.75rem 0 .4rem; text-transform: uppercase; letter-spacing: .12em; }
.panel > h2:first-child { margin-top: 0; }
p.note { color: var(--muted); margin: .2rem 0 .8rem; font-size: .82rem; }

/* ── tables ─────────────────────────────────────────────────── */
.scroll { overflow-x: auto; border: 1px solid var(--rule); }
table { border-collapse: collapse; width: 100%; font-size: .82rem; }
th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { font-weight: 700; font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; white-space: nowrap; background: var(--tint); border-bottom: 1px solid var(--hard); }
tbody tr:last-child td { border-bottom: none; }
td.num { text-align: right; white-space: nowrap; }
td.hash { font-size: .7rem; color: var(--muted); word-break: break-all; }
td.dash { color: var(--muted); }
td.nowrap { white-space: nowrap; }
table.tree td.name { padding-left: calc(.6rem + var(--d) * 1.3rem); white-space: nowrap; }
table.tree th:nth-child(2) { text-align: right; }
table.tree td.name strong { font-weight: 700; }
.tag { display: inline-block; padding: 0 .4rem; font-size: .72rem; font-weight: 700; letter-spacing: .06em; border: 1px solid currentColor; box-shadow: 0 0 0 1px var(--paper) inset; }
.tag.pass { color: var(--pass); }
.tag.fail { color: var(--fail); }
.tag.degraded { color: var(--warn); }
.tag.raw { color: var(--muted); font-weight: 400; }
.tag.unknown { color: var(--warn); }

/* ── receipt ────────────────────────────────────────────────── */
.receipt { border: 1px solid var(--hard); margin: 0 0 1.25rem; }
.receipt > .caption {
  display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap;
  background: var(--hard); color: var(--paper); padding: .35rem .6rem;
  font-size: .74rem; text-transform: uppercase; letter-spacing: .18em; font-weight: 700;
}
.receipt > .caption .tally { letter-spacing: .1em; }
.receipt .scroll { border: none; }
.receipt table td:first-child { white-space: nowrap; font-weight: 700; }
.receipt tbody tr.fail td:first-child { color: var(--fail); }
.receipt tbody tr.unknown td:first-child { color: var(--warn); }
.receipt td.detail { color: var(--muted); }

/* ── guided path and limits ─────────────────────────────────── */
ol.steps { margin: 0 0 1.25rem; padding-left: 1.5rem; font-size: .84rem; }
ol.steps li { margin: .3rem 0; }
ol.steps li .what { display: block; color: var(--muted); font-size: .8rem; }
ul.limits { margin: 0 0 1.25rem; padding-left: 1.3rem; font-size: .82rem; color: var(--muted); }
ul.limits li { margin: .2rem 0; }
footer { margin-top: 2.5rem; padding-top: .75rem; border-top: 3px double var(--hard); color: var(--muted); font-size: .78rem; }

/* ── artifact viewer ────────────────────────────────────────── */
.fileheader { border-bottom: 3px double var(--hard); padding-bottom: .7rem; margin-bottom: 1.25rem; }
.fileheader h1 { font-size: 1.05rem; text-transform: none; letter-spacing: 0; word-break: break-all; }
.filenav { display: flex; gap: 1.2rem; font-size: .78rem; text-transform: uppercase; letter-spacing: .1em; }
.doc > :first-child { margin-top: 0; }
.doc h1, .doc h2, .doc h3, .doc h4, .doc h5, .doc h6 {
  font-size: .95rem; margin: 1.6rem 0 .5rem; text-transform: uppercase; letter-spacing: .1em;
}
.doc h1 { font-size: 1.1rem; }
.doc h3, .doc h4, .doc h5, .doc h6 { text-transform: none; letter-spacing: .04em; color: var(--muted); }
.doc p { margin: 0 0 .9rem; }
.doc ul, .doc ol { margin: 0 0 .9rem; padding-left: 1.6rem; }
.doc li { margin: .15rem 0; }
.doc blockquote { margin: 0 0 .9rem; padding: .1rem 0 .1rem .9rem; border-left: 3px solid var(--rule); color: var(--muted); }
.doc hr { border: none; border-top: 1px solid var(--rule); margin: 1.4rem 0; }
.doc table { margin-bottom: 0; }
.doc .scroll { margin-bottom: .9rem; }
.doc del { color: var(--muted); }

@media print {
  body { padding: 0; }
  nav.tabs { display: none; }
  .panel { display: block; page-break-inside: avoid; }
}
"""


_SCRIPT = """
document.addEventListener('click', function (event) {
  var tab = event.target.closest('nav.tabs button[data-panel]');
  if (!tab) return;
  var root = tab.closest('[data-tabgroup]') || tab.closest('main');
  // A nested strip lives inside its parent's panels, so only elements whose nearest
  // tab group is this one are switched; an inner strip keeps its own selection.
  var mine = function (element) {
    return (element.closest('[data-tabgroup]') || root) === root;
  };
  root.querySelectorAll('nav.tabs button[data-panel]').forEach(function (button) {
    if (mine(button)) button.setAttribute('aria-selected', String(button === tab));
  });
  root.querySelectorAll('.panel').forEach(function (panel) {
    if (mine(panel)) panel.classList.toggle('active', panel.id === 'panel-' + tab.dataset.panel);
  });
});
"""


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    """Inline the Drydock mark so a copied kit keeps its letterhead offline."""
    from drydock import paths

    try:
        path = paths.get_quarterdeck_root() / "static" / "drydock_logo.png"
    except (FileNotFoundError, OSError):
        return ""
    if not path.is_file():
        return ""
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _page(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>{_STYLE}</style>\n"
        f"</head>\n<body>\n<main>\n{body}\n</main>\n<script>{_SCRIPT}</script>\n"
        "</body>\n</html>\n"
    )


# ── artifact viewers ─────────────────────────────────────────────────────────────────
#
# A report links hundreds of artifacts. Opened directly they are raw text, styled by nothing
# and rendered by the browser's own defaults, so leaving a report means leaving its typography.
# Every linked text artifact therefore gets a generated viewer page carrying the report's own
# styling: Markdown is rendered, everything else is shown as source. The raw file stays one
# click away and stays the thing SHA256SUMS covers.

_VIEW_DIR = "view"

_ASSETS_DIR = "assets"

_CSS_NAME = "kit.css"

#: Generated subtrees, rewritten on every rebuild and never inventoried or checksummed.
_GENERATED_DIRS = frozenset({_VIEW_DIR, _ASSETS_DIR})

_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})

_TEXT_SUFFIXES = frozenset({
    ".cfg",
    ".conf",
    ".css",
    ".csv",
    ".diff",
    ".html",
    ".ini",
    ".jinja",
    ".js",
    ".json",
    ".jsonl",
    ".log",
    ".patch",
    ".ps1",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
})

#: Extensionless files Drydock and its Targets are known to write as text.
_TEXT_STEMS = frozenset({"LICENSE", "NOTICE", "SHA256SUMS", "Makefile", "Dockerfile"})

#: A viewer inlines the artifact, so an artifact larger than this stays raw-only.
_MAX_VIEW_BYTES = 4_000_000


#: Populated for the duration of one render so ``_anchor`` can route a linked artifact to its
#: viewer. Rendering is single-threaded and deterministic; the map is cleared when it finishes.
_VIEWERS: dict[str, str] = {}


@contextmanager
def _viewers(mapping: dict[str, str]) -> Iterator[None]:
    """Route links to generated viewers while a page renders."""
    _VIEWERS.clear()
    _VIEWERS.update(mapping)
    try:
        yield
    finally:
        _VIEWERS.clear()


def _is_viewable(path: Path) -> bool:
    if path.suffix.lower() in _MARKDOWN_SUFFIXES or path.suffix.lower() in _TEXT_SUFFIXES:
        return True
    return not path.suffix and path.name in _TEXT_STEMS


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_VIEW_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _viewer_page(base: Path, relative: str, kind: str, home: str) -> str:
    """Render one artifact inside the report's styling, or return "" if it cannot be shown."""
    text = _read_text(base / relative)
    if text is None:
        return ""
    depth = relative.count("/") + 1  # the viewer itself lives one level down, under view/
    up = "../" * depth
    markdown = Path(relative).suffix.lower() in _MARKDOWN_SUFFIXES
    body = render_markdown(text) if markdown else f"<pre>{html.escape(text)}</pre>"
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(relative)}</title>\n"
        f'<link rel="stylesheet" href="{up}{_ASSETS_DIR}/{_CSS_NAME}">\n'
        "</head>\n<body>\n<main>\n"
        f'<header class="fileheader"><div class="kind">{html.escape(kind)}</div>'
        f"<h1>{html.escape(relative)}</h1>"
        f'<div class="filenav"><a href="{up}{html.escape(home)}">&larr; Report</a>'
        f'<a href="{up}{html.escape(relative)}">Raw file</a></div></header>\n'
        f'<article class="doc">{body}</article>\n'
        "</main>\n</body>\n</html>\n"
    )


def _write_viewers(base: Path, relatives: Iterable[str], kind: str, home: str) -> dict[str, str]:
    """Write a viewer for every artifact that can be shown; map artifact path to viewer path.

    The generated subtrees are removed first, so a viewer for an artifact that no longer
    exists cannot survive a rebuild.
    """
    for name in _GENERATED_DIRS:
        shutil.rmtree(base / name, ignore_errors=True)
    (base / _ASSETS_DIR).mkdir(parents=True, exist_ok=True)
    (base / _ASSETS_DIR / _CSS_NAME).write_text(_STYLE, encoding="utf-8")
    mapping: dict[str, str] = {}
    for relative in sorted(set(relatives)):
        source = base / relative
        if not source.is_file() or not _is_viewable(source):
            continue
        # An empty artifact has nothing to show. A page reading "This file is empty." wastes a
        # click and, on a failed command, actively misleads: the reader went looking for the
        # failure and was handed a blank stdout while the explanation sat in stderr.
        if source.stat().st_size == 0:
            continue
        page = _viewer_page(base, relative, kind, home)
        if not page:
            continue
        target = base / _VIEW_DIR / f"{relative}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
        mapping[relative] = f"{_VIEW_DIR}/{relative}.html"
    return mapping


def _letterhead(
    kind: str,
    heading: str,
    docline: str,
    passed: bool | str,
    mark: str,
    sub: str = "Drydock UAT",
) -> str:
    """Render the report's masthead: Drydock mark, document identity, and the verdict stamp.

    ``passed`` is a boolean for a two-state document, or a state name — ``pass``, ``warn``, or
    ``fail`` — for one that reports an unfinished middle as well as an outcome.
    """
    logo = _logo_data_uri()
    brand = (
        f'<img class="logo" src="{logo}" alt="Drydock">'
        if logo
        else '<div class="wordmark">DRYDOCK</div>'
    )
    state = passed if isinstance(passed, str) else ("pass" if passed else "fail")
    return (
        f'<header class="letterhead">{brand}'
        f'<div class="ident"><div class="kind">{html.escape(kind)}</div>'
        f"<h1>{html.escape(heading)}</h1>"
        f'<div class="docline">{html.escape(docline)}</div></div>'
        f'<div class="stamp {state}"><span class="mark">{html.escape(mark)}</span>'
        f'<span class="sub">{html.escape(sub)}</span></div></header>'
    )


def _verdict(passed: bool, verdict: str, detail: str) -> str:
    state = "pass" if passed else "fail"
    detail_html = f'<div class="detail">{detail}</div>' if detail else ""
    return (
        f'<div class="verdict {state}"><span class="state">{html.escape(verdict)}</span>'
        f"{detail_html}</div>"
    )


def _tabs(panels: Sequence[tuple[str, str, str]], group: str = "main") -> str:
    """Render a tab strip and its panels from ``(slug, label, body)`` triples.

    ``group`` names the strip. Every strip is emitted inside its own ``data-tabgroup``
    container and the click handler resolves the nearest container first, so nested and
    sibling strips switch their own panels only.
    """
    panels = [panel for panel in panels if panel[2]]
    if not panels:
        return ""
    buttons = "".join(
        f'<button type="button" data-panel="{slug}" '
        f'aria-selected="{"true" if index == 0 else "false"}">{html.escape(label)}</button>'
        for index, (slug, label, _) in enumerate(panels)
    )
    sections = "".join(
        f'<section class="panel{" active" if index == 0 else ""}" id="panel-{slug}">{body}</section>'
        for index, (slug, _, body) in enumerate(panels)
    )
    return (
        f'<div class="tabgroup" data-tabgroup="{html.escape(group)}">'
        f'<nav class="tabs">{buttons}</nav>{sections}</div>'
    )


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return '<p class="note">None recorded.</p>'
    head = "".join(f"<th>{html.escape(name)}</th>" for name in headers)
    body = "".join("<tr>" + "".join(row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _anchor(target: str, label: str = "") -> str:
    """Link a kit file. Kits are read from ``file://``, so every link opens its own tab.

    An artifact with a generated viewer is linked through it, so the reader stays inside the
    report's styling instead of landing on raw text the browser renders however it likes.
    """
    href = _VIEWERS.get(target, target)
    return (
        f'<a class="mono" href="{html.escape(href)}" target="_blank" '
        f'rel="noopener">{html.escape(label or target)}</a>'
    )


def _link(target: str, label: str = "") -> str:
    if not target:
        return '<td class="dash">—</td>'
    return f"<td>{_anchor(target, label)}</td>"


def _stream_link(base: Path, relative: str, label: str) -> str:
    """Link a captured stream only when it holds bytes.

    An absent or zero-length stream is the normal case for a command that printed nothing to
    it, so it is rendered as a dash rather than a link that opens an empty file.
    """
    if not relative:
        return '<td class="dash">—</td>'
    path = base / relative
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return '<td class="dash">—</td>'
    except OSError:
        return '<td class="dash">—</td>'
    return f"<td>{_anchor(relative, label)}</td>"


def _llm_log_cell(base: Path, logs: Sequence[str]) -> str:
    """Link every LLM activity log one command produced, beside its stdout and stderr.

    Token and cost accounting is written to these logs instead of the command's streams, so a
    receipt that shows stdout and stderr without them is missing the run's billing evidence.
    A command that called no model, or whose logs the kit did not publish, renders as a dash.
    """
    linked = [path for path in logs if path and (base / path).is_file()]
    if not linked:
        return '<td class="dash">—</td>'
    labels = (
        ("llm",)
        if len(linked) == 1
        else tuple(f"llm {index}" for index in range(1, len(linked) + 1))
    )
    return (
        "<td>"
        + " · ".join(_anchor(path, label) for path, label in zip(linked, labels, strict=True))
        + "</td>"
    )


def _cell(text: object, *, css: str = "") -> str:
    attribute = f' class="{css}"' if css else ""
    return f"<td{attribute}>{html.escape(str(text))}</td>"


def _is_status_command(argv: Sequence[object]) -> bool:
    """Return whether argv invokes Drydock's informational ``status`` command."""
    return _command_text(argv).split()[:2] == ["drydock", "status"]


#: The verdicts ``drydock status`` prints as the first word of its first line. These are states,
#: not outcomes: the command succeeded in every case and its exit code is the verdict channel.
_STATUS_HEADLINES = (
    "READY TO BUILD",
    "BUILD COMPLETE",
    "NOT READY",
    "INCOMPLETE",
    "COMPLETE",
    "BLOCKED",
)


def status_headline(text: str) -> str:
    """Return the state a ``drydock status`` invocation reported, from the line it printed.

    ``--ready`` and ``--check`` each lead with their verdict. A bare ``drydock status`` renders a
    projection with no headline, which reports as no state rather than an invented one.
    """
    for line in (text or "").splitlines():
        stripped = line.strip()
        for headline in _STATUS_HEADLINES:
            if stripped.startswith(headline):
                return headline
    return ""


def recorded_status_headline(base: Path, stdout: str, argv: Sequence[object]) -> str:
    """Read the state a status step reported, so its row can show that instead of a grade."""
    if not stdout or not _is_status_command(argv):
        return ""
    try:
        with (base / stdout).open("r", encoding="utf-8", errors="replace") as handle:
            return status_headline(handle.read(4096))
    except OSError:
        return ""


def _status_cell(returncode: object, argv: Sequence[object] = (), headline: str = "") -> str:
    """Grade a command's exit code, or report a status command's state without grading it.

    ``drydock status`` is a status check. Its nonzero exits are states — NOT READY, INCOMPLETE —
    so the Result column carries the state it reported and never a pass/fail verdict over it.
    """
    ok = returncode == 0
    if _is_status_command(argv):
        if not headline:
            return '<td class="dash">—</td>'
        return (
            f'<td><span class="tag raw" title="exit {html.escape(str(returncode))}">'
            f"{html.escape(headline)}</span></td>"
        )
    label = "OK" if ok else f"FAIL {returncode}"
    state = "pass" if ok else "fail"
    return (
        f'<td><span class="tag {state}" title="exit {html.escape(str(returncode))}">'
        f"{html.escape(label)}</span></td>"
    )


def _command_text(argv: Sequence[object]) -> str:
    """Render argv the way an operator would type it, hiding the interpreter shim."""
    parts = [str(part) for part in argv]
    if "-m" in parts and len(parts) > parts.index("-m") + 1:
        parts = ["drydock", *parts[parts.index("-m") + 2 :]]
    return " ".join(parts)


def _meta(pairs: Sequence[tuple[str, str]]) -> str:
    items = "".join(
        f"<div><dt>{html.escape(name)}</dt><dd>{value}</dd></div>" for name, value in pairs if value
    )
    return f'<dl class="meta">{items}</dl>' if items else ""


def _tokens(usage: dict) -> str:
    """Render usage the way it is billed: cache reads, full-rate input, generated output."""
    if not usage:
        return ""
    cached = int(usage.get("cached_input_tokens", 0) or 0)
    uncached = int(usage.get("fresh_input_tokens", 0) or 0) or max(
        int(usage.get("input_tokens", 0) or 0) - cached, 0
    )
    return (
        f"{usage.get('calls', 0)} calls · cached {cached:,} · "
        f"uncached {uncached:,} · output {int(usage.get('output_tokens', 0) or 0):,}"
    )


# Directories holding unprocessed provider or runtime output. Their contents are kept for
# reproducibility but are not the reviewable record, so the tree marks them rather than
# leaving a reader to open a 30 MB transcript to find that out.
_RAW_PREFIXES = (
    "evidence/provider_raw/",
    "evidence/prompt_outputs/",
    "workspace/logs/",
    "logs/",
)


def _is_raw(path: str) -> bool:
    return path.startswith(_RAW_PREFIXES) or path.endswith(".raw.jsonl")


def _tree_rows(
    files: Sequence[FileRecord], prefix: str = ""
) -> list[tuple[int, str, FileRecord | None, int]]:
    """Flatten an inventory into ``(depth, name, record, bytes)`` rows, directories first.

    A directory row carries no record and reports the total size of everything beneath it.
    """
    rows: list[tuple[int, str, FileRecord | None, int]] = []

    def walk(prefix: str, records: Sequence[FileRecord], depth: int) -> None:
        directories: dict[str, list[FileRecord]] = {}
        leaves: list[FileRecord] = []
        for record in records:
            remainder = record.path[len(prefix) :]
            head, separator, _ = remainder.partition("/")
            if separator:
                directories.setdefault(head, []).append(record)
            else:
                leaves.append(record)
        for name, children in sorted(directories.items()):
            rows.append((depth, f"{name}/", None, sum(item.bytes for item in children)))
            walk(f"{prefix}{name}/", children, depth + 1)
        for record in sorted(leaves, key=lambda item: item.path):
            rows.append((depth, record.path.rpartition("/")[2], record, record.bytes))

    walk(prefix, files, 0)
    return rows


def _tree(files: Sequence[FileRecord], root: str, display_root: str) -> str:
    """Render one directory tree: indented names, sizes, and a marker on raw output."""
    if not files:
        return '<p class="note">None recorded.</p>'
    rows = []
    rows.append(
        f'<tr><td class="name" style="--d:0"><strong>{html.escape(display_root)}</strong></td>'
        f'<td class="num">{sum(record.bytes for record in files):,}</td><td></td></tr>'
    )
    # The tree is rooted at the group's own directory, so its name is the caption row and is
    # not repeated as the first branch.
    for depth, name, record, size in _tree_rows(files, f"{root}/"):
        # A zero-byte artifact is listed but never linked: there is nothing behind the link.
        if record is None:
            cell = f"<strong>{html.escape(name)}</strong>"
        elif record.bytes == 0:
            cell = f'{html.escape(name)} <span class="tag">empty</span>'
        else:
            cell = _anchor(record.path, name)
        raw = (
            '<span class="tag raw">raw</span>'
            if _is_raw(record.path if record is not None else f"{root}/{name}")
            else ""
        )
        rows.append(
            f'<tr><td class="name" style="--d:{depth + 1}">{cell}</td>'
            f'<td class="num">{size:,}</td><td>{raw}</td></tr>'
        )
    return (
        '<div class="scroll"><table class="tree"><thead><tr><th>Path</th><th>Bytes</th>'
        f"<th></th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def inventory_panels(
    groups: Sequence[ArtifactGroup],
    run_prefix: str,
    tabs: Mapping[str, tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """Render the file inventory as one directory tree per tab.

    ``tabs`` maps an :class:`ArtifactGroup` name to the ``(slug, label)`` its tab uses. A group
    absent from the map is inventoried but not shown as a tree — a single-file group is a link,
    not a directory.
    """
    panels: list[tuple[str, str, str]] = []
    for group in groups:
        tab = tabs.get(group.name)
        if tab is None:
            continue
        slug, label = tab
        # The kit, not the run, is the unit an operator publishes and reads, so every path is
        # stated relative to it even though the links resolve from this run directory.
        body = (
            f"<h2>{html.escape(group.name)}</h2>"
            f'<p class="note">{html.escape(group.description)} '
            f"{len(group.files)} files, {group.total_bytes:,} bytes.</p>"
            + _tree(group.files, slug, f"{run_prefix}{slug}/")
        )
        panels.append((slug, label, body))
    return panels


def local_run_window(environment: Mapping[str, object]) -> str:
    """Render a run's start and finish in the reader's local time.

    A run id is UTC, so it reads hours away from the wall clock the operator watched the run on
    and cannot be matched to a session by eye. The report states the local window explicitly
    rather than making the reader convert a timezone in their head to answer "is this the run I
    just did?". The zone abbreviation is included because the answer depends on it.
    """
    started = _local_time(environment.get("started_at"))
    finished = _local_time(environment.get("finished_at"))
    if started and finished:
        return f"{started} — {finished}"
    return started or finished or "unrecorded"


def _local_time(value: object) -> str:
    """Render a recorded UTC instant in the reader's local time.

    Both instant spellings Drydock writes are accepted: the log stamp's ``...Z`` and the
    offset form ``...+00:00`` the workflow ladder records.
    """
    if not isinstance(value, str) or not value:
        return ""
    try:
        moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _md_link(case_root: Path, relative: str, label: str = "") -> str:
    """Link a run artifact in Markdown, or say plainly that the run did not write one."""
    if not relative or not (case_root / relative).exists():
        return "not recorded for this run."
    trimmed = relative.rstrip("/")
    return f"[`{label or relative}`]({trimmed})"


# ── receipt ──────────────────────────────────────────────────────────────────────────
#
# A reader who did not run the build cannot be asked to reconstruct a verdict from eighteen
# exit codes. The receipt states the six claims a run either earned or did not, each with the
# artifact that settles it, above every explanation of how Drydock works. A claim the record
# does not settle is rendered as unproven, never as a pass.


@dataclass(frozen=True)
class Check:
    """One receipt claim: what was asserted, whether the record supports it, and the proof."""

    name: str
    state: str  # "pass", "fail", or "unknown"
    detail: str
    evidence: str = ""


_CHECK_TAGS = {"pass": "PASS", "fail": "FAIL", "unknown": "UNPROVEN"}


def _exit_state(code: object) -> str:
    if code is None or code == "":
        return "unknown"
    return "pass" if code == 0 else "fail"


def _command_by_suffix(commands: Sequence[dict], suffix: str) -> dict | None:
    """Find the last lifecycle command whose label ends in ``suffix``.

    Labels are sequence-prefixed (``16-score-acceptance``), and a stage can run more than once,
    so the receipt reports the final occurrence: the one that decided the run.
    """
    matches = [item for item in commands if str(item.get("label") or "").endswith(suffix)]
    return matches[-1] if matches else None


def _evidence_link(case_root: Path, relative: str, prefix: str, label: str = "") -> str:
    """Link a run artifact from the run receipt, or from the project page one level above it.

    The run receipt routes through :func:`_anchor`, which reaches the generated viewer. The
    project page has no viewer map for another directory's files, so it addresses that run's
    viewer by its known path and falls back to the raw artifact.
    """
    # A receipt links only artifacts that are on disk: a dead link in a proof kit is a claim
    # the kit cannot support.
    if not relative or not (case_root / relative).exists():
        return ""
    if not prefix:
        return _anchor(relative, label or relative)
    viewer = case_root / _VIEW_DIR / f"{relative}.html"
    href = f"{prefix}{_VIEW_DIR}/{relative}.html" if viewer.is_file() else f"{prefix}{relative}"
    return (
        f'<a class="mono" href="{html.escape(href)}" target="_blank" rel="noopener">'
        f"{html.escape(label or relative)}</a>"
    )


_RUN_NOTES = (
    "One run is evidence of one run. It is not a benchmark.",
    "It is not a security certification of the delivered code.",
)


def run_notes() -> str:
    return (
        '<h2>RUN NOTES:</h2><ul class="limits">'
        + "".join(f"<li>{html.escape(item)}</li>" for item in _RUN_NOTES)
        + "</ul>"
    )


def _render_receipt(
    base: Path,
    checks: Sequence[Check],
    prefix: str = "",
    tags: Mapping[str, str] | None = None,
) -> str:
    """Render the receipt table: one row per claim, its verdict, and the artifact proving it.

    The claims themselves are the caller's: what a UAT run must prove about the harness is not
    what a build must prove about the product. This renders whatever list it is handed.
    """
    passed = sum(check.state == "pass" for check in checks)
    rows = [
        [
            _cell(check.name),
            f'<td><span class="tag {check.state}">{(tags or _CHECK_TAGS)[check.state]}</span></td>',
            _cell(check.detail, css="detail"),
            f"<td>{_evidence_link(base, check.evidence, prefix) or '—'}</td>",
        ]
        for check in checks
    ]
    tally = f"{passed} of {len(checks)} claims proven"
    return (
        '<section class="receipt">'
        f'<div class="caption"><span>Receipt</span><span class="tally">{html.escape(tally)}</span>'
        "</div>" + _table(("Claim", "Verdict", "Recorded outcome", "Proof"), rows) + "</section>"
    )
