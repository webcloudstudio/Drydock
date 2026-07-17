"""Dependency legitimacy checks for build-time Python manifests."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol
from urllib import error, parse, request

DEFAULT_PYPI_REGISTRY = "https://pypi.org/simple"
DEFAULT_MAX_PACKAGE_AGE_DAYS = 30

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def canonicalize_package_name(name: str) -> str:
    """Normalize a package name using the PyPI canonicalization rules."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class DependencyReference:
    """One package name found in a dependency manifest."""

    package_name: str
    normalized_name: str
    source_file: str
    registry_url: str


@dataclass(frozen=True)
class RegistryPackageInfo:
    """Registry existence and publication metadata for one package."""

    exists: bool
    registry_url: str
    first_published_at: datetime | None = None


@dataclass(frozen=True)
class DependencyIssue:
    """One failed dependency legitimacy check."""

    package_name: str
    normalized_name: str
    source_file: str
    registry_url: str
    verdict: str
    detail: str
    first_published_at: datetime | None = None
    age_days: int | None = None


@dataclass(frozen=True)
class DependencyGateResult:
    """The outcome of dependency legitimacy verification."""

    scanned_files: tuple[str, ...]
    checked_dependencies: tuple[DependencyReference, ...]
    issues: tuple[DependencyIssue, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.issues)


class RegistryClient(Protocol):
    """Lookup interface for registry-backed package verification."""

    def lookup_package(self, normalized_name: str, registry_url: str) -> RegistryPackageInfo:
        """Return registry existence and publication metadata for one package."""


