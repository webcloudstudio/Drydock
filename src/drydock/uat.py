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

from drydock import sea_trials, technology_stack
from drydock.acceptance_contract import AcceptanceContract, contract_from_config, write_contract
from drydock.build_report import build_score_report
from drydock.errors import DrydockError, SpecificationError
from drydock.llm_usage import normalize_tokens, read_records
from drydock.uat_console import StepSink
from drydock.uat_report import build_case_kit, local_run_window, write_kit_index

DEFAULT_MAX_BUILD_PASSES = 25
#: Repairs one build block may spend under UAT, above the interactive default of 3. Progress is
#: what earns each pass — two consecutive flat passes end the block well before this — so the
#: bound only decides how much genuine convergence Drydock is willing to pay for. It is a block
#: bound, not a step bound: the repair loop runs once per ``BuildUnit``, and a unit is one block.
DEFAULT_UAT_REPAIR_ATTEMPTS = 6
#: Read size for the child output pump. Small enough that a chunk reaches the console promptly.
_STREAM_CHUNK_BYTES = 4096

#: Ordered resumable entry points. A run directory holds its own Drydock workspace and build
#: tree, so a lifecycle that failed late can be re-entered at a named stage instead of paying
#: for every earlier LLM pass again. This is a development affordance: a resumed run reuses
#: whatever the prior attempt left on disk and is therefore not a clean-room measurement.
STAGES = ("init", "import", "analyze", "plan", "build", "refit", "test", "score")


def stage_index(name: str) -> int:
    """Return the ordinal of a resumable stage, rejecting an unknown name."""
    try:
        return STAGES.index(name)
    except ValueError:
        raise SpecificationError(
            f"Unknown UAT stage {name!r}; expected one of: {', '.join(STAGES)}"
        ) from None


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
    #: Optional frozen ``SEA_TRIALS.md`` seeded into the Target after ``init``. Without it the
    #: model authors the exam it is then graded on, so every run is a fresh random draw of
    #: acceptance criteria and no two runs measure the same thing — which is why a fixture could
    #: stop passing without changing. With it, every run is graded against the same exam and a
    #: regression is finally detectable.
    sea_trials: Path | None = None
    acceptance: AcceptanceContract = field(default_factory=AcceptanceContract)
    #: The verdict this fixture is expected to produce. UAT does not ask "did the fixture project
    #: pass" — it asks "did Drydock reach the correct conclusion about it". A fixture with a known
    #: product defect that Drydock correctly reports as FAILED is a UAT *pass*: the harness worked.
    #: Declared as ``"expect": {"verdict": "..."}`` in ``uat.json``; defaults to PASSED.
    expected_verdict: str = "PASSED"


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
    #: Stages that failed but did not stop the run. A build that exhausts its repair budget is a
    #: terminal state, not an aborted one: the work it produced is exactly what the remaining
    #: stages measure, so the run continues and reports ``degraded`` rather than discarding the
    #: measurement it was launched to take.
    degraded: tuple[str, ...] = ()
    #: Stage this run was re-entered at, empty for a run executed from the beginning. A resumed
    #: run reuses prior state, so its receipt must not present itself as a clean lifecycle.
    resumed_from: str = ""
    #: Whether Drydock ran the lifecycle without an infrastructure fault: PASS or ERROR.
    execution_status: str = "PASS"
    #: Whether the product passed governed acceptance: PASS, FAIL, or NOT_RUN.
    acceptance_status: str = "NOT_RUN"
    #: The verdict the fixture declared it should produce, and the one it did. ``status`` is a
    #: comparison of these two, not a copy of the observed one: a fixture with a known defect is
    #: expected to report FAILED, and reporting it is Drydock working.
    expected_verdict: str = "PASSED"
    observed_verdict: str = "PASSED"
    #: Project guardrails the release gate could not settle either way. The run passed — nothing
    #: demonstrated a violation — but each names a prohibition a human must confirm by hand
    #: before the build is released. Reported, never a failure.
    attestations: tuple[str, ...] = ()
    #: Story-acceptance outcomes for the run, three-valued. ``product_defects`` counts assertions
    #: that exercised the built code and found it wrong; ``harness_defects`` counts assertions
    #: that never reached it. A reader distinguishes "Drydock produced a bad artifact" from
    #: "Drydock's checker rejected a good one" from this field alone.
    assertions: dict[str, int] = field(default_factory=dict)

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


