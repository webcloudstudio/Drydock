"""The build lifecycle: the one workflow ``drydock run builder`` and ``drydock uat`` both execute.

:class:`Lifecycle` defines every step from an empty Target to a complete build — init, import,
analyze, plan, plan verification, and the build/recovery loop — as child ``drydock`` commands
issued through an injected ``execute``. It owns argv, step labels, and loop policy, and nothing
about where a command runs or how its evidence is kept. ``drydock uat`` drives it inside a
sealed run directory and extends it with refit, test, and score stages; :class:`BuildRun`
drives it in place against a configured Target.

:class:`BuildRun` derives its position from the Target directory on every pass, so starting and
resuming are one operation. It journals each run to ``<Target>/logs/runs/<run-id>/RUN.jsonl``:
a ``start`` record naming the stage topology and policy, one ``step`` record per child command
with its stage, label, argv, timing, exit code, evidence paths, and the Target's standing state
afterwards, ``blocker`` records for each ``BLOCKERS.md`` settlement, and an ``end`` record.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TextIO

from drydock import project_status
from drydock.blockers import Blockers, batch_may_run_owner, read_blockers
from drydock.errors import UsageError
from drydock.source_files import iter_source_files

if TYPE_CHECKING:
    from drydock.uat import CommandResult, Runner

#: Ordered lifecycle stages. ``drydock uat`` appends its own refit, test, and score stages.
STAGES = ("init", "import", "analyze", "plan", "verify", "build")

DEFAULT_MAX_BUILD_PASSES = 25
#: ``drydock run builder`` repairs unfinished work with ``diagnose --apply`` up to this many
#: times per run. ``drydock uat`` measures the build alone and sets zero.
DEFAULT_DIAGNOSE_ATTEMPTS = 3
#: ``BLOCKERS.md`` settlements one ``BuildRun`` may make before it stops asking.
MAX_BLOCKER_ROUNDS = 10

IMPORT_FORMATS = ("auto", "markdown", "source", "speckit", "compass", "intent")

COMPLETE = "complete"
INCOMPLETE = "incomplete"
HALTED = "halted"
BLOCKED = "blocked"
FAILED = "failed"
NEEDS_SOURCES = "needs sources"

RUNS_DIRNAME = "runs"
JOURNAL_FILENAME = "RUN.jsonl"


@dataclass(frozen=True)
class SourceInput:
    """One ``drydock import`` the lifecycle runs: a file or directory and its import format."""

    path: Path
    format: str

    @classmethod
    def parse(cls, value: str, *, directory: bool) -> SourceInput:
        """Parse ``[FORMAT=]PATH``; a file defaults to ``auto``, a directory to ``markdown``."""
        prefix, separator, rest = value.partition("=")
        fmt, raw = (prefix, rest) if separator and prefix in IMPORT_FORMATS else ("", value)
        path = Path(raw).expanduser().resolve()
        flag = "--indir" if directory else "--infile"
        if directory and not path.is_dir():
            raise UsageError(f"{flag}: not a directory: {raw}")
        if not directory and not path.is_file():
            raise UsageError(f"{flag}: not a file: {raw}")
        if directory and fmt == "auto":
            raise UsageError(f"{flag}: a directory needs markdown or source, not auto: {raw}")
        return cls(path, fmt or ("markdown" if directory else "auto"))


@dataclass(frozen=True)
class Policy:
    """How the lifecycle builds: bounds, recovery, and whether answer gates are waived."""

    repair_attempts: int
    max_build_passes: int = DEFAULT_MAX_BUILD_PASSES
    diagnose_attempts: int = 0
    #: Waive answer-dependent gates (``--override``) for a run with no Commander at the keyboard.
    unattended: bool = False
    #: Model for every ``drydock plan`` child; every other child runs on the configured model.
    plan_model: str | None = None


class Execute(Protocol):
    """Run one child ``drydock`` command (argv without the ``drydock`` prefix)."""

    def __call__(
        self, parts: Sequence[str], label: str, *, required: bool = True
    ) -> CommandResult: ...


class Halt(Protocol):
    """Record why a stage stopped: ``reason`` is the full detail, ``summary`` one degraded line.

    An empty ``summary`` is a stop that does not degrade the build, such as an unrunnable plan.
    """

    def __call__(
        self,
        stage: str,
        reason: str,
        *,
        summary: str,
        result: CommandResult | None = None,
        explanation: str = "",
    ) -> None: ...


def build_failure_detail(command: CommandResult, target: str) -> str:
    """Preserve a failed build's diagnostics and their evidence locations in its blocker."""
    lines = [f"drydock build {target} exited {command.returncode}."]
    diagnostics = ""
    for stream, value in (("stderr", command.stderr_path), ("stdout", command.stdout_path)):
        if not value:
            continue
        try:
            with Path(value).open(encoding="utf-8", errors="replace") as handle:
                content = handle.read(12001)
        except OSError:
            continue
        if content.strip():
            diagnostics = f"{stream}:\n{content[:12000].strip()}"
            if len(content) > 12000:
                diagnostics += "\n[Excerpt truncated; full output is in the evidence file below.]"
            break
    lines += ["", diagnostics or "No diagnostic output was captured; inspect the command evidence."]
    lines += ["", "Evidence:"]
    for stream, value in (("stderr", command.stderr_path), ("stdout", command.stdout_path)):
        if value:
            lines.append(f"  {stream}: {value}")
    return "\n".join(lines)


