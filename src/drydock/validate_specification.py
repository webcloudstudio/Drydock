"""drydock validate — structural validation of a specification directory."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from drydock.metadata import get_field, parse_metadata
from drydock.paths import get_stack_dir


class Severity(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class Finding:
    section: str
    severity: Severity
    message: str


@dataclass
class ValidationResult:
    spec_name: str
    spec_dir: Path
    findings: list[Finding] = field(default_factory=list)

    def has_failures(self) -> bool:
        return any(f.severity == Severity.FAIL for f in self.findings)

    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.FAIL]

    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.WARN]

    def passes(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.PASS]

    def exit_code(self) -> int:
        return 1 if self.has_failures() else 0


_VALID_STATUSES = {"IDEA", "PROTOTYPE", "ACTIVE", "PRODUCTION", "ARCHIVED"}

_ALLOWED_ROOT_NAMES = {
    "METADATA.md",
    "README.md",
    "INTENT.md",
    "ARCHITECTURE.md",
    "DATABASE.md",
    "UI.md",
    "UI-GENERAL.md",
    "HOMEPAGE.md",
    "ACCEPTANCE_CRITERIA.md",
    "IDEAS.md",
    "REFERENCE_GAPS.md",
    "SCORECARD.md",
    "BUILD_PLAN.md",
    "BUILD_PLAN_INTENT.md",
    "SPEC_SCORECARD.md",
    "SPEC_ITERATION.md",
    "SPEC_PATCHES.md",
}

_SPEC_FILE_PREFIXES = ("SCREEN-", "FEATURE-", "UI-", "AC-", "DOC-")

_GENERATED_FILES = {
    "BUILD_PLAN.md",
    "SCORECARD.md",
    "SPEC_SCORECARD.md",
    "SPEC_ITERATION.md",
    "SPEC_PATCHES.md",
    "REFERENCE_GAPS.md",
}

_TERMINAL_SECTIONS_REQUIRED = {"Acceptance Criteria", "Guardrails", "Open Questions"}
_INTENT_EXTRA_SECTIONS = {"Intent", "Constraints", "Success Criteria"}

_EXAMPLE_FILES = {"SCREEN-Example.md", "FEATURE-Example.md", "UI-Component-Example.md"}

_NO_TERMINAL_NEEDED = {
    "METADATA.md",
    "README.md",
    "ACCEPTANCE_CRITERIA.md",
    "IDEAS.md",
    "REFERENCE_GAPS.md",
    "SCORECARD.md",
    "BUILD_PLAN.md",
    "BUILD_PLAN_INTENT.md",
    "SPEC_SCORECARD.md",
    "SPEC_ITERATION.md",
}

_TYPED_HEADING_RE = re.compile(r"^#\s+[A-Za-z][A-Za-z0-9_-]*:\s+.+")


def _has_section(text: str, heading: str) -> bool:
    return bool(re.search(rf"^## {re.escape(heading)}$", text, re.MULTILINE))


def _file_needs_typed_heading(fname: str) -> bool:
    if fname in _NO_TERMINAL_NEEDED:
        return False
    if fname in _GENERATED_FILES:
        return False
    if re.match(r"^(AC|PATCH)-\d{3}-", fname):
        return False
    if re.match(r".*-AC\.md$|.*-AC-.*\.md$", fname):
        return False
    return True


def validate_specification(
    spec_name: str,
    specification_directory: Path,
    *,
    verbose: bool = False,
) -> ValidationResult:
    """
    Run all validation rules against a specification directory.

    Args:
        spec_name: Name of the specification.
        specification_directory: Root directory for specifications.
        verbose: If True, include PASS findings in output.

    Returns:
        ValidationResult with findings and exit code.
    """
    spec_dir = specification_directory / spec_name
    result = ValidationResult(spec_name=spec_name, spec_dir=spec_dir)

    def p(section: str, msg: str) -> None:
        result.findings.append(Finding(section, Severity.PASS, msg))

    def w(section: str, msg: str) -> None:
        result.findings.append(Finding(section, Severity.WARN, msg))

    def f(section: str, msg: str) -> None:
        result.findings.append(Finding(section, Severity.FAIL, msg))

    # --- Directory existence ---
    section = "Directory"
    if not spec_dir.is_dir():
        f(section, f"Specification directory not found: {spec_dir}")
        return result
    p(section, f"Directory exists: {spec_dir}")

    # --- Required files ---
    section = "Required files"
    for required in ("METADATA.md", "README.md", "ARCHITECTURE.md"):
        if (spec_dir / required).exists():
            p(section, f"{required} exists")
        else:
            f(section, f"{required} is missing")

    # --- METADATA.md fields ---
    section = "METADATA fields"
    metadata_path = spec_dir / "METADATA.md"
    metadata: dict[str, str] = {}
    if metadata_path.exists():
        metadata = parse_metadata(metadata_path)
        for key in ("name", "display_name", "short_description", "status"):
            val = get_field(metadata, key)
            if val:
                p(section, f"{key}: {val}")
            else:
                f(section, f"{key} not set in METADATA.md")

        # name matches spec_name
        meta_name = get_field(metadata, "name")
        if meta_name and meta_name != spec_name:
            f(section, f"METADATA.md name={meta_name!r} does not match spec name {spec_name!r}")
        elif meta_name:
            p(section, f"name matches spec name ({spec_name!r})")

        # status value
        status = get_field(metadata, "status")
        if status:
            if status in _VALID_STATUSES:
                p(section, f"status value valid: {status}")
            else:
                f(
                    section,
                    f"status value invalid: {status!r} (expected {' | '.join(sorted(_VALID_STATUSES))})",
                )

        # stack file check
        stack = get_field(metadata, "stack")
        if stack:
            section2 = "Stack files"
            stack_dir = get_stack_dir()
            for component in re.split(r"[/,\s]+", stack):
                component = component.strip()
                if not component:
                    continue
                comp_lower = component.lower()
                stack_file = stack_dir / f"{comp_lower}.md"
                if stack_file.exists():
                    p(section2, f"stack file exists: Rigging/stack/{comp_lower}.md")
                else:
                    w(
                        section2,
                        f"stack file missing: Rigging/stack/{comp_lower}.md (declared stack: {stack})",
                    )

    # --- Naming conventions ---
    section = "Naming conventions"
    bad_names = 0
    for md_file in sorted(spec_dir.glob("*.md")):
        fname = md_file.name
        if fname in _ALLOWED_ROOT_NAMES:
            p(section, f"{fname} (standard file)")
            continue
        if any(fname.startswith(prefix) for prefix in _SPEC_FILE_PREFIXES):
            p(section, f"{fname} (spec file)")
            continue
        if re.match(r"^(ARCHITECTURE|DATABASE|UI-GENERAL)-.*-\d{3}\.md$", fname):
            p(section, f"{fname} (base-file patch)")
            continue
        if re.match(r"^.*-AC\.md$|^.*-AC-.*\.md$|^AC-", fname):
            p(section, f"{fname} (acceptance criteria file)")
            continue
        w(section, f"Unexpected file name: {fname}")
        bad_names += 1
    if bad_names == 0:
        p(section, "All file names follow conventions")

    # --- Template example file warnings ---
    section = "Template cleanup"
    example_found = False
    for ex in _EXAMPLE_FILES:
        if (spec_dir / ex).exists():
            w(section, f"{ex} still present — rename or delete when spec is ready")
            example_found = True
    if not example_found:
        p(section, "No unedited example template files remaining")

    # --- Terminal sections ---
    section = "Terminal sections"
    for md_file in sorted(spec_dir.glob("*.md")):
        fname = md_file.name
        if fname in _NO_TERMINAL_NEEDED or fname in _GENERATED_FILES:
            continue
        if re.match(r"^(AC|PATCH)-\d{3}-|.*-AC\.md$|.*-AC-.*\.md$", fname):
            continue

        is_example = fname in _EXAMPLE_FILES
        text = md_file.read_text(encoding="utf-8")

        for heading in _TERMINAL_SECTIONS_REQUIRED:
            if _has_section(text, heading):
                p(section, f"{fname} has ## {heading}")
            else:
                if is_example:
                    w(section, f"{fname} (example) missing ## {heading}")
                else:
                    w(section, f"{fname} missing ## {heading}")

        if fname == "INTENT.md":
            for heading in _INTENT_EXTRA_SECTIONS:
                if _has_section(text, heading):
                    p(section, f"INTENT.md has ## {heading}")
                else:
                    w(section, f"INTENT.md missing ## {heading}")
            if _has_section(text, "Goals"):
                w(
                    section,
                    "INTENT.md contains legacy ## Goals section — merge into ## Success Criteria",
                )

    # --- Typed spec file headers ---
    section = "Typed headings"
    for md_file in sorted(spec_dir.glob("*.md")):
        fname = md_file.name
        if not _file_needs_typed_heading(fname):
            continue
        if fname in _GENERATED_FILES:
            continue
        text = md_file.read_text(encoding="utf-8")
        first_heading = next((line for line in text.splitlines() if line.startswith("# ")), "")
        if _TYPED_HEADING_RE.match(first_heading):
            p(section, f"{fname} has typed heading")
        else:
            w(section, f"{fname} missing typed heading (expected: # FileType: ObjectName)")

        ver_match = re.search(r"\|\s*Version\s*\|\s*([^|]+)\|", text)
        if ver_match:
            ver_val = ver_match.group(1).strip()
            if ver_val and "(set version)" not in ver_val and "TODO" not in ver_val:
                p(section, f"{fname} has Version field: {ver_val}")
            else:
                w(section, f"{fname} Version field is placeholder — set it (e.g. 20260608 V1)")
        else:
            w(section, f"{fname} missing | Version | in header table")

    # --- Relationship consistency ---
    section = "Relationship consistency"
    route_to_feature: dict[str, str] = {}
    for feat_file in sorted(spec_dir.glob("FEATURE-*.md")):
        fname = feat_file.name
        if fname == "FEATURE-Example.md":
            continue
        text = feat_file.read_text(encoding="utf-8")
        provides_match = re.search(r"\|\s*Provides\s*\|\s*([^|]+)\|", text)
        if provides_match:
            for route in provides_match.group(1).split(","):
                route = route.strip()
                if route:
                    route_to_feature[route] = fname

    rel_warn = 0
    for screen_file in sorted(spec_dir.glob("SCREEN-*.md")):
        fname = screen_file.name
        if fname == "SCREEN-Example.md":
            continue
        text = screen_file.read_text(encoding="utf-8")
        depends_match = re.search(r"\|\s*Depends On\s*\|\s*([^|]+)\|", text)
        depends_on = depends_match.group(1) if depends_match else ""

        for route in re.findall(r"\b(GET|POST|PUT|DELETE|PATCH) /[^\s,|)]+", text):
            route_key = " ".join(route) if isinstance(route, tuple) else route
            providing = route_to_feature.get(route_key)
            if providing:
                if providing in depends_on:
                    p(section, f"{fname} depends on {providing} (provides {route_key})")
                else:
                    w(
                        section,
                        f"{fname} references {route_key} (from {providing}) but {providing} not in Depends On",
                    )
                    rel_warn += 1

    if rel_warn == 0:
        p(section, "Relationship declarations consistent")

    return result
