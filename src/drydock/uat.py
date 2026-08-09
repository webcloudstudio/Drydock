"""Project-level unattended acceptance runs for known Drydock fixtures."""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import IO

from drydock import technology_stack
from drydock.errors import DrydockError, SpecificationError
from drydock.llm_usage import normalize_tokens, read_records
from drydock.uat_console import StepSink
from drydock.uat_report import build_case_kit

DEFAULT_MAX_BUILD_PASSES = 25
#: Read size for the child output pump. Small enough that a chunk reaches the console promptly.
_STREAM_CHUNK_BYTES = 4096


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    elapsed_ms: int
    stdout_path: str
    stderr_path: str
    label: str = ""
    cwd: str = ""


@dataclass(frozen=True)
class UATFixture:
    name: str
    target: str
    root: Path
    sources: tuple[Path, ...]
    updates: tuple[Path, ...]
    test_command: tuple[str, ...]
    #: Optional ``TECHNOLOGY_STACK.md`` seeded into the Target after ``init``. A fixture
    #: that declares its stack removes the language choice from the model; one that does
    #: not lets ``analyze`` propose it as usual.
    stack: Path | None = None


Runner = Callable[[Sequence[str], Path, dict[str, str], Path, str], CommandResult]


def _relativize(value: object, base: Path) -> str:
    """Express a recorded path relative to ``base`` so a written report stays portable."""
    text = str(value or "")
    if not text:
        return text
    try:
        return Path(text).relative_to(base).as_posix()
    except ValueError:
        return text


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
    evidence_dir: str = ""
    environment: dict[str, str] = field(default_factory=dict)

    def to_dict(self, base: Path | None = None) -> dict[str, object]:
        """Serialize the result, rewriting absolute paths relative to ``base`` when given."""
        payload = asdict(self)
        payload["commands"] = [asdict(command) for command in self.commands]
        if base is None:
            return payload
        for key in ("output_dir", "evidence_dir"):
            payload[key] = _relativize(payload[key], base)
        for command in payload["commands"]:
            for key in ("stdout_path", "stderr_path", "cwd"):
                command[key] = _relativize(command[key], base)
        return payload


