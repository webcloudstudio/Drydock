"""Per-target manifest (``target.yaml``).

Binds a Target to its Blueprint and to the ``code_root`` holding the built and
served application code. The manifest is a tiny scalar file; Drydock carries no
YAML dependency, so it is parsed with a small line scanner like
``prompts.load_prompt``.

``code_root`` is interpreted relative to the Target directory (or absolute). The
default ``../..`` points at ``$DRYDOCK_WORKSPACE`` for self-hosting and brownfield
Targets whose code already exists in the workspace. A greenfield Target uses
``code`` (``targets/<Target>/code``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drydock.errors import DrydockError

MANIFEST_NAME = "target.yaml"
DEFAULT_CODE_ROOT = "../.."


@dataclass
class TargetManifest:
    blueprint: str = ""
    code_root: str = DEFAULT_CODE_ROOT

    def render(self) -> str:
        return f"blueprint: {self.blueprint}\ncode_root: {self.code_root}\n"


def parse_manifest(text: str) -> TargetManifest:
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return TargetManifest(
        blueprint=data.get("blueprint", ""),
        code_root=data.get("code_root", DEFAULT_CODE_ROOT),
    )


def write_manifest(target_dir: Path, manifest: TargetManifest) -> Path:
    path = target_dir / MANIFEST_NAME
    path.write_text(manifest.render(), encoding="utf-8", newline="\n")
    return path


def read_manifest(target_dir: Path) -> TargetManifest:
    path = target_dir / MANIFEST_NAME
    if not path.is_file():
        raise DrydockError(f"Target manifest not found: {path}\n  Run: drydock init <Target>")
    return parse_manifest(path.read_text(encoding="utf-8"))


def resolve_code_root(target_dir: Path, manifest: TargetManifest) -> Path:
    """Resolve the manifest's ``code_root`` to an absolute path.

    Relative roots are resolved against the Target directory; an empty value
    falls back to the default (``$DRYDOCK_WORKSPACE``).
    """
    value = manifest.code_root or DEFAULT_CODE_ROOT
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (target_dir / candidate).resolve()
