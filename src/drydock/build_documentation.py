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
    metadata: dict[str, object] = {"ideas": []}
    ideas = metadata["ideas"]
    assert isinstance(ideas, list)

    current_idea: dict[str, object] | None = None
    in_ideas = False
    in_sub_list = False

    for line in frontmatter.splitlines():
        if not line.strip():
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
            in_ideas = name == "ideas" and not value
            in_sub_list = False
            if not in_ideas:
                metadata[name] = value

    return metadata


def _render_ideas(metadata: dict[str, object]) -> str:
    ideas = metadata.get("ideas", [])
    if not isinstance(ideas, list) or not ideas:
        return ""

    parts = ['<section class="ideas">']
    ideas_title = str(metadata.get("ideas_title", "What Drydock Adds"))
    parts.append(f"<h2>{html.escape(ideas_title)}</h2>")
    for item in ideas:
        if not isinstance(item, dict):
            continue
        title = html.escape(str(item.get("title", "")))
        parts.append('<article class="idea">')
        parts.append(f"<strong>{title}</strong>")
        sub_list = item.get("sub_list", [])
        if isinstance(sub_list, list) and sub_list:
            parts.append("<ul>")
            parts.extend(f"<li>{html.escape(str(value))}</li>" for value in sub_list)
            parts.append("</ul>")
        parts.append("</article>")
    parts.append("</section>")
    return "\n".join(parts)


def _json_for_script(value: str) -> str:
    return json.dumps(value).replace("</", r"<\/")


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
  font: 15px/1.65 "Segoe UI", Arial, sans-serif; }}
header {{ background: var(--navy); color: white; padding: 12px 28px;
  display: flex; justify-content: space-between; gap: 24px; }}
header strong {{ letter-spacing: .04em; }}
header span {{ color: #c8d6df; font-size: 12px; }}
main {{ max-width: 980px; margin: 0 auto; padding: 40px 32px 80px; }}
.cover {{ background: var(--panel); border-top: 5px solid var(--green);
  border-bottom: 1px solid var(--line); padding: 30px; margin-bottom: 28px; }}
.eyebrow {{ color: var(--green); font-size: 11px; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; }}
h1 {{ font-size: 40px; line-height: 1.1; margin: 8px 0 12px; }}
.subtitle {{ color: var(--muted); font-size: 17px; max-width: 800px; }}
.meta {{ color: var(--muted); display: flex; gap: 18px; margin-top: 20px; font-size: 13px; }}
.ideas {{ margin: 0 0 32px; }}
.ideas h2, #content h2 {{ border-bottom: 2px solid var(--green); padding-bottom: 5px; }}
.idea {{ background: var(--panel); border-left: 4px solid var(--green);
  margin: 10px 0; padding: 12px 16px; }}
.idea ul {{ margin-bottom: 0; }}
#content {{ background: var(--panel); border: 1px solid var(--line); padding: 30px; }}
#content h2 {{ margin-top: 38px; }}
#content h2:first-child {{ margin-top: 0; }}
#content h3 {{ color: var(--green); margin-top: 26px; }}
#content table {{ border-collapse: collapse; display: block; overflow-x: auto; width: 100%; }}
#content th, #content td {{ border: 1px solid var(--line); padding: 7px 10px; text-align: left; }}
#content th {{ background: var(--navy); color: white; }}
#content code {{ background: var(--code); border-radius: 3px; padding: 1px 4px; }}
#content pre {{ background: var(--pre-bg); color: var(--ink); overflow-x: auto; padding: 15px; border-left: 3px solid var(--line); }}
#content pre code {{ background: transparent; padding: 0; }}
#content blockquote {{ border-left: 4px solid var(--green); color: var(--muted);
  margin-left: 0; padding: 2px 18px; }}
.diagram {{ background: white; border: 1px solid var(--line); overflow-x: auto; padding: 16px; }}
footer {{ color: var(--muted); font-size: 12px; padding: 20px 28px; text-align: center; }}
@media (max-width: 680px) {{
  main {{ padding: 20px 12px 50px; }} .cover, #content {{ padding: 20px; }}
  header, .meta {{ flex-direction: column; gap: 4px; }} h1 {{ font-size: 32px; }}
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
