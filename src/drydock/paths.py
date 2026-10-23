"""Rigging resource resolver — source tree vs installed package."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def _repo_root_candidates() -> list[Path]:
    """Candidate repository roots when running from the source tree."""
    here = Path(__file__).parent  # src/drydock/
    return [
        here.parent.parent,  # repo root (src/../..)
        here.parent.parent.parent,  # one level higher in editable installs
    ]


def _source_tree_rigging() -> Path | None:
    """Return root-level Rigging/ path if we are running from the source tree."""
    for candidate in _repo_root_candidates():
        rigging = candidate / "Rigging"
        if rigging.is_dir() and (rigging / "spec_template").is_dir():
            return rigging
    return None


def _source_tree_prompts() -> Path | None:
    """Return root-level prompts/ path if we are running from the source tree."""
    for candidate in _repo_root_candidates():
        prompts = candidate / "prompts"
        if prompts.is_dir() and (prompts / "README.md").is_file():
            return prompts
    return None


def _source_tree_quarterdeck() -> Path | None:
    for candidate in _repo_root_candidates():
        quarterdeck = candidate / "QuarterDeck"
        if quarterdeck.is_dir() and (quarterdeck / "app.py").is_file():
            return quarterdeck
    return None


def _source_tree_product_specification() -> Path | None:
    for candidate in _repo_root_candidates():
        specification = candidate / "docs" / "Drydock_Specification.md"
        if specification.is_file():
            return specification
    return None


def _source_tree_repo_root() -> Path | None:
    """Return the repository root when running from the source tree."""
    for candidate in _repo_root_candidates():
        if (
            (candidate / "src" / "drydock").is_dir()
            and (candidate / "prompts").is_dir()
            and (candidate / "docs" / "Drydock_Specification.md").is_file()
        ):
            return candidate
    return None


def get_rigging_root() -> Path:
    """
    Return the authoritative Rigging/ directory.

    Precedence:
      1. Root-level Rigging/ when running from the source tree.
      2. drydock/resources/Rigging/ inside the installed package.
    """
    src = _source_tree_rigging()
    if src is not None:
        return src

    # Installed package: use importlib.resources
    try:
        pkg_files = importlib.resources.files("drydock") / "resources" / "Rigging"
        # Materialise to a real filesystem path when possible
        with importlib.resources.as_file(pkg_files) as p:
            return Path(p)
    except (FileNotFoundError, TypeError) as exc:
        raise FileNotFoundError(
            "Rigging resources not found. Reinstall drydock or run from the source tree."
        ) from exc


def get_model_config_seed() -> Path:
    """
    Return the seed ``model_config.jsonl``.

    Precedence:
      1. Root-level model_config.jsonl when running from the source tree.
      2. drydock/resources/model_config.jsonl inside the installed package.
    """
    for candidate in _repo_root_candidates():
        seed = candidate / "model_config.jsonl"
        if seed.is_file() and (candidate / "src" / "drydock").is_dir():
            return seed
    try:
        pkg_file = importlib.resources.files("drydock") / "resources" / "model_config.jsonl"
        with importlib.resources.as_file(pkg_file) as p:
            return Path(p)
    except (FileNotFoundError, TypeError) as exc:
        raise FileNotFoundError(
            "model_config.jsonl resource not found. Reinstall drydock or run from the source tree."
        ) from exc


def get_prompts_root() -> Path:
    """
    Return the authoritative prompts/ directory.

    Precedence:
      1. Root-level prompts/ when running from the source tree.
      2. drydock/resources/prompts/ inside the installed package.
    """
    src = _source_tree_prompts()
    if src is not None:
        return src

    try:
        pkg_files = importlib.resources.files("drydock") / "resources" / "prompts"
        with importlib.resources.as_file(pkg_files) as p:
            return Path(p)
    except (FileNotFoundError, TypeError) as exc:
        raise FileNotFoundError(
            "Prompt resources not found. Reinstall drydock or run from the source tree."
        ) from exc


def get_quarterdeck_root() -> Path:
    """Return the reusable QuarterDeck runtime template."""
    src = _source_tree_quarterdeck()
    if src is not None:
        return src
    try:
        pkg_files = importlib.resources.files("drydock") / "resources" / "QuarterDeck"
        with importlib.resources.as_file(pkg_files) as path:
            return Path(path)
    except (FileNotFoundError, TypeError) as exc:
        raise FileNotFoundError(
            "QuarterDeck resources not found. Reinstall drydock or run from the source tree."
        ) from exc


def get_quarterdeck_template_dir() -> Path:
    """Return the QuarterDeck template directory."""
    return get_quarterdeck_root() / "templates"


def get_product_specification_path() -> Path:
    """Return the canonical Drydock product specification."""
    src = _source_tree_product_specification()
    if src is not None:
        return src
    try:
        pkg_file = (
            importlib.resources.files("drydock") / "resources" / "docs" / "Drydock_Specification.md"
        )
        with importlib.resources.as_file(pkg_file) as path:
            return Path(path)
    except (FileNotFoundError, TypeError) as exc:
        raise FileNotFoundError(
            "Drydock product specification resource not found. Reinstall drydock or run from "
            "the source tree."
        ) from exc


def get_spec_template_dir() -> Path:
    """Return the spec_template/ directory inside Rigging."""
    return get_rigging_root() / "spec_template"


def get_stack_dir() -> Path:
    """Return the stack/ directory inside Rigging."""
    return get_rigging_root() / "stack"


def get_database_dir(language: str = "python") -> Path:
    """Return the selected language bundle's persistence library.

    It holds shipped persistence source — not guidance — copied into a build unchanged.
    """
    return get_language_dir(language) / "persistence"


def get_repo_root() -> Path:
    """Return the Drydock repository root when running from a source checkout."""
    src = _source_tree_repo_root()
    if src is not None:
        return src
    raise FileNotFoundError(
        "Drydock repository root not found. `drydock prompt review` requires a source checkout."
    )


def language_directories(rigging_root: Path | None = None) -> tuple[Path, ...]:
    """Return installed language bundles, in stable order."""
    root = (rigging_root or get_rigging_root()) / "languages"
    return tuple(p for p in sorted(root.glob("*")) if p.is_dir() and (p / f"{p.name}.md").is_file())


def get_language_dir(language: str) -> Path:
    """Resolve a language bundle without accepting a path as a language name."""
    if not language.isidentifier():
        raise ValueError(f"Invalid language name: {language!r}")
    path = get_rigging_root() / "languages" / language
    if not (path / f"{language}.md").is_file():
        raise ValueError(f"No language bundle is shipped for {language!r}")
    return path


def stack_paths(stack_dir: Path | None = None) -> tuple[Path, ...]:
    """Search stack guidance and sibling language bundles without depending on cwd."""
    stack = stack_dir if stack_dir is not None else get_stack_dir()
    return (stack, *language_directories(stack.parent))


def resolve_rigging_file(name: str, stack_dir: Path | None = None) -> Path | None:
    """Resolve a selectable basename from the stack or a language bundle."""
    if Path(name).name != name:
        return None
    return next((root / name for root in stack_paths(stack_dir) if (root / name).is_file()), None)
