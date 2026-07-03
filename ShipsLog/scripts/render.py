#!/usr/bin/env python3
"""Render a post into a Slate-branded standalone HTML page and rebuild a local index.

Implements the brand contract in Drydock's Rigging/BRANDING_MAIN.md: dark chrome
header carrying the Drydock logo, light content column, system font stack, teal
accent on headings. Light text on dark, dark text on light — always.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

from devblog_lib import load_shell_config, parse_frontmatter

LOGO_FILENAME = "drydock_logo.png"

STYLE = """
:root{
  --c-topbar-bg:#1A1D23;--c-side-section:#8A8F9A;--c-accent:#2CB67D;
  --c-h1:#1E2328;--c-h2:#2E3640;--c-h3:#505A68;
  --c-bg:#FAFAF8;--c-text:#2A2E35;
  --c-code-bg:#EDEEE8;--c-code-text:#2E3640;
  --c-td-border:#D5D8DE;--c-tr-alt:#F3F4F2;
}
body{margin:0;background:var(--c-bg);color:var(--c-text);
  font:14px/1.65 'Segoe UI','Trebuchet MS',Arial,Helvetica,sans-serif}
header{background:var(--c-topbar-bg);position:relative;display:flex;align-items:center;
  justify-content:center;padding:12px 88px;min-height:46px}
header img{height:46px;width:auto;display:block;position:absolute;left:28px;
  top:50%;transform:translateY(-50%)}
header .site{color:#FFFFFF;font-size:15px;font-weight:700;letter-spacing:.02em;
  text-align:center}
header .site small{display:block;color:var(--c-side-section);font-weight:400;font-size:12px}
main{max-width:860px;margin:0 auto;padding:28px 32px 72px}
h1{color:var(--c-h1);font-size:22px;font-weight:700;margin:10px 0 4px;
  padding-bottom:6px;border-bottom:2px solid var(--c-accent)}
.meta{color:var(--c-h3);font-size:12.5px;margin:8px 0 4px}
.summary{color:var(--c-h3);font-size:13.5px;margin:0 0 24px}
h2{color:var(--c-h2);font-size:17px;font-weight:700;margin:30px 0 12px;
  padding:6px 12px;background:rgba(44,182,125,.06);border-left:4px solid var(--c-accent)}
p{margin:10px 0}
ul{margin:10px 0;padding-left:1.35em}
li{margin:7px 0}
strong{color:var(--c-h2)}
code{font:12.5px 'Cascadia Code',Consolas,'Courier New',monospace;
  background:var(--c-code-bg);color:var(--c-code-text);padding:1px 5px;border-radius:3px}
a{color:var(--c-accent)}
article{margin:1.6rem 0;padding-bottom:1.2rem;border-bottom:1px solid var(--c-td-border)}
article h2{background:none;border-left:none;padding:0;margin:0 0 2px}
article h2 a{color:var(--c-h2);text-decoration:none}
article h2 a:hover{color:var(--c-accent)}
@media (max-width:720px){main{padding:20px 16px 48px}header{padding:10px 64px}
  header img{left:12px;height:36px}}
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("post", nargs="?", help="Post markdown file to render")
    parser.add_argument("--output", help="HTML file to write")
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Rebuild blog/posts/index.html from the posts on disk without rendering a post",
    )
    return parser