#: The terminal verdicts a run can reach. ``PENDING`` is declared here so a fixture can name it,
#: but nothing produces it yet: the release gate still settles every criterion PASS or FAIL.
VALID_EXPECTED_VERDICTS = ("PASSED", "PENDING", "FAILED", "ERROR")


def _expected_verdict(raw: object, *, where: str) -> str:
    """Read the fixture's declared expected verdict, defaulting to ``PASSED``."""
    if raw is None:
        return "PASSED"
    if not isinstance(raw, dict):
        raise SpecificationError(f"UAT fixture expect must be an object: {where}")
    value = raw.get("verdict", "PASSED")
    if not isinstance(value, str) or value.strip().upper() not in VALID_EXPECTED_VERDICTS:
        raise SpecificationError(
            f"UAT fixture expect.verdict must be one of "
            f"{', '.join(VALID_EXPECTED_VERDICTS)}: {where}"
        )
    return value.strip().upper()


def _observed_verdict(execution_status: str, acceptance_status: str) -> str:
    """Fold the run's two status views into the single verdict a fixture is judged against.

    An infrastructure fault outranks everything: if Drydock could not run the lifecycle it has
    said nothing about the product, which is ERROR and not FAILED. A release gate that never ran
    is the same case — no verdict was produced, so none can be compared.
    """
    if execution_status != "PASS":
        return "ERROR"
    if acceptance_status == "PASS":
        return "PASSED"
    if acceptance_status == "FAIL":
        return "FAILED"
    return "ERROR"


def _fixture_sea_trials(path: Path | None) -> Path | None:
    """Return the fixture's frozen ``SEA_TRIALS.md``, validated, or ``None``.

    Validation is strict for the same reason the stack's is: a contract that will not parse
    degrades into a missing gate long after the run stopped being cheap, and the run would then
    measure nothing while reporting a verdict.
    """
    if path is None:
        return None
    try:
        sea_trials.parse_sea_trials_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecificationError(f"Unreadable UAT fixture Sea Trials: {path}") from exc
    except SpecificationError as exc:
        raise SpecificationError(f"Invalid UAT fixture Sea Trials {path}: {exc}") from exc
    return path


def _fixture_stack(path: Path | None) -> Path | None:
    """Return the fixture's declared ``TECHNOLOGY_STACK.md``, validated, or ``None``.

    The technology stack is configuration, not a command-line decision: a fixture that
    must be built in a particular language ships the decision-of-record artifact itself.
    It is seeded into the Target between ``init`` and ``analyze``, where the existing
    never-overwrite contract makes it authoritative for the rest of the lifecycle.

    Validation is strict here because a typo would otherwise degrade silently into a
    missing context file at build time, long after the run stopped being cheap.
    """
    if path is None:
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
        raw_acceptance = config.get("acceptance")
        raw_sea_trials = config.get("sea_trials")
        raw_stack = config.get("technology_stack")
        expected_verdict = _expected_verdict(config.get("expect"), where=str(config_path))
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

        def resolve_optional_path(value: object, field: str) -> Path | None:
            if value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                raise SpecificationError(f"UAT fixture {field} must be a path: {config_path}")
            return resolve_paths([value], field)[0]

        sources = resolve_paths(raw_sources, "source")
        updates = resolve_paths(raw_updates, "update")
        declared_sea_trials = resolve_optional_path(raw_sea_trials, "sea_trials")
        declared_stack = resolve_optional_path(raw_stack, "technology_stack")
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
                _fixture_stack(declared_stack),
                _fixture_sea_trials(declared_sea_trials),
                contract_from_config(raw_acceptance, where=str(config_path)),
                expected_verdict,
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


