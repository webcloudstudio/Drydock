"""Append-only mechanical build lineage; no model-authored file attribution."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from drydock import build_git
from drydock.build import StepAssembly
from drydock.build_plan import PlanBlock, parse_build_plan
from drydock.errors import SpecificationError


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def serializable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return serializable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [serializable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def node_record(node: PlanBlock) -> dict[str, object]:
    """Retain Manifest keys, including optional/new fields without a second schema."""
    return {
        **node.fields,
        "id": node.block_id,
        "name": node.name,
        "block_type": node.block_type,
        "number": node.number,
        "state": node.state,
        "parent": node.parent,
        "depends": node.depends,
        "scope": node.scope,
    }


class BuildLineage:
    def __init__(
        self,
        target: str,
        target_dir: Path,
        build_dir: Path,
        on_text: Callable[[str], None] | None = None,
    ) -> None:
        self.target = target
        self.target_dir = target_dir.resolve()
        self.build_dir = build_dir.resolve()
        self.on_text = on_text
        self.run_id = uuid4().hex
        self.run_started_at = now()
        self.run_log = os.environ.get("DRYDOCK_PARENT_TRANSCRIPT")
        self.ready = False
        self.context: dict[str, object] = {}
        self.application_head: str | None = None

    def emit(self, message: str) -> None:
        if self.on_text is not None:
            self.on_text(message)

    def prepare(self) -> None:
        if self.ready:
            return
        for root in dict.fromkeys((self.build_dir, self.target_dir)):
            build_git.prepare(root)
        self._recover()
        for root in dict.fromkeys((self.build_dir, self.target_dir)):
            commit = build_git.checkpoint(root, f"Checkpoint before drydock build {self.target}")
            if commit:
                self.emit(f"git: baseline {root.name} {commit[:12]}")
        self.ready = True
        self.application_head = build_git.head(self.build_dir)

    def _pending_path(self) -> Path:
        path = Path(
            build_git.git(
                self.target_dir, "rev-parse", "--git-path", "drydock-build-lineage.json"
            ).strip()
        )
        return path if path.is_absolute() else self.target_dir / path

    def _save_pending(self, row: dict[str, object], message: str) -> None:
        path = self._pending_path()
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(serializable({"row": row, "message": message}), stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def _append(self, row: dict[str, object]) -> None:
        path = self.target_dir / "BUILD_LINEAGE.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(serializable(row), ensure_ascii=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _recover(self) -> None:
        pending = self._pending_path()
        if not pending.exists():
            return
        payload = json.loads(pending.read_text(encoding="utf-8"))
        row, message = payload["row"], payload["message"]
        application = row["application"]
        root = Path(application["repository"])
        if not application.get("checkpoint_complete"):
            commit = (
                build_git.git(
                    root,
                    "log",
                    "--all",
                    "-1",
                    "--format=%H",
                    "--fixed-strings",
                    f"--grep=Build-Lineage-Id: {row['record_id']}",
                ).strip()
                if build_git.head(root)
                else ""
            )
            if not commit:
                raise SpecificationError(
                    f"Interrupted build checkpoint needs inspection: {pending}. "
                    "Application changes were not confirmed committed; lineage is preserved."
                )
            application.update(
                after_commit=commit,
                committed=True,
                checkpoint_complete=True,
                files=build_git.changes(root, application["before_commit"], commit),
            )
        path = self.target_dir / "BUILD_LINEAGE.jsonl"
        rows = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        if not any(json.loads(line)["record_id"] == row["record_id"] for line in rows):
            self._append(row)
        build_git.git(self.target_dir, "add", "-f", "--", "BUILD_LINEAGE.jsonl")
        commit = build_git.checkpoint(self.target_dir, message)
        if commit:
            self.emit(
                f"git: recovered {row['block']} | {', '.join(row['implements'])} | target={commit[:12]}"
            )
        pending.unlink()

    def begin(
        self,
        block_id: str,
        name: str,
        steps: Sequence[PlanBlock],
        assemblies: Sequence[StepAssembly],
    ) -> None:
        self.prepare()
        manifest = self.target_dir / "MANIFEST.md"
        plan = parse_build_plan(manifest)
        ids = {node.block_id for node in steps}
        specs: dict[str, dict[str, object]] = {}
        for assembly in assemblies:
            for item in assembly.files:
                if item.role != "implements":
                    continue
                specs[item.name] = {
                    "path": item.name,
                    "source": item.source,
                    "sha256": sha256(item.source.read_bytes()).hexdigest()
                    if item.source is not None and item.source.is_file()
                    else None,
                }
        self.context = {
            "step_id": uuid4().hex,
            "step_started_at": now(),
            "block": block_id,
            "name": name,
            "implements": list(specs),
            "specifications": list(specs.values()),
            "manifest": {
                "path": "MANIFEST.md",
                "sha256": sha256(manifest.read_bytes()).hexdigest(),
                "plan_hash": plan.plan_hash,
                "state": plan.state,
                "nodes": [node_record(node) for node in steps],
                "acceptance_nodes": [
                    node_record(node)
                    for node in plan.blocks
                    if node.block_type == "ac" and node.parent in ids
                ],
            },
        }

    def record(
        self,
        *,
        started_at: str,
        result: object | None,
        attempt: int | None,
        status: str,
        details: Mapping[str, object],
        event: str = "execution",
    ) -> None:
        """Commit output, append its receipt, then commit Target state and receipt.

        The Target commit carries Build-Lineage-Id: its own SHA cannot occur inside
        the receipt it commits. The receipt records its parent and application SHA;
        the trailer and console line resolve the final Target checkpoint exactly.
        """
        record_id = uuid4().hex
        before = build_git.head(self.build_dir)
        if before != self.application_head:
            raise SpecificationError("Application Git HEAD changed during build execution")
        target_before = build_git.head(self.target_dir)
        block = self.context["block"]
        label = ", ".join(str(path) for path in self.context["implements"])
        subject = f"Build {block}: {label} [{status}]"
        message = f"{subject}\n\nBuild-Lineage-Id: {record_id}\nBuild-Run-Id: {self.run_id}"
        record = getattr(result, "record", None)
        artifacts = getattr(result, "artifacts", None)
        paths = artifacts.paths() if callable(getattr(artifacts, "paths", None)) else {}
        row = {
            "schema_version": 1,
            "record_id": record_id,
            "event": event,
            "run_id": self.run_id,
            "run_started_at": self.run_started_at,
            "run_log": self.run_log,
            "target": self.target,
            **self.context,
            "started_at": started_at,
            "completed_at": now(),
            "attempt": attempt,
            "execution_id": getattr(result, "execution_id", None),
            "status": status,
            "attribution_basis": "execution_scope",
            "stats": getattr(result, "stats", None),
            "execution": record,
            "artifacts": paths,
            "details": details,
            "application": {
                "repository": str(self.build_dir),
                "before_commit": before,
                "after_commit": None,
                "committed": False,
                "checkpoint_complete": False,
                "files": [],
            },
            "target_checkpoint": {
                "repository": str(self.target_dir),
                "before_commit": target_before,
                "commit_trailer": f"Build-Lineage-Id: {record_id}",
            },
        }
        self._save_pending(row, message)
        application_commit = build_git.checkpoint(self.build_dir, message)
        after = build_git.head(self.build_dir)
        row["application"].update(
            after_commit=after,
            committed=application_commit is not None,
            checkpoint_complete=True,
            files=build_git.changes(self.build_dir, before, after),
        )
        self._save_pending(row, message)
        self._append(row)
        # Force only the receipt: a broad user ignore must not silently lose lineage.
        build_git.git(self.target_dir, "add", "-f", "--", "BUILD_LINEAGE.jsonl")
        target_commit = build_git.checkpoint(self.target_dir, message)
        self._pending_path().unlink()
        self.application_head = build_git.head(self.build_dir)
        app_label = application_commit[:12] if application_commit else "unchanged"
        target_label = target_commit[:12] if target_commit else "unchanged"
        call = f"call={attempt + 1}" if attempt is not None else event
        self.emit(f"git: {block} | {label} | {call} | app={app_label} target={target_label}")

    def finish(self) -> None:
        """Checkpoint command epilogue artifacts without attributing them to a spec."""
        if not self.ready:
            return
        for root in dict.fromkeys((self.build_dir, self.target_dir)):
            commit = build_git.checkpoint(root, f"Complete drydock build {self.target}")
            if commit:
                self.emit(f"git: build complete {root.name} {commit[:12]}")
