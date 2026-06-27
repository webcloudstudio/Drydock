"""Target documentation generation and assembly."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from drydock.errors import DrydockError, SpecificationError, UsageError
from drydock.llm import run_prompt
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

PROMPT_NAME = "document_generate"
DEFAULT_THEME = "slate"
CONFIG_NAME = "documentation.yaml"

DEFAULT_SECTIONS: tuple[str, ...] = (
    "OVERVIEW",
    "FEATURES",
    "SCREENS",
    "ARCHITECTURE",
    "SCHEMA",
    "FLOWS",
    "PIPELINE",
    "SIGNALS",
)

REQUIRED_SECTIONS: tuple[str, ...] = ("OVERVIEW", "FEATURES", "SCREENS", "ARCHITECTURE")

GUIDE_TITLES: dict[str, str] = {
    "OVERVIEW": "Overview",
    "FEATURES": "Features",
    "SCREENS": "Screens",
    "ARCHITECTURE": "Architecture",
    "SCHEMA": "Schema",
    "FLOWS": "Work Flows",
    "PIPELINE": "Pipeline",
    "SIGNALS": "Signals",
}

GUIDE_SECTIONS: dict[str, str] = {
    "OVERVIEW": "OVERVIEW",
    "PIPELINE": "OVERVIEW",
    "SCHEMA": "OVERVIEW",
    "SIGNALS": "OVERVIEW",
    "FLOWS": "OVERVIEW",
    "FEATURES": "FEATURES",
    "ARCHITECTURE": "SYSTEM",
    "SCREENS": "SCREENS",
}

THEMES: dict[str, dict[str, str]] = {
    "slate": {
        "--c-bg": "#f4f6f8",
        "--c-text": "#26313d",
        "--c-muted": "#647180",
        "--c-topbar-bg": "#17212b",
        "--c-side-bg": "#1f2c38",
        "--c-side-border": "#334252",
        "--c-side-section": "#9fb0c0",
        "--c-accent": "#2cb67d",
        "--c-h3": "#4f6f88",
        "--c-code-bg": "#e8edf2",
        "--c-code-text": "#1c3342",
        "--c-th-bg": "#d8e1e8",
        "--c-th-text": "#26313d",
        "--c-td-border": "#d7dee5",
        "--c-tr-alt": "#eef3f6",
        "--c-pre-bg": "#202a34",
        "--c-pre-text": "#edf4f7",
        "--c-callout-bg": "#eaf4ef",
    },
    "harbor": {
        "--c-bg": "#f7faf8",
        "--c-text": "#24342f",
        "--c-muted": "#5d7069",
        "--c-topbar-bg": "#103d3f",
        "--c-side-bg": "#17494d",
        "--c-side-border": "#27656a",
        "--c-side-section": "#a8c8c6",
        "--c-accent": "#d49b32",
        "--c-h3": "#3d716b",
        "--c-code-bg": "#e8efeb",
        "--c-code-text": "#203a38",
        "--c-th-bg": "#dbe7e3",
        "--c-th-text": "#213932",
        "--c-td-border": "#d8e2de",
        "--c-tr-alt": "#eef5f2",
        "--c-pre-bg": "#183033",
        "--c-pre-text": "#eef7f4",
        "--c-callout-bg": "#f8f0df",
    },
    "paper": {
        "--c-bg": "#fbfbf8",
        "--c-text": "#2e312d",
        "--c-muted": "#6a6f68",
        "--c-topbar-bg": "#2f3430",
        "--c-side-bg": "#3d463f",
        "--c-side-border": "#59635c",
        "--c-side-section": "#c6cec7",
        "--c-accent": "#427a5b",
        "--c-h3": "#556359",
        "--c-code-bg": "#eceee9",
        "--c-code-text": "#28322d",
        "--c-th-bg": "#e0e5dd",
        "--c-th-text": "#2c332e",
        "--c-td-border": "#dfe3dd",
        "--c-tr-alt": "#f2f4ef",
        "--c-pre-bg": "#2d342f",
        "--c-pre-text": "#f4f5ef",
        "--c-callout-bg": "#edf5ee",
    },
}


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class DocumentationConfig:
    theme: str = DEFAULT_THEME
    sections: tuple[str, ...] = DEFAULT_SECTIONS


@dataclass(frozen=True)
class GeneratedDocumentation:
    target_dir: Path
    docs_dir: Path
    files: tuple[Path, ...]
    execution_id: str


@dataclass(frozen=True)
class AssembledDocumentation:
    target_dir: Path
    output: Path
    guides: tuple[str, ...]
    theme: str


def default_config_text() -> str:
    lines = [f"theme: {DEFAULT_THEME}", "sections:"]
    lines.extend(f"  - {section}" for section in DEFAULT_SECTIONS)
    return "\n".join(lines) + "\n"


def _normalize_section(value: str) -> str:
    return value.strip().upper().replace("-", "_")


def _read_config(path: Path) -> DocumentationConfig:
    if not path.exists():
        return DocumentationConfig()

    theme = DEFAULT_THEME
    sections: list[str] = []
    in_sections = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("theme:"):
            theme = stripped.split(":", 1)[1].strip().strip("'\"") or DEFAULT_THEME
            in_sections = False
            continue
        if stripped == "sections:":
            in_sections = True
            continue
        if in_sections and stripped.startswith("-"):
            section = _normalize_section(stripped[1:])
            if section:
                sections.append(section)

    return DocumentationConfig(theme=theme, sections=tuple(sections) or DEFAULT_SECTIONS)


def _ensure_config(target_dir: Path) -> DocumentationConfig:
    path = target_dir / CONFIG_NAME
    if not path.exists():
        path.write_text(default_config_text(), encoding="utf-8", newline="\n")
    return _read_config(path)


def _validate_theme(theme: str) -> str:
    normalized = theme.strip().lower()
    if normalized not in THEMES:
        available = ", ".join(sorted(THEMES))
        raise UsageError(f"Unknown documentation theme: {theme!r}. Available themes: {available}")
    return normalized


def _target_dirs(target: str, targets_root: Path) -> tuple[Path, Path, Path]:
    from drydock.config import build_dir_for

    target_dir = targets_root / target
    blueprint_dir = target_dir / "blueprint"
    docs_dir = build_dir_for(target) / "docs"
    if not target_dir.is_dir():
        raise SpecificationError(f"Target not found: {target_dir}")
    return target_dir, blueprint_dir, docs_dir


def _metadata(target_dir: Path, target: str) -> dict[str, str]:
    fields = {"name": target, "display_name": target}
    path = target_dir / "METADATA.md"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
    fields.setdefault("display_name", fields.get("name", target))
    return fields


def _manifest_text(target_dir: Path) -> str:
    path = target_dir / "MANIFEST.md"
    if not path.is_file():
        raise SpecificationError(f"MANIFEST.md not found: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _blueprint_sources(blueprint_dir: Path) -> list[Path]:
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")
    excluded_prefixes = ("DOC-",)
    excluded_names = {"SPEC_SCORECARD.md", "SPEC_ITERATION.md", "REFERENCE_GAPS.md"}
    sources: list[Path] = []
    for path in sorted(blueprint_dir.rglob("*.md")):
        rel = path.relative_to(blueprint_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.name in excluded_names or path.name.startswith(excluded_prefixes):
            continue
        if re.match(r"^(SCREEN|FEATURE|PATCH|AC|CHANGE)-\d{3}-", path.name):
            continue
        sources.append(path)
    if not sources:
        raise SpecificationError(f"No Blueprint Markdown files found: {blueprint_dir}")
    return sources


def _assemble_prompt_assembly(
    prompt_body: str,
    *,
    target: str,
    target_dir: Path,
    blueprint_dir: Path,
    docs_dir: Path,
    config: DocumentationConfig,
    model: str | None,
) -> PromptAssembly:
    metadata = _metadata(target_dir, target)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    sources = _blueprint_sources(blueprint_dir)
    parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Documentation job",
            [
                "## Documentation job",
                "",
                f"- TARGET: {target}",
                f"- DISPLAY_NAME: {metadata.get('display_name', target)}",
                f"- SHORT_DESCRIPTION: {metadata.get('short_description', '')}",
                f"- TARGET_DIR: {target_dir}",
                f"- BLUEPRINT_DIR: {blueprint_dir}",
                f"- TARGET_DOCS: {docs_dir}",
                f"- DATE: {today}",
                f"- MODEL_OVERRIDE: {model or ''}",
                f"- SECTIONS: {', '.join(config.sections)}",
                "",
            ],
            kind="job",
        ),
    ]
    metadata_text = "\n".join(f"{key}: {value}" for key, value in sorted(metadata.items()))
    parts.extend(
        contextual_markdown_parts(
            "METADATA.md",
            metadata_text,
            filename="METADATA.md",
            role="target metadata",
        )
    )
    parts.extend(
        contextual_markdown_parts(
            "MANIFEST.md",
            _manifest_text(target_dir),
            filename="MANIFEST.md",
            role="build plan",
        )
    )
    for source in sources:
        rel = source.relative_to(blueprint_dir)
        parts.extend(
            contextual_markdown_parts(
                str(rel),
                source.read_text(encoding="utf-8", errors="replace"),
                filename=source.name,
                role="Blueprint source",
            )
        )
    parts.extend([
        section_heading_part("# Agent Task"),
        part("Prompt body", prompt_body + "\n\n", kind="prompt-body"),
    ])
    return PromptAssembly(parts=tuple(parts))


_DOC_BLOCK = re.compile(
    r"^===\s*(DOC-[A-Z0-9_-]+\.md)\s*===\s*$\n(.*?)(?=^===\s*DOC-[A-Z0-9_-]+\.md\s*===\s*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
_OUTER_FENCE = re.compile(r"\A```(?:markdown|md)?\s*\n(.*)\n```\s*\Z", re.DOTALL)


def parse_generated_docs(text: str, *, sections: tuple[str, ...]) -> dict[str, str]:
    docs: dict[str, str] = {}
    allowed = {f"DOC-{section}.md" for section in sections}
    for match in _DOC_BLOCK.finditer(text.strip()):
        name = match.group(1).strip()
        body = match.group(2).strip()
        fenced = _OUTER_FENCE.match(body)
        if fenced:
            body = fenced.group(1).strip()
        if name not in allowed:
            raise DrydockError(f"LLM output contains unexpected documentation file: {name}")
        if not body:
            raise DrydockError(f"LLM output contains empty documentation file: {name}")
        docs[name] = body + "\n"

    required = {f"DOC-{section}.md" for section in REQUIRED_SECTIONS if section in sections}
    missing = sorted(required - set(docs))
    if missing:
        raise DrydockError(
            "LLM output is missing required documentation block(s): " + ", ".join(missing)
        )
    if not docs:
        raise DrydockError("LLM output did not contain any DOC-*.md blocks")
    return docs


def generate_documentation(
    target: str,
    targets_root: Path,
    *,
    model: str | None = None,
    llm_provider: str | None = None,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
) -> GeneratedDocumentation:
    target_dir, blueprint_dir, docs_dir = _target_dirs(target, targets_root)
    config = _ensure_config(target_dir)
    prompt = load_prompt(PROMPT_NAME)
    assembly = _assemble_prompt_assembly(
        prompt.body,
        target=target,
        target_dir=target_dir,
        blueprint_dir=blueprint_dir,
        docs_dir=docs_dir,
        config=config,
        model=model,
    )
    run = runner if runner is not None else run_prompt
    result = run(
        assembly.rendered_text,
        target_dir,
        llm=llm_provider,
        model=model or prompt.model,
        command_name="document generate",
        parameters={"target": target, "docs_dir": str(docs_dir), "sections": list(config.sections)},
        log_dir=targets_root.parent / "logs",
        target=target,
        on_text=on_text,
        prompt_assembly=assembly,
    )
    if not result.ok:
        raise DrydockError("LLM execution failed for document generate")

    docs = parse_generated_docs(result.text, sections=config.sections)
    docs_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in sorted(docs.items()):
        path = docs_dir / name
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)

    emitted = set(docs)
    for section in config.sections:
        name = f"DOC-{section}.md"
        path = docs_dir / name
        if name not in emitted and path.exists() and section not in REQUIRED_SECTIONS:
            path.unlink()

    return GeneratedDocumentation(
        target_dir=target_dir,
        docs_dir=docs_dir,
        files=tuple(written),
        execution_id=result.execution_id,
    )


def _anchor(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _extract_h2(content: str) -> list[tuple[str, str]]:
    return [
        (m.group(1).strip(), _anchor(m.group(1).strip()))
        for m in re.finditer(r"^## (.+)$", content, re.MULTILINE)
    ]


def _discover_guides(docs_dir: Path, sections: tuple[str, ...]) -> list[dict[str, str]]:
    found = {path.stem[4:]: path for path in docs_dir.glob("DOC-*.md") if path.is_file()}
    ordered = [section for section in sections if section in found]
    ordered.extend(sorted(section for section in found if section not in ordered))
    guides = []
    for key in ordered:
        path = found[key]
        guides.append({
            "key": key,
            "title": GUIDE_TITLES.get(key, key.replace("_", " ").title()),
            "content": path.read_text(encoding="utf-8"),
        })
    return guides


def _sidebar(metadata: dict[str, str], guides: list[dict[str, str]]) -> str:
    display_name = metadata.get("display_name") or metadata.get("name") or "Project"
    parts = [
        '  <div class="sidebar-header" onclick="showHome()">',
        f'    <span class="sidebar-icon">{html.escape(metadata.get("icon", "D"))}</span>',
        f"    <h1>{html.escape(display_name)}</h1>",
        "  </div>",
    ]
    current_section = ""
    for guide in guides:
        section = GUIDE_SECTIONS.get(guide["key"], "OTHER")
        if section != current_section:
            if current_section:
                parts.append('  <div class="nav-sep"></div>')
            parts.append(f'  <div class="nav-section">{html.escape(section)}</div>')
            current_section = section
        key = html.escape(guide["key"])
        parts.append(
            f'  <a class="sn" data-key="{key}" onclick="showGuide({json.dumps(guide["key"])})">{html.escape(guide["title"])}</a>'
        )
        if guide["key"] in {"FEATURES", "SCREENS"}:
            for title, anchor in _extract_h2(guide["content"]):
                parts.append(
                    f'  <a class="sn-sub" data-key="{key}" onclick="showGuideSection({json.dumps(guide["key"])}, {json.dumps(anchor)})">{html.escape(title)}</a>'
                )
    return "\n".join(parts)


def _css(theme: str) -> str:
    vars_text = "\n".join(f"  {key}: {value};" for key, value in THEMES[theme].items())
    return f""":root {{
{vars_text}
}}
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ margin: 0; display: flex; flex-direction: column; height: 100vh; overflow: hidden; background: var(--c-bg); color: var(--c-text); font: 14px/1.65 "Segoe UI", Arial, sans-serif; }}
.page-header {{ background: var(--c-topbar-bg); color: #fff; border-bottom: 1px solid var(--c-side-border); display: flex; justify-content: space-between; align-items: center; padding: 8px 18px; }}
.page-header strong {{ font-size: 14px; }}
.page-header span {{ color: #cbd5df; font-size: 12px; }}
.layout {{ display: flex; flex: 1; overflow: hidden; }}
.sidebar {{ width: 220px; min-width: 220px; overflow-y: auto; background: var(--c-side-bg); border-right: 1px solid var(--c-side-border); }}
.sidebar-header {{ background: var(--c-topbar-bg); padding: 10px 12px; cursor: pointer; display: flex; align-items: center; gap: 9px; }}
.sidebar-icon {{ width: 28px; height: 28px; border-radius: 4px; background: var(--c-accent); color: #102018; display: inline-flex; align-items: center; justify-content: center; font-weight: 800; }}
.sidebar-header h1 {{ color: #fff; font-size: 15px; line-height: 1.2; margin: 0; }}
.nav-section {{ font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--c-side-section); padding: 10px 16px 3px; }}
.nav-sep {{ border-top: 1px solid var(--c-side-border); margin: 5px 0; }}
.sn, .sn-sub {{ display: block; cursor: pointer; border-left: 3px solid transparent; text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.sn {{ padding: 3px 16px; font-size: 13px; color: #fff; }}
.sn-sub {{ padding: 2px 16px 2px 28px; font-size: 11px; color: rgba(255,255,255,.78); }}
.sn:hover, .sn-sub:hover {{ background: rgba(255,255,255,.07); border-left-color: var(--c-accent); }}
.sn.active, .sn-sub.active {{ color: var(--c-accent); border-left-color: var(--c-accent); background: rgba(44,182,125,.12); }}
main {{ flex: 1; overflow-y: auto; padding: 28px 36px 48px; }}
.content-section {{ display: none; max-width: 900px; }}
.content-section.active {{ display: block; }}
.badge {{ display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 3px; background: var(--c-code-bg); color: var(--c-code-text); font-family: Consolas, monospace; }}
.md h1 {{ font-size: 22px; font-weight: 700; color: var(--c-accent); border-bottom: 2px solid var(--c-accent); padding-bottom: 5px; margin: 24px 0 10px; }}
.md h1:first-child {{ margin-top: 0; }}
.md h2 {{ font-size: 14px; font-weight: 700; color: #fff; background: var(--c-side-bg); border-left: 3px solid var(--c-accent); padding: 5px 12px; margin: 18px 0 9px; border-radius: 0 4px 4px 0; }}
.md h3 {{ font-size: 14px; font-weight: 600; color: var(--c-h3); margin: 12px 0 5px; }}
.md p {{ margin: 7px 0; }}
.md ul, .md ol {{ margin: 5px 0 5px 18px; }}
.md table {{ border-collapse: collapse; margin: 8px 0; font-size: 13px; width: 100%; }}
.md th {{ background: var(--c-th-bg); color: var(--c-th-text); font-weight: 600; font-size: 11px; text-transform: uppercase; padding: 4px 12px; text-align: left; }}
.md td {{ padding: 4px 12px; border-bottom: 1px solid var(--c-td-border); }}
.md tr:nth-child(even) td {{ background: var(--c-tr-alt); }}
.md pre {{ background: var(--c-pre-bg); color: var(--c-pre-text); border: 1px solid var(--c-side-border); border-radius: 4px; padding: 10px 14px; overflow-x: auto; margin: 8px 0; }}
.md code {{ font-family: Consolas, monospace; font-size: 12.5px; background: var(--c-code-bg); color: var(--c-code-text); padding: 1px 5px; border-radius: 3px; }}
.md pre code {{ background: none; padding: 0; color: inherit; }}
.doc-footer {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid var(--c-td-border); font-size: 11px; color: var(--c-h3); display: flex; justify-content: space-between; gap: 16px; }}
"""


def _page(target: str, target_dir: Path, guides: list[dict[str, str]], theme: str) -> str:
    metadata = _metadata(target_dir, target)
    display_name = metadata.get("display_name") or metadata.get("name") or target
    short_desc = metadata.get("short_description", "")
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    guides_js = "const GUIDES = " + json.dumps({g["key"]: g["content"] for g in guides}) + ";"
    home = [
        f"<h1>{html.escape(display_name)}</h1>",
        f"<p>{html.escape(short_desc)}</p>" if short_desc else "",
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:0 0 18px;">',
        f'<span class="badge">{len(guides)} guide{"s" if len(guides) != 1 else ""}</span>',
        f'<span class="badge">{html.escape(theme)}</span>',
        "</div>",
        '<div id="home-overview" class="md"></div>',
    ]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(display_name)} - Documentation</title>
<link rel="stylesheet" href="styles/spec.css">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{ startOnLoad:false, theme:'neutral' }});</script>
</head>
<body>
<header class="page-header"><strong>{html.escape(display_name)}</strong><span>Documentation</span></header>
<div class="layout">
<nav class="sidebar">
{_sidebar(metadata, guides)}
</nav>
<main>
  <div id="home" class="content-section active md">
    {"".join(home)}
    <div class="doc-footer"><span>Generated: {html.escape(generated)}</span><span>Target: {html.escape(target)}</span></div>
  </div>
  <div id="guide" class="content-section">
    <div id="guide-content" class="md"></div>
    <div class="doc-footer"><span>Generated: {html.escape(generated)}</span><span>Source: DOC-*.md</span></div>
  </div>
</main>
</div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
{guides_js}
marked.setOptions({{ gfm: true, breaks: false }});
function clearActive() {{
  document.querySelectorAll('.sn,.sn-sub').forEach(function(a) {{ a.classList.remove('active'); }});
}}
function renderMarkdown(text) {{
  var html = marked.parse(text || '');
  html = html.replace(/<h2>(.*?)<\\/h2>/g, function(_, title) {{
    var id = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return '<h2 id="' + id + '">' + title + '</h2>';
  }});
  return html;
}}
function show(id) {{
  document.querySelectorAll('.content-section').forEach(function(s) {{ s.classList.remove('active'); }});
  document.getElementById(id).classList.add('active');
}}
function showHome() {{
  show('home');
  clearActive();
}}
function showGuide(key) {{
  show('guide');
  clearActive();
  document.querySelectorAll('[data-key="' + key + '"]').forEach(function(a) {{ if (a.classList.contains('sn')) a.classList.add('active'); }});
  document.getElementById('guide-content').innerHTML = renderMarkdown(GUIDES[key] || '');
  mermaid.run({{ querySelector: '.language-mermaid' }}).catch(function() {{}});
}}
function showGuideSection(key, anchor) {{
  showGuide(key);
  document.querySelectorAll('[data-key="' + key + '"]').forEach(function(a) {{ if (a.textContent) a.classList.add('active'); }});
  setTimeout(function() {{
    var node = document.getElementById(anchor);
    if (node) node.scrollIntoView({{ block: 'start' }});
  }}, 0);
}}
document.getElementById('home-overview').innerHTML = renderMarkdown(GUIDES.OVERVIEW || '');
</script>
</body>
</html>
"""


def assemble_documentation(
    target: str,
    targets_root: Path,
    *,
    theme: str | None = None,
) -> AssembledDocumentation:
    target_dir, _blueprint_dir, docs_dir = _target_dirs(target, targets_root)
    config = _ensure_config(target_dir)
    selected_theme = _validate_theme(theme or config.theme)
    guides = _discover_guides(docs_dir, config.sections)
    if not guides:
        raise SpecificationError(f"No DOC-*.md files found: {docs_dir}")

    styles_dir = docs_dir / "styles"
    styles_dir.mkdir(parents=True, exist_ok=True)
    (styles_dir / "spec.css").write_text(_css(selected_theme), encoding="utf-8", newline="\n")
    output = docs_dir / "index.html"
    output.write_text(
        _page(target, target_dir, guides, selected_theme), encoding="utf-8", newline="\n"
    )
    return AssembledDocumentation(
        target_dir=target_dir,
        output=output,
        guides=tuple(g["key"] for g in guides),
        theme=selected_theme,
    )


def document_target(
    target: str,
    targets_root: Path,
    *,
    model: str | None = None,
    llm_provider: str | None = None,
    theme: str | None = None,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
) -> tuple[GeneratedDocumentation, AssembledDocumentation]:
    generated = generate_documentation(
        target,
        targets_root,
        model=model,
        llm_provider=llm_provider,
        runner=runner,
        on_text=on_text,
    )
    assembled = assemble_documentation(target, targets_root, theme=theme)
    return generated, assembled
