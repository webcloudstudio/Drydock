"""Portable proof-kit rendering for completed UAT runs.

A UAT run leaves behind command logs, LLM transcripts, a Blueprint, and delivered code.
This module turns that raw output into a self-contained, checkable receipt:

* every file under the run is inventoried with byte count and SHA-256;
* ``SHA256SUMS`` makes the whole kit verifiable with ``sha256sum -c``;
* ``index.html`` links each lifecycle command to its own stdout and stderr, states the
  verdict for the run, and never reports success that the recorded exit codes do not
  support.

Rendering is deterministic and reads only what is already on disk, so a kit can be rebuilt
for an old run without re-executing it.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import shutil
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = [
    "ArtifactGroup",
    "FileRecord",
    "build_case_kit",
    "build_kit_index",
    "prune_generated",
]

# Interpreter and tooling caches are regenerated on demand, differ between machines, and
# make a checked-in receipt noisy. They are removed before the kit is inventoried.
PRUNED_DIRECTORIES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"})

_INDEX_NAME = "index.html"
_SUMS_NAME = "SHA256SUMS"
# Generated at the top of a kit and rewritten on every rebuild, so they are never inventoried:
# a checksum of a file that the next rebuild replaces is a checksum that fails verification.
_KIT_OUTPUTS = frozenset({_INDEX_NAME, _SUMS_NAME, "README.md"})

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


def _iter_files(root: Path, base: Path, *, skip: Iterable[Path] = ()) -> Iterator[FileRecord]:
    if not root.is_dir():
        return
    skipped = {path.resolve() for path in skip}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(parent.resolve() in skipped for parent in path.parents):
            continue
        if path.parent == base and path.name in _KIT_OUTPUTS:
            continue
        yield _hash_file(path, base)


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
    try:
        return Path(text).relative_to(base).as_posix()
    except ValueError:
        return text


def _tail(path: Path, limit: int = _MAX_EXCERPT_BYTES) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace").strip()


def _case_groups(case_root: Path, target: str) -> tuple[ArtifactGroup, ...]:
    """Inventory a completed case as the four directories a run writes, plus its record.

    ``target`` is unused: every directory is inventoried whole, so a Target rename cannot
    silently drop files from the receipt.
    """
    del target
    groups = [
        ArtifactGroup(
            "Build",
            "Working tree produced by drydock build, exactly as the build left it.",
            tuple(_iter_files(case_root / "build", case_root)),
        ),
        ArtifactGroup(
            "Evidence",
            "Captured command streams, assembled prompts, model output, and provider transcripts.",
            tuple(_iter_files(case_root / "evidence", case_root)),
        ),
        ArtifactGroup(
            "Sources",
            "Input bundle staged for drydock import before the lifecycle started.",
            tuple(_iter_files(case_root / "sources", case_root)),
        ),
        ArtifactGroup(
            "Workspace",
            "Drydock workspace the run drove: Blueprint, Manifest, Target artifacts, and logs.",
            tuple(_iter_files(case_root / "workspace", case_root)),
        ),
        ArtifactGroup(
            "Run record",
            "Machine-readable outcome for this project.",
            tuple(
                _hash_file(path, case_root)
                for path in sorted(case_root.glob("*"))
                if path.is_file() and not path.is_symlink() and path.name not in _KIT_OUTPUTS
            ),
        ),
    ]
    return tuple(group for group in groups if group.files)


def _llm_calls(records_path: Path, base: Path) -> tuple[dict[str, object], ...]:
    """Summarize each recorded LLM execution for the receipt's call table."""
    from drydock.llm_usage import normalize_tokens, read_records

    records, _ = read_records(records_path)
    calls: list[dict[str, object]] = []
    for record in records:
        job = record.get("job") if isinstance(record.get("job"), dict) else {}
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), dict) else {}
        total, cached, output = normalize_tokens(str(job.get("llm") or ""), stats)
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
            "prompt": _relative(artifacts.get("prompt"), base),
            "output": _relative(artifacts.get("output"), base),
            "raw": _relative(artifacts.get("raw"), base),
        })
    return tuple(calls)