def _release_attestations(target_dir: Path) -> tuple[str, ...]:
    """Return the unproven guardrails the release gate handed back for manual verification.

    Read from the Target's own score evidence rather than the console stream, so a resumed or
    re-reported run recovers the same list. A run that never reached ``score release``, or an
    older record predating the field, simply has none.
    """
    record_path = target_dir / "evidence" / "score-release.json"
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    items = payload.get("attestations")
    return tuple(str(item) for item in items) if isinstance(items, list) else ()


def _assertion_outcomes(target_dir: Path, target: str, records_path: Path) -> dict[str, int]:
    """Return the run's PASS/FAIL/UNVERIFIED assertion tally and its defect attribution.

    This is the field that tells the two failure modes apart without reading a log. A FAIL is
    evidence about the product Drydock built. An UNVERIFIED is evidence about Drydock's own kit:
    the assertion never reached the code under test, so it says nothing about the build. The two
    need opposite fixes, and ``status: failed`` alone cannot distinguish them.
    """
    empty = {"passed": 0, "failed": 0, "unverified": 0, "product_defects": 0, "harness_defects": 0}
    try:
        report = build_score_report(target, target_dir, records_path=records_path)
    except (OSError, ValueError):
        return empty
    passed = report.passed_checks
    unverified = report.unverified_checks
    failed = max(report.total_checks - passed, 0)
    return {
        "passed": passed,
        "failed": failed,
        "unverified": unverified,
        "product_defects": failed,
        "harness_defects": unverified,
    }


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


def seed_sea_trials(fixture: UATFixture, workspace: Path) -> Path | None:
    """Place the fixture's frozen Sea Trials in the Target before ``analyze`` authors any.

    ``analyze`` never overwrites an existing ``SEA_TRIALS.md``, so seeding it here makes the
    fixture's contract the exam for the whole run. Returns the written path, or ``None`` when
    the fixture is content to let ``analyze`` generate criteria — which is the right choice for
    a real Target, where generating them is the product.
    """
    if fixture.sea_trials is None:
        return None
    target_dir = workspace / "targets" / fixture.target
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / sea_trials.FILENAME
    shutil.copyfile(fixture.sea_trials, destination)
    return destination


def seed_acceptance_contract(fixture: UATFixture, workspace: Path) -> Path | None:
    """Place the fixture's governed acceptance commands in the Target before the build.

    This is the fixture acting as Commander. The contract is the only thing in the run that can
    close a story ``closed/verified`` or fail the release, and nothing the model writes can
    reach it — ``ACCEPTANCE.json`` is not a Blueprint artifact and no LLM-assisted command emits
    it. UAT populates the same target-level contract the build and scoring engines read for a
    real Target, so the two cannot drift apart.
    """
    if not fixture.acceptance.declared:
        return None
    target_dir = workspace / "targets" / fixture.target
    target_dir.mkdir(parents=True, exist_ok=True)
    return write_contract(target_dir, fixture.acceptance)


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


def _next_sequence(command_logs: Path) -> int:
    """Return the highest recorded step number in ``command_logs``.

    A resumed run appends to the same evidence directory, so its numbering continues past the
    prior attempt rather than overwriting logs the earlier failure produced.
    """
    highest = 0
    if not command_logs.is_dir():
        return highest
    for path in command_logs.glob("*.log"):
        prefix = path.name.split("-", 1)[0]
        if prefix.isdigit():
            highest = max(highest, int(prefix))
    return highest


