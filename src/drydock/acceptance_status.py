"""Per-criterion acceptance status: what the build learned about each criterion, persisted.

A criterion's status is a fact about the criterion, not about the product. The build's baseline
run classifies it before its block builds; FLAKY detection and AC repair refine it later. The
store is keyed by criterion id and bound to a digest of the criterion's code, so an edited
criterion is re-classified rather than inheriting a verdict about code it no longer has.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from drydock.acceptance import (
    MALFORMED_FAILURE_PREFIX,
    SKIPPED_FAILURE_PREFIX,
    UNBUILT_FOUNDATION_FAILURE_PREFIX,
    UNVERIFIED_FAILURE_PREFIX,
    AcceptanceObservation,
    ProgrammaticAcceptance,
    observe_programmatic_acceptance,
)
from drydock.proof_integrity import analyze_proof
from drydock.source_roles import StagedAsset

#: Where the build records each criterion's status, under the Target's ``evidence/``.
ACCEPTANCE_STATUS_EVIDENCE = "acceptance-status.json"

#: Red before the build: the criterion can fail, so a later pass is evidence about the work.
STATUS_VALID = "VALID"
#: The criterion could not run as written: died in its own frame, or its environment is absent.
STATUS_ERROR = "ERROR"
#: Passes whatever the product does: a vacuous assertion.
STATUS_ALWAYS_PASSES = "ALWAYS_PASSES"
#: Green before its block built: measures nothing, or measures something already delivered.
STATUS_PREBUILD_PASSES = "PREBUILD_PASSES"
#: AC repair could not produce a valid criterion.
STATUS_UNFIXABLE = "UNFIXABLE"
#: The verdict changed on an unchanged build tree.
STATUS_FLAKY = "FLAKY"

STATUSES = (
    STATUS_VALID,
    STATUS_ERROR,
    STATUS_ALWAYS_PASSES,
    STATUS_PREBUILD_PASSES,
    STATUS_UNFIXABLE,
    STATUS_FLAKY,
)

#: Statuses no baseline overwrites while the criterion's code is unchanged. Only editing the
#: criterion clears one, because nothing else can change what it found.
TERMINAL_STATUSES = frozenset({STATUS_ALWAYS_PASSES, STATUS_UNFIXABLE, STATUS_FLAKY})

#: Statuses whose criterion is not run after a block: it cannot measure the product. ERROR is
#: re-checked by the next baseline; the others hold until the criterion is edited.
EXCLUDED_STATUSES = frozenset({STATUS_ALWAYS_PASSES, STATUS_ERROR, STATUS_UNFIXABLE, STATUS_FLAKY})

#: Statuses green before the build, which therefore cannot verify the story that owns them.
PREPASSED_STATUSES = frozenset({STATUS_PREBUILD_PASSES, STATUS_ALWAYS_PASSES})

ERROR_MALFORMED = "malformed"
ERROR_ENVIRONMENT = "environment"
ERROR_PRODUCT_MISSING = "product-missing"
ERROR_BASELINE_RED = "baseline-red"
ERROR_VACUOUS = "vacuous"
ERROR_VERDICT_CHANGED = "verdict-changed"
#: PREBUILD_PASSES observed in an empty directory: the criterion passes with no product at all.
ERROR_EMPTY_TREE = "empty-tree"
#: PREBUILD_PASSES observed only against the current tree, with no empty-directory run to tell
#: "passes with nothing" from "measures something already delivered".
ERROR_CURRENT_TREE = "current-tree"
#: VALID, red with no product and green on the current tree: an earlier block delivered it.
ERROR_EXISTING_BEHAVIOR = "existing-behavior"
ERROR_REPAIRED = "repaired"
ERROR_REPAIR_IMPOSSIBLE = "repair-impossible"
ERROR_REPAIR_REJECTED = "repair-rejected"

#: Signatures of a criterion reaching for product code or output that does not exist yet. Before
#: the build that is the expected red, and it is what proves the criterion exercises the product.
_PRODUCT_MISSING_MARKERS = (
    "ModuleNotFoundError",
    "ImportError",
    "FileNotFoundError",
    "No such file or directory",
    "command not found",
)


@dataclass(frozen=True)
class CriterionStatus:
    status: str
    error_code: str
    code_sha256: str
    updated_at: str
    detail: str = ""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def code_digest(code: str) -> str:
    """Return the digest that binds a status to the criterion code it was observed on."""
    return sha256(code.encode("utf-8")).hexdigest()


def classify_baseline(
    observation: AcceptanceObservation,
    check: ProgrammaticAcceptance,
    *,
    empty: AcceptanceObservation | None = None,
    at: str | None = None,
) -> CriterionStatus | None:
    """Classify one criterion from its pre-build observations, or ``None`` when it cannot be.

    ``observation`` ran against the current tree; ``empty`` ran in an empty directory holding
    only the staged inputs. A pass with nothing is PREBUILD_PASSES; red with nothing and green on
    the current tree is VALID existing behavior an earlier block delivered. Without ``empty`` the
    two cannot be told apart, and a current-tree pass is recorded as PREBUILD_PASSES.

    "Product missing" and "environment missing" both fail before the build and mean opposite
    things: the first is the red that proves the criterion measures the product, the second is a
    criterion that could not run. A baseline that never ran (authorized tooling not provisioned
    yet) says nothing, so it records nothing.
    """
    stamp = at or _now()
    digest = code_digest(check.code)
    # Vacuity is a property of the code, not of this run: a swallowed assertion can be red today
    # only because the product is absent, and will pass whatever the product does once it exists.
    integrity = analyze_proof(check.code)
    if not integrity.ok:
        reasons = "; ".join(integrity.reasons)
        return CriterionStatus(STATUS_ALWAYS_PASSES, ERROR_VACUOUS, digest, stamp, reasons)
    error = observation.error or ""
    if error.startswith("baseline unavailable"):
        return None
    if observation.passed and not observation.integrity_ok:
        reasons = "; ".join(observation.integrity_reasons)
        return CriterionStatus(STATUS_ALWAYS_PASSES, ERROR_VACUOUS, digest, stamp, reasons)
    if empty is not None and empty.passed:
        return CriterionStatus(STATUS_PREBUILD_PASSES, ERROR_EMPTY_TREE, digest, stamp)
    if observation.passed:
        if empty is not None:
            return CriterionStatus(STATUS_VALID, ERROR_EXISTING_BEHAVIOR, digest, stamp)
        return CriterionStatus(STATUS_PREBUILD_PASSES, ERROR_CURRENT_TREE, digest, stamp)
    if error.startswith(MALFORMED_FAILURE_PREFIX):
        return CriterionStatus(STATUS_ERROR, ERROR_MALFORMED, digest, stamp, error)
    if observation.skipped or error.startswith((SKIPPED_FAILURE_PREFIX, UNVERIFIED_FAILURE_PREFIX)):
        return CriterionStatus(STATUS_ERROR, ERROR_ENVIRONMENT, digest, stamp, error)
    text = f"{error}\n{observation.stderr}\n{observation.stdout}"
    if error.startswith(UNBUILT_FOUNDATION_FAILURE_PREFIX) or any(
        marker in text for marker in _PRODUCT_MISSING_MARKERS
    ):
        return CriterionStatus(STATUS_VALID, ERROR_PRODUCT_MISSING, digest, stamp)
    return CriterionStatus(STATUS_VALID, ERROR_BASELINE_RED, digest, stamp)


def read_acceptance_status(evidence_dir: Path) -> dict[str, CriterionStatus]:
    """Return the recorded status per criterion id, or an empty map."""
    try:
        payload = json.loads(
            (evidence_dir / ACCEPTANCE_STATUS_EVIDENCE).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    entries = payload.get("criteria") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}
    statuses: dict[str, CriterionStatus] = {}
    for check_id, entry in entries.items():
        if not isinstance(entry, dict) or entry.get("status") not in STATUSES:
            continue
        statuses[str(check_id)] = CriterionStatus(
            status=str(entry["status"]),
            error_code=str(entry.get("error_code", "")),
            code_sha256=str(entry.get("code_sha256", "")),
            updated_at=str(entry.get("updated_at", "")),
            detail=str(entry.get("detail", "")),
        )
    return statuses


def _write(evidence_dir: Path, statuses: Mapping[str, CriterionStatus]) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload = {"criteria": {key: asdict(statuses[key]) for key in sorted(statuses)}}
    (evidence_dir / ACCEPTANCE_STATUS_EVIDENCE).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def record_baseline_status(
    evidence_dir: Path,
    incoming: Mapping[str, CriterionStatus],
    *,
    resume: bool = False,
) -> dict[str, CriterionStatus]:
    """Merge baseline classifications into the store and return the merged map.

    A terminal status survives while its criterion's code is unchanged. A resumed block's tree
    holds its own partial work, so its baseline never records PREBUILD_PASSES, and otherwise only
    fills gaps, replaces an edited criterion, or re-checks an ERROR whose environment may since
    have been repaired.
    """
    known = read_acceptance_status(evidence_dir)
    changed = False
    for check_id, status in incoming.items():
        existing = known.get(check_id)
        # Green on a resumed tree may be the block's own partial work, so it is never evidence
        # that the criterion was green before the block. Green in the empty directory still is.
        if resume and status.error_code in {ERROR_CURRENT_TREE, ERROR_EXISTING_BEHAVIOR}:
            continue
        if existing is not None and existing.code_sha256 == status.code_sha256:
            if existing.status in TERMINAL_STATUSES:
                continue
            if resume and existing.status != STATUS_ERROR:
                continue
            if existing == status:
                continue
        known[check_id] = status
        changed = True
    if changed:
        _write(evidence_dir, known)
    return known


def record_status(
    evidence_dir: Path, check: ProgrammaticAcceptance, status: str, error_code: str, detail: str
) -> None:
    """Record one status decided after the baseline: FLAKY, UNFIXABLE, or a repaired VALID."""
    known = read_acceptance_status(evidence_dir)
    known[check.check_id] = CriterionStatus(
        status, error_code, code_digest(check.code), _now(), detail
    )
    _write(evidence_dir, known)


def current_status(
    statuses: Mapping[str, CriterionStatus], check: ProgrammaticAcceptance
) -> CriterionStatus | None:
    """Return the status recorded for ``check``'s current code, or ``None`` when stale or absent."""
    entry = statuses.get(check.check_id)
    if entry is None or entry.code_sha256 != code_digest(check.code):
        return None
    return entry


