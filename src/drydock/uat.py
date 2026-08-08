"""Project-level unattended acceptance runs for known Drydock fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from drydock.errors import DrydockError, SpecificationError
from drydock.llm_usage import normalize_tokens, read_records

DEFAULT_MAX_BUILD_PASSES = 25


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    elapsed_ms: int
    stdout_path: str
    stderr_path: str


@dataclass(frozen=True)
class UATFixture:
    name: str
    target: str
    root: Path
    specifications: tuple[Path, ...]
    sources: tuple[Path, ...] = ()
    test_command: tuple[str, ...] = ()


Runner = Callable[[Sequence[str], Path, dict[str, str], Path, str], CommandResult]


@dataclass(frozen=True)
class UATResult:
    fixture: str
    target: str
    run_id: str
    status: str
    elapsed_ms: int
    build_passes: int
    output_dir: str
    commands: tuple[CommandResult, ...]
    score_exit_codes: dict[str, int]
    usage: dict[str, int]
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["commands"] = [asdict(command) for command in self.commands]
        return payload


def discover_fixtures(root: Path, selected: str | None = None) -> tuple[UATFixture, ...]:
    """Discover fixture directories containing ordered ``spec_N.md`` inputs."""
    if not root.is_dir():
        raise SpecificationError(f"UAT fixtures directory does not exist: {root}")
    directories = (
        [root / selected] if selected else sorted(path for path in root.iterdir() if path.is_dir())
    )
    fixtures: list[UATFixture] = []
    for directory in directories:
        if not directory.is_dir():
            raise SpecificationError(f"Unknown UAT fixture: {directory.name}")
        specs = tuple(sorted(directory.glob("spec_*.md"), key=_spec_order))
        if not specs:
            raise SpecificationError(f"UAT fixture has no spec_N.md inputs: {directory}")
        config_path = directory / "uat.json"
        target = directory.name
        sources: tuple[Path, ...] = ()
        test_command: tuple[str, ...] = ()
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SpecificationError(
                    f"Invalid UAT fixture configuration: {config_path}"
                ) from exc
            target = str(config.get("target") or target).strip()
            raw_sources = config.get("sources", [])
            raw_test_command = config.get("test_command", [])
            if not isinstance(raw_sources, list) or not all(
                isinstance(item, str) and item.strip() for item in raw_sources
            ):
                raise SpecificationError(f"UAT fixture sources must be a list of paths: {config_path}")
            if not isinstance(raw_test_command, list) or not all(
                isinstance(item, str) and item for item in raw_test_command
            ):
                raise SpecificationError(
                    f"UAT fixture test_command must be an argv list: {config_path}"
                )
            resolved_sources: list[Path] = []
            for item in raw_sources:
                source = (directory / item).resolve()
                if not source.is_relative_to(directory.resolve()) or not source.is_file():
                    raise SpecificationError(f"Invalid UAT fixture source: {item}")
                resolved_sources.append(source)
            sources = tuple(resolved_sources)
            test_command = tuple(raw_test_command)
        if not target:
            raise SpecificationError(f"UAT fixture target is empty: {directory}")
        fixtures.append(UATFixture(directory.name, target, directory, specs, sources, test_command))
    if not fixtures:
        raise SpecificationError(f"No UAT fixtures found under: {root}")
    return tuple(fixtures)


def _spec_order(path: Path) -> tuple[int, str]:
    suffix = path.stem.removeprefix("spec_")
    try:
        return int(suffix), path.name
    except ValueError:
        return sys.maxsize, path.name


def subprocess_runner(
    argv: Sequence[str], cwd: Path, env: dict[str, str], output_dir: Path, label: str
) -> CommandResult:
    """Run one child Drydock command and persist its complete console output."""
    stdout_path = output_dir / f"{label}.stdout.log"
    stderr_path = output_dir / f"{label}.stderr.log"
    started = time.monotonic()
    proc = subprocess.run(
        list(argv),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed_ms = round((time.monotonic() - started) * 1000)
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    return CommandResult(
        argv=tuple(argv),
        returncode=proc.returncode,
        elapsed_ms=elapsed_ms,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )


def _usage_totals(records_path: Path) -> dict[str, int]:
    records, invalid = read_records(records_path)
    totals = {
        "calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "fresh_input_tokens": 0,
        "output_tokens": 0,
        "llm_elapsed_ms": 0,
        "invalid_records": invalid,
    }
    for record in records:
        job = record.get("job") if isinstance(record.get("job"), dict) else {}
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        total, cached, output = normalize_tokens(str(job.get("llm") or ""), stats)
        totals["calls"] += 1
        totals["input_tokens"] += total
        totals["cached_input_tokens"] += cached
        totals["fresh_input_tokens"] += max(total - cached, 0)
        totals["output_tokens"] += output
        try:
            totals["llm_elapsed_ms"] += int(stats.get("elapsed_ms") or 0)
        except (TypeError, ValueError):
            pass
    return totals


def run_fixture(
    fixture: UATFixture,
    run_root: Path,
    *,
    model: str,
    provider: str,
    effort: str | None = None,
    max_build_passes: int = DEFAULT_MAX_BUILD_PASSES,
    runner: Runner = subprocess_runner,
    on_event: Callable[[str], None] | None = None,
) -> UATResult:
    """Execute one initial build and each subsequent specification refit in isolation."""
    started = time.monotonic()
    case_root = run_root / fixture.name
    workspace = case_root / "workspace"
    build_root = case_root / "build"
    command_logs = case_root / "commands"
    for path in (workspace, build_root, command_logs):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DRYDOCK_WORKSPACE"] = str(workspace)
    env["DRYDOCK_BUILD_DIRECTORY"] = str(build_root)
    env["DRYDOCK_MODEL"] = model
    env["LLM_PROVIDER"] = provider
    if effort:
        env["DRYDOCK_EFFORT"] = effort
    env.pop("DRYDOCK_PARENT_TRANSCRIPT", None)

    commands: list[CommandResult] = []
    scores: dict[str, int] = {}
    build_passes = 0
    sequence = 0

    def execute(parts: Sequence[str], label: str, *, required: bool = True) -> CommandResult:
        nonlocal sequence
        sequence += 1
        argv = (sys.executable, "-m", "drydock", *parts)
        if on_event:
            on_event(f"{fixture.name}: {label}")
        result = runner(argv, workspace, env, command_logs, f"{sequence:02d}-{label}")
        commands.append(result)
        if required and result.returncode != 0:
            raise DrydockError(f"{fixture.name}: {label} exited {result.returncode}")
        return result

    def execute_test() -> None:
        if not fixture.test_command:
            return
        nonlocal sequence
        sequence += 1
        if on_event:
            on_event(f"{fixture.name}: test")
        result = runner(
            fixture.test_command,
            build_root / fixture.target,
            env,
            command_logs,
            f"{sequence:02d}-test",
        )
        commands.append(result)
        if result.returncode != 0:
            raise DrydockError(f"{fixture.name}: test exited {result.returncode}")

    def build_to_completion(stage: str) -> None:
        nonlocal build_passes
        stage_passes = 0
        while True:
            ready = execute(("status", fixture.target, "--ready"), f"{stage}-ready", required=False)
            if ready.returncode != 0:
                break
            stage_passes += 1
            build_passes += 1
            if stage_passes > max_build_passes:
                raise DrydockError(
                    f"{fixture.name}: exceeded {max_build_passes} build passes during {stage}"
                )
            execute(("build", fixture.target, "--override"), f"{stage}-build-{stage_passes}")
        execute(("status", fixture.target, "--check"), f"{stage}-complete")

    error = ""
    status = "passed"
    try:
        execute(("init", fixture.target), "init")
        execute(
            ("import", fixture.target, str(fixture.specifications[0]), "--format", "markdown"),
            "import-spec-1",
        )
        for index, source in enumerate(fixture.sources, start=1):
            execute(
                ("import", fixture.target, str(source), "--format", "markdown"),
                f"import-source-{index}",
            )
        execute(("analyze", fixture.target), "analyze")
        execute(("plan", fixture.target, "--override"), "plan")
        build_to_completion("initial")

        for index, specification in enumerate(fixture.specifications[1:], start=2):
            execute(
                (
                    "import",
                    fixture.target,
                    str(specification),
                    "--format",
                    "markdown",
                    "--update",
                ),
                f"import-spec-{index}",
            )
            execute(("refit", fixture.target, "--sources"), f"refit-spec-{index}")
            build_to_completion(f"refit-{index}")

        execute_test()

        for name, parts in (
            ("acceptance", ("score", "ac", fixture.target)),
            ("build-report", ("score", "build", fixture.target)),
            ("release", ("score", "release", fixture.target)),
        ):
            result = execute(parts, f"score-{name}", required=False)
            scores[name] = result.returncode
    except DrydockError as exc:
        status = "failed"
        error = str(exc)

    elapsed_ms = round((time.monotonic() - started) * 1000)
    result = UATResult(
        fixture=fixture.name,
        target=fixture.target,
        run_id=run_root.name,
        status=status,
        elapsed_ms=elapsed_ms,
        build_passes=build_passes,
        output_dir=str(case_root),
        commands=tuple(commands),
        score_exit_codes=scores,
        usage=_usage_totals(workspace / "logs" / "llm.jsonl"),
        error=error,
    )
    (case_root / "result.json").write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def render_summary(results: Sequence[UATResult]) -> str:
    lines = ["# Drydock UAT Summary", ""]
    for result in results:
        usage = result.usage
        lines.extend([
            f"## {result.fixture}: {result.status.upper()}",
            "",
            f"- Target: `{result.target}`",
            f"- Elapsed: {result.elapsed_ms / 1000:.1f}s",
            f"- Build passes: {result.build_passes}",
            f"- LLM calls: {usage['calls']}",
            f"- Tokens: input {usage['input_tokens']:,}; cached {usage['cached_input_tokens']:,}; "
            f"fresh {usage['fresh_input_tokens']:,}; output {usage['output_tokens']:,}",
            f"- LLM elapsed: {usage['llm_elapsed_ms'] / 1000:.1f}s",
            "- Advisory scores: "
            + ", ".join(f"{name}=exit {code}" for name, code in result.score_exit_codes.items()),
        ])
        if result.error:
            lines.append(f"- Failure: {result.error}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_uat(
    workspace: Path,
    *,
    selected: str | None,
    fixtures_root: Path,
    output_root: Path,
    model: str,
    provider: str,
    effort: str | None = None,
    max_build_passes: int = DEFAULT_MAX_BUILD_PASSES,
    runner: Runner = subprocess_runner,
    on_event: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> tuple[Path, tuple[UATResult, ...]]:
    """Run selected known projects and write aggregate JSON and Markdown reports."""
    del workspace  # retained in the contract to make caller path ownership explicit
    timestamp = now or datetime.now(UTC)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
    run_root = output_root / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    fixtures = discover_fixtures(fixtures_root, selected)
    results = tuple(
        run_fixture(
            fixture,
            run_root,
            model=model,
            provider=provider,
            effort=effort,
            max_build_passes=max_build_passes,
            runner=runner,
            on_event=on_event,
        )
        for fixture in fixtures
    )
    (run_root / "summary.json").write_text(
        json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_root / "SUMMARY.md").write_text(render_summary(results), encoding="utf-8")
    return run_root, results