def _prior_run(case_root: Path) -> tuple[tuple[CommandResult, ...], int]:
    """Load a prior attempt's commands and build-pass count from its ``result.json``.

    Carrying the earlier commands forward keeps the receipt an honest record of everything the
    run directory actually executed, including the failure that made a resume necessary.
    """
    path = case_root / "result.json"
    if not path.is_file():
        return (), 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecificationError(f"Unreadable prior UAT result: {path}") from exc
    if not isinstance(payload, dict):
        raise SpecificationError(f"Prior UAT result must be an object: {path}")

    def absolute(value: object) -> str:
        text = str(value or "")
        if not text:
            return text
        candidate = Path(text)
        return text if candidate.is_absolute() else str(case_root / candidate)

    commands = []
    for item in payload.get("commands") or []:
        if not isinstance(item, dict):
            continue
        commands.append(
            CommandResult(
                argv=tuple(str(part) for part in item.get("argv") or ()),
                returncode=int(item.get("returncode") or 0),
                elapsed_ms=int(item.get("elapsed_ms") or 0),
                stdout_path=absolute(item.get("stdout_path")),
                stderr_path=absolute(item.get("stderr_path")),
                label=str(item.get("label") or ""),
                cwd=absolute(item.get("cwd")),
            )
        )
    try:
        passes = int(payload.get("build_passes") or 0)
    except (TypeError, ValueError):
        passes = 0
    return tuple(commands), passes


def run_sort_key(run_id: str) -> str:
    """Order run identifiers chronologically across identifier formats.

    Run identifiers are UTC timestamps, so lexical order is chronological order — except
    that the retired ``20260809T204459.901240Z`` form and the current ``20260809.204459``
    form punctuate differently. Comparing the digits alone is chronological for both.
    """
    return "".join(character for character in run_id if character.isdigit())


def resolve_run_dir(fixture: UATFixture, run: str | None = None) -> Path:
    """Return the run directory a resume re-enters: ``run`` when named, else the newest."""
    runs = fixture.root / "runs"
    if run:
        candidate = runs / run
        if not candidate.is_dir():
            raise SpecificationError(f"No such run for kit {fixture.name}: {candidate}")
        return candidate
    existing = (
        sorted(
            (path for path in runs.iterdir() if (path / "result.json").is_file()),
            key=lambda path: run_sort_key(path.name),
        )
        if runs.is_dir()
        else []
    )
    if not existing:
        raise SpecificationError(f"No completed run to resume for kit {fixture.name}: {runs}")
    return existing[-1]


#: The Target artifact each resumable stage consumes, and the stage that produces it. A resume
#: into a stage whose input the prior attempt never produced would otherwise fail several
#: commands later with a message about the missing artifact rather than the wrong entry point.
_STAGE_PREREQUISITES: dict[str, tuple[str, str]] = {
    "import": ("METADATA.md", "init"),
    "analyze": ("METADATA.md", "init"),
    "plan": ("ANALYSIS.md", "analyze"),
    "build": ("MANIFEST.md", "plan"),
    "refit": ("MANIFEST.md", "plan"),
    "test": ("MANIFEST.md", "plan"),
    "score": ("MANIFEST.md", "plan"),
}


def verify_resume_prerequisite(fixture: UATFixture, case_root: Path, start_stage: str) -> None:
    """Reject a resume whose entry stage has no input, naming the stage that produces it."""
    required = _STAGE_PREREQUISITES.get(start_stage)
    if required is None:
        return
    artifact, producer = required
    path = case_root / "workspace" / "targets" / fixture.target / artifact
    if path.is_file():
        return
    raise SpecificationError(
        f"Cannot resume {fixture.name} at {start_stage!r}: {artifact} does not exist in "
        f"{case_root.name}. Resume at {producer!r} instead."
    )