def prepassed_ids(
    statuses: Mapping[str, CriterionStatus], checks: Iterable[ProgrammaticAcceptance]
) -> frozenset[str]:
    """Return ids among ``checks`` whose current code was green before its block built."""
    return frozenset(
        check.check_id
        for check in checks
        if (entry := current_status(statuses, check)) is not None
        and (entry.status in PREPASSED_STATUSES or entry.error_code == ERROR_EXISTING_BEHAVIOR)
    )


#: The verdicts of a criterion's last recorded run.
OUTCOME_PASS = "PASS"
OUTCOME_FAIL = "FAIL"
OUTCOME_DISPUTED = "DISPUTED"


@dataclass(frozen=True)
class CriterionHistory:
    previously_passed: bool
    last_block: str
    #: PASS, FAIL, or DISPUTED from the last build pass that ran it.
    last_outcome: str = ""


def acceptance_history(target_dir: Path) -> dict[str, CriterionHistory]:
    """Project ``BUILD_LINEAGE.jsonl`` into per-criterion history, read once.

    ``previously_passed`` is true when any recorded build pass saw the criterion pass;
    ``last_block`` names the block whose pass last ran it. UNVERIFIED results ran nothing.
    """
    path = target_dir / "BUILD_LINEAGE.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    passed: set[str] = set()
    last_block: dict[str, str] = {}
    last_outcome: dict[str, str] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        details = row.get("details") if isinstance(row, dict) else None
        results = details.get("acceptance") if isinstance(details, dict) else None
        if not isinstance(results, list):
            continue
        block = str(row.get("block") or "")
        for result in results:
            if not isinstance(result, dict) or result.get("skipped"):
                continue
            check_id = str(result.get("check_id") or "")
            if not check_id:
                continue
            last_block[check_id] = block
            if result.get("passed"):
                passed.add(check_id)
                last_outcome[check_id] = OUTCOME_PASS
            else:
                binding = result.get("binding", True) is not False
                last_outcome[check_id] = OUTCOME_FAIL if binding else OUTCOME_DISPUTED
    return {
        check_id: CriterionHistory(check_id in passed, block, last_outcome[check_id])
        for check_id, block in last_block.items()
    }