def _environment(model: str, provider: str, effort: str | None) -> dict[str, str]:
    """Capture the provenance a reader needs to judge whether a run is reproducible."""
    try:
        version = metadata.version("drydock")
    except metadata.PackageNotFoundError:  # editable checkout without installed metadata
        version = "unknown"
    commit = ""
    try:
        commit = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return {
        "drydock_version": version,
        "git_commit": commit,
        "provider": provider,
        "model": model,
        "effort": effort or "",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def _fixture_stack(directory: Path) -> Path | None:
    """Return the fixture's declared ``TECHNOLOGY_STACK.md``, validated, or ``None``.

    The technology stack is configuration, not a command-line decision: a fixture that
    must be built in a particular language ships the decision-of-record artifact itself.
    It is seeded into the Target between ``init`` and ``analyze``, where the existing
    never-overwrite contract makes it authoritative for the rest of the lifecycle.

    Validation is strict here because a typo would otherwise degrade silently into a
    missing context file at build time, long after the run stopped being cheap.
    """
    path = directory / technology_stack.FILENAME
    if not path.is_file():
        return None
    try:
        entries = technology_stack.parse(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecificationError(f"Unreadable UAT fixture technology stack: {path}") from exc
    if not entries:
        raise SpecificationError(f"UAT fixture technology stack declares no technologies: {path}")
    catalog = set(technology_stack.rigging_names())
    unknown = sorted({name for name in technology_stack.stack_files_from(entries)} - catalog)
    if unknown:
        raise SpecificationError(
            f"UAT fixture technology stack names unknown Rigging files: {', '.join(unknown)}"
        )
    return path


def discover_fixtures(root: Path, selected: str | None = None) -> tuple[UATFixture, ...]:
    """Discover the configured UAT kits under ``root``.

    A kit is a directory holding ``uat.json``. Sweeping the root skips anything else, because a
    kit's own ``runs/`` history and a published repository's supporting directories live beside
    the kits and are not themselves runnable. Naming a kit explicitly still errors when it has
    no configuration, so a typo is never silently ignored.
    """
    if not root.is_dir():
        raise SpecificationError(f"UAT kit directory does not exist: {root}")
    directories = (
        [root / selected]
        if selected
        else sorted(path for path in root.iterdir() if (path / "uat.json").is_file())
    )
    fixtures: list[UATFixture] = []
    for directory in directories:
        if not directory.is_dir():
            raise SpecificationError(f"Unknown UAT kit: {directory.name}")
        config_path = directory / "uat.json"
        if not config_path.is_file():
            raise SpecificationError(f"UAT kit has no uat.json: {directory}")
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SpecificationError(f"Invalid UAT fixture configuration: {config_path}") from exc
        if not isinstance(config, dict):
            raise SpecificationError(f"UAT fixture configuration must be an object: {config_path}")
        target = str(config.get("target") or directory.name).strip()
        raw_sources = config.get("sources")
        raw_updates = config.get("updates", [])
        raw_test_command = config.get("test_command")
        if (
            not isinstance(raw_sources, list)
            or not raw_sources
            or not all(isinstance(item, str) and item.strip() for item in raw_sources)
        ):
            raise SpecificationError(
                f"UAT fixture sources must be a nonempty list of paths: {config_path}"
            )
        if not isinstance(raw_updates, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_updates
        ):
            raise SpecificationError(f"UAT fixture updates must be a list of paths: {config_path}")
        if (
            not isinstance(raw_test_command, list)
            or not raw_test_command
            or not all(isinstance(item, str) and item for item in raw_test_command)
        ):
            raise SpecificationError(
                f"UAT fixture test_command must be a nonempty argv list: {config_path}"
            )

        def resolve_paths(items: list[str], field: str) -> tuple[Path, ...]:
            resolved: list[Path] = []
            for item in items:
                source = (directory / item).resolve()
                if not source.is_relative_to(directory.resolve()) or not source.is_file():
                    raise SpecificationError(f"Invalid UAT fixture {field} path: {item}")
                resolved.append(source)
            return tuple(resolved)

        sources = resolve_paths(raw_sources, "source")
        updates = resolve_paths(raw_updates, "update")
        source_names = [source.name for source in sources]
        if len(source_names) != len(set(source_names)):
            raise SpecificationError(
                f"UAT fixture sources collide after import flattening: {config_path}"
            )
        unknown_updates = sorted({update.name for update in updates} - set(source_names))
        if unknown_updates:
            raise SpecificationError(
                "UAT fixture updates must replace an imported basename: "
                + ", ".join(unknown_updates)
            )
        if not target:
            raise SpecificationError(f"UAT fixture target is empty: {directory}")
        fixtures.append(
            UATFixture(
                directory.name,
                target,
                directory,
                sources,
                updates,
                tuple(raw_test_command),
                _fixture_stack(directory),
            )
        )
    if not fixtures:
        raise SpecificationError(f"No UAT kits found under: {root}")
    return tuple(fixtures)


def _pump(
    pipe: IO[bytes], handle: IO[bytes], source: str, sink: StepSink | None
) -> threading.Thread:
    """Copy one child stream to its evidence log and, when watched, to the console.

    The log receives the child's bytes unaltered. The sink receives incrementally decoded text
    as each read completes, so a caller can display output while the command is still running.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def drain() -> None:
        try:
            while True:
                data = pipe.read(_STREAM_CHUNK_BYTES)
                if not data:
                    break
                handle.write(data)
                handle.flush()
                if sink is not None:
                    text = decoder.decode(data)
                    if text:
                        sink.chunk(source, text)
            if sink is not None:
                tail = decoder.decode(b"", True)
                if tail:
                    sink.chunk(source, tail)
        finally:
            pipe.close()

    return threading.Thread(target=drain, daemon=True)


def subprocess_runner(
    argv: Sequence[str],
    cwd: Path,
    env: dict[str, str],
    output_dir: Path,
    label: str,
    *,
    sink: StepSink | None = None,
) -> CommandResult:
    """Run one child Drydock command, persisting and optionally streaming its console output.

    Output is teed rather than captured: a UAT step can run for many minutes, and withholding
    its output until the process exits leaves the operator unable to distinguish progress from
    a stall.
    """
    stdout_path = output_dir / f"{label}.stdout.log"
    stderr_path = output_dir / f"{label}.stderr.log"
    if sink is not None:
        sink.step(argv, label)
    started = time.monotonic()
    proc = subprocess.Popen(  # noqa: S603 - argv is built by this module, never a shell string
        list(argv),
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    with stdout_path.open("wb") as out_handle, stderr_path.open("wb") as err_handle:
        assert proc.stdout is not None and proc.stderr is not None  # noqa: S101 - PIPE guarantee
        pumps = (
            _pump(proc.stdout, out_handle, "stdout", sink),
            _pump(proc.stderr, err_handle, "stderr", sink),
        )
        for pump in pumps:
            pump.start()
        returncode = proc.wait()
        for pump in pumps:
            pump.join()
    elapsed_ms = round((time.monotonic() - started) * 1000)
    if sink is not None:
        sink.finish(returncode, elapsed_ms)
    return CommandResult(
        argv=tuple(argv),
        returncode=returncode,
        elapsed_ms=elapsed_ms,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        label=label,
        cwd=str(cwd),
    )


def make_streaming_runner(sink: StepSink) -> Runner:
    """Bind ``sink`` to the standard runner so the pipeline stays unaware of the console."""

    def runner(
        argv: Sequence[str], cwd: Path, env: dict[str, str], output_dir: Path, label: str
    ) -> CommandResult:
        return subprocess_runner(argv, cwd, env, output_dir, label, sink=sink)

    return runner


def _file_evidence(path: Path, case_root: Path) -> dict[str, object]:
    """Describe one preserved evidence artifact without relying on absolute paths."""
    content = path.read_bytes()
    return {
        "path": path.relative_to(case_root).as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _collect_evidence(
    case_root: Path, workspace: Path, evidence_dir: Path, commands: Sequence[CommandResult]
) -> Path:
    """Collect command and LLM transcripts into a stable, indexed UAT evidence bundle."""
    llm_logs = workspace / "logs"
    prompts_dir = evidence_dir / "prompts"
    outputs_dir = evidence_dir / "prompt_outputs"
    raw_dir = evidence_dir / "provider_raw"
    for path in (prompts_dir, outputs_dir, raw_dir):
        path.mkdir(parents=True, exist_ok=True)

    llm_artifacts: list[dict[str, object]] = []
    artifact_groups = (
        ("prompt", "*.prompt.md", prompts_dir),
        ("prompt_output", "*.output.txt", outputs_dir),
        ("provider_raw", "*.raw.jsonl", raw_dir),
    )
    if llm_logs.is_dir():
        for kind, pattern, destination in artifact_groups:
            for source in sorted(llm_logs.glob(pattern)):
                target = destination / source.name
                shutil.copyfile(source, target)
                artifact = _file_evidence(target, case_root)
                artifact["kind"] = kind
                llm_artifacts.append(artifact)
        records = llm_logs / "llm.jsonl"
        if records.is_file():
            target = evidence_dir / "llm.jsonl"
            shutil.copyfile(records, target)
            artifact = _file_evidence(target, case_root)
            artifact["kind"] = "llm_execution_records"
            llm_artifacts.append(artifact)

    command_artifacts: list[dict[str, object]] = []
    for index, command in enumerate(commands, start=1):
        entry: dict[str, object] = {
            "sequence": index,
            "label": command.label,
            "argv": list(command.argv),
            "cwd": command.cwd,
            "returncode": command.returncode,
            "elapsed_ms": command.elapsed_ms,
        }
        for stream, value in (("stdout", command.stdout_path), ("stderr", command.stderr_path)):
            path = Path(value)
            if path.is_file() and path.is_relative_to(case_root):
                entry[stream] = _file_evidence(path, case_root)
        command_artifacts.append(entry)

    manifest = {
        "schema_version": 1,
        "commands": command_artifacts,
        "llm_artifacts": llm_artifacts,
    }
    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# UAT Evidence",
        "",
        "The manifest records relative paths, byte counts, and SHA-256 hashes for the preserved evidence.",
        "",
        f"- Commands: {len(command_artifacts)} (stdout and stderr captured separately)",
        f"- Prompts: {sum(item['kind'] == 'prompt' for item in llm_artifacts)}",
        f"- Prompt outputs: {sum(item['kind'] == 'prompt_output' for item in llm_artifacts)}",
        f"- Provider raw transcripts: {sum(item['kind'] == 'provider_raw' for item in llm_artifacts)}",
        "- Machine index: `manifest.json`",
        "",
    ]
    (evidence_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return manifest_path


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


def seed_technology_stack(fixture: UATFixture, workspace: Path) -> Path | None:
    """Place the fixture's declared stack in the Target before ``analyze`` proposes one.

    ``analyze`` never overwrites an existing ``TECHNOLOGY_STACK.md``, so seeding it here
    makes the fixture's declaration the decision of record and ``plan`` reads it as the
    sole stack authority. Returns the written path, or ``None`` when the fixture is
    content to let ``analyze`` choose.
    """
    if fixture.stack is None:
        return None
    target_dir = workspace / "targets" / fixture.target
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / technology_stack.FILENAME
    shutil.copyfile(fixture.stack, destination)
    return destination


def run_fixture(
    fixture: UATFixture,
    case_root: Path,
    *,
    run_id: str = "",
    model: str,
    provider: str,
    effort: str | None = None,
    max_build_passes: int = DEFAULT_MAX_BUILD_PASSES,
    runner: Runner = subprocess_runner,
    on_event: Callable[[str], None] | None = None,
) -> UATResult:
    """Execute one initial build and each subsequent specification refit in isolation.

    ``case_root`` is the kit's own run directory — ``<kit>/runs/<run-id>/`` — so a kit and its
    complete run history form one self-contained tree that can be published as its own repository.
    """
    started = time.monotonic()
    started_at = datetime.now(UTC)
    workspace = case_root / "workspace"
    build_root = case_root / "build"
    source_root = case_root / "sources"
    evidence_dir = case_root / "evidence"
    command_logs = evidence_dir / "commands"
    for path in (workspace, build_root, source_root, evidence_dir, command_logs):
        path.mkdir(parents=True, exist_ok=True)
    for source in fixture.sources:
        shutil.copyfile(source, source_root / source.name)

    env = os.environ.copy()
    env["DRYDOCK_WORKSPACE"] = str(workspace)
    env["DRYDOCK_BUILD_DIRECTORY"] = str(build_root)
    env["DRYDOCK_MODEL"] = model
    env["LLM_PROVIDER"] = provider
    # Mark every child command as part of a UAT run. A UAT measures what Drydock delivers at
    # the full repair budget, so the build's interactive stall short-circuit is suppressed.
    env["DRYDOCK_UAT"] = "1"
    # Child output is teed to the console as it arrives. Block buffering into a pipe would
    # withhold it until the step exits, which is exactly what the streaming runner prevents.
    env["PYTHONUNBUFFERED"] = "1"
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

    def capture_status(stage: str) -> None:
        """Preserve all supported status views without turning a snapshot into a gate."""
        execute(("build", "status", fixture.target), f"{stage}-build-status", required=False)
        execute(("status", fixture.target), f"{stage}-target-status", required=False)
        execute(("status",), f"{stage}-workspace-status", required=False)

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
        seed_technology_stack(fixture, workspace)
        execute(
            ("import", fixture.target, str(source_root), "--format", "markdown"),
            "import-sources",
        )
        execute(("analyze", fixture.target), "analyze")
        execute(("plan", fixture.target, "--override"), "plan")
        capture_status("after-plan")
        build_to_completion("initial")
        capture_status("after-initial-build")

        for index, update in enumerate(fixture.updates, start=1):
            shutil.copyfile(update, source_root / update.name)
            execute(("import", fixture.target, "--update"), f"import-update-{index}")
            execute(("refit", fixture.target, "--sources"), f"refit-update-{index}")
            capture_status(f"after-refit-{index}")
            build_to_completion(f"refit-{index}")
            capture_status(f"after-refit-{index}-build")

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

    _collect_evidence(case_root, workspace, evidence_dir, commands)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    environment = _environment(model, provider, effort)
    environment["started_at"] = started_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    environment["finished_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    result = UATResult(
        fixture=fixture.name,
        target=fixture.target,
        run_id=run_id or case_root.name,
        status=status,
        elapsed_ms=elapsed_ms,
        build_passes=build_passes,
        output_dir=str(case_root),
        commands=tuple(commands),
        score_exit_codes=scores,
        usage=_usage_totals(workspace / "logs" / "llm.jsonl"),
        error=error,
        evidence_dir=str(evidence_dir),
        environment=environment,
    )
    (case_root / "result.json").write_text(
        json.dumps(result.to_dict(case_root), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # build_case_kit writes README.md and index.html from result.json, so `drydock uat --report`
    # reproduces byte-identical reports for a run it did not execute.
    build_case_kit(case_root)
    return result


def render_summary(results: Sequence[UATResult], base: Path | None = None) -> str:
    lines = [
        "# Drydock UAT Summary",
        "",
        "Open `index.html` for the linked proof kit; verify it with `sha256sum -c SHA256SUMS`.",
        "",
    ]
    for result in results:
        usage = result.usage
        lines.extend([
            f"## {result.fixture}: {result.status.upper()}",
            "",
            f"- Target: `{result.target}`",
            f"- Elapsed: {result.elapsed_ms / 1000:.1f}s",
            f"- Build passes: {result.build_passes}",
            f"- Receipt: `{_relativize(result.output_dir, base) if base else result.output_dir}"
            "/index.html`",
            f"- Evidence: `{_relativize(result.evidence_dir, base) if base else result.evidence_dir}`",
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
    uat_root: Path,
    model: str,
    provider: str,
    effort: str | None = None,
    max_build_passes: int = DEFAULT_MAX_BUILD_PASSES,
    runner: Runner = subprocess_runner,
    on_event: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> tuple[str, tuple[UATResult, ...]]:
    """Run the selected kits, each into its own ``<kit>/runs/<run-id>/`` directory.

    Every kit owns its inputs and its complete run history, so ``<uat-root>/<Kit>/`` can be
    published as an independent, self-runnable repository. One invocation stamps every kit it
    runs with the same run id, which is what lets separate repositories be correlated later.
    """
    del workspace  # retained in the contract to make caller path ownership explicit
    timestamp = now or datetime.now(UTC)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
    fixtures = discover_fixtures(uat_root, selected)
    results: list[UATResult] = []
    for fixture in fixtures:
        case_root = fixture.root / "runs" / run_id
        case_root.mkdir(parents=True, exist_ok=False)
        results.append(
            run_fixture(
                fixture,
                case_root,
                run_id=run_id,
                model=model,
                provider=provider,
                effort=effort,
                max_build_passes=max_build_passes,
                runner=runner,
                on_event=on_event,
            )
        )
    return run_id, tuple(results)