BUILD_FAILED_EXPLANATION = (
    "The build did not complete. The lifecycle stopped before acceptance tests and scoring "
    "because the application is unfinished. Resolve the build error above, then rerun."
)


class Lifecycle:
    """The steps from an empty Target to a complete build, issued through ``execute``."""

    def __init__(
        self,
        target: str,
        policy: Policy,
        *,
        execute: Execute,
        halt: Halt,
        build_passes: int = 0,
        build_failed_explanation: str = BUILD_FAILED_EXPLANATION,
    ) -> None:
        self.target = target
        self.policy = policy
        self.build_passes = build_passes
        self.build_failed_explanation = build_failed_explanation
        self.diagnoses = 0
        self._execute = execute
        self._halt = halt

    def run(self, *parts: str, label: str, required: bool = True) -> CommandResult:
        if self.policy.plan_model and parts[0] == "plan":
            parts = (*parts, "--plan-override-model", self.policy.plan_model)
        return self._execute(parts, label, required=required)

    def _override(self) -> tuple[str, ...]:
        return ("--override",) if self.policy.unattended else ()

    # -- stages -----------------------------------------------------------------

    def init(self) -> None:
        self.run("init", self.target, label="init")

    def import_sources(self, inputs: Sequence[SourceInput]) -> None:
        for index, item in enumerate(inputs, start=1):
            self.run(
                "import",
                self.target,
                str(item.path),
                "--format",
                item.format,
                label="import-sources" if index == 1 else f"import-sources-{index}",
            )

    def analyze(self) -> None:
        self.run("analyze", self.target, label="analyze")

    def plan(self) -> None:
        self.run("plan", self.target, *self._override(), label="plan")

    def verify_plan(self) -> bool:
        """Verify the plan, repair it once if needed, and halt if it still cannot run.

        A criterion that cannot execute costs the build its entire repair budget on a story whose
        code was already correct. Verification is deterministic and free, so it always runs; the
        repair call is paid for only when verification fails. One attempt: a second pass asks
        the same model the same question with the same context.
        """
        if self.run("plan", "verify", self.target, label="plan-verify", required=False).returncode:
            self.run("plan", "repair", self.target, label="plan-repair", required=False)
            confirmed = self.run(
                "plan", "verify", self.target, label="plan-verify-after-repair", required=False
            )
            if confirmed.returncode:
                # No summary: a plan that cannot run is a stop, not a degraded build.
                self._halt(
                    "plan-repair",
                    "acceptance criteria still cannot run after one repair pass",
                    summary="",
                )
                return False
        return True

    def build(self, stage: str) -> str:
        """Build until the frontier is empty; return ``complete``, ``incomplete``, or ``halted``.

        Each pass builds every ready block, which readies more, until ``status --ready`` reports
        nothing left. ``status --check`` then separates completion from a frontier that was empty
        because the work is stalled. Unfinished work is handed to ``diagnose --apply`` while the
        policy's diagnose budget lasts; past it, a failed build halts and a stalled one reports
        ``incomplete``. A frontier empty before the first pass and not complete halts: the
        Manifest was unbuildable on arrival, and a score taken over it grades an empty tree.
        """
        passes = 0
        while True:
            ready = self.run(
                "status", self.target, "--ready", label=f"{stage}-ready", required=False
            )
            if ready.returncode == 0:
                passes += 1
                self.build_passes += 1
                bound = self.policy.max_build_passes
                if passes > bound:
                    self._halt(
                        stage,
                        f"The build made {bound} passes without emptying the frontier. Either a "
                        "block is looping without progress or the bound is too low for this "
                        "Manifest.",
                        summary=f"{stage}: exceeded {bound} build passes without completing",
                    )
                    return HALTED
                label = f"{stage}-build-{passes}"
                built = self.run(
                    "build",
                    self.target,
                    *self._override(),
                    "--repair-attempts",
                    str(self.policy.repair_attempts),
                    label=label,
                    required=False,
                )
                if built.returncode == 0:
                    continue
                recovered = self._diagnose(stage)
                if recovered is not None and recovered.returncode == 0:
                    continue
                self._halt(
                    label,
                    build_failure_detail(built, self.target),
                    summary=f"{label} exited {built.returncode}",
                    result=built,
                    explanation=self.build_failed_explanation,
                )
                return HALTED
            unstarted = passes == 0
            checked = self.run(
                "status",
                self.target,
                "--check",
                label=f"{stage}-unstarted-check" if unstarted else f"{stage}-complete",
                required=False,
            )
            if checked.returncode == 0:
                if unstarted:
                    # A resumed stage may arrive complete; the completion record is still taken.
                    self.run(
                        "status", self.target, "--check", label=f"{stage}-complete", required=False
                    )
                return COMPLETE
            recovered = self._diagnose(stage)
            if recovered is not None and recovered.returncode == 0:
                continue
            if recovered is not None:
                reason = "diagnosis did not restore progress"
                self._halt(stage, reason, summary=f"{stage}: {reason}", result=recovered)
                return HALTED
            if not unstarted:
                return INCOMPLETE
            reason = (
                "blocked before the first build pass"
                if checked.returncode == 2
                else "no buildable frontier before the first build pass"
            )
            self._halt(
                stage,
                f"The build stage found {reason}. Answer the blocking DECISIONS.json records "
                "parking the Manifest's stories, then rerun; a score taken over a build that never "
                "ran grades an empty tree, not the product.",
                summary=f"{stage}: {reason}",
            )
            return HALTED

    def _diagnose(self, stage: str) -> CommandResult | None:
        """Repair unfinished work once, while the diagnose budget lasts; ``None`` past it."""
        if self.diagnoses >= self.policy.diagnose_attempts:
            return None
        self.diagnoses += 1
        return self.run(
            "diagnose",
            self.target,
            "--apply",
            label=f"{stage}-diagnose-{self.diagnoses}",
            required=False,
        )


