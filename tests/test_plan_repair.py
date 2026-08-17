"""Tests for ``drydock plan repair`` — one pass, surgical writes, no fabricated success.

Every test injects a fake runner. Nothing here spends credits or touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from drydock.plan_repair import _assemble, repair
from drydock.plan_verify import verify

_BROKEN = """# FEATURE: Path Discovery

## Programmatic Acceptance

=== AC path-filter ===
Intent: Filtered paths select only matching locations.

import subprocess

result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)
assert result.returncode == 0
=== END AC path-filter ===

=== AC paths-recursive ===
Intent: Recursive discovery reports non-root paths.

import json

assert json.loads("[1]") == [1]
=== END AC paths-recursive ===
"""

_FIXED_BLOCK = """=== AC path-filter ===
Intent: Filtered paths select only matching locations.

import os
import subprocess

result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)
assert result.returncode == 0
=== END AC path-filter ===
"""


@dataclass
class _Run:
    text: str
    ok: bool = True
    execution_id: str = "exec-1"


def _runner(text: str, *, ok: bool = True):
    calls: list[dict] = []

    def run(prompt, cwd, **kwargs):
        calls.append({"prompt": prompt, "cwd": cwd, **kwargs})
        return _Run(text, ok=ok)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _target(tmp_path, **specs: str):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    for name, text in specs.items():
        (blueprint / f"{name}.md").write_text(text, encoding="utf-8")
    return target


def test_nothing_to_repair_makes_no_model_call(tmp_path):
    """The whole point of the verify/repair split: the paid call is skipped when it is not needed."""
    target = _target(tmp_path, FEATURE_Ok="## Programmatic Acceptance\n")
    runner = _runner("")

    result = repair("Demo", target, runner=runner)

    assert result.nothing_to_repair
    assert result.ok
    assert runner.calls == []


def test_a_repaired_criterion_is_spliced_in_and_verifies(tmp_path):
    target = _target(tmp_path, FEATURE_Path=_BROKEN)

    result = repair("Demo", target, runner=_runner(_FIXED_BLOCK))

    assert result.ok
    assert result.files_changed == ("FEATURE_Path.md",)
    assert verify("Demo", target).ok
    text = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")
    assert "import os" in text
    # The untouched criterion is preserved byte for byte.
    assert "=== AC paths-recursive ===" in text
    assert 'assert json.loads("[1]") == [1]' in text


def test_only_the_defective_criterion_is_replaced(tmp_path):
    """A bonus block for a healthy criterion is ignored; repair rewrites what it was asked to."""
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    smuggled = _FIXED_BLOCK + (
        "\n=== AC paths-recursive ===\nIntent: Rewritten.\n\nassert True\n"
        "=== END AC paths-recursive ===\n"
    )

    repair("Demo", target, runner=_runner(smuggled))

    text = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")
    assert 'assert json.loads("[1]") == [1]' in text
    assert "Intent: Rewritten." not in text


def test_a_criterion_still_broken_is_reported_not_claimed(tmp_path):
    """One attempt. A repair that did not work says so rather than being counted as success."""
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    unchanged = _BROKEN.split("=== AC paths-recursive ===")[0].strip() + "\n"

    result = repair("Demo", target, runner=_runner(unchanged))

    assert not result.ok
    assert result.exit_code() == 1
    (item,) = [i for i in result.items if i.check_id == "path-filter"]
    assert item.status == "unrepaired"
    assert "`os`" in item.detail


def test_exactly_one_call_is_made_per_file(tmp_path):
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    runner = _runner(_BROKEN)

    repair("Demo", target, runner=runner)

    assert len(runner.calls) == 1


def test_an_impossible_repair_is_recorded_and_the_file_is_untouched(tmp_path):
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    before = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")

    result = repair(
        "Demo",
        target,
        runner=_runner("REPAIR_IMPOSSIBLE: path-filter — the assertion would have to change\n"),
    )

    assert not result.ok
    (item,) = [i for i in result.items if i.check_id == "path-filter"]
    assert item.status == "impossible"
    assert (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8") == before


def test_a_missing_block_is_reported_as_not_emitted(tmp_path):
    target = _target(tmp_path, FEATURE_Path=_BROKEN)

    result = repair("Demo", target, runner=_runner("I could not do it.\n"))

    (item,) = [i for i in result.items if i.check_id == "path-filter"]
    assert item.status == "not-emitted"


def test_a_repair_that_breaks_the_file_is_reverted_whole(tmp_path):
    """A splice can never leave the Blueprint worse than it found it."""
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    spec = target / "blueprint" / "FEATURE_Path.md"
    before = spec.read_text(encoding="utf-8")
    # A repaired block carrying an unclosed opener inside its body: the splice succeeds, the
    # resulting file does not parse, and the whole write must be undone.
    poisoned = (
        "=== AC path-filter ===\n"
        "Intent: Filtered paths select only matching locations.\n\n"
        "import os\n\n"
        "=== AC smuggled ===\n"
        "assert os is not None\n"
        "=== END AC path-filter ===\n"
    )

    result = repair("Demo", target, runner=_runner(poisoned))

    assert spec.read_text(encoding="utf-8") == before
    assert not result.ok
    assert "reverted" in result.outstanding[0].detail


def test_a_failed_execution_leaves_the_file_alone(tmp_path):
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    before = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")

    result = repair("Demo", target, runner=_runner("", ok=False))

    assert not result.ok
    assert (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8") == before
    assert result.outstanding[0].detail == "LLM execution failed"


def test_an_unparseable_file_is_declined_rather_than_guessed_at(tmp_path):
    target = _target(tmp_path, FEATURE_Broken="=== AC orphan ===\nIntent: x\n\nassert True\n")
    runner = _runner(_FIXED_BLOCK)

    result = repair("Demo", target, runner=runner)

    assert not result.ok
    assert result.items[0].status == "impossible"
    assert runner.calls == []


# ── prompt assembly ───────────────────────────────────────────────────────────


def test_the_prompt_names_every_defective_criterion_and_carries_the_file(tmp_path):
    from drydock.plan_verify import verify as run_verify

    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    defects = list(run_verify("Demo", target).defects)

    assembly = _assemble("BODY", rel_source="FEATURE_Path.md", source_text=_BROKEN, defects=defects)

    rendered = assembly.rendered_text
    assert "path-filter" in rendered
    assert "reads undefined global name" in rendered
    assert 'filename="FEATURE_Path.md"' in rendered
    assert rendered.rstrip().endswith("BODY")


def test_the_repair_prompt_forbids_changing_an_assertion():
    from drydock.prompts import load_prompt

    body = " ".join(load_prompt("plan_repair").body.split())

    assert "Repair the mechanics. Never touch the assertion." in body
    assert "REPAIR_IMPOSSIBLE" in body
    assert "pytest.skip" in body


@pytest.mark.parametrize("missing", ["blueprint"])
def test_a_missing_blueprint_is_an_error(tmp_path, missing):
    from drydock.errors import SpecificationError

    (tmp_path / "Demo").mkdir()

    with pytest.raises(SpecificationError):
        repair("Demo", tmp_path / "Demo", runner=_runner(""))
