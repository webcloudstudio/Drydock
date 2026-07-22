"""Blueprint-owned acceptance assertions for build verification."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from drydock.build_plan import BuildPlan, PlanBlock
from drydock.proof_integrity import analyze_proof

SECTION_RE = re.compile(r"^## (?P<name>[^\n]+)\n", re.MULTILINE)
PYTHON_FENCE_RE = re.compile(r"```python\s*\n(?P<code>.*?)\n```", re.DOTALL)
HEADING_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$", re.MULTILINE)
TIMEOUT_SECONDS = 60
# A full-corpus check runs a complete conformance suite; a story timeout would kill it.
CORPUS_TIMEOUT_SECONDS = 900


def _timeout_output_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _scrub_script_path(text: str, script: Path) -> str:
    """Replace the throwaway script's absolute path with its stable check name.

    The path is a per-run temporary directory; leaving it in evidence makes otherwise
    identical failures compare unequal across runs.
    """
    return text.replace(str(script), script.name)


@dataclass(frozen=True)
class ProgrammaticAcceptance:
    check_id: str
    source: str
    intent: str
    code: str
    sea_trials: tuple[str, ...] = ()
    full_corpus: bool = False

    @property
    def timeout_seconds(self) -> int:
        """A full-corpus check runs a whole conformance suite, not a story unit test."""
        return CORPUS_TIMEOUT_SECONDS if self.full_corpus else TIMEOUT_SECONDS


@dataclass(frozen=True)
class AcceptanceRunResult:
    check_id: str
    source: str
    intent: str
    passed: bool
    return_code: int | None
    stdout: str
    stderr: str
    error: str | None = None


@dataclass(frozen=True)
class AcceptanceObservation:
    check_id: str
    source: str
    intent: str
    passed: bool
    return_code: int | None
    stdout: str
    stderr: str
    error: str | None = None
    integrity_ok: bool = True
    integrity_reasons: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if not self.passed:
            return "baseline-red"
        return "green" if self.integrity_ok else "green-vacuous"

    @property
    def weak(self) -> bool:
        return self.passed


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "acceptance"


def _sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("name").strip().lower()] = text[start:end].strip()
    return sections


def _last_heading(text: str) -> str | None:
    headings = list(HEADING_RE.finditer(text))
    if not headings:
        return None
    return headings[-1].group("title").strip()


def _intent(prefix: str, title: str | None) -> str:
    lines = []
    for raw in prefix.splitlines():
        line = raw.strip()
        if not line or line.startswith("###"):
            continue
        if re.match(r"(Sea Trials|Corpus):", line, re.I):
            continue
        lines.append(line)
    if lines:
        return " ".join(lines)
    return title or "Programmatic acceptance assertion"


def _full_corpus(prefix: str) -> bool:
    """Whether the assertion opts in to running a complete conformance corpus.

    Story acceptance is bounded by default so an ordinary check cannot accidentally invoke a
    whole suite. The terminal verification story declares ``Corpus: full`` to gate on the real
    corpus rather than a sample of it.
    """
    return bool(re.search(r"^Corpus:\s*full\s*$", prefix, re.MULTILINE | re.IGNORECASE))


def _sea_trials(prefix: str) -> tuple[str, ...]:
    match = re.search(r"^Sea Trials:\s*(.+?)\s*$", prefix, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ()
    return tuple(value.lower() for raw in match.group(1).split(",") if (value := raw.strip()))


def parse_programmatic_acceptance(path: Path) -> tuple[ProgrammaticAcceptance, ...]:
    """Return Python acceptance snippets from one Blueprint spec file."""
    text = path.read_text(encoding="utf-8")
    section = _sections(text).get("programmatic acceptance", "")
    if not section or section.strip() == "- None.":
        return ()

    checks: list[ProgrammaticAcceptance] = []
    previous_end = 0
    for index, match in enumerate(PYTHON_FENCE_RE.finditer(section), start=1):
        prefix = section[previous_end : match.start()]
        title = _last_heading(prefix)
        check_id = _slugify(title or f"{path.stem}-{index}")
        checks.append(
            ProgrammaticAcceptance(
                check_id=check_id,
                source=path.name,
                intent=_intent(prefix, title),
                code=match.group("code").strip(),
                sea_trials=_sea_trials(prefix),
                full_corpus=_full_corpus(prefix),
            )
        )
        previous_end = match.end()
    return tuple(checks)


def programmatic_acceptance_for_step(
    block: PlanBlock, blueprint_dir: Path
) -> tuple[ProgrammaticAcceptance, ...]:
    """Load programmatic assertions from the Blueprint files a step implements."""
    checks: list[ProgrammaticAcceptance] = []
    for name in block.fields.get("implements", ()):
        if not isinstance(name, str):
            continue
        path = blueprint_dir / name
        if path.is_file():
            checks.extend(parse_programmatic_acceptance(path))
    return tuple(checks)


def all_programmatic_acceptance(
    plan: BuildPlan, blueprint_dir: Path
) -> tuple[ProgrammaticAcceptance, ...]:
    """Every Blueprint assertion the plan implements, deduped by ``(source, check_id)``.

    This is the projection source for ``SOUNDINGS.md``: one entry per individual Programmatic
    Acceptance assertion across the Blueprint spec files the plan's stories implement.
    """
    checks: list[ProgrammaticAcceptance] = []
    seen: set[tuple[str, str]] = set()
    for block in plan.blocks:
        if block.block_type != "story":
            continue
        for name in block.fields.get("implements", ()):
            if not isinstance(name, str):
                continue
            path = blueprint_dir / name
            if not path.is_file():
                continue
            for check in parse_programmatic_acceptance(path):
                key = (check.source, check.check_id)
                if key in seen:
                    continue
                seen.add(key)
                checks.append(check)
    return tuple(checks)


def run_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
) -> tuple[AcceptanceRunResult, ...]:
    """Execute Python acceptance snippets from the build directory."""
    results: list[AcceptanceRunResult] = []
    pythonpath = os.pathsep.join(
        part for part in (str(build_dir), os.environ.get("PYTHONPATH", "")) if part
    )
    env = {
        **os.environ,
        "DRYDOCK_BUILD_DIR": str(build_dir),
        "DRYDOCK_TARGET_DIR": str(target_dir),
        "DRYDOCK_BLUEPRINT_DIR": str(blueprint_dir),
        "PYTHONPATH": pythonpath,
    }
    for check in checks:
        # Run from a real file, never ``python -c``: a ``-c`` traceback reports
        # ``File "<string>", line N`` with no source text, so a failing assertion names
        # neither the assertion nor the expectation it asserted. Written to a file, the
        # traceback carries the offending line and the failure is diagnosable in one pass.
        with tempfile.TemporaryDirectory(prefix="drydock-acceptance-") as tmp:
            script = Path(tmp) / f"{check.check_id or 'acceptance'}.py"
            script.write_text(check.code + "\n", encoding="utf-8")
            try:
                completed = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=build_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=check.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                results.append(
                    AcceptanceRunResult(
                        check_id=check.check_id,
                        source=check.source,
                        intent=check.intent,
                        passed=False,
                        return_code=None,
                        stdout=_timeout_output_text(exc.stdout),
                        stderr=_timeout_output_text(exc.stderr),
                        error=f"timed out after {check.timeout_seconds}s",
                    )
                )
                continue
        results.append(
            AcceptanceRunResult(
                check_id=check.check_id,
                source=check.source,
                intent=check.intent,
                passed=completed.returncode == 0,
                return_code=completed.returncode,
                stdout=completed.stdout,
                stderr=_scrub_script_path(completed.stderr, script),
            )
        )
    return tuple(results)


def observe_programmatic_acceptance(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
) -> tuple[AcceptanceObservation, ...]:
    """Execute checks and annotate whether a passing proof is integrity-valid or vacuous."""
    if not checks:
        return ()
    runtime = run_programmatic_acceptance(
        checks, build_dir=build_dir, target_dir=target_dir, blueprint_dir=blueprint_dir
    )
    observations: list[AcceptanceObservation] = []
    for check, result in zip(checks, runtime, strict=True):
        integrity = analyze_proof(check.code)
        observations.append(
            AcceptanceObservation(
                check_id=result.check_id,
                source=result.source,
                intent=result.intent,
                passed=result.passed,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                error=result.error,
                integrity_ok=integrity.ok,
                integrity_reasons=integrity.reasons,
            )
        )
    return tuple(observations)
