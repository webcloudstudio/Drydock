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

import hashlib
import html
import json
import shutil
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
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
    """Inventory a completed case in the order a reviewer reads it."""
    workspace = case_root / "workspace"
    blueprint_root = workspace / "targets" / target
    evidence = case_root / "evidence"
    groups = [
        ArtifactGroup(
            "Delivered code",
            "Working tree produced by drydock build, exactly as the build left it.",
            tuple(_iter_files(case_root / "build", case_root)),
        ),
        ArtifactGroup(
            "Imported sources",
            "Input bundle staged for drydock import before the lifecycle started.",
            tuple(_iter_files(case_root / "sources", case_root)),
        ),
        ArtifactGroup(
            "Blueprint and Target state",
            "Typed Specifications, Manifest, and Target artifacts the lifecycle produced.",
            tuple(_iter_files(blueprint_root, case_root, skip=[blueprint_root / "logs"])),
        ),
        ArtifactGroup(
            "Command logs",
            "Captured stdout and stderr for every lifecycle command.",
            tuple(_iter_files(evidence / "commands", case_root)),
        ),
        ArtifactGroup(
            "LLM evidence",
            "Assembled prompts, model output, provider transcripts, and execution records.",
            tuple(
                record
                for subdirectory in ("prompts", "prompt_outputs", "provider_raw")
                for record in _iter_files(evidence / subdirectory, case_root)
            )
            + tuple(
                _hash_file(evidence / "llm.jsonl", case_root)
                for _ in range(int((evidence / "llm.jsonl").is_file()))
            ),
        ),
        ArtifactGroup(
            "Run record",
            "Machine-readable outcome for this project.",
            tuple(
                _hash_file(case_root / name, case_root)
                for name in ("result.json",)
                if (case_root / name).is_file()
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
  --bg: #f6f7f9; --panel: #ffffff; --ink: #14181d; --muted: #5c6672; --line: #d9dee5;
  --pass: #0f7b3d; --pass-bg: #e6f4ec; --fail: #b3261e; --fail-bg: #fbeae9;
  --accent: #1b4f8f; --code-bg: #f0f2f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1216; --panel: #171b21; --ink: #e6e9ee; --muted: #98a2b0; --line: #2a313a;
    --pass: #5fd18c; --pass-bg: #12271b; --fail: #ff8a80; --fail-bg: #2a1616;
    --accent: #7fb2f0; --code-bg: #10141a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1.25rem 5rem; background: var(--bg); color: var(--ink);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1120px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; letter-spacing: -.01em; }
h2 { font-size: 1.1rem; margin: 2.25rem 0 .5rem; letter-spacing: -.01em; }
p.sub { color: var(--muted); margin: 0 0 1.5rem; }
p.note { color: var(--muted); margin: .25rem 0 .75rem; font-size: .9rem; }
code, pre, .mono { font-family: ui-monospace, SFMono-Regular, "Cascadia Mono", Menlo, monospace; }
code { background: var(--code-bg); padding: .1em .35em; border-radius: 3px; font-size: .88em; }
pre {
  background: var(--code-bg); border: 1px solid var(--line); border-radius: 6px;
  padding: .85rem 1rem; overflow-x: auto; font-size: .82rem; margin: 0 0 1rem;
}
a { color: var(--accent); }
.banner {
  border: 1px solid var(--line); border-left-width: 6px; border-radius: 8px;
  padding: 1rem 1.15rem; margin: 0 0 1.5rem; background: var(--panel);
}
.banner.pass { border-left-color: var(--pass); background: var(--pass-bg); }
.banner.fail { border-left-color: var(--fail); background: var(--fail-bg); }
.banner .verdict { font-size: 1.15rem; font-weight: 650; letter-spacing: .02em; }
.banner.pass .verdict { color: var(--pass); }
.banner.fail .verdict { color: var(--fail); }
.banner .detail { color: var(--ink); margin-top: .35rem; }
.scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }
table { border-collapse: collapse; width: 100%; font-size: .875rem; }
th, td { text-align: left; padding: .5rem .7rem; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; white-space: nowrap; }
tbody tr:last-child td { border-bottom: none; }
td.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
td.hash { font-size: .72rem; color: var(--muted); word-break: break-all; }
.tag { display: inline-block; padding: .05rem .5rem; border-radius: 999px; font-size: .74rem; font-weight: 650; letter-spacing: .03em; }
.tag.pass { color: var(--pass); background: var(--pass-bg); border: 1px solid var(--pass); }
.tag.fail { color: var(--fail); background: var(--fail-bg); border: 1px solid var(--fail); }
dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: .3rem 1.25rem; margin: 0 0 1rem; }
dl.meta dt { color: var(--muted); font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; }
dl.meta dd { margin: 0; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line); color: var(--muted); font-size: .82rem; }
"""


def _page(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>{_STYLE}</style>\n"
        f"</head>\n<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def _banner(passed: bool, verdict: str, detail: str) -> str:
    state = "pass" if passed else "fail"
    detail_html = f'<div class="detail">{detail}</div>' if detail else ""
    return (
        f'<div class="banner {state}"><div class="verdict">{html.escape(verdict)}</div>'
        f"{detail_html}</div>"
    )


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return '<p class="note">None recorded.</p>'
    head = "".join(f"<th>{html.escape(name)}</th>" for name in headers)
    body = "".join("<tr>" + "".join(row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _link(target: str, label: str = "") -> str:
    if not target:
        return "<td>—</td>"
    return (
        f'<td><a class="mono" href="{html.escape(target)}">{html.escape(label or target)}</a></td>'
    )


def _cell(text: object, *, css: str = "") -> str:
    attribute = f' class="{css}"' if css else ""
    return f"<td{attribute}>{html.escape(str(text))}</td>"


def _status_cell(returncode: object) -> str:
    ok = returncode == 0
    label = "exit 0" if ok else f"exit {returncode}"
    state = "pass" if ok else "fail"
    return f'<td><span class="tag {state}">{html.escape(label)}</span></td>'


def _command_text(argv: Sequence[object]) -> str:
    """Render argv the way an operator would type it, hiding the interpreter shim."""
    parts = [str(part) for part in argv]
    if "-m" in parts and len(parts) > parts.index("-m") + 1:
        parts = ["drydock", *parts[parts.index("-m") + 2 :]]
    return " ".join(parts)


def _meta(pairs: Sequence[tuple[str, str]]) -> str:
    items = "".join(
        f"<dt>{html.escape(name)}</dt><dd>{value}</dd>" for name, value in pairs if value
    )
    return f'<dl class="meta">{items}</dl>' if items else ""


def _tokens(usage: dict) -> str:
    if not usage:
        return ""
    return (
        f"{usage.get('calls', 0)} calls · input {usage.get('input_tokens', 0):,} "
        f"(cached {usage.get('cached_input_tokens', 0):,}) · "
        f"output {usage.get('output_tokens', 0):,}"
    )


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
        f"- Tokens: input {usage.get('input_tokens', 0):,}; "
        f"cached {usage.get('cached_input_tokens', 0):,}; "
        f"fresh {usage.get('fresh_input_tokens', 0):,}; output {usage.get('output_tokens', 0):,}",
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
            _link(stdout, "stdout"),
            _link(stderr, "stderr"),
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

    inventory = []
    for group in groups:
        rows = [
            [
                _link(record.path),
                _cell(f"{record.bytes:,}", css="num"),
                _cell(record.sha256, css="hash"),
            ]
            for record in group.files
        ]
        inventory.append(
            f"<h2>{html.escape(group.name)}</h2>"
            f'<p class="note">{html.escape(group.description)} '
            f"{len(group.files)} files, {group.total_bytes:,} bytes.</p>"
            + _table(("File", "Bytes", "SHA-256"), rows)
        )

    calls = _llm_calls(case_root / "evidence" / "llm.jsonl", case_root)
    call_rows = [
        [
            _cell(call["command"]),
            _cell(f"{call['provider']}/{call['model']}"),
            _status_cell(call["returncode"]),
            _cell(f"{int(call['elapsed_ms'] or 0) / 1000:.1f}s", css="num"),
            _cell(f"{int(call['input_tokens']):,}", css="num"),
            _cell(f"{int(call['cached_input_tokens']):,}", css="num"),
            _cell(f"{int(call['output_tokens']):,}", css="num"),
            _link(str(call["prompt"]), "prompt"),
            _link(str(call["output"]), "output"),
            _link(str(call["raw"]), "transcript"),
        ]
        for call in calls
    ]
    calls_table = _table(
        ("Command", "Model", "Result", "Elapsed", "Input", "Cached", "Output", "", "", ""),
        call_rows,
    )

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    recorded = result.get("environment")
    environment = dict(recorded) if isinstance(recorded, dict) else {}
    # Runs recorded before provenance capture still name their provider in every LLM record.
    for key, field in (("provider", "provider"), ("model", "model")):
        if not environment.get(key) and calls:
            environment[key] = str(calls[0][field] or "")
    meta = _meta([
        ("Target", f"<code>{html.escape(target)}</code>"),
        ("Run", f"<code>{html.escape(str(result.get('run_id') or ''))}</code>"),
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

    return _page(
        f"Drydock UAT proof — {fixture}",
        "\n".join([
            f"<h1>Drydock UAT proof kit — {html.escape(fixture)}</h1>",
            '<p class="sub">Every claim on this page is backed by a file in this directory. '
            "Links are relative, so the kit stays valid wherever it is checked in.</p>",
            _banner(passed, verdict, detail),
            meta,
            "<h2>Lifecycle commands</h2>",
            '<p class="note">Each Drydock command executed in order, with its recorded exit '
            "code and its own captured streams.</p>",
            commands_table,
            excerpt,
            "<h2>Advisory scores</h2>",
            '<p class="note">Scoring is advisory and does not gate the run.</p>',
            _table(("Score", "Result"), score_rows),
            "<h2>LLM executions</h2>",
            '<p class="note">One row per model invocation, with the exact prompt sent, the '
            "output returned, and the raw provider transcript.</p>",
            calls_table,
            *inventory,
            "<h2>Verifying this kit</h2>",
            "<pre>cd " + html.escape(case_root.name) + "\nsha256sum -c SHA256SUMS</pre>",
            "<footer>Generated by <code>drydock uat --report</code>. Byte counts and digests "
            "are computed from the files in this directory at generation time.</footer>",
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
        state = "pass" if case_status == "passed" else "fail"
        rows.append([
            f'<td><a href="runs/{html.escape(run_id)}/index.html">{html.escape(run_id)}</a></td>',
            f'<td><span class="tag {state}">{html.escape(case_status.upper())}</span></td>',
            _cell(len(commands), css="num"),
            _cell(item.get("build_passes", ""), css="num"),
            _cell(f"{int(item.get('elapsed_ms') or 0) / 1000:.1f}s", css="num"),
            _cell(_tokens(usage)),
        ])

    return _page(
        f"Drydock UAT kit {kit_root.name}",
        "\n".join([
            f"<h1>Drydock UAT kit — {html.escape(kit_root.name)}</h1>",
            '<p class="sub">Every unattended build of this project, each a complete, '
            "self-verifying record of the commands Drydock executed.</p>",
            _banner(passed, verdict, html.escape(detail)),
            "<h2>Runs</h2>",
            _table(
                ("Run", "Status", "Commands", "Build passes", "Elapsed", "LLM usage"),
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
    runs_root = kit_root / "runs"
    results: list[tuple[str, dict]] = []
    if runs_root.is_dir():
        for case_root in sorted(
            (path for path in runs_root.iterdir() if path.is_dir()), reverse=True
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
