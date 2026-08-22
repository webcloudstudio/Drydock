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


_BROKEN_REGEX = """# FEATURE: Malformed Pattern

## Programmatic Acceptance

=== AC lexer-conformance-slice ===
Intent: Selects a conformance slice by pattern.

import re

SELECT = r'^(\\\\.|\\\\[|\\\\{|def)'
selector = re.compile(SELECT)
assert selector
=== END AC lexer-conformance-slice ===
"""

_FIXED_REGEX_BLOCK = """=== AC lexer-conformance-slice ===
Intent: Selects a conformance slice by pattern.

import re

SELECT = r'^(\\.|\\[|\\{|def)'
selector = re.compile(SELECT)
assert selector
=== END AC lexer-conformance-slice ===
"""

_BROKEN_STAGED_REGEX = """# FEATURE: Staged Runner Pattern

## Programmatic Acceptance

=== AC lexer-conformance ===
Intent: Selects lexical conformance cases through the staged runner.

import subprocess
import sys

selector = r"\\\\(|@format"
result = subprocess.run([sys.executable, "sources/run_conformance.py", "--select", selector])
assert result.returncode == 0
=== END AC lexer-conformance ===
"""

_FIXED_STAGED_REGEX_BLOCK = """=== AC lexer-conformance ===
Intent: Selects lexical conformance cases through the staged runner.

import subprocess
import sys

selector = r"\\(|@format"
result = subprocess.run([sys.executable, "sources/run_conformance.py", "--select", selector])
assert result.returncode == 0
=== END AC lexer-conformance ===
"""

_STAGED_REGEX_RUNNER = """import argparse
import re

parser = argparse.ArgumentParser()
parser.add_argument("--select")
args = parser.parse_args()
selector = re.compile(args.select) if args.select else None
"""


_WARNING_ONLY = """# FEATURE: Diagnostics

## Programmatic Acceptance

=== AC quiet-suite ===
Intent: Runs a suite and asserts overall success.

import subprocess

result = subprocess.run(["true"], capture_output=True)
assert result.returncode == 0
=== END AC quiet-suite ===
"""

_WARNING_ONLY_FIXED = """=== AC quiet-suite ===
Intent: Runs a suite and asserts overall success.

import subprocess

result = subprocess.run(["true"], capture_output=True)
print(result.returncode)
assert result.returncode == 0
=== END AC quiet-suite ===
"""

_BAD_CONTAINER = """# FEATURE: Container

## Programmatic Acceptance

=== AC first ===
Intent: First check.

assert True
=== END AC second ===

=== AC second ===
Intent: Second check.

assert True
=== END AC second ===
"""

_FIXED_CONTAINER = """=== BEGIN REPAIRED SPECIFICATION ===
# FEATURE: Container

## Programmatic Acceptance

=== AC first ===
Intent: First check.

assert True
=== END AC first ===

=== AC second ===
Intent: Second check.

assert True
=== END AC second ===
=== END REPAIRED SPECIFICATION ===
"""


