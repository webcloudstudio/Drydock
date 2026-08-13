"""Governed acceptance commands: the oracles Drydock trusts to decide state.

The problem this exists for. A build's acceptance criteria are written by the same model that
writes the implementation, in the same call, before any code exists — and it writes the input, the
expected output, and the code that must satisfy them. When such a criterion fails, no analysis can
recover whether the criterion or the product is at fault, because both came from one author with
one set of assumptions. Drydock spent a long time trying to recover it anyway, from the criterion's
text, and every attempt was a heuristic that failed correct builds.

Authority cannot be inferred from an artifact the model wrote. It has to come from data the model
does not author:

* the **full gate** — one command that decides whether the project is acceptable;
* optional **stage gates** — one command per story, deciding whether that story's slice is done.

Both are argv arrays Drydock executes directly. It does not generate a wrapper and then inspect the
wrapper's text: a criterion that declares ``Suite:`` or mentions ``sources/`` proves nothing, since
a model can type either string.

``ACCEPTANCE.json`` in the Target root carries them. It is Commander-owned and appears in
``RESERVED_ARTIFACTS`` so no LLM-assisted command may write it; ``drydock uat`` seeds it from the
fixture's own declaration, exactly as it seeds ``SEA_TRIALS.md`` and ``TECHNOLOGY_STACK.md``.

Where no contract exists, nothing here blocks anything. Model-authored criteria still run and still
drive the repair loop; their blocks close ``closed/implemented`` rather than ``closed/verified``,
because "verified" is a claim about an oracle and there was none.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import SpecificationError

#: The Commander-owned contract, in the Target root beside ``SEA_TRIALS.md``.
FILENAME = "ACCEPTANCE.json"

#: A governed gate runs a whole conformance suite, not a unit test.
GATE_TIMEOUT_SECONDS = 1800

#: The exit status a governed command uses to say it could not run. Drydock's own commands reserve
#: 2 for a usage error, and the shipped gate scripts follow it, so a gate is held to the same
#: contract. A Commander-supplied command that means something else by 2 is misread as a kit fault
#: rather than a product failure -- the safe direction, since a kit fault never fails a release.
GATE_USAGE_EXIT = 2

# The three things a gate execution can mean. The distinction is the point: a command that ran and
# reported failure is evidence about the product, while a command that could not run is evidence
# about the kit and must never be charged to the build.
OUTCOME_PASS = "PASS"
OUTCOME_FAIL = "FAIL"
OUTCOME_ERROR = "ERROR"


@dataclass(frozen=True)
class GateResult:
    """One governed command execution, classified and fully recorded.

    Every field a later reader needs to confirm the verdict was produced by the command it claims,
    against the artifact it claims. Without the identity fields, "the same authoritative suite"
    is an assumption rather than a fact.
    """

    name: str
    outcome: str
    argv: tuple[str, ...]
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    detail: str = ""
    timed_out: bool = False
    build_identity: str = ""

    @property
    def passed(self) -> bool:
        return self.outcome == OUTCOME_PASS

    @property
    def blocks(self) -> bool:
        """Only a product failure blocks. A kit fault is reported and never charged."""
        return self.outcome == OUTCOME_FAIL

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "outcome": self.outcome,
            "argv": list(self.argv),
            "return_code": self.return_code,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
            "timed_out": self.timed_out,
            "build_identity": self.build_identity,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    @property
    def rendered(self) -> str:
        argv = " ".join(self.argv)
        suffix = f" — {self.detail}" if self.detail else ""
        return f"{self.name}: {self.outcome} (exit {self.return_code}) · {argv}{suffix}"


@dataclass(frozen=True)
class AcceptanceContract:
    """The governed oracles for one Target. Absent file means an empty contract, never an error."""

    full: tuple[str, ...] = ()
    stages: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.full or self.stages)

    def stage_for(self, *story_ids: str) -> tuple[str, tuple[str, ...]] | None:
        """Return the first declared stage gate among ``story_ids``, or ``None``.

        A block may deliver several stories; the first with a governed gate owns the block's
        verdict. Order follows the caller's, which is Manifest order.
        """
        for story_id in story_ids:
            argv = self.stages.get(story_id)
            if argv:
                return story_id, argv
        return None


def _argv(value: object, *, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise SpecificationError(f"{FILENAME}: {where} must be a non-empty argv list")
    if not all(isinstance(item, str) and item for item in value):
        raise SpecificationError(f"{FILENAME}: {where} argv entries must be non-empty strings")
    return tuple(value)


def load_contract(target_dir: Path) -> AcceptanceContract:
    """Read the Target's governed acceptance contract, or an empty one when absent."""
    path = target_dir / FILENAME
    if not path.is_file():
        return AcceptanceContract()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SpecificationError(f"{FILENAME} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SpecificationError(f"{FILENAME} must contain a JSON object")
    full = _argv(payload["full"], where="full") if payload.get("full") is not None else ()
    raw_stages = payload.get("stages") or {}
    if not isinstance(raw_stages, dict):
        raise SpecificationError(f"{FILENAME}: stages must be an object keyed by story id")
    stages = {
        str(story_id): _argv(argv, where=f"stages.{story_id}")
        for story_id, argv in raw_stages.items()
    }
    return AcceptanceContract(full=full, stages=stages, source=str(path))


def write_contract(target_dir: Path, contract: AcceptanceContract) -> Path:
    """Persist a contract into the Target. Used by ``drydock uat`` to seed from a fixture."""
    path = target_dir / FILENAME
    payload: dict[str, object] = {}
    if contract.full:
        payload["full"] = list(contract.full)
    if contract.stages:
        payload["stages"] = {name: list(argv) for name, argv in sorted(contract.stages.items())}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def contract_from_config(payload: object, *, where: str) -> AcceptanceContract:
    """Build a contract from a fixture's ``acceptance`` block. Rejects a malformed declaration."""
    if payload is None:
        return AcceptanceContract()
    if not isinstance(payload, dict):
        raise SpecificationError(f"{where}: acceptance must be an object")
    full = _argv(payload["full"], where=f"{where}.full") if payload.get("full") is not None else ()
    raw_stages = payload.get("stages") or {}
    if not isinstance(raw_stages, dict):
        raise SpecificationError(f"{where}: acceptance.stages must be an object")
    stages = {
        str(story_id): _argv(argv, where=f"{where}.stages.{story_id}")
        for story_id, argv in raw_stages.items()
    }
    return AcceptanceContract(full=full, stages=stages, source=where)


def build_identity(build_dir: Path) -> str:
    """Return a digest over the built tree, so a verdict names the artifact it judged."""
    digest = hashlib.sha256()
    if not build_dir.is_dir():
        return ""
    for path in sorted(build_dir.rglob("*")):
        name = path.relative_to(build_dir).as_posix()
        if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        if not path.is_file():
            continue
        digest.update(name.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:  # pragma: no cover - unreadable file mid-build
            continue
    return digest.hexdigest()[:16]


def run_gate(
    name: str,
    argv: tuple[str, ...],
    *,
    build_dir: Path,
    timeout: int = GATE_TIMEOUT_SECONDS,
    record_identity: bool = True,
) -> GateResult:
    """Execute one governed command and classify the result as PASS, FAIL, or ERROR.

    Exit zero is the product passing. A non-zero exit from a command that ran is the product
    failing. Everything that prevented the command from running — an absent executable, a
    timeout, a signal, a permission refusal, or an exit of ``GATE_USAGE_EXIT`` — is ERROR, which
    is evidence about the kit and is never charged against the build. Collapsing that third case
    into FAIL is how a missing harness becomes a product defect in the record.
    """
    identity = build_identity(build_dir) if record_identity else ""
    if not build_dir.is_dir():
        return GateResult(
            name,
            OUTCOME_ERROR,
            argv,
            detail=f"build directory not found: {build_dir}",
            build_identity=identity,
        )
    if shutil.which(argv[0]) is None and not (build_dir / argv[0]).exists():
        return GateResult(
            name,
            OUTCOME_ERROR,
            argv,
            detail=f"command not found: {argv[0]}",
            build_identity=identity,
        )
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=build_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return GateResult(
            name,
            OUTCOME_ERROR,
            argv,
            stdout=_text(exc.stdout),
            stderr=_text(exc.stderr),
            duration_ms=round((time.monotonic() - started) * 1000),
            detail=f"timed out after {timeout}s",
            timed_out=True,
            build_identity=identity,
        )
    except OSError as exc:
        return GateResult(
            name,
            OUTCOME_ERROR,
            argv,
            duration_ms=round((time.monotonic() - started) * 1000),
            detail=f"could not execute: {exc}",
            build_identity=identity,
        )
    duration = round((time.monotonic() - started) * 1000)
    # A negative return code is POSIX for "killed by signal N". The command did not decide
    # anything; something else stopped it.
    if completed.returncode < 0:
        return GateResult(
            name,
            OUTCOME_ERROR,
            argv,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration,
            detail=f"terminated by signal {-completed.returncode}",
            build_identity=identity,
        )
    # Exit 2 is a usage error, not a verdict: the command is saying it could not run. This is the
    # `diff` and `grep` convention -- 1 is a legitimate negative answer, 2 is trouble -- and the
    # one Drydock's own commands follow. A gate script reports it for an unset variable, a bad
    # argument, or a harness that is not the version the run named, none of which observed the
    # product.
    if completed.returncode == GATE_USAGE_EXIT:
        return GateResult(
            name,
            OUTCOME_ERROR,
            argv,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration,
            detail=f"exited {GATE_USAGE_EXIT} (usage error): the gate could not run",
            build_identity=identity,
        )
    outcome = OUTCOME_PASS if completed.returncode == 0 else OUTCOME_FAIL
    return GateResult(
        name,
        outcome,
        argv,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=duration,
        build_identity=identity,
    )


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