# -- in-place runs --------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    """Where a Target stands in the lifecycle, read from its directory."""

    initialized: bool
    imported: bool
    analyzed: bool
    planned: bool
    building: bool
    state: str

    @classmethod
    def of(cls, target_dir: Path) -> Position:
        entries = project_status.read_status(target_dir) if target_dir.is_dir() else ()
        standing = project_status.standing_state(entries)
        sources = target_dir / "blueprint" / "sources"
        return cls(
            initialized=(target_dir / "METADATA.md").is_file(),
            imported=next(iter_source_files(sources), None) is not None,
            analyzed=(target_dir / "ANALYSIS.md").is_file(),
            planned=(target_dir / "MANIFEST.md").is_file(),
            building=any(entry.label in {"BUILDING", "BUILT"} for entry in entries),
            state=_state_text(standing),
        )

    def next_stage(self) -> str:
        """The first stage this position has not established; ``build`` once planned."""
        for stage, done in (
            ("init", self.initialized),
            ("import", self.imported),
            ("analyze", self.analyzed),
            ("plan", self.planned),
            ("verify", self.building),
        ):
            if not done:
                return stage
        return "build"


def _state_text(entry: project_status.StatusEntry | None) -> str:
    if entry is None:
        return "none"
    return entry.label if entry.passed else f"{entry.label} failed"