_FUSED_CONTAINER = """# FEATURE: Container

## Programmatic Acceptance

=== AC first ===
Intent: First check.

assert True
=== END AC second ===
Intent: Second check.

assert True
=== END AC second ===
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


def test_a_warning_only_file_still_gets_a_repair_call(tmp_path):
    """A criterion with no defect but an advisory is not unreachable: it is its own call."""
    target = _target(tmp_path, FEATURE_Diagnostics=_WARNING_ONLY)
    assert verify("Demo", target).ok  # confirms the fixture is warning-only, not defective
    runner = _runner(_WARNING_ONLY_FIXED)

    result = repair("Demo", target, runner=runner)

    assert len(runner.calls) == 1
    prompt = runner.calls[0]["prompt"]
    assert "Criteria to improve" in prompt
    assert "quiet-suite" in prompt
    assert "prints none of it" in prompt
    assert result.files_changed == ("FEATURE_Diagnostics.md",)
    (item,) = [i for i in result.items if i.check_id == "quiet-suite"]
    assert item.status == "repaired"
    text = (target / "blueprint" / "FEATURE_Diagnostics.md").read_text(encoding="utf-8")
    assert "print(result.returncode)" in text


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


def test_a_bad_acceptance_container_gets_one_delimiter_only_repair_attempt(tmp_path):
    target = _target(tmp_path, FEATURE_Container=_BAD_CONTAINER)
    runner = _runner(_FIXED_CONTAINER)

    result = repair("Demo", target, runner=runner)

    assert result.ok
    assert result.files_changed == ("FEATURE_Container.md",)
    assert verify("Demo", target).ok
    assert "Bad acceptance container" in runner.calls[0]["prompt"]
    (item,) = result.items
    assert item.check_id == ""
    assert item.status == "repaired"


def test_a_fused_acceptance_boundary_is_repaired_deterministically_without_a_model_call(tmp_path):
    """The recurring live-jq defect: one opener, a closer naming the next criterion, duplicated
    at the real end. This is mechanically decidable, so it must not cost an LLM call — and must
    not fail the way the LLM-based repair failed on every attempt in the real run."""
    target = _target(tmp_path, FEATURE_Container=_FUSED_CONTAINER)

    def unreachable_runner(prompt, cwd, **kwargs):
        raise AssertionError("the deterministic fused-boundary fix must not call the runner")

    result = repair("Demo", target, runner=unreachable_runner)

    assert result.ok
    assert result.files_changed == ("FEATURE_Container.md",)
    assert verify("Demo", target).ok
    (item,) = result.items
    assert item.status == "repaired"
    assert "deterministically" in item.detail
    text = (target / "blueprint" / "FEATURE_Container.md").read_text(encoding="utf-8")
    assert "=== END AC first ===" in text
    assert "=== AC second ===" in text


def test_a_bad_container_repair_cannot_change_non_delimiter_content(tmp_path):
    target = _target(tmp_path, FEATURE_Container=_BAD_CONTAINER)
    unsafe = _FIXED_CONTAINER.replace("assert True", "assert False", 1)

    result = repair("Demo", target, runner=_runner(unsafe))

    assert not result.ok
    assert result.items[0].status == "unrepaired"
    assert "other than AC delimiters" in result.items[0].detail
    assert (target / "blueprint" / "FEATURE_Container.md").read_text(
        encoding="utf-8"
    ) == _BAD_CONTAINER


def test_an_uncompilable_regex_pattern_is_repaired_and_verifies(tmp_path):
    """The jq-run defect: a raw string escapes the backslash, not the bracket after it."""
    target = _target(tmp_path, FEATURE_Bad=_BROKEN_REGEX)

    result = repair("Demo", target, runner=_runner(_FIXED_REGEX_BLOCK))

    assert result.ok
    assert result.files_changed == ("FEATURE_Bad.md",)
    assert verify("Demo", target).ok


def test_a_staged_runner_regex_is_repaired_and_reverified(tmp_path):
    target = _target(tmp_path, FEATURE_Bad=_BROKEN_STAGED_REGEX)
    sources = target / "blueprint" / "sources"
    sources.mkdir()
    (sources / "run_conformance.py").write_text(_STAGED_REGEX_RUNNER, encoding="utf-8")

    result = repair("Demo", target, runner=_runner(_FIXED_STAGED_REGEX_BLOCK))

    assert result.ok
    assert result.files_changed == ("FEATURE_Bad.md",)
    assert verify("Demo", target).ok


def test_a_block_emitted_without_a_trailing_newline_still_splices(tmp_path):
    """A model that ends its last block at EOF must not glue the delimiter to the next section."""
    spec = _BROKEN + "\n## User Acceptance\n\n- None.\n"
    target = _target(tmp_path, FEATURE_Path=spec)

    result = repair("Demo", target, runner=_runner(_FIXED_BLOCK.rstrip("\n")))

    assert result.ok, [item.rendered for item in result.outstanding]
    text = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")
    assert "=== END AC path-filter ===\n" in text
    assert "## User Acceptance" in text
    assert verify("Demo", target).ok


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


def test_an_unparseable_file_gets_one_constrained_container_repair_attempt(tmp_path):
    target = _target(tmp_path, FEATURE_Broken="=== AC orphan ===\nIntent: x\n\nassert True\n")
    runner = _runner(_FIXED_BLOCK)

    result = repair("Demo", target, runner=runner)

    assert not result.ok
    assert result.items[0].status == "unrepaired"
    assert "no repaired specification returned" in result.items[0].detail
    assert len(runner.calls) == 1
    assert "Bad acceptance container" in runner.calls[0]["prompt"]


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


def test_a_files_advisories_ride_along_with_the_call_it_is_already_paying_for(tmp_path):
    """An advisory never buys a model call of its own; it goes with one already being made."""
    silent = _BROKEN.replace("result = subprocess.run", "captured = None\nresult = subprocess.run")
    target = _target(tmp_path, FEATURE_Path=silent)
    runner = _runner(_FIXED_BLOCK)

    repair("Demo", target, runner=runner)

    prompt = runner.calls[0]["prompt"]
    assert "Advisories for this file" in prompt
    assert "prints none of it" in prompt


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
