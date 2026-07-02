"""Deterministic README.md generator assembled from Blueprint spec files.

Called automatically after a successful drydock build. No LLM required — all
content is sourced from METADATA.md, COMPASS.md, ARCHITECTURE.md, FEATURE-*.md,
and SCREEN-*.md, plus structural inspection of the build output directory.
"""

from __future__ import annotations

import re
from pathlib import Path

from drydock.metadata import get_field, parse_metadata

# Map stack filenames to human-readable display names.
_STACK_DISPLAY: dict[str, str] = {
    "fastapi.md": "FastAPI",
    "flask.md": "Flask",
    "django.md": "Django",
    "persistence.md": "JSON file persistence",
    "postgres.md": "PostgreSQL",
    "sqlite.md": "SQLite",
    "bootstrap5.md": "Bootstrap 5",
    "aws-dynamodb.md": "AWS DynamoDB",
    "aws-s3.md": "AWS S3",
    "aws-lambda.md": "AWS Lambda",
    "aws-sqs.md": "AWS SQS",
    "aws-api-gateway.md": "AWS API Gateway",
    "github-actions.md": "GitHub Actions",
    "terraform.md": "Terraform",
}

# Stack files that are generic/infrastructure and not worth naming in the README.
_STACK_SKIP = {"common.md", "python.md"}


# ---------------------------------------------------------------------------
# Markdown parsing helpers
# ---------------------------------------------------------------------------


def _section(text: str, heading: str) -> str:
    """Extract body of '## heading' through the next '## ' or end of file."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$(.+?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _header_field(text: str, field_name: str) -> str:
    """Read a value from a '| Field | Value |' typed-header table row."""
    pattern = re.compile(
        rf"^\|\s*{re.escape(field_name)}\s*\|\s*(.+?)\s*\|",
        re.MULTILINE | re.IGNORECASE,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _bullets(section_text: str) -> list[str]:
    """Return lines that start with '-' from a section body."""
    return [line.strip() for line in section_text.splitlines() if line.strip().startswith("-")]


# ---------------------------------------------------------------------------
# Per-file extractors
# ---------------------------------------------------------------------------


def _intent_from_compass(target_dir: Path) -> str:
    path = target_dir / "COMPASS.md"
    if not path.exists():
        return ""
    return _section(path.read_text(encoding="utf-8"), "Compass")


def _features(blueprint_dir: Path) -> list[tuple[str, str]]:
    """Return (description, purpose) for each FEATURE-*.md, omitting empty entries."""
    results = []
    for path in sorted(blueprint_dir.glob("FEATURE-*.md")):
        text = path.read_text(encoding="utf-8")
        desc = _header_field(text, "Description")
        purpose = _section(text, "Purpose")
        if purpose:
            results.append((desc or path.stem, purpose))
    return results


def _screens(blueprint_dir: Path) -> list[str]:
    """Return the Description field for each SCREEN-*.md."""
    results = []
    for path in sorted(blueprint_dir.glob("SCREEN-*.md")):
        text = path.read_text(encoding="utf-8")
        desc = _header_field(text, "Description")
        if desc:
            results.append(desc)
    return results


def _modules(blueprint_dir: Path) -> list[str]:
    """Return the bullet entries from ARCHITECTURE.md ## Modules."""
    path = blueprint_dir / "ARCHITECTURE.md"
    if not path.exists():
        return []
    return _bullets(_section(path.read_text(encoding="utf-8"), "Modules"))


def _routes(blueprint_dir: Path) -> list[str]:
    """Return the bullet entries from ARCHITECTURE.md ## Route Groupings."""
    path = blueprint_dir / "ARCHITECTURE.md"
    if not path.exists():
        return []
    return _bullets(_section(path.read_text(encoding="utf-8"), "Route Groupings"))


# ---------------------------------------------------------------------------
# Stack and run-command inference
# ---------------------------------------------------------------------------


def _stack_label(stack_str: str) -> str:
    """Map 'fastapi.md, persistence.md' to 'FastAPI, JSON file persistence'."""
    parts = [p.strip() for p in stack_str.split(",") if p.strip()]
    names = []
    for part in parts:
        if part in _STACK_SKIP:
            continue
        names.append(_STACK_DISPLAY.get(part, part.replace(".md", "").replace("-", " ").title()))
    return ", ".join(names)