class StepFailed(Exception):
    """A required step exited nonzero."""

    def __init__(self, label: str, result: CommandResult) -> None:
        super().__init__(f"{label} exited {result.returncode}")
        self.label = label
        self.result = result


class Blocked(Exception):
    """A step failed while ``BLOCKERS.md`` stands; the run settles it and re-derives."""


#: Ask the Commander per blocker and record each answer; ``False`` when they quit.
Ask = Callable[[Path, Blockers], bool]


@dataclass
class BuildOutcome:
    status: str
    reason: str = ""
    run_id: str = ""
    journal: Path | None = None
    steps: int = 0
    build_passes: int = 0
    elapsed_ms: int = 0
    state: str = ""

    @property
    def exit_code(self) -> int:
        if self.status == COMPLETE:
            return 0
        return 2 if self.status == NEEDS_SOURCES else 1


@dataclass
class _Journal:
    path: Path
    records: list[dict[str, object]] = field(default_factory=list)

    def write(self, event: str, **payload: object) -> None:
        record = {"event": event, "at": datetime.now(UTC).isoformat(timespec="seconds"), **payload}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")


class BuildRun:
    """One in-place run of the lifecycle against a configured Target, journaled.

    The run re-derives its :class:`Position` after every ``BLOCKERS.md`` settlement, so a run
    that stopped anywhere — or a Target already complete — continues from where it stands.
    """

    def __init__(
        self,
        target: str,
        target_dir: Path,
        policy: Policy,
        *,
        runner: Runner,
        env: dict[str, str],
        inputs: Sequence[SourceInput] = (),
        ask: Ask | None = None,
        on_blocker: Callable[[Blockers], None] | None = None,
        run_id: str = "",
    ) -> None:
        self.target = target
        self.target_dir = target_dir
        self.policy = policy
        self.inputs = tuple(inputs)
        self.run_id = run_id or datetime.now(UTC).strftime("%Y%m%d.%H%M%S")
        self.run_dir = target_dir / "logs" / RUNS_DIRNAME / self.run_id
        self.commands_dir = self.run_dir / "commands"
        self.journal = _Journal(self.run_dir / JOURNAL_FILENAME)
        self._runner = runner
        self._env = env
        self._ask = ask
        self._on_blocker = on_blocker
        self._sequence = 0
        self._stage = ""
        self._halt_reason = ""
        self.lifecycle = Lifecycle(target, policy, execute=self._execute, halt=self._halt)

    # -- Lifecycle hooks --------------------------------------------------------

    def _execute(self, parts: Sequence[str], label: str, *, required: bool = True) -> CommandResult:
        self._sequence += 1
        self.commands_dir.mkdir(parents=True, exist_ok=True)
        argv = (sys.executable, "-m", "drydock", *parts)
        return self._record(argv, label, required=required)

    def _record(
        self,
        argv: Sequence[str],
        label: str,
        *,
        required: bool,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        started = datetime.now(UTC).isoformat(timespec="seconds")
        result = self._runner(
            argv, Path.cwd(), env or self._env, self.commands_dir, f"{self._sequence:02d}-{label}"
        )
        self.journal.write(
            "step",
            step=self._sequence,
            stage=self._stage,
            label=label,
            argv=["drydock", *argv[3:]],
            started=started,
            elapsed_ms=result.elapsed_ms,
            returncode=result.returncode,
            stdout=_relative(result.stdout_path, self.run_dir),
            stderr=_relative(result.stderr_path, self.run_dir),
            state=Position.of(self.target_dir).state,
        )
        if result.returncode and read_blockers(self.target_dir) is not None:
            raise Blocked()
        if result.returncode and required:
            raise StepFailed(label, result)
        return result

    def _halt(
        self,
        stage: str,
        reason: str,
        *,
        summary: str,
        result: CommandResult | None = None,
        explanation: str = "",
    ) -> None:
        self._halt_reason = summary or f"{stage}: {reason}"
        self.journal.write("halt", stage=stage, summary=self._halt_reason, reason=reason)

    # -- driving ----------------------------------------------------------------

    def execute(self) -> BuildOutcome:
        started = time.monotonic()
        position = Position.of(self.target_dir)
        self.journal.write(
            "start",
            run=self.run_id,
            target=self.target,
            stages=list(STAGES),
            next_stage=position.next_stage(),
            state=position.state,
            policy=asdict(self.policy),
            inputs=[{"path": str(item.path), "format": item.format} for item in self.inputs],
        )
        status, reason = self._drive()
        final = Position.of(self.target_dir)
        outcome = BuildOutcome(
            status=status,
            reason=reason,
            run_id=self.run_id,
            journal=self.journal.path,
            steps=self._sequence,
            build_passes=self.lifecycle.build_passes,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            state=final.state,
        )
        self.journal.write(
            "end",
            status=status,
            reason=reason,
            steps=outcome.steps,
            build_passes=outcome.build_passes,
            elapsed_ms=outcome.elapsed_ms,
            state=final.state,
        )
        return outcome

    def _drive(self) -> tuple[str, str]:
        for _ in range(MAX_BLOCKER_ROUNDS):
            try:
                if not self._settle_blockers():
                    return BLOCKED, self._blocked_reason()
                return self._advance()
            except Blocked:
                continue
            except StepFailed as exc:
                return FAILED, str(exc)
        return BLOCKED, f"BLOCKERS.md still stands after {MAX_BLOCKER_ROUNDS} settlements"

    def _advance(self) -> tuple[str, str]:
        lifecycle = self.lifecycle
        position = Position.of(self.target_dir)
        if not position.initialized:
            self._stage = "init"
            lifecycle.init()
        if not Position.of(self.target_dir).imported:
            if not self.inputs:
                return NEEDS_SOURCES, (
                    f"{self.target} has no imported source material; "
                    "name it with --infile or --indir"
                )
            self._stage = "import"
            lifecycle.import_sources(self.inputs)
            if not Position.of(self.target_dir).imported:
                return FAILED, "the imports added no source material"
        elif self.inputs and position.imported:
            self.journal.write("note", text="sources already imported; --infile/--indir ignored")
        if not Position.of(self.target_dir).analyzed:
            self._stage = "analyze"
            lifecycle.analyze()
        planned_now = False
        if not Position.of(self.target_dir).planned:
            self._stage = "plan"
            lifecycle.plan()
            planned_now = True
        if planned_now or not Position.of(self.target_dir).building:
            self._stage = "verify"
            if not lifecycle.verify_plan():
                return HALTED, self._halt_reason
            self._snapshot("after-plan")
        self._stage = "build"
        status = lifecycle.build("initial")
        self._snapshot("after-initial-build")
        if status == COMPLETE:
            return COMPLETE, ""
        if status == INCOMPLETE:
            return INCOMPLETE, "unfinished work remains and the diagnose budget is spent"
        return HALTED, self._halt_reason

    def _snapshot(self, stage: str) -> None:
        self.lifecycle.run(
            "build", "status", self.target, label=f"{stage}-build-status", required=False
        )

    def _settle_blockers(self) -> bool:
        """Answer or admit ``BLOCKERS.md`` and rerun its owner; ``False`` when the run must stop."""
        blockers = read_blockers(self.target_dir)
        if blockers is None:
            return True
        if self._on_blocker is not None:
            self._on_blocker(blockers)
        if self._ask is not None:
            if not self._ask(self.target_dir, blockers):
                self.journal.write("blocker", owner=blockers.owner, outcome="declined")
                return False
            blockers = read_blockers(self.target_dir) or blockers
        elif not batch_may_run_owner(blockers):
            self.journal.write("blocker", owner=blockers.owner, outcome="refused unattended")
            return False
        self.journal.write(
            "blocker",
            owner=blockers.owner,
            outcome="owner rerun",
            blockers=[item.blocker_id for item in blockers.blockers],
            resolved=[item.blocker_id for item in blockers.resolutions()],
        )
        self._sequence += 1
        self._stage = "blockers"
        self.commands_dir.mkdir(parents=True, exist_ok=True)
        owner = blockers.owner.split()[0] if blockers.owner else "owner"
        env = {**self._env, "DRYDOCK_OWNER_RERUN": blockers.owner}
        argv = (sys.executable, "-m", "drydock", *blockers.rerun_tokens())
        try:
            self._record(argv, f"owner-rerun-{owner}", required=True, env=env)
        except StepFailed:
            return read_blockers(self.target_dir) is None
        return True

    def _blocked_reason(self) -> str:
        blockers = read_blockers(self.target_dir)
        return blockers.line() if blockers is not None else "BLOCKERS.md"


_OUTCOME_HEADINGS = {
    COMPLETE: "BUILD COMPLETE",
    INCOMPLETE: "BUILD INCOMPLETE",
    HALTED: "BUILD STOPPED",
    FAILED: "BUILD STOPPED",
    BLOCKED: "BLOCKED",
    NEEDS_SOURCES: "NO SOURCES",
}


def render_outcome(outcome: BuildOutcome, target: str, *, stream: TextIO | None = None) -> str:
    """The run's closing box: green when complete, yellow when it waits on you, red otherwise."""
    from drydock import console
    from drydock.execution import format_ms

    lines = [
        f"Run: {outcome.run_id} | {outcome.steps} step(s) | "
        f"{outcome.build_passes} build pass(es) | {format_ms(outcome.elapsed_ms)}",
        f"State: {outcome.state}",
    ]
    if outcome.reason:
        lines.append(outcome.reason)
    if outcome.journal is not None:
        lines.append(f"Journal: {outcome.journal}")
    if outcome.status == COMPLETE:
        tone = console.GREEN
    elif outcome.status in {BLOCKED, INCOMPLETE, NEEDS_SOURCES}:
        tone = console.YELLOW
    else:
        tone = console.RED
    return console.box(
        f"{_OUTCOME_HEADINGS[outcome.status]}: {target}", lines, tone=tone, stream=stream
    )


def _relative(value: str, base: Path) -> str:
    try:
        return os.path.relpath(value, base)
    except ValueError:
        return value


def builder_env(model: str, provider: str, effort: str | None) -> dict[str, str]:
    """The child environment: the resolved model and provider, streamed, own transcripts."""
    env = os.environ.copy()
    env["DRYDOCK_MODEL"] = model
    env["LLM_PROVIDER"] = provider
    env["PYTHONUNBUFFERED"] = "1"
    if effort:
        env["DRYDOCK_EFFORT"] = effort
    # The parent's transcript already receives every child's output through the step console.
    env.pop("DRYDOCK_PARENT_TRANSCRIPT", None)
    return env