def excluded_criteria(
    statuses: Mapping[str, CriterionStatus], checks: Iterable[ProgrammaticAcceptance]
) -> dict[str, CriterionStatus]:
    """Return the criteria among ``checks`` whose current status keeps them from running."""
    return {
        check.check_id: entry
        for check in checks
        # PREBUILD_PASSES still runs: running costs nothing and can still catch a break, and
        # ``prepassed_ids`` already keeps it from verifying the story that owns it.
        if (entry := current_status(statuses, check)) is not None
        and entry.status in EXCLUDED_STATUSES
    }


def observe_empty_baseline(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    target_dir: Path,
    blueprint_dir: Path,
    staged: Iterable[StagedAsset] = (),
) -> tuple[AcceptanceObservation, ...]:
    """Run ``checks`` in an empty directory holding only the staged inputs, never the product.

    The directory has no Target ``.venv``: an editable install there would put the product back
    on the path. Acceptance therefore resolves the interpreter Drydock itself runs on, which is
    what a new build uses before it owns an environment.
    """
    if not checks:
        return ()
    with tempfile.TemporaryDirectory(prefix="drydock-empty-baseline-") as directory:
        empty = Path(directory)
        for asset in staged:
            destination = empty / asset.relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset.source, destination)
        return observe_programmatic_acceptance(
            checks,
            build_dir=empty,
            target_dir=target_dir,
            blueprint_dir=blueprint_dir,
            strict_target=True,
        )