def inline_markup(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_html(body: str) -> str:
    chunks = [chunk.strip() for chunk in body.split("\n\n") if chunk.strip()]
    rendered: list[str] = []
    for chunk in chunks:
        if chunk.startswith("## "):
            rendered.append(f"<h2>{inline_markup(chunk[3:].strip())}</h2>")
            continue
        lines = chunk.splitlines()
        if all(line.startswith("- ") for line in lines):
            items = "".join(f"<li>{inline_markup(line[2:].strip())}</li>" for line in lines)
            rendered.append(f"<ul>{items}</ul>")
            continue
        rendered.append(f"<p>{inline_markup(' '.join(line.strip() for line in lines))}</p>")
    return "\n".join(rendered)


def page_header(logo_available: bool) -> str:
    logo = f"<img src='{LOGO_FILENAME}' alt='Drydock'>" if logo_available else ""
    return (
        "<header>"
        f"{logo}"
        "<div class='site'>Drydock Development Log"
        "<small>Ed Barlow &middot; specification-driven software delivery</small></div>"
        "</header>"
    )


def page(title: str, header_html: str, main_html: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>"
        f"{header_html}<main>{main_html}</main></body></html>"
    )


def render_post(
    title: str, summary: str, date_value: str, post_type: str, body_html: str, logo_available: bool
) -> str:
    meta = " &middot; ".join(html.escape(part) for part in (date_value, post_type) if part)
    main_html = (
        f"<h1>{html.escape(title)}</h1>"
        + (f"<p class='meta'>{meta}</p>" if meta else "")
        + (f"<p class='summary'>{html.escape(summary)}</p>" if summary else "")
        + body_html
    )
    return page(title, page_header(logo_available), main_html)


def build_directory_index(directory: Path, logo_available: bool) -> str:
    rows: list[str] = []
    entries: list[tuple[str, str]] = []
    for html_file in sorted(directory.glob("*.html"), reverse=True):
        if html_file.name == "index.html":
            continue
        title = html_file.stem
        md_file = html_file.with_suffix(".md")
        summary = ""
        date_value = ""
        if md_file.exists():
            parsed = parse_frontmatter(md_file.read_text(encoding="utf-8"))
            title = str(parsed.frontmatter.get("title", title))
            summary = str(parsed.frontmatter.get("summary", ""))
            date_value = str(parsed.frontmatter.get("date", ""))
        else:
            # A rendered page can outlive its Markdown source; recover the
            # display fields from the page itself instead of showing the stem.
            page_text = html_file.read_text(encoding="utf-8")
            title_match = re.search(r"<title>(.*?)</title>", page_text, re.DOTALL)
            if title_match:
                title = html.unescape(title_match.group(1)).strip()
            summary_match = re.search(r"<p class='summary'>(.*?)</p>", page_text, re.DOTALL)
            if summary_match:
                summary = html.unescape(summary_match.group(1)).strip()
            meta_match = re.search(r"<p class='meta'>(\d{4}-\d{2}-\d{2})", page_text)
            if meta_match:
                date_value = meta_match.group(1)
        entries.append((date_value, html_file.name))
        rows.append(
            "<article>"
            f'<h2><a href="{html.escape(html_file.name)}">{html.escape(title)}</a></h2>'
            f"<p class='meta'>{html.escape(date_value)}</p>"
            f"<p>{html.escape(summary)}</p>"
            "</article>"
        )
    main_html = "<h1>Drydock Development Log</h1>" + "".join(rows)
    return page("Drydock Development Log", page_header(logo_available), main_html)


def ensure_logo(posts_dir: Path) -> bool:
    """Copy the configured brand logo next to the rendered pages."""
    target = posts_dir / LOGO_FILENAME
    if target.exists():
        return True
    source = Path(load_shell_config().get("LOGO", ""))
    if source.exists():
        shutil.copy2(source, target)
        return True
    return False


def rebuild_index(posts_dir: Path) -> int:
    logo_available = ensure_logo(posts_dir)
    index_path = posts_dir / "index.html"
    index_path.write_text(build_directory_index(posts_dir, logo_available), encoding="utf-8")
    print(f"render: rebuilt {index_path}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.index_only:
        return rebuild_index(Path(load_shell_config()["POSTS_DIR"]))
    if not args.post:
        print("render: a post file is required unless --index-only is given.")
        return 2
    draft_path = Path(args.post)
    parsed = parse_frontmatter(draft_path.read_text(encoding="utf-8"))
    title = str(parsed.frontmatter.get("title", "Drydock Development Log"))
    summary = str(parsed.frontmatter.get("summary", ""))
    date_value = str(parsed.frontmatter.get("date", ""))
    post_type = str(parsed.frontmatter.get("type", ""))
    body_html = markdown_to_html(parsed.body)
    output = Path(args.output) if args.output else draft_path.with_suffix(".html")
    output.parent.mkdir(parents=True, exist_ok=True)
    logo_available = ensure_logo(output.parent)
    output.write_text(
        render_post(title, summary, date_value, post_type, body_html, logo_available),
        encoding="utf-8",
    )
    index_path = output.parent / "index.html"
    index_path.write_text(build_directory_index(output.parent, logo_available), encoding="utf-8")
    print(f"render: wrote {output}")
    print(f"render: rebuilt {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
