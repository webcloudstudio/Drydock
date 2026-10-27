"""Regressions for configuration coverage and ineffective corpus repairs (October 2026)."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from drydock.acceptance import (
    AcceptanceRunResult,
    ProgrammaticAcceptance,
    run_programmatic_acceptance,
)
from drydock.acceptance_store import store_setup_defects
from drydock.build_run import _defective_acceptance_claim, _render_repair_feedback
from drydock.paths import get_language_dir


def _configuration_module():
    source = get_language_dir("python") / "acceptance" / "drydock_acceptance.py"
    spec = importlib.util.spec_from_file_location("drydock_acceptance", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_database_environment_restores_state_even_after_failure(monkeypatch, tmp_path):
    fixture = _configuration_module().database_environment
    canonical = tmp_path / "canonical.db"
    canonical.write_bytes(b"unchanged")
    monkeypatch.setenv("DATABASE_URL", str(canonical))
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    cwd = Path.cwd()
    with pytest.raises(RuntimeError, match="expected"):
        with fixture(url="sqlite://primary.db", path="fallback.db") as root:
            assert Path.cwd() == root
            assert os.environ["DATABASE_URL"] == "sqlite://" + str(root / "primary.db")
            assert os.environ["DATABASE_PATH"] == str(root / "fallback.db")
            assert not (root / "missing").exists()
            raise RuntimeError("expected")
    assert not root.exists()
    assert Path.cwd() == cwd
    assert os.environ["DATABASE_URL"] == str(canonical)
    assert "DATABASE_PATH" not in os.environ
    assert canonical.read_bytes() == b"unchanged"


@pytest.mark.parametrize(
    "value",
    ["/tmp/external.db", "../escape.db", "sqlite:///tmp/a.db", "postgres://host/db", ":memory:"],
)
def test_database_environment_refuses_paths_outside_its_scratch_directory(value):
    with pytest.raises(ValueError):
        with _configuration_module().database_environment(url=value):
            pytest.fail("unsafe configuration was admitted")


def test_database_environment_is_available_in_real_acceptance(tmp_path):
    code = """from drydock_acceptance import database_environment
import os
from pathlib import Path
with database_environment() as root:
    assert 'DATABASE_URL' not in os.environ
    assert 'DATABASE_PATH' not in os.environ
    Path('data').mkdir()
    Path('data/app.db').write_text('scratch')
with database_environment(url='missing/app.db') as root:
    assert not Path(os.environ['DATABASE_URL']).parent.exists()
"""
    assert store_setup_defects(code) == ()
    (result,) = run_programmatic_acceptance(
        (
            ProgrammaticAcceptance(
                check_id="config",
                code=code,
                source="FEATURE-Config.md",
                intent="Configuration isolation",
            ),
        ),
        build_dir=tmp_path,
        target_dir=tmp_path,
        blueprint_dir=tmp_path,
    )
    assert result.passed, result.stderr
    assert not (tmp_path / "data").exists()
    assert store_setup_defects("import os\nos.environ['DATABASE_URL']='other.db'")


def _failure(output=""):
    return AcceptanceRunResult(
        check_id="links-conformance",
        source="FEATURE-Links.md",
        intent="Links",
        passed=False,
        return_code=1,
        stdout=output,
        stderr="AssertionError",
    )


def test_parser_failure_description_does_not_dispute_acceptance():
    report = (
        "Scoped links conformance remains incomplete",
        "Remaining failures include multiline and malformed reference definitions, image integration, and autolink precedence.",
    )
    assert _defective_acceptance_claim(report, (_failure(),)) == ()
    assert _defective_acceptance_claim(
        ("The links-conformance check is malformed; it never runs the parser.",), (_failure(),)
    ) == ("links-conformance",)


def test_repair_feedback_contains_first_complete_failure_and_a_falsifiable_edit():
    output = (
        'Example 212 (lines 3415-3420) Link reference definitions\n[foo]: /url\n"title" ok\n\n--- expected HTML\n+++ actual HTML\n@@ -1 +1 @@\n-<p>&quot;title&quot; ok</p>\n+<p>[foo]: /url &quot;title&quot; ok</p>\n\n'
        + "unrelated tail\n" * 10
        + "110 passed, 7 failed, 0 errored, 538 skipped\n"
    )
    text = _render_repair_feedback(
        SimpleNamespace(),
        (_failure(output),),
        None,
        (),
        {},
        case_baseline={"links-conformance": 110},
    )
    assert "-<p>&quot;title&quot; ok</p>" in text
    assert "No measured improvement" in text
    assert "failing example" in text and "before editing" in text
    assert "executed" in text and "unrun" in text


def test_empty_interface_fields_do_not_discard_shared_repository_citations():
    from drydock.database_contract import parse_database_interface

    uses = parse_database_interface("""## Database Interface

- `FEATURE-ACCOUNT-005` — read: list accounts - returns: `account`, `name`
- `FEATURE-TXN-006` — write: delete transactions - supplies: `min_txn_id`
""")
    assert uses[0].identifier == "FEATURE-ACCOUNT-005"
    assert uses[0].supplies == ()
    assert uses[0].returns == ("account", "name")
    assert uses[1].supplies == ("min_txn_id",)
    assert uses[1].returns == ()


def test_current_batch_ledger_repeats_frozen_acceptance_obligations():
    from drydock.plan_graph import PlannedStory
    from drydock.plan_score import score_plan
    from drydock.planning_session import _render_ledger

    stages = (
        PlannedStory(
            story_id="core",
            implements="FEATURE-Core.md",
            provides=("core records",),
            fields={
                "instructions": "Test core records directly; defer enriched records to integration."
            },
        ),
        PlannedStory(
            story_id="enrichment",
            implements="FEATURE-Enrichment.md",
            depends=("core",),
            fields={"instructions": "Implement enrichment later."},
        ),
    )
    text = _render_ledger(score_plan(stages, {"TOPOLOGY.md": "complete"}), size=1, stories=stages)
    assert "Test core records directly; defer enriched records to integration." in text
    assert "provides: core records" in text
    assert "Implement enrichment later." not in text