def _write_sums(base: Path, groups: Sequence[ArtifactGroup]) -> None:
    lines = [f"{record.sha256}  {record.path}" for group in groups for record in group.files]
    (base / _SUMS_NAME).write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


# ── rendering ────────────────────────────────────────────────────────────────────────


_STYLE = """
:root {
  --paper: #ffffff; --ink: #14171a; --muted: #5b616a; --rule: #c9c9c3; --hard: #14171a;
  --pass: #16663a; --fail: #a3170f; --tint: #f7f7f4;
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
.tag.raw { color: var(--muted); font-weight: 400; }
footer { margin-top: 2.5rem; padding-top: .75rem; border-top: 3px double var(--hard); color: var(--muted); font-size: .78rem; }

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
  var root = tab.closest('main');
  root.querySelectorAll('nav.tabs button[data-panel]').forEach(function (button) {
    button.setAttribute('aria-selected', String(button === tab));
  });
  root.querySelectorAll('.panel').forEach(function (panel) {
    panel.classList.toggle('active', panel.id === 'panel-' + tab.dataset.panel);
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


def _letterhead(kind: str, heading: str, docline: str, passed: bool, mark: str) -> str:
    """Render the report's masthead: Drydock mark, document identity, and the verdict stamp."""
    logo = _logo_data_uri()
    brand = (
        f'<img class="logo" src="{logo}" alt="Drydock">'
        if logo
        else '<div class="wordmark">DRYDOCK</div>'
    )
    state = "pass" if passed else "fail"
    return (
        f'<header class="letterhead">{brand}'
        f'<div class="ident"><div class="kind">{html.escape(kind)}</div>'
        f"<h1>{html.escape(heading)}</h1>"
        f'<div class="docline">{html.escape(docline)}</div></div>'
        f'<div class="stamp {state}"><span class="mark">{html.escape(mark)}</span>'
        '<span class="sub">Drydock UAT</span></div></header>'
    )


def _verdict(passed: bool, verdict: str, detail: str) -> str:
    state = "pass" if passed else "fail"
    detail_html = f'<div class="detail">{detail}</div>' if detail else ""
    return (
        f'<div class="verdict {state}"><span class="state">{html.escape(verdict)}</span>'
        f"{detail_html}</div>"
    )