class PyPiRegistryClient:
    """Minimal PyPI-backed registry client."""

    def __init__(self, *, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def lookup_package(self, normalized_name: str, registry_url: str) -> RegistryPackageInfo:
        normalized_registry = registry_url.rstrip("/")
        if normalized_registry != DEFAULT_PYPI_REGISTRY:
            raise ValueError(f"unsupported registry for dependency legitimacy gate: {registry_url}")

        url = f"https://pypi.org/pypi/{parse.quote(normalized_name)}/json"
        req = request.Request(url, headers={"Accept": "application/json"})
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except error.HTTPError as exc:
            if exc.code == 404:
                return RegistryPackageInfo(exists=False, registry_url=registry_url)
            raise

        releases = payload.get("releases")
        first_published = _first_published_at(releases)
        return RegistryPackageInfo(
            exists=True,
            registry_url=registry_url,
            first_published_at=first_published,
        )


def _first_published_at(releases: object) -> datetime | None:
    if not isinstance(releases, dict):
        return None
    published: list[datetime] = []
    for files in releases.values():
        if not isinstance(files, list):
            continue
        for item in files:
            if not isinstance(item, dict):
                continue
            text = item.get("upload_time_iso_8601")
            if not isinstance(text, str) or not text:
                continue
            try:
                published.append(datetime.fromisoformat(text.replace("Z", "+00:00")))
            except ValueError:
                continue
    if not published:
        return None
    return min(published).astimezone(UTC)


def check_python_dependency_manifests(
    build_dir: Path,
    changed_files: tuple[str, ...],
    *,
    client: RegistryClient | None = None,
    today: date | None = None,
    max_package_age_days: int = DEFAULT_MAX_PACKAGE_AGE_DAYS,
) -> DependencyGateResult:
    """Validate registry-backed Python dependency names in changed build manifests."""
    changed_paths = tuple(path for path in changed_files if _is_python_dependency_manifest(path))
    references = collect_python_dependency_references(build_dir, changed_paths)
    if not references:
        return DependencyGateResult(changed_paths, (), ())

    lookup_client = client or PyPiRegistryClient()
    today_value = today or date.today()
    cache: dict[tuple[str, str], RegistryPackageInfo] = {}
    issues: list[DependencyIssue] = []

    for reference in references:
        key = (reference.normalized_name, reference.registry_url)
        if key not in cache:
            cache[key] = lookup_client.lookup_package(*key)
        info = cache[key]
        if not info.exists:
            issues.append(
                DependencyIssue(
                    package_name=reference.package_name,
                    normalized_name=reference.normalized_name,
                    source_file=reference.source_file,
                    registry_url=reference.registry_url,
                    verdict="missing",
                    detail=(
                        f"{reference.package_name} does not resolve in the declared registry "
                        f"{reference.registry_url}"
                    ),
                )
            )
            continue
        if info.first_published_at is None:
            continue
        age_days = (today_value - info.first_published_at.date()).days
        if age_days < max_package_age_days:
            issues.append(
                DependencyIssue(
                    package_name=reference.package_name,
                    normalized_name=reference.normalized_name,
                    source_file=reference.source_file,
                    registry_url=reference.registry_url,
                    verdict="newly-published",
                    detail=(
                        f"{reference.package_name} was first published {age_days} day(s) ago, "
                        f"inside the {max_package_age_days}-day legitimacy window"
                    ),
                    first_published_at=info.first_published_at,
                    age_days=age_days,
                )
            )
    return DependencyGateResult(changed_paths, references, tuple(issues))


def collect_python_dependency_references(
    build_dir: Path, changed_files: tuple[str, ...]
) -> tuple[DependencyReference, ...]:
    """Return unique registry-backed dependencies from changed Python manifests."""
    seen: set[tuple[str, str, str]] = set()
    references: list[DependencyReference] = []
    for rel_path in changed_files:
        path = build_dir / rel_path
        if not path.is_file():
            continue
        for reference in _references_for_manifest(path, rel_path):
            key = (reference.normalized_name, reference.source_file, reference.registry_url)
            if key in seen:
                continue
            seen.add(key)
            references.append(reference)
    return tuple(references)


def _is_python_dependency_manifest(rel_path: str) -> bool:
    name = Path(rel_path).name
    return name in {"pyproject.toml", "requirements.txt", "uv.lock"}


def _references_for_manifest(path: Path, rel_path: str) -> tuple[DependencyReference, ...]:
    name = path.name
    if name == "pyproject.toml":
        return _references_from_pyproject(path, rel_path)
    if name == "requirements.txt":
        return _references_from_requirements(path, rel_path)
    if name == "uv.lock":
        return _references_from_uv_lock(path, rel_path)
    return ()


def _references_from_pyproject(path: Path, rel_path: str) -> tuple[DependencyReference, ...]:
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    project = doc.get("project")
    if not isinstance(project, dict):
        return ()
    references: list[DependencyReference] = []
    references.extend(_dependency_strings_to_refs(project.get("dependencies"), rel_path))
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for values in optional.values():
            references.extend(_dependency_strings_to_refs(values, rel_path))
    return tuple(references)


def _references_from_requirements(path: Path, rel_path: str) -> tuple[DependencyReference, ...]:
    references: list[DependencyReference] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith((
            "-",
            "--",
            "git+",
            "http://",
            "https://",
            "file:",
            ".",
            "/",
        )):
            continue
        if " @ " in line and ("://" in line or "file:" in line):
            continue
        name = _extract_requirement_name(line)
        if name is None:
            continue
        references.append(_make_reference(name, rel_path))
    return tuple(references)


def _references_from_uv_lock(path: Path, rel_path: str) -> tuple[DependencyReference, ...]:
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    packages = doc.get("package")
    if not isinstance(packages, list):
        return ()
    references: list[DependencyReference] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        name = package.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        source = package.get("source")
        if not isinstance(source, dict):
            continue
        registry = source.get("registry")
        if not isinstance(registry, str) or not registry.strip():
            continue
        references.append(_make_reference(name, rel_path, registry_url=registry))
    return tuple(references)


def _dependency_strings_to_refs(values: object, rel_path: str) -> list[DependencyReference]:
    if not isinstance(values, list):
        return []
    refs: list[DependencyReference] = []
    for value in values:
        if not isinstance(value, str):
            continue
        if " @ " in value and ("://" in value or "file:" in value):
            continue
        name = _extract_requirement_name(value)
        if name is None:
            continue
        refs.append(_make_reference(name, rel_path))
    return refs


def _extract_requirement_name(value: str) -> str | None:
    match = _NAME_RE.match(value)
    if match is None:
        return None
    return match.group(1)


def _make_reference(
    package_name: str,
    source_file: str,
    *,
    registry_url: str = DEFAULT_PYPI_REGISTRY,
) -> DependencyReference:
    return DependencyReference(
        package_name=package_name,
        normalized_name=canonicalize_package_name(package_name),
        source_file=source_file,
        registry_url=registry_url.rstrip("/"),
    )
