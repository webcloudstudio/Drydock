"""REFIT tickets: ordered, per-Blueprint change nodes appended to the Manifest.

A REFIT ticket is ``blueprint/<Blueprint-stem>_refit_<NNN>.md``. The filename is the whole
identity: the stem names the one Blueprint it amends, and the number fixes its order and its
parent (``NNN - 1``, or the Blueprint itself for ``001``). The effective specification is the
Blueprint read together with its chain in order; a later ticket wins a conflict.

``add_ticket`` is deterministic. It numbers the ticket, writes it, and appends one Manifest story
that depends on the previous ticket's story, or on every story implementing the Blueprint for the
first ticket. It never builds; ``drydock build`` is the only apply step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest, ManifestNode

REFIT_SEPARATOR = "_refit_"
_REFIT_RE = re.compile(r"^(?P<stem>.+)_refit_(?P<number>\d{3,})\.md$")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
#: Fields a ticket story inherits from the Blueprint's own story, so the build places it in the
#: same stack and taxonomy the Blueprint was built with.
_INHERITED_FIELDS = ("type", "kind", "stack", "stack_mode")


@dataclass(frozen=True)
class AddedTicket:
    path: Path
    story_id: str
    depends: tuple[str, ...]


def ticket_filename(stem: str, number: int) -> str:
    return f"{stem}{REFIT_SEPARATOR}{number:03d}.md"


def parse_ticket_name(name: str) -> tuple[str, int] | None:
    """``(Blueprint stem, number)`` for a REFIT ticket filename, else ``None``."""
    match = _REFIT_RE.match(name)
    if match is None:
        return None
    return match.group("stem"), int(match.group("number"))


def ticket_chain(blueprint_dir: Path, stem: str) -> list[Path]:
    """The Blueprint's REFIT tickets in application order."""
    chain = []
    for path in blueprint_dir.glob(f"{stem}{REFIT_SEPARATOR}*.md"):
        parsed = parse_ticket_name(path.name)
        if parsed is not None and parsed[0] == stem:
            chain.append((parsed[1], path))
    return [path for _, path in sorted(chain)]


def _resolve_blueprint(blueprint_dir: Path, blueprint: str) -> str:
    name = blueprint if blueprint.endswith(".md") else f"{blueprint}.md"
    if Path(name).name != name:
        raise SpecificationError(f"Blueprint must be a file name in blueprint/: {blueprint}")
    if parse_ticket_name(name) is not None or name.endswith("_compact.md"):
        raise SpecificationError(f"Not an authored Blueprint: {name}")
    if not (blueprint_dir / name).is_file():
        raise SpecificationError(f"Blueprint not found: blueprint/{name}")
    return name


def _story_ids_implementing(manifest: DrydockManifest, filename: str) -> list[ManifestNode]:
    return [
        node
        for node in manifest.blocks
        if node.block_type == "story" and filename in _as_tuple(node.fields.get("implements"))
    ]


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


def _split_title(text: str, stem: str, number: int) -> tuple[str, str]:
    """The body's leading H1 becomes the ticket title, so the ticket carries one H1."""
    body = text.strip()
    match = _H1_RE.match(body)
    if match is None:
        return f"Refit {stem} {number:03d}", body
    return match.group(1), body[match.end() :].strip()


def _render_ticket(
    blueprint: str, stem: str, number: int, previous: str | None, title: str, body: str
) -> str:
    supersedes = f"`{blueprint}`" + (f" and `{previous}`" if previous else "")
    lines = [
        f"# REFIT: {stem} {number:03d} — {title}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Blueprint | {blueprint} |",
        f"| Parent | {previous or blueprint} |",
        "",
        f"This ticket amends {supersedes}. Where they conflict, this ticket governs.",
        "",
        body.strip(),
        "",
    ]
    return "\n".join(lines)


def add_ticket(
    target_dir: Path, blueprint: str, text: str, *, today: str | None = None
) -> AddedTicket:
    """Write the next REFIT ticket for ``blueprint`` and append its Manifest story."""
    blueprint_dir = target_dir / "blueprint"
    manifest_path = target_dir / "MANIFEST.md"
    if not text.strip():
        raise SpecificationError("REFIT ticket text is empty")
    if not manifest_path.is_file():
        raise SpecificationError(
            f"No MANIFEST.md for {target_dir.name}; plan the Target before refitting it.\n"
            f"  Run: drydock plan {target_dir.name}"
        )
    blueprint = _resolve_blueprint(blueprint_dir, blueprint)
    stem = blueprint[: -len(".md")]
    manifest = DrydockManifest.load(manifest_path, compatibility=True)

    owners = _story_ids_implementing(manifest, blueprint)
    if not owners:
        raise SpecificationError(f"No Manifest story implements {blueprint}")

    chain = ticket_chain(blueprint_dir, stem)
    number = (parse_ticket_name(chain[-1].name)[1] + 1) if chain else 1
    previous = chain[-1].name if chain else None
    if previous is not None:
        parents = _story_ids_implementing(manifest, previous)
        if not parents:
            raise SpecificationError(f"No Manifest story implements {previous}")
    else:
        parents = owners
    depends = tuple(node.block_id for node in parents)

    filename = ticket_filename(stem, number)
    story_id = f"{stem.lower()}-refit-{number:03d}"
    template = owners[-1]
    stories = [node for node in manifest.blocks if node.block_type == "story"]
    phase = max([node.phase for node in parents] + [1])
    block = max([node.block for node in stories], default=0) + 1
    context = tuple(
        dict.fromkeys([
            *_as_tuple(template.fields.get("context")),
            blueprint,
            *(p.name for p in chain),
        ])
    )
    inherited = {key: template.fields[key] for key in _INHERITED_FIELDS if template.fields.get(key)}
    title, body = _split_title(text, stem, number)
    # A ticket that carries executable AC blocks is held to them, as its Blueprint's story is.
    acceptance = {"acceptance": "yes"} if "=== AC " in body else {}

    manifest.add(
        DrydockManifest.create_node(
            "story",
            story_id,
            title,
            number=max((node.number for node in manifest.blocks), default=0) + 1,
            state="pending",
            depends=depends,
            summary=title,
            created=today or date.today().isoformat(),
            **inherited,
            phase=str(phase),
            block=str(block),
            implements=(filename,),
            context=context,
            **acceptance,
            instructions=(
                f"Implement {filename}. It amends {blueprint} and every earlier ticket in its "
                "chain; where they conflict, the ticket governs."
            ),
        )
    )
    manifest.set_metadata(
        blocks=str(
            len({node.block for node in manifest.blocks if node.block_type == "story"} - {0})
        )
    )

    ticket_path = blueprint_dir / filename
    ticket_path.write_text(
        _render_ticket(blueprint, stem, number, previous, title, body),
        encoding="utf-8",
        newline="\n",
    )
    try:
        manifest.save()
    except Exception:
        ticket_path.unlink(missing_ok=True)
        raise
    return AddedTicket(path=ticket_path, story_id=story_id, depends=depends)