def _setup_and_run(build_dir: Path, stack_str: str) -> tuple[str, str, str]:
    """Return (install_cmd, run_cmd, access_url) from build_dir inspection."""
    # Install command
    if (build_dir / "requirements.txt").exists():
        install = "pip install -r requirements.txt"
    elif (build_dir / "pyproject.toml").exists():
        install = "pip install -e ."
    else:
        install = ""

    # Run command: prefer explicit run.py, then app/main.py, then manage.py
    run_cmd = ""
    if (build_dir / "run.py").exists():
        run_cmd = "python run.py"
    elif (build_dir / "app" / "main.py").exists():
        run_cmd = "python app/main.py"
    elif (build_dir / "manage.py").exists():
        run_cmd = "python manage.py runserver"

    # Port: scan app/main.py for the APP_PORT default
    port = "8000"
    main_py = build_dir / "app" / "main.py"
    if main_py.exists():
        m = re.search(r"APP_PORT[^,)\"']*[,\"']\s*(\d{4,5})", main_py.read_text(encoding="utf-8"))
        if m:
            port = m.group(1)

    # Access URL for web stacks
    web_stacks = {"fastapi.md", "flask.md", "django.md"}
    stack_parts = {p.strip() for p in stack_str.split(",")}
    access_url = f"http://127.0.0.1:{port}" if stack_parts & web_stacks else ""

    return install, run_cmd, access_url


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _render(
    *,
    display_name: str,
    short_description: str,
    stack_label: str,
    intent: str,
    features: list[tuple[str, str]],
    screen_descs: list[str],
    modules: list[str],
    routes: list[str],
    install: str,
    run_cmd: str,
    access_url: str,
) -> str:
    lines: list[str] = []

    def blank() -> None:
        lines.append("")

    lines.append(f"# {display_name}")
    blank()
    if short_description:
        lines.append(short_description)
        blank()

    if intent:
        lines.append("## Intent")
        blank()
        lines.append(intent)
        blank()

    # What It Does — feature purposes + screen descriptions
    what_parts: list[str] = [purpose for _, purpose in features]
    what_parts.extend(screen_descs)
    if what_parts:
        lines.append("## What It Does")
        blank()
        for part in what_parts:
            lines.append(part)
            blank()

    if modules:
        lines.append("## Architecture")
        blank()
        lines.extend(modules)
        blank()

    if routes:
        lines.append("## API")
        blank()
        lines.extend(routes)
        blank()

    if stack_label:
        lines.append("## Stack")
        blank()
        lines.append(stack_label)
        blank()

    if install or run_cmd:
        lines.append("## Setup and Running")
        blank()
        if install:
            lines.append("**Install dependencies:**")
            blank()
            lines.append("```bash")
            lines.append(install)
            lines.append("```")
            blank()
        if run_cmd:
            lines.append("**Start the application:**")
            blank()
            lines.append("```bash")
            lines.append(run_cmd)
            lines.append("```")
            blank()
        if access_url:
            lines.append(f"Open {access_url} in a browser.")
            if "fastapi" in stack_label.lower():
                blank()
                lines.append(f"Interactive API documentation is available at {access_url}/docs")
            blank()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_readme(target_dir: Path, build_dir: Path) -> Path | None:
    """Write README.md to build_dir assembled from Blueprint spec files.

    Returns the written path, or None when METADATA.md is absent or build_dir
    does not exist.  Never raises — failures are swallowed so a README problem
    does not abort a successful build.
    """
    if not build_dir.exists():
        return None
    meta_path = target_dir / "METADATA.md"
    if not meta_path.exists():
        return None

    try:
        blueprint_dir = target_dir / "blueprint"
        has_blueprint = blueprint_dir.is_dir()

        # Blueprint METADATA.md carries identity fields (display_name, stack, short_description).
        # Root METADATA.md carries lifecycle state only; use it as fallback.
        blueprint_meta = blueprint_dir / "METADATA.md" if has_blueprint else None
        if blueprint_meta and blueprint_meta.exists():
            fields = parse_metadata(blueprint_meta)
        else:
            fields = parse_metadata(meta_path)

        display_name = (
            get_field(fields, "display_name") or get_field(fields, "name") or target_dir.name
        )
        short_description = get_field(fields, "short_description") or ""
        stack_str = get_field(fields, "stack") or ""

        content = _render(
            display_name=display_name,
            short_description=short_description,
            stack_label=_stack_label(stack_str),
            intent=_intent_from_compass(target_dir),
            features=_features(blueprint_dir) if has_blueprint else [],
            screen_descs=_screens(blueprint_dir) if has_blueprint else [],
            modules=_modules(blueprint_dir) if has_blueprint else [],
            routes=_routes(blueprint_dir) if has_blueprint else [],
            **dict(zip(("install", "run_cmd", "access_url"), _setup_and_run(build_dir, stack_str))),
        )

        readme_path = build_dir / "README.md"
        readme_path.write_text(content, encoding="utf-8", newline="\n")
        return readme_path

    except Exception:  # noqa: BLE001
        return None