def run_fixture(
    fixture: UATFixture,
    case_root: Path,
    *,
    run_id: str = "",
    start_stage: str = "init",
    model: str,
    provider: str,
    effort: str | None = None,
    max_build_passes: int = DEFAULT_MAX_BUILD_PASSES,
    repair_attempts: int = DEFAULT_UAT_REPAIR_ATTEMPTS,
    runner: Runner = subprocess_runner,
    on_event: Callable[[str], None] | None = None,
) -> UATResult:
    """Execute one initial build and each subsequent specification refit in isolation.

    ``case_root`` is the kit's own run directory — ``<kit>/runs/<run-id>/`` — so a kit and its
    complete run history form one self-contained tree that can be published as its own repository.

    ``start_stage`` re-enters an existing run directory at a named stage, reusing the workspace,
    Blueprint, and build tree the earlier attempt produced.
    """
    started = time.monotonic()
    started_at = datetime.now(UTC)
    start = stage_index(start_stage)
    if start:
        verify_resume_prerequisite(fixture, case_root, start_stage)
    workspace = case_root / "workspace"
    build_root = case_root / "build"
    source_root = case_root / "sources"
    input_root = case_root / "inputs"
    evidence_dir = case_root / "evidence"
    command_logs = evidence_dir / "commands"
    for path in (workspace, build_root, source_root, input_root, evidence_dir, command_logs):
        path.mkdir(parents=True, exist_ok=True)
    # Resuming past `import` must not restore the base sources: an update already applied to the
    # bundle is part of the state the resumed stage is expected to see.
    if start <= stage_index("import"):
        for source in fixture.sources:
            shutil.copyfile(source, source_root / source.name)
    if start <= stage_index("init"):
        for lifecycle_input in (fixture.sea_trials, fixture.stack):
            if lifecycle_input is not None:
                shutil.copyfile(lifecycle_input, input_root / lifecycle_input.name)

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

    prior_commands, prior_passes = _prior_run(case_root) if start else ((), 0)
    commands: list[CommandResult] = list(prior_commands)
    scores: dict[str, int] = {}
    build_passes = prior_passes
    sequence = _next_sequence(command_logs) if start else 0

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
        if result.returncode == 0:
            return
        # The scoring command is the run's headline measurement, and the scores that follow it
        # describe the same application. Record the verdict and let them run: a degraded build
        # is expected to fail here, and a clean build that fails here still fails the run.
        if degraded:
            degraded.append(f"test exited {result.returncode}")
        else:
            test_failures.append(f"{fixture.name}: test exited {result.returncode}")

    def capture_status(stage: str) -> None:
        """Preserve all supported status views without turning a snapshot into a gate."""
        execute(("build", "status", fixture.target), f"{stage}-build-status", required=False)
        execute(("status", fixture.target), f"{stage}-target-status", required=False)
        execute(("status",), f"{stage}-workspace-status", required=False)

    def build_to_completion(stage: str) -> None:
        """Build until nothing is ready, recording — not raising on — a terminal build failure.

        A build that exhausts its repair budget has reached its terminal state. Stopping the run
        there discards the measurement the UAT exists to take: the partial application, the
        scores over it, and the test command's verdict are all still meaningful, and are the only
        record of how far Drydock actually got. So the stage is marked degraded and the lifecycle
        continues to scoring.
        """
        nonlocal build_passes
        stage_passes = 0
        stage_degraded = False
        while True:
            ready = execute(("status", fixture.target, "--ready"), f"{stage}-ready", required=False)
            if ready.returncode != 0:
                break
            stage_passes += 1
            build_passes += 1
            if stage_passes > max_build_passes:
                degraded.append(
                    f"{stage}: exceeded {max_build_passes} build passes without completing"
                )
                stage_degraded = True
                break
            built = execute(
                (
                    "build",
                    fixture.target,
                    "--override",
                    "--repair-attempts",
                    str(repair_attempts),
                ),
                f"{stage}-build-{stage_passes}",
                required=False,
            )
            if built.returncode != 0:
                degraded.append(f"{stage}-build-{stage_passes} exited {built.returncode}")
                stage_degraded = True
                break
        # ``--check`` is the completion gate. Once the stage is known incomplete it is a status
        # snapshot, not a verdict, and failing the run on it would restate the degradation.
        execute(
            ("status", fixture.target, "--check"),
            f"{stage}-complete",
            required=not stage_degraded,
        )

    error = ""
    status = "passed"
    degraded: list[str] = []
    test_failures: list[str] = []
    try:
        if start <= stage_index("init"):
            execute(("init", fixture.target), "init")
            seed_technology_stack(fixture, workspace)
            seed_sea_trials(fixture, workspace)
            seed_acceptance_contract(fixture, workspace)
        if start <= stage_index("import"):
            execute(
                ("import", fixture.target, str(source_root), "--format", "markdown"),
                "import-sources",
            )
        if start <= stage_index("analyze"):
            execute(("analyze", fixture.target), "analyze")
        if start <= stage_index("plan"):
            execute(("plan", fixture.target, "--override"), "plan")
            capture_status("after-plan")
        if start <= stage_index("build"):
            build_to_completion("initial")
            capture_status("after-initial-build")

        # A refit re-specifies work against a build that completed. Running it over a terminal
        # partial build measures nothing and costs a full LLM pass, and its own `import --update`
        # and `refit` steps are required steps — a failure there would raise and rewrite the run
        # as ``failed``, destroying the degraded verdict this stage exists to preserve.
        if start <= stage_index("refit") and not degraded:
            for index, update in enumerate(fixture.updates, start=1):
                shutil.copyfile(update, source_root / update.name)
                execute(("import", fixture.target, "--update"), f"import-update-{index}")
                execute(("refit", fixture.target, "--sources"), f"refit-update-{index}")
                capture_status(f"after-refit-{index}")
                build_to_completion(f"refit-{index}")
                capture_status(f"after-refit-{index}-build")

        if start <= stage_index("test"):
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

    # Two independent verdicts, because they answer different questions and one must not be
    # able to launder the other. ``execution_status`` asks whether Drydock itself ran the
    # lifecycle: a crashed command, a skipped stage, an unreachable harness. ``acceptance_status``
    # asks whether the product passed its governed acceptance. A product failure is not an
    # infrastructure error — but an infrastructure error must still stop the run reading as a
    # pass, which a single status derived from the final command's exit code would allow.
    execution_status = "ERROR" if (status == "failed" or degraded) else "PASS"
    if test_failures:
        acceptance_status = "FAIL"
    elif scores.get("release") is None:
        acceptance_status = "NOT_RUN"
    else:
        acceptance_status = "PASS" if scores.get("release") == 0 else "FAIL"
    if status != "failed" and test_failures:
        status = "failed"
        error = test_failures[0]
    elif status != "failed" and degraded:
        # Every stage ran; one of them ended below completion. The run is a measurement with a
        # named shortfall, not an aborted run and not a clean pass.
        status = "degraded"
        error = "; ".join(degraded)
    if status == "passed" and not (execution_status == "PASS" and acceptance_status == "PASS"):
        status = "failed" if acceptance_status == "FAIL" else "degraded"
        error = error or f"execution {execution_status}, acceptance {acceptance_status}"

    # The fixture's own question, asked last: did Drydock reach the conclusion this fixture was
    # built to elicit? A fixture carrying a known product defect expects FAILED, and Drydock
    # naming that defect is the harness working — so the run passes. Reported failures stay in
    # ``error`` and ``acceptance_status``, because a passing UAT run that contains a demonstrated
    # product failure must still say what the failure was.
    observed_verdict = _observed_verdict(execution_status, acceptance_status)
    expected_verdict = fixture.expected_verdict
    if observed_verdict == expected_verdict and execution_status == "PASS":
        status = "passed"
    elif status == "passed":
        status = "failed"
        error = error or f"expected verdict {expected_verdict}, observed {observed_verdict}"

    attestations = _release_attestations(workspace / "targets" / fixture.target)
    assertions = _assertion_outcomes(
        workspace / "targets" / fixture.target,
        fixture.target,
        workspace / "logs" / "llm.jsonl",
    )
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
        resumed_from=start_stage if start else "",
        degraded=tuple(degraded),
        execution_status=execution_status,
        acceptance_status=acceptance_status,
        expected_verdict=expected_verdict,
        observed_verdict=observed_verdict,
        attestations=attestations,
        assertions=assertions,
    )
    (case_root / "result.json").write_text(
        json.dumps(result.to_dict(case_root), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # build_case_kit writes README.md and index.html from result.json, so `drydock uat --report`
    # reproduces byte-identical reports for a run it did not execute.
    build_case_kit(case_root)
    # The kit landing page indexes the runs, so a completed run must appear on it without
    # requiring a separate `drydock uat --report`.
    write_kit_index(case_root.parent.parent)
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
            f"- Execution: {result.execution_status} · Acceptance: {result.acceptance_status}",
            f"- Verdict: expected {result.expected_verdict}, observed {result.observed_verdict}",
            f"- Target: `{result.target}`",
            f"- Run: `{result.run_id}`",
            f"- Ran: {local_run_window(result.environment)}",
            f"- Elapsed: {result.elapsed_ms / 1000:.1f}s",
            f"- Build passes: {result.build_passes}",
            f"- Receipt: `{_relativize(result.output_dir, base) if base else result.output_dir}"
            "/index.html`",
            f"- Evidence: `{_relativize(result.evidence_dir, base) if base else result.evidence_dir}`",
            f"- LLM calls: {usage['calls']}",
            f"- Tokens: cached {usage['cached_input_tokens']:,}; "
            f"uncached {usage['fresh_input_tokens']:,}; output {usage['output_tokens']:,}",
            f"- LLM elapsed: {usage['llm_elapsed_ms'] / 1000:.1f}s",
            "- Advisory scores: "
            + ", ".join(f"{name}=exit {code}" for name, code in result.score_exit_codes.items()),
        ])
        if result.error:
            # A kit that expects FAILED passes by reporting a product failure, so the detail is
            # labelled for what it is rather than as a failure of the run.
            label = "Reported" if result.status == "passed" else "Failure"
            lines.append(f"- {label}: {result.error}")
        if result.attestations:
            # The kit passed. These are prohibitions the release gate could not settle from
            # evidence, and the operator reading this summary is the one who must settle them,
            # so they are named here and not left to the written report alone.
            lines.extend([
                "",
                "### Manual verification required",
                "",
                "The release gate completed. It could not settle the following project "
                "guardrails from evidence; each needs a manual test before release.",
                "",
            ])
            lines.extend(f"- {item}" for item in result.attestations)
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
    repair_attempts: int = DEFAULT_UAT_REPAIR_ATTEMPTS,
    runner: Runner = subprocess_runner,
    on_event: Callable[[str], None] | None = None,
    now: datetime | None = None,
    start_stage: str = "init",
    run: str | None = None,
) -> tuple[str, tuple[UATResult, ...]]:
    """Run the selected kits, each into its own ``<kit>/runs/<run-id>/`` directory.

    Every kit owns its inputs and its complete run history, so ``<uat-root>/<Kit>/`` can be
    published as an independent, self-runnable repository. One invocation stamps every kit it
    runs with the same run id, which is what lets separate repositories be correlated later.

    ``start_stage`` (with optional ``run``) resumes an existing run directory instead of
    creating one, re-entering the lifecycle at that stage.
    """
    del workspace  # retained in the contract to make caller path ownership explicit
    resuming = stage_index(start_stage) > 0
    if run is not None and not resuming:
        raise SpecificationError("A UAT run can only be selected together with a resume stage.")
    timestamp = now or datetime.now(UTC)
    # UTC to the second: readable at a glance, and two runs of one kit cannot start within
    # the same second.
    run_id = timestamp.strftime("%Y%m%d.%H%M%S")
    fixtures = discover_fixtures(uat_root, selected)
    results: list[UATResult] = []
    for fixture in fixtures:
        if resuming:
            case_root = resolve_run_dir(fixture, run)
            run_id = case_root.name
        else:
            case_root = fixture.root / "runs" / run_id
            case_root.mkdir(parents=True, exist_ok=False)
        results.append(
            run_fixture(
                fixture,
                case_root,
                run_id=case_root.name if resuming else run_id,
                start_stage=start_stage,
                model=model,
                provider=provider,
                effort=effort,
                max_build_passes=max_build_passes,
                repair_attempts=repair_attempts,
                runner=runner,
                on_event=on_event,
            )
        )
    return run_id, tuple(results)
