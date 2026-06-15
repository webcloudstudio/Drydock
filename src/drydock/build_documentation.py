"""Assemble Drydock's authoritative specification into a documentation page."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

DEFAULT_SPECIFICATION = Path("docs/Drydock_Specification.md")
DEFAULT_OUTPUT = Path("docs/index.html")


def parse_source(text: str) -> tuple[dict[str, object], str]:
    """Split conformed Markdown into frontmatter metadata and body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if match is None:
        raise ValueError("source is missing a --- frontmatter --- block")
    return parse_frontmatter(match.group(1)), match.group(2).strip("\n")


def parse_frontmatter(frontmatter: str) -> dict[str, object]:
    """Parse the scalar and ideas-list subset used by the Drydock Blueprint."""
    metadata: dict[str, object] = {"ideas": [], "sail_lead": []}
    ideas = metadata["ideas"]
    sail_lead = metadata["sail_lead"]
    assert isinstance(ideas, list)
    assert isinstance(sail_lead, list)

    current_idea: dict[str, object] | None = None
    in_ideas = False
    in_sub_list = False
    in_sail_lead = False

    for line in frontmatter.splitlines():
        if not line.strip():
            continue

        if in_sail_lead:
            lead_item = re.match(r"^\s*-\s+(.+)$", line)
            if lead_item:
                sail_lead.append(lead_item.group(1).strip())
                continue

        if in_ideas and in_sub_list and current_idea is not None:
            sub_item = re.match(r"^\s{4,}-\s+(.+)$", line)
            if sub_item:
                sub_list = current_idea.setdefault("sub_list", [])
                assert isinstance(sub_list, list)
                sub_list.append(sub_item.group(1).strip())
                continue

        idea = re.match(r"^\s*-\s*title:\s*(.*)$", line)
        if in_ideas and idea:
            current_idea = {"title": idea.group(1).strip()}
            ideas.append(current_idea)
            in_sub_list = False
            continue

        sub_list_header = re.match(r"^\s+sub_list:\s*$", line)
        if in_ideas and current_idea is not None and sub_list_header:
            current_idea["sub_list"] = []
            in_sub_list = True
            continue

        key = re.match(r"^([A-Za-z][\w_]*):\s*(.*)$", line)
        if key:
            name, value = key.group(1), key.group(2).strip()
            if name == "sail_lead" and not value:
                in_sail_lead = True
                in_ideas = False
                in_sub_list = False
                continue
            in_ideas = name == "ideas" and not value
            in_sail_lead = False
            in_sub_list = False
            if not in_ideas:
                metadata[name] = value

    return metadata


