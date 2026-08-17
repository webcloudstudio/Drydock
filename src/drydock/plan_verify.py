"""``drydock plan verify`` — decide whether the planned Blueprint is fit to build.

The failure this exists for. A criterion that reads an unimported name is not a failing test; it
is a test that cannot run. It raises ``NameError`` in its own frame, settles UNVERIFIED, and the
build spends its whole repair budget on a story whose code was already correct — then stops on a
score that never moved. Every part of that is detectable before the first build call, from the
text of the Blueprint alone, and Drydock already detects it: ``drydock status`` printed both
defects forty minutes before the run that motivated this module died on one of them. Nothing
consumed the detection.

So this command consumes it. It is read-only and deterministic — no model, no build directory, no
network — and its exit status is the whole verdict: zero when the Blueprint is fit to build,
non-zero when a defect will cost build calls to discover. The intended use is a two-line workflow
in which the repair call is only paid for when it is needed::

    drydock plan verify <Target> || drydock plan repair <Target>

What it refuses to judge. Whether a criterion is *correct* — whether its expected value matches
what the product should do — is not decidable from the text, and the analyzers that tried to
decide it were retracted after failing specifications that had validated for weeks. A wrong-but-
runnable criterion fails at build time on the evidence of its own traceback, which is a sounder
authority than a prediction. This command judges only facts about the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from drydock.acceptance import (
    parse_programmatic_acceptance,
    syntax_defect,
    unresolved_globals,
)
from drydock.errors import SpecificationError
from drydock.story_guidance import load_guidance

#: Files under ``blueprint/`` that no Blueprint author wrote and no repair may touch.
_GENERATED_FILES = frozenset({"MANIFEST.md", "TOPOLOGY.md", "SCORECARD.md"})


@dataclass(frozen=True)
class Defect:
    """One repairable fault, addressed to the exact criterion that carries it."""

    #: Blueprint file name, relative to ``blueprint/``.
    filename: str
    #: Acceptance criterion id, or empty when the fault is the file's own parse.
    check_id: str
    #: Machine-stable class, used to route the repair and to assert on in tests.
    kind: str
    #: One sentence naming the fault and what would fix it.
    detail: str

    @property
    def rendered(self) -> str:
        where = f"{self.filename} [{self.check_id}]" if self.check_id else self.filename
        return f"{where}: {self.detail}"


@dataclass(frozen=True)
class VerifyResult:
    """What verification found. ``ok`` is the exit status and nothing else decides it."""

    target: str
    blueprint_dir: Path
    defects: tuple[Defect, ...] = ()
    warnings: tuple[str, ...] = ()
    checked_files: int = 0
    checked_criteria: int = 0
    guidance_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.defects

    def exit_code(self) -> int:
        return 0 if self.ok else 1

    @property
    def summary(self) -> str:
        if self.ok:
            return (
                f"{self.checked_criteria} acceptance "
                f"{'criterion' if self.checked_criteria == 1 else 'criteria'} in "
                f"{self.checked_files} {'file' if self.checked_files == 1 else 'files'}: "
                "every one can run"
            )
        return (
            f"{len(self.defects)} "
            f"{'criterion' if len(self.defects) == 1 else 'criteria'} cannot run as written"
        )


def _blueprint_files(blueprint_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(blueprint_dir.glob("*.md"))
        if path.name not in _GENERATED_FILES and "_compact." not in path.name
    ]


def verify(target: str, target_dir: Path) -> VerifyResult:
    """Judge every acceptance criterion in the Target's Blueprint. Never writes."""
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    defects: list[Defect] = []
    warnings: list[str] = []
    checked_criteria = 0
    files = _blueprint_files(blueprint_dir)

    for path in files:
        try:
            checks = parse_programmatic_acceptance(path)
        except ValueError as exc:
            # The container is malformed, so no criterion in this file is readable. Reported
            # against the file rather than a criterion, because there is no criterion to name.
            defects.append(Defect(path.name, "", "unparseable-file", str(exc)))
            continue
        for check in checks:
            checked_criteria += 1
            # Order matters: a snippet that does not compile has no meaningful name analysis, so
            # reporting both would name the same fault twice and give repair two things to fix.
            if (reason := syntax_defect(check.code)) is not None:
                defects.append(Defect(path.name, check.check_id, "syntax", reason))
                continue
            if names := unresolved_globals(check.code):
                rendered = ", ".join(f"`{name}`" for name in sorted(names))
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "unresolved-global",
                        f"reads undefined global name(s): {rendered}; import or assign each "
                        "name inside this acceptance criterion",
                    )
                )
                continue
            for literal in check.retyped_expectations:
                # Advisory, deliberately not a defect. A re-typed expectation is an authoring
                # smell with a real false-positive rate, and gating on it would refuse correct
                # specifications. Repair is told about it and may act; verification does not
                # fail on it.
                warnings.append(
                    f"{path.name} [{check.check_id}]: expects {literal!r}, a value re-typed "
                    "rather than derived from the input or read back from the system"
                )

    guidance = load_guidance(target_dir)
    return VerifyResult(
        target=target,
        blueprint_dir=blueprint_dir,
        defects=tuple(defects),
        warnings=tuple(warnings),
        checked_files=len(files),
        checked_criteria=checked_criteria,
        guidance_ids=guidance.ids,
    )


def render(result: VerifyResult) -> str:
    """Render the verdict for a terminal. One line per defect, path first so it is clickable."""
    lines = [f"plan verify: {result.target}", f"  {result.summary}"]
    for defect in result.defects:
        lines.append(f"  ✗  {defect.rendered}")
    for warning in result.warnings:
        lines.append(f"  ⚠  {warning}")
    if result.defects:
        lines.append(f"  Run: drydock plan repair {result.target}")
    return "\n".join(lines)