def _tabs(panels: Sequence[tuple[str, str, str]]) -> str:
    """Render a tab strip and its panels from ``(slug, label, body)`` triples."""
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
    return f'<nav class="tabs">{buttons}</nav>{sections}'


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return '<p class="note">None recorded.</p>'
    head = "".join(f"<th>{html.escape(name)}</th>" for name in headers)
    body = "".join("<tr>" + "".join(row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _anchor(target: str, label: str = "") -> str:
    """Link a kit file. Kits are read from ``file://``, so every link opens its own tab."""
    return (
        f'<a class="mono" href="{html.escape(target)}" target="_blank" '
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


def _cell(text: object, *, css: str = "") -> str:
    attribute = f' class="{css}"' if css else ""
    return f"<td{attribute}>{html.escape(str(text))}</td>"


def _status_cell(returncode: object) -> str:
    """Stamp a recorded exit code as the verdict it is, keeping the code on a failure."""
    ok = returncode == 0
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


# The four directories a run writes, each rendered as its own tree. The run record is not a
# tab: the footer already links it, and one file is not a tree.
_INVENTORY_TABS = {
    "Build": ("build", "Build"),
    "Evidence": ("evidence", "Evidence"),
    "Sources": ("sources", "Sources"),
    "Workspace": ("workspace", "Workspace"),
}

# Directories holding unprocessed provider or runtime output. Their contents are kept for
# reproducibility but are not the reviewable record, so the tree marks them rather than
# leaving a reader to open a 30 MB transcript to find that out.
_RAW_PREFIXES = (
    "evidence/provider_raw/",
    "evidence/prompt_outputs/",
    "workspace/logs/",
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
        cell = (
            _anchor(record.path, name)
            if record is not None
            else f"<strong>{html.escape(name)}</strong>"
        )
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


def _delivered_root(groups: Sequence[ArtifactGroup], run_prefix: str) -> str:
    """Name the directory the build delivered its code into, stated relative to the kit."""
    files = next((group.files for group in groups if group.name == "Build"), ())
    if not files:
        return ""
    common = files[0].path.rpartition("/")[0]
    for record in files[1:]:
        directory = record.path.rpartition("/")[0]
        while common and not (directory == common or directory.startswith(f"{common}/")):
            common = common.rpartition("/")[0]
    return f"{run_prefix}{common or 'build'}/"


def _inventory_panels(
    groups: Sequence[ArtifactGroup], run_prefix: str
) -> list[tuple[str, str, str]]:
    """Render the file inventory as one directory tree per tab."""
    panels: list[tuple[str, str, str]] = []
    for group in groups:
        tab = _INVENTORY_TABS.get(group.name)
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


def _render_case_markdown(result: dict) -> str:
    """Render the run report a forge shows when a reader opens the run directory.

    Markdown, not HTML: a published kit is read on GitHub, which renders the README of whatever
    directory the reader lands in and shows HTML as source. ``index.html`` carries the same run
    for local ``file://`` reading, where nothing renders Markdown.
    """
    fixture = str(result.get("fixture") or "")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    scores = (
        result.get("score_exit_codes") if isinstance(result.get("score_exit_codes"), dict) else {}
    )
    environment = result.get("environment") if isinstance(result.get("environment"), dict) else {}
    lines = [
        f"# {fixture}: {str(result.get('status') or '').upper()}",
        "",
        "Open `index.html` for the linked proof kit; verify it with `sha256sum -c SHA256SUMS`.",
        "",
        f"- Target: `{result.get('target') or ''}`",
        f"- Run: `{result.get('run_id') or ''}`",
        f"- Provider and model: `{environment.get('provider', '')}` / "
        f"`{environment.get('model', '')}`",
        f"- Elapsed: {int(result.get('elapsed_ms') or 0) / 1000:.1f}s",
        f"- Build passes: {result.get('build_passes', 0)}",
        f"- LLM calls: {usage.get('calls', 0)}",
        f"- Tokens: cached {usage.get('cached_input_tokens', 0):,}; "
        f"uncached {usage.get('fresh_input_tokens', 0):,}; "
        f"output {usage.get('output_tokens', 0):,}",
        f"- LLM elapsed: {int(usage.get('llm_elapsed_ms') or 0) / 1000:.1f}s",
        "- Advisory scores: "
        + (", ".join(f"{name}=exit {code}" for name, code in scores.items()) or "none recorded"),
    ]
    if result.get("error"):
        lines.append(f"- Failure: {result['error']}")
    lines += [
        "",
        "## Commands",
        "",
        "| # | Command | Exit | Elapsed | Output |",
        "|---|---|---|---|---|",
    ]
    for item in (entry for entry in result.get("commands") or [] if isinstance(entry, dict)):
        argv = " ".join(str(part) for part in item.get("argv") or [])
        stdout = str(item.get("stdout_path") or "")
        lines.append(
            f"| {item.get('label', '')} | `{argv}` | {item.get('returncode', '')} "
            f"| {int(item.get('elapsed_ms') or 0) / 1000:.1f}s "
            f"| [stdout]({stdout}) · [stderr]({item.get('stderr_path') or ''}) |"
        )
    lines += [
        "",
        "## Evidence",
        "",
        "- [`evidence/commands/`](evidence/commands) — stdout and stderr of every command",
        "- [`evidence/prompts/`](evidence/prompts) — the assembled prompt for every LLM call",
        "- [`evidence/provider_raw/`](evidence/provider_raw) — unmodified provider transcripts",
        "- [`result.json`](result.json) — the machine-readable record of this run",
        "",
    ]
    return "\n".join(lines)


def _render_case(case_root: Path, result: dict, groups: Sequence[ArtifactGroup]) -> str:
    target = str(result.get("target") or case_root.name)
    fixture = str(result.get("fixture") or case_root.name)
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    failed = [item for item in commands if item.get("returncode") not in (0, None)]
    status = str(result.get("status") or ("passed" if not failed else "failed"))
    passed = status == "passed"

    resumed = str(result.get("resumed_from") or "")
    detail = ""
    if result.get("error"):
        detail = f"Failure: <code>{html.escape(str(result['error']))}</code>"
    elif passed and resumed:
        # A resumed run reuses state an earlier attempt produced, and its command table still
        # carries that attempt's failures. Saying "every command exited 0" would be false.
        detail = (
            f"Resumed at <code>{html.escape(resumed)}</code>; every required command from that "
            "stage onward exited 0. Earlier rows are the prior attempt, retained as evidence."
        )
    elif passed:
        detail = (
            f"{len(commands)} lifecycle commands ran; every required command exited 0. "
            "Each row below links to its own captured output."
        )
    verdict = f"{fixture}: {status.upper()}"

    command_rows: list[list[str]] = []
    for index, command in enumerate(commands, start=1):
        argv = command.get("argv") or []
        label = command.get("label") or f"step-{index:02d}"
        stdout = _relative(command.get("stdout_path"), case_root)
        stderr = _relative(command.get("stderr_path"), case_root)
        elapsed = command.get("elapsed_ms") or 0
        command_rows.append([
            _cell(index, css="num"),
            _cell(label),
            f"<td><code>{html.escape(_command_text(argv))}</code></td>",
            _status_cell(command.get("returncode")),
            _cell(f"{elapsed / 1000:.1f}s", css="num"),
            _stream_link(case_root, stdout, "stdout"),
            _stream_link(case_root, stderr, "stderr"),
        ])
    commands_table = _table(("#", "Stage", "Command", "Result", "Elapsed", "", ""), command_rows)

    excerpt = ""
    if failed:
        last = failed[-1]
        sections = []
        for stream in ("stdout_path", "stderr_path"):
            relative = _relative(last.get(stream), case_root)
            text = _tail(case_root / relative) if relative else ""
            if text:
                sections.append(
                    f'<p class="note">Tail of <code>{html.escape(relative)}</code>.</p>'
                    f"<pre>{html.escape(text[-4000:])}</pre>"
                )
        if sections:
            excerpt = (
                "<h2>Recorded failure output</h2>"
                f'<p class="note">Stage <code>{html.escape(str(last.get("label") or ""))}</code> '
                "exited nonzero. The text below is quoted verbatim from the captured streams.</p>"
                + "".join(sections)
            )

    inventory = _inventory_panels(groups, f"runs/{result.get('run_id') or case_root.name}/")

    calls = _llm_calls(case_root / "evidence" / "llm.jsonl", case_root)
    call_rows = [
        [
            _cell(call["command"]),
            _cell(f"{call['provider']}/{call['model']}"),
            _status_cell(call["returncode"]),
            _cell(f"{int(call['elapsed_ms'] or 0) / 1000:.1f}s", css="num"),
            _cell(f"{int(call['cached_input_tokens']):,}", css="num"),
            _cell(
                f"{max(int(call['input_tokens']) - int(call['cached_input_tokens']), 0):,}",
                css="num",
            ),
            _cell(f"{int(call['output_tokens']):,}", css="num"),
            _link(str(call["prompt"]), "prompt"),
            _link(str(call["output"]), "output"),
            _link(str(call["raw"]), "transcript"),
        ]
        for call in calls
    ]
    calls_table = _table(
        ("Command", "Model", "Result", "Elapsed", "Cached", "Uncached", "Output", "", "", ""),
        call_rows,
    )

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    recorded = result.get("environment")
    environment = dict(recorded) if isinstance(recorded, dict) else {}
    # Runs recorded before provenance capture still name their provider in every LLM record.
    for key, field in (("provider", "provider"), ("model", "model")):
        if not environment.get(key) and calls:
            environment[key] = str(calls[0][field] or "")
    run_prefix = f"runs/{result.get('run_id') or case_root.name}/"
    meta = _meta([
        ("Target", f"<code>{html.escape(target)}</code>"),
        ("Run", f"<code>{html.escape(str(result.get('run_id') or ''))}</code>"),
        ("Code", f"<code>{html.escape(_delivered_root(groups, run_prefix))}</code>"),
        ("Elapsed", f"{int(result.get('elapsed_ms') or 0) / 1000:.1f}s"),
        ("Build passes", str(result.get("build_passes", ""))),
        ("Provider", html.escape(str(environment.get("provider") or "not recorded"))),
        ("Model", html.escape(str(environment.get("model") or "not recorded"))),
        ("Drydock", html.escape(str(environment.get("drydock_version") or "not recorded"))),
        (
            "Commit",
            f"<code>{html.escape(str(environment.get('git_commit') or 'not recorded'))}</code>",
        ),
        ("Python", html.escape(str(environment.get("python_version") or "not recorded"))),
        ("Platform", html.escape(str(environment.get("platform") or "not recorded"))),
        ("LLM usage", html.escape(_tokens(usage))),
    ])

    scores = (
        result.get("score_exit_codes") if isinstance(result.get("score_exit_codes"), dict) else {}
    )
    score_rows = [[_cell(name), _status_cell(code)] for name, code in sorted(scores.items())]
    scores_block = (
        "<h2>Advisory scores</h2>"
        '<p class="note">Scoring is advisory and does not gate the run.</p>'
        + _table(("Score", "Result"), score_rows)
        if score_rows
        else ""
    )

    steps_panel = "".join([
        "<h2>Lifecycle commands</h2>",
        '<p class="note">Each Drydock command executed in order, with its recorded exit code '
        "and its own captured streams. A stream is linked only when it captured output; "
        "stderr carries provider progress on successful commands and is not a failure "
        "indicator on its own.</p>",
        commands_table,
        scores_block,
    ])
    llm_panel = (
        "".join([
            "<h2>LLM executions</h2>",
            '<p class="note">One row per model invocation, with the exact prompt sent, the '
            "output returned, and the raw provider transcript.</p>",
            calls_table,
        ])
        if call_rows
        else ""
    )

    provider = str(environment.get("provider") or "")
    model = str(environment.get("model") or "")
    docline = " · ".join(
        part
        for part in (
            f"Run {result.get('run_id') or ''}",
            f"Target {target}",
            f"{provider}/{model}" if provider or model else "",
        )
        if part
    )
    return _page(
        f"Drydock UAT report — {fixture}",
        "\n".join([
            _letterhead(
                "User Acceptance Test — Run Report",
                fixture,
                docline,
                passed,
                "Approved" if passed else "Rejected",
            ),
            _verdict(passed, verdict, detail),
            meta,
            _tabs([
                ("steps", "Steps", steps_panel),
                ("error", "Error", excerpt),
                ("llm", "LLM", llm_panel),
                *inventory,
            ]),
            "<footer>Generated by <code>drydock uat --report</code>. Byte counts and digests are "
            "computed from the files in this directory at generation time. Verify the kit with "
            f"<code>cd {html.escape(case_root.name)} &amp;&amp; sha256sum -c SHA256SUMS</code>. "
            f"Record: {_anchor('result.json')} · {_anchor('SHA256SUMS')}</footer>",
        ]),
    )


def _render_kit(kit_root: Path, results: Sequence[tuple[str, dict]]) -> str:
    """Render the kit landing page: one row per run, newest first."""
    latest = results[0][1] if results else {}
    passed = str(latest.get("status")) == "passed"
    verdict = f"latest run {str(latest.get('status') or 'unknown').upper()}"
    detail = (
        str(latest.get("error") or "") or "Open a run below for its command-by-command evidence."
    )

    rows = []
    for run_id, item in results:
        case_status = str(item.get("status") or "")
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        commands = [entry for entry in item.get("commands") or [] if isinstance(entry, dict)]
        environment = item.get("environment") if isinstance(item.get("environment"), dict) else {}
        state = "pass" if case_status == "passed" else "fail"
        rows.append([
            f"<td>{_anchor(f'runs/{run_id}/index.html', run_id)}</td>",
            f'<td><span class="tag {state}">{html.escape(case_status.upper())}</span></td>',
            _cell(str(environment.get("model") or "not recorded"), css="nowrap"),
            _cell(len(commands), css="num"),
            _cell(item.get("build_passes", ""), css="num"),
            _cell(f"{int(item.get('elapsed_ms') or 0) / 1000:.1f}s", css="num"),
            _cell(_tokens(usage)),
        ])

    return _page(
        f"Drydock UAT kit {kit_root.name}",
        "\n".join([
            _letterhead(
                "User Acceptance Test — Project Register",
                kit_root.name,
                f"{len(results)} recorded runs · newest first",
                passed,
                "Approved" if passed else "Rejected",
            ),
            _verdict(passed, verdict, html.escape(detail)),
            "<h2>Runs</h2>",
            '<p class="note">Every unattended build of this project, each a complete, '
            "self-verifying record of the commands Drydock executed.</p>",
            _table(
                ("Run", "Status", "Model", "Commands", "Build passes", "Elapsed", "LLM usage"),
                rows,
            ),
            "<h2>Kit inputs</h2>",
            _table(
                ("File", "Purpose"),
                [
                    [_link("README.md"), _cell("How to run this kit and read its evidence")],
                    [_link("uat.json"), _cell("Source bundle, updates, and test command")],
                ],
            ),
            "<footer>Generated by <code>drydock uat --report</code>.</footer>",
        ]),
    )


# ── entry points ─────────────────────────────────────────────────────────────────────


def build_case_kit(case_root: Path) -> Path:
    """Inventory one project case and write its receipt; returns the index path."""
    _make_portable(case_root / "result.json", case_root)
    result = _read_json(case_root / "result.json")
    if not isinstance(result, dict):
        raise ValueError(f"UAT case has no readable result.json: {case_root}")
    prune_generated(case_root)
    target = str(result.get("target") or case_root.name)

    manifest_path = case_root / "evidence" / "manifest.json"
    groups = _case_groups(case_root, target)
    _write_sums(case_root, groups)

    manifest = _read_json(manifest_path)
    if isinstance(manifest, dict):
        manifest = _portable(manifest, case_root)
        manifest["environment"] = result.get("environment") or {}
        manifest["artifacts"] = {
            group.name: [record.to_dict() for record in group.files] for group in groups
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    (case_root / "README.md").write_text(_render_case_markdown(result), encoding="utf-8")
    index = case_root / _INDEX_NAME
    index.write_text(_render_case(case_root, result, groups), encoding="utf-8")
    return index


def build_kit_index(kit_root: Path) -> Path:
    """Rebuild every run receipt under one kit and write the kit landing page."""
    from drydock.uat import run_sort_key

    runs_root = kit_root / "runs"
    results: list[tuple[str, dict]] = []
    if runs_root.is_dir():
        for case_root in sorted(
            (path for path in runs_root.iterdir() if path.is_dir()),
            key=lambda path: run_sort_key(path.name),
            reverse=True,
        ):
            if not (case_root / "result.json").is_file():
                continue
            build_case_kit(case_root)
            result = _read_json(case_root / "result.json")
            if isinstance(result, dict):
                results.append((case_root.name, result))
    index = kit_root / _INDEX_NAME
    index.write_text(_render_kit(kit_root, results), encoding="utf-8")
    return index