def _render_ideas(metadata: dict[str, object]) -> str:
    ideas = metadata.get("ideas", [])
    if not isinstance(ideas, list) or not ideas:
        return ""

    layout = str(metadata.get("ideas_layout", "")).strip().lower()
    if layout == "sail":
        return _render_sail_ideas(metadata, ideas)

    parts = ['<section class="ideas">']
    ideas_title = str(metadata.get("ideas_title", "What Drydock Adds"))
    parts.append(f"<h2>{_render_inline_markup(ideas_title)}</h2>")
    for item in ideas:
        if not isinstance(item, dict):
            continue
        title = _render_inline_markup(str(item.get("title", "")))
        parts.append('<article class="idea">')
        parts.append(f'<div class="idea-title">{title}</div>')
        sub_list = item.get("sub_list", [])
        if isinstance(sub_list, list) and sub_list:
            parts.append("<ul>")
            parts.extend(f"<li>{_render_inline_markup(str(value))}</li>" for value in sub_list)
            parts.append("</ul>")
        parts.append("</article>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_sail_ideas(metadata: dict[str, object], ideas: list[object]) -> str:
    parts = ['<section class="ideas ideas-sail">']
    ideas_title = str(metadata.get("ideas_title", "The SAIL Method"))
    parts.append(f"<h2>{_render_inline_markup(ideas_title)}</h2>")
    sail_lead = metadata.get("sail_lead", [])
    if isinstance(sail_lead, list) and sail_lead:
        parts.append('<div class="sail-lead">')
        parts.extend(f"<p>{_render_inline_markup(str(value))}</p>" for value in sail_lead)
        parts.append("</div>")
    parts.append('<div class="sail-grid">')
    for item in ideas:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        match = re.match(r"^\*\*([SAIL])\*\*\s+[—-]\s+(.+)$", title)
        if match:
            letter, label = match.group(1), match.group(2)
        else:
            letter, label = title[:1].upper(), title[1:].strip(" -—")
        parts.append('<article class="sail-card">')
        parts.append(f'<div class="sail-letter">{html.escape(letter)}</div>')
        parts.append('<div class="sail-copy">')
        parts.append(f'<div class="idea-title">{_render_inline_markup(label)}</div>')
        sub_list = item.get("sub_list", [])
        if isinstance(sub_list, list) and sub_list:
            parts.append("<ul>")
            parts.extend(f"<li>{_render_inline_markup(str(value))}</li>" for value in sub_list)
            parts.append("</ul>")
        parts.append("</div>")
        parts.append("</article>")
    parts.append("</div>")
    parts.append("</section>")
    return "\n".join(parts)


def _json_for_script(value: str) -> str:
    return json.dumps(value).replace("</", r"<\/")


def _render_inline_markup(text: str) -> str:
    """Render a small inline-markup subset safely for metadata fields."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"<em>\1</em>", escaped)
    return escaped


def render_page(metadata: dict[str, object], body: str) -> str:
    """Render parsed Blueprint content into a self-contained HTML document."""
    title = html.escape(str(metadata.get("title", "Drydock")))
    eyebrow = html.escape(str(metadata.get("eyebrow", "")))
    subtitle = html.escape(str(metadata.get("subtitle", "")))
    author = html.escape(str(metadata.get("author", "")))
    studio = html.escape(str(metadata.get("studio", "")))
    year = html.escape(str(metadata.get("year", "")))
    copyright_text = html.escape(str(metadata.get("copyright", "")))
    ideas = _render_ideas(metadata)
    body_json = _json_for_script(body)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} Documentation</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
:root {{
  --ink: #17212b; --muted: #5b6875; --paper: #f8fafb; --panel: #ffffff;
  --navy: #123047; --green: #0a7650; --line: #d6dee4; --code: #eef3f5; --pre-bg: #f0f1f3;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink);
  font: 14px/1.5 "Segoe UI", Arial, sans-serif; }}
header {{ background: var(--navy); color: white; padding: 10px 28px;
  display: flex; justify-content: space-between; gap: 24px; }}
header strong {{ letter-spacing: .04em; }}
header span {{ color: #c8d6df; font-size: 12px; }}
main {{ max-width: 980px; margin: 0 auto; padding: 32px 32px 60px; }}
.cover {{ background: var(--panel); border-top: 5px solid var(--green);
  border-bottom: 1px solid var(--line); padding: 24px 30px; margin-bottom: 22px; }}
.eyebrow {{ color: var(--green); font-size: 11px; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; }}
h1 {{ font-size: 36px; line-height: 1.1; margin: 6px 0 10px; }}
.subtitle {{ color: var(--muted); font-size: 15px; max-width: 800px; }}
.meta {{ color: var(--muted); display: flex; gap: 18px; margin-top: 14px; font-size: 12px; }}
.ideas {{ margin: 0 0 22px; }}
.ideas h2, #content h2 {{ border-bottom: 2px solid var(--green); padding-bottom: 4px; }}
.ideas h2 {{ font-size: 1.08rem; letter-spacing: .03em; text-transform: uppercase; }}
.idea {{ background: var(--panel); border-left: 5px solid var(--green);
  margin: 8px 0; padding: 10px 14px 10px 16px; }}
.idea-title {{ color: var(--navy); font-size: 1.14rem; font-weight: 800; line-height: 1.2; }}
.idea ul {{ margin: 6px 0 0; color: var(--muted); }}
.ideas-sail {{ background:
  linear-gradient(135deg, rgba(18, 48, 71, 0.06), rgba(10, 118, 80, 0.03)),
  var(--panel);
  border: 1px solid var(--line);
  padding: 20px 22px 10px;
}}
.sail-lead {{
  margin: 2px 0 16px;
  padding: 0 0 12px;
  border-bottom: 1px solid var(--line);
}}
.sail-lead p {{
  margin: 0 0 6px;
  color: var(--navy);
  font-size: 1rem;
  font-weight: 600;
}}
.sail-lead p:last-child {{ margin-bottom: 0; }}
.sail-grid {{ display: grid; gap: 16px; }}
.sail-card {{
  display: grid;
  grid-template-columns: 108px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  padding: 12px 0 16px;
  border-bottom: 1px solid var(--line);
}}
.sail-card:last-child {{ border-bottom: none; }}
.sail-letter {{
  color: var(--green);
  font-size: 4.8rem;
  line-height: 0.9;
  font-weight: 900;
  letter-spacing: -0.05em;
  text-shadow: 2px 2px 0 rgba(18, 48, 71, 0.08);
}}
.sail-copy .idea-title {{ font-size: 1.22rem; margin-bottom: 4px; }}
.sail-copy ul {{ margin: 0; padding-left: 20px; color: var(--muted); }}
.sail-copy li {{ margin-bottom: 4px; }}
#content {{ background: var(--panel); border: 1px solid var(--line); padding: 26px 30px; }}
#content h2 {{ margin-top: 28px; margin-bottom: 10px; }}
#content h2:first-child {{ margin-top: 0; }}
#content h3 {{ color: var(--green); margin-top: 18px; margin-bottom: 6px; }}
#content p {{ margin: 6px 0 10px; }}
#content table {{ border-collapse: collapse; display: block; overflow-x: auto; width: 100%; margin: 8px 0; }}
#content th, #content td {{ border: 1px solid var(--line); padding: 3px 8px; text-align: left; }}
#content th {{ background: var(--pre-bg); color: var(--ink); font-size: 13px; }}
#content td {{ font-size: 13px; }}
#content code {{ background: var(--code); border-radius: 3px; padding: 1px 4px; font-size: 13px; }}
#content pre {{ background: var(--pre-bg); color: var(--ink); overflow-x: auto;
  padding: 10px 14px; margin: 6px 0 12px; border-left: 3px solid var(--line); font-size: 13px; }}
#content pre code {{ background: transparent; padding: 0; font-size: inherit; }}
#content blockquote {{ border-left: 4px solid var(--green); background: var(--paper);
  color: var(--muted); font-style: italic; margin: 14px 0 14px 18px;
  padding: 10px 18px; border-radius: 0 3px 3px 0; }}
#content blockquote p {{ margin: 4px 0; }}
#content ul, #content ol {{ margin: 6px 0 10px; padding-left: 24px; }}
#content li {{ margin-bottom: 3px; }}
.diagram {{ background: white; border: 1px solid var(--line); overflow-x: auto; padding: 14px; margin: 8px 0; }}
footer {{ color: var(--muted); font-size: 12px; padding: 16px 28px; text-align: center; }}
@media (max-width: 680px) {{
  main {{ padding: 16px 12px 40px; }} .cover, #content {{ padding: 16px; }}
  header, .meta {{ flex-direction: column; gap: 4px; }} h1 {{ font-size: 28px; }}
  .ideas-sail {{ padding: 16px; }}
  .sail-card {{ grid-template-columns: 1fr; gap: 8px; }}
  .sail-letter {{ font-size: 3.8rem; }}
}}
@media print {{
  header, footer {{ display: none; }}
  body {{ background: white; font-size: 12px; line-height: 1.45; }}
  main {{ padding: 0; max-width: 100%; }}
  #content {{ border: none; padding: 0; }}
  .cover {{ border-top: 3px solid var(--green); padding: 16px; }}
  .ideas-sail {{ border: 1px solid var(--line); padding: 14px 16px 8px; }}
  .sail-card {{ break-inside: avoid; grid-template-columns: 70px minmax(0, 1fr); gap: 10px; }}
  .sail-letter {{ font-size: 3rem; }}
  #content pre, #content blockquote {{ break-inside: avoid; }}
  #content h2, #content h3 {{ break-after: avoid; }}
}}
</style>
</head>
<body>
<header><strong>Drydock</strong><span>{copyright_text}</span></header>
<main>
<section class="cover">
  <div class="eyebrow">{eyebrow}</div>
  <h1>{title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="meta"><span>{author}</span><span>{studio}</span><span>{year}</span></div>
</section>
{ideas}
<article id="content"></article>
</main>
<footer>{author} · {studio} · {year}</footer>
<script>
const BODY = {body_json};
marked.setOptions({{ gfm: true, breaks: false }});
const content = document.getElementById("content");
content.innerHTML = marked.parse(BODY);
content.querySelectorAll("pre > code.language-mermaid").forEach((code) => {{
  const wrapper = document.createElement("div");
  wrapper.className = "diagram";
  const diagram = document.createElement("div");
  diagram.className = "mermaid";
  diagram.textContent = code.textContent;
  wrapper.appendChild(diagram);
  code.parentNode.replaceWith(wrapper);
}});
mermaid.initialize({{ startOnLoad: false, theme: "neutral" }});
mermaid.run({{ nodes: content.querySelectorAll(".mermaid") }});
</script>
</body>
</html>
"""


def build_documentation(source: Path, output: Path) -> Path:
    """Read a conformed Blueprint and write its assembled documentation page."""
    metadata, body = parse_source(source.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_page(metadata, body), encoding="utf-8")
    return output


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_source(root: Path) -> Path:
    return root / DEFAULT_SPECIFICATION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="conformed Markdown source")
    parser.add_argument("--output", type=Path, help="HTML output path")
    args = parser.parse_args(argv)

    root = _repository_root()
    source = args.source or _default_source(root)
    output = args.output or root / DEFAULT_OUTPUT
    built = build_documentation(source, output)
    print(f"Built documentation: {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
