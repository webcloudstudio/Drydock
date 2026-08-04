from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.source_refit import (
    SourceDeletionDecision,
    source_refit_target,
    update_import,
)


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "fake"


def _manifest(source: str) -> str:
    return f'''# MANIFEST: Demo
state: approved
source_lineage: |
  {{"version": 1, "files": {{"{source}": {{"hash": "old", "blueprints": ["FEATURE-Demo.md"]}}}}}}

## story 1: Demo
id: demo
summary: Demo
implements: FEATURE-Demo.md
state: closed/verified
'''


def _target(tmp_path: Path, source_root: Path) -> Path:
    target = tmp_path / "Demo"
    sources = target / "blueprint" / "sources"
    sources.mkdir(parents=True)
    (sources / ".drydock-import").write_text(
        f"source: {source_root}\nformat: markdown\n", encoding="utf-8"
    )
    (target / "MANIFEST.md").write_text(_manifest("change.md"), encoding="utf-8")
    (target / "blueprint" / "FEATURE-Demo.md").write_text("# FEATURE: Demo\n", encoding="utf-8")
    return target


def test_update_import_copies_changed_files_and_records_pending_change(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path, source)
    (target / "blueprint" / "sources" / "change.md").write_text("old\n", encoding="utf-8")

    result = update_import(target)

    assert result.changed == ("change.md",)
    assert (target / "blueprint" / "sources" / "change.md").read_text() == "new\n"
    assert '"pending_change":true' in (target / "MANIFEST.md").read_text()


def test_update_import_blocks_deleted_files(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    target = _target(tmp_path, source)
    (target / "blueprint" / "sources" / "removed.md").write_text("old\n", encoding="utf-8")

    with pytest.raises(SourceDeletionDecision, match="removed.md"):
        update_import(target)


def test_source_refit_writes_ordered_ticket_and_manifest_story(tmp_path):
    source = tmp_path / "authoring"
    source.mkdir()
    (source / "change.md").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path, source)
    sources = target / "blueprint" / "sources"
    (sources / "change.md").write_text("old\n", encoding="utf-8")
    update_import(target)

    def runner(prompt, working_directory, **kwargs):
        return FakeRun(text="exact change specification\n")

    result = source_refit_target(target, runner=runner)

    ticket = target / "blueprint" / "FEATURE-Demo_refit_1.md"
    assert result.items[0].ticket == ticket
    ticket_text = ticket.read_text()
    assert "| Blueprint | FEATURE-Demo.md |" in ticket_text
    assert "exact change specification" in ticket_text
    manifest = (target / "MANIFEST.md").read_text()
    assert "implements: FEATURE-Demo_refit_1.md" in manifest
    assert '"pending_change"' not in manifest
