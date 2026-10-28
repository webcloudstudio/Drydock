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

#: Both criteria defective — for tests that need two defects sharing one file.
_BROKEN_TWO = """# FEATURE: Path Discovery

## Programmatic Acceptance

=== AC path-filter ===
Intent: Filtered paths select only matching locations.

import subprocess

result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)
assert result.returncode == 0
=== END AC path-filter ===

=== AC paths-recursive ===
Intent: Recursive discovery reports non-root paths.

assert json.loads("[1]") == [1]
=== END AC paths-recursive ===
"""


def _fixed_block(filename: str, check_id: str, body: str) -> str:
    """Build one composite-keyed response block, as the model would emit it."""
    return f"=== AC {filename} :: {check_id} ===\n{body}\n=== END AC {filename} :: {check_id} ===\n"


_FIXED_BLOCK = _fixed_block(
    "FEATURE_Path.md",
    "path-filter",
    "Intent: Filtered paths select only matching locations.\n\n"
    "import os\n"
    "import subprocess\n\n"
    'result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)\n'
    "assert result.returncode == 0",
)


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

_FIXED_REGEX_BLOCK = _fixed_block(
    "FEATURE_Bad.md",
    "lexer-conformance-slice",
    "Intent: Selects a conformance slice by pattern.\n\n"
    "import re\n\n"
    "SELECT = r'^(\\.|\\[|\\{|def)'\n"
    "selector = re.compile(SELECT)\n"
    "assert selector",
)

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

_FIXED_STAGED_REGEX_BLOCK = _fixed_block(
    "FEATURE_Bad.md",
    "lexer-conformance",
    "Intent: Selects lexical conformance cases through the staged runner.\n"
    "Probe: --list\n"
    "Probe Count: lines\n\n"
    "import subprocess\n"
    "import sys\n\n"
    'selector = r"\\(|@format"\n'
    'result = subprocess.run([sys.executable, "sources/run_conformance.py", "--select", selector])\n'
    "assert result.returncode == 0",
)

_STAGED_REGEX_RUNNER = """import argparse
import re

parser = argparse.ArgumentParser()
parser.add_argument("--select")
parser.add_argument("--list", action="store_true")
args = parser.parse_args()
selector = re.compile(args.select) if args.select else None
if args.list:
    print("case-1")
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


_PROBE_RUNNER = """import argparse

CASES = ["alpha", "beta", "gamma"]

parser = argparse.ArgumentParser()
parser.add_argument("--select")
parser.add_argument("--list", action="store_true")
args = parser.parse_args()
selected = [c for c in CASES if args.select in c] if args.select else CASES
if args.list:
    for case in selected:
        print(case)
"""

_BROKEN_MISSING_PROBE = """# FEATURE: Selector

## Programmatic Acceptance

=== AC select-alpha ===
Intent: Selects a conformance slice through the staged runner.

import subprocess
import sys

result = subprocess.run(
    [sys.executable, "sources/run_probe.py", "--select", "alpha"],
    capture_output=True, text=True,
)
assert result.returncode == 0
=== END AC select-alpha ===
"""

_FIXED_PROBE_BLOCK = _fixed_block(
    "FEATURE_Selector.md",
    "select-alpha",
    "Intent: Selects a conformance slice through the staged runner.\n"
    "Probe: --list\n"
    "Probe Count: lines\n\n"
    "import subprocess\n"
    "import sys\n\n"
    "result = subprocess.run(\n"
    '    [sys.executable, "sources/run_probe.py", "--select", "alpha"],\n'
    "    capture_output=True, text=True,\n"
    ")\n"
    "assert result.returncode == 0",
)

_STILL_EMPTY_PROBE_BLOCK = _fixed_block(
    "FEATURE_Selector.md",
    "select-alpha",
    "Intent: Selects a conformance slice through the staged runner.\n"
    "Probe: --list\n"
    "Probe Count: lines\n\n"
    "import subprocess\n"
    "import sys\n\n"
    "result = subprocess.run(\n"
    '    [sys.executable, "sources/run_probe.py", "--select", "zzz"],\n'
    "    capture_output=True, text=True,\n"
    ")\n"
    "assert result.returncode == 0",
)


def _probe_target(tmp_path, **specs: str):
    target = _target(tmp_path, **specs)
    sources = target / "blueprint" / "sources"
    sources.mkdir()
    (sources / "run_probe.py").write_text(_PROBE_RUNNER, encoding="utf-8")
    return target


def test_a_missing_selection_probe_is_repaired_and_reverified(tmp_path):
    target = _probe_target(tmp_path, FEATURE_Selector=_BROKEN_MISSING_PROBE)

    result = repair("Demo", target, runner=_runner(_FIXED_PROBE_BLOCK))

    assert result.ok
    assert result.files_changed == ("FEATURE_Selector.md",)
    assert verify("Demo", target).ok


def test_a_selector_still_empty_after_repair_stays_unrepaired(tmp_path):
    """A declared probe that still proves zero cases is not a successful repair."""
    target = _probe_target(
        tmp_path, FEATURE_Selector=_BROKEN_MISSING_PROBE.replace('"alpha"', '"zzz"')
    )

    result = repair("Demo", target, runner=_runner(_STILL_EMPTY_PROBE_BLOCK))

    assert not result.ok
    assert result.items[0].status == "unrepaired"
    assert not verify("Demo", target).ok


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
        "\n"
        + _fixed_block("FEATURE_Path.md", "paths-recursive", "Intent: Rewritten.\n\nassert True")
    )

    repair("Demo", target, runner=_runner(smuggled))

    text = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")
    assert 'assert json.loads("[1]") == [1]' in text
    assert "Intent: Rewritten." not in text


def test_a_criterion_still_broken_is_reported_not_claimed(tmp_path):
    """One attempt. A repair that did not work says so rather than being counted as success."""
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    still_broken = _fixed_block(
        "FEATURE_Path.md",
        "path-filter",
        "Intent: Filtered paths select only matching locations.\n\n"
        "import subprocess\n\n"
        'result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)\n'
        "assert result.returncode == 0",
    )

    result = repair("Demo", target, runner=_runner(still_broken))

    assert not result.ok
    assert result.exit_code() == 1
    (item,) = [i for i in result.items if i.check_id == "path-filter"]
    assert item.status == "unrepaired"
    assert "`os`" in item.detail


def test_exactly_one_call_is_made_for_the_whole_pass(tmp_path):
    """One call covers every defective criterion across every file, not one call per file."""
    target = _target(tmp_path, FEATURE_Path=_BROKEN, FEATURE_Bad=_BROKEN_REGEX)
    response = _FIXED_BLOCK + "\n" + _FIXED_REGEX_BLOCK
    runner = _runner(response)

    result = repair("Demo", target, runner=runner)

    assert len(runner.calls) == 1
    assert result.ok
    assert set(result.files_changed) == {"FEATURE_Path.md", "FEATURE_Bad.md"}


def test_an_impossible_repair_is_recorded_and_the_file_is_untouched(tmp_path):
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    before = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")

    result = repair(
        "Demo",
        target,
        runner=_runner(
            "REPAIR_IMPOSSIBLE: FEATURE_Path.md :: path-filter — "
            "the assertion would have to change\n"
        ),
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
        "=== AC FEATURE_Path.md :: path-filter ===\n"
        "Intent: Filtered paths select only matching locations.\n\n"
        "import os\n\n"
        "=== AC smuggled ===\n"
        "assert os is not None\n"
        "=== END AC FEATURE_Path.md :: path-filter ===\n"
    )

    result = repair("Demo", target, runner=_runner(poisoned))

    assert spec.read_text(encoding="utf-8") == before
    assert not result.ok
    assert "reverted" in result.outstanding[0].detail


def test_only_the_broken_criterion_reverts_the_sibling_stays_fixed(tmp_path):
    """Per-criterion revert: one file, two defects, one fixed and one still broken in the same
    call — the fix stays spliced in; only the still-broken criterion reverts."""
    target = _target(tmp_path, FEATURE_Path=_BROKEN_TWO)
    fixed = _fixed_block(
        "FEATURE_Path.md",
        "path-filter",
        "Intent: Filtered paths select only matching locations.\n\n"
        "import os\n"
        "import subprocess\n\n"
        'result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)\n'
        "assert result.returncode == 0",
    )
    # paths-recursive comes back unchanged: still missing its `json` import.
    still_broken = _fixed_block(
        "FEATURE_Path.md",
        "paths-recursive",
        'Intent: Recursive discovery reports non-root paths.\n\nassert json.loads("[1]") == [1]',
    )
    response = fixed + "\n" + still_broken

    result = repair("Demo", target, runner=_runner(response))

    assert not result.ok
    (path_filter,) = [i for i in result.items if i.check_id == "path-filter"]
    (paths_recursive,) = [i for i in result.items if i.check_id == "paths-recursive"]
    assert path_filter.status == "repaired"
    assert paths_recursive.status == "unrepaired"
    assert "`json`" in paths_recursive.detail
    text = (target / "blueprint" / "FEATURE_Path.md").read_text(encoding="utf-8")
    assert "import os" in text  # the fix stayed spliced in
    assert "import json" not in text  # the broken criterion's original body came back verbatim


def test_the_same_check_id_in_two_files_is_repaired_independently(tmp_path):
    """Composite keying: two files that happen to reuse a check_id do not cross-contaminate."""
    broken_a = (
        "# FEATURE: A\n\n## Programmatic Acceptance\n\n=== AC shared-check ===\n"
        "Intent: A's own check.\n\nassert os.getcwd()\n=== END AC shared-check ===\n"
    )
    broken_b = (
        "# FEATURE: B\n\n## Programmatic Acceptance\n\n=== AC shared-check ===\n"
        "Intent: B's own check.\n\nassert json.loads('1') == 1\n=== END AC shared-check ===\n"
    )
    target = _target(tmp_path, FEATURE_A=broken_a, FEATURE_B=broken_b)
    fixed_a = _fixed_block(
        "FEATURE_A.md", "shared-check", "Intent: A's own check.\n\nimport os\n\nassert os.getcwd()"
    )
    fixed_b = _fixed_block(
        "FEATURE_B.md",
        "shared-check",
        "Intent: B's own check.\n\nimport json\n\nassert json.loads('1') == 1",
    )
    runner = _runner(fixed_a + "\n" + fixed_b)

    result = repair("Demo", target, runner=runner)

    assert result.ok
    text_a = (target / "blueprint" / "FEATURE_A.md").read_text(encoding="utf-8")
    text_b = (target / "blueprint" / "FEATURE_B.md").read_text(encoding="utf-8")
    assert "import os" in text_a and "import json" not in text_a
    assert "import json" in text_b and "import os" not in text_b


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
    from drydock.plan_repair import _block_bodies

    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    defects = list(verify("Demo", target).defects)
    bodies = _block_bodies(_BROKEN)
    jobs = [(defect, bodies[defect.check_id]) for defect in defects]

    assembly = _assemble("BODY", jobs=jobs)

    rendered = assembly.rendered_text
    assert "path-filter" in rendered
    assert "reads undefined global name" in rendered
    assert 'file="FEATURE_Path.md"' in rendered
    assert rendered.rstrip().endswith("BODY")


def test_the_request_omits_the_files_own_heading_and_healthy_siblings(tmp_path):
    """Minimal context: the request never carries a file's heading or its healthy siblings."""
    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    runner = _runner(_FIXED_BLOCK)

    repair("Demo", target, runner=runner)

    prompt = runner.calls[0]["prompt"]
    assert "path-filter" in prompt
    assert "# FEATURE: Path Discovery" not in prompt
    assert 'assert json.loads("[1]") == [1]' not in prompt


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


def test_a_persistence_defect_is_never_handed_to_the_criterion_prompt(tmp_path):
    """``plan repair`` rewrites acceptance criteria. Sent DATABASE.md as a "container", it would
    rewrite the declaration as one; the defect stays outstanding so the command cannot pass."""
    database = (
        "# DATABASE: Demo\n\n## Access Patterns\n\n### FEATURE-X-001 — Store setting\n\n"
        "| Field | Value |\n|---|---|\n| Owner | FEATURE_Ok.md |\n| Access | read |\n"
        "| Repository operation | `settings.get` |\n| Compatibility | data |\n\n"
        "## `settings`\n\n| Field | Type | Notes |\n|---|---|---|\n| key | TEXT PK | |\n"
    )
    target = _target(tmp_path, DATABASE=database, FEATURE_Ok="## Programmatic Acceptance\n")
    runner = _runner("")

    result = repair("Demo", target, runner=runner)

    assert runner.calls == []
    assert not result.ok
    (item,) = result.outstanding
    assert item.filename == "DATABASE.md"
    assert "drydock plan Demo" in item.detail


_GO_BROKEN = (
    "# FEATURE: CLI\n\n## Programmatic Acceptance\n\n"
    "=== AC usage ===\nIntent: Missing arguments exit 2 with empty stdout.\n"
    "import subprocess\n"
    'result = subprocess.run(["go", "run", "./cmd/dupfind"], capture_output=True, text=True)\n'
    "assert result.returncode == 2\nassert result.stdout == ''\n"
    "=== END AC usage ===\n"
)


@pytest.mark.parametrize("fenced", [False, True])
def test_go_repair_preserves_exit_and_output_assertions(tmp_path, monkeypatch, fenced):
    """DupFind: repaired Go criteria compile and call the variadic client correctly."""
    import sys
    from types import SimpleNamespace

    from drydock.acceptance import parse_programmatic_acceptance

    target = _target(tmp_path, FEATURE_Cli=_GO_BROKEN)
    proof = (
        "from drydock_go import cli_runner\n"
        "code, out, err = cli_runner()\n"
        "assert code == 2\nassert out == ''"
    )
    if fenced:
        proof = "```python\n" + proof + "\n```"
    response = _fixed_block(
        "FEATURE_Cli.md", "usage", "Intent: Missing arguments exit 2 with empty stdout.\n" + proof
    )
    runner = _runner(response)
    result = repair("Demo", target, runner=runner)
    assert result.ok, result.items
    assert verify("Demo", target).ok
    (check,) = parse_programmatic_acceptance(target / "blueprint/FEATURE_Cli.md")
    calls = []

    def cli_runner(*args):
        calls.append(args)
        return 2, "", "usage"

    monkeypatch.setitem(sys.modules, "drydock_go", SimpleNamespace(cli_runner=cli_runner))
    exec(compile(check.code, "<criterion>", "exec"), {})
    assert calls == [()]
    assert 'cli_runner("--summary", ".")' in runner.calls[0]["prompt"]
    assert "*args: str" in runner.calls[0]["prompt"]


@pytest.mark.parametrize(
    "proof",
    [
        "from drydock_go import cli_runner\ncode, out, err = cli_runner([])\nassert code == 2",
        "import subprocess\nr = subprocess.run(['go', 'run', './cmd/dupfind'])\nassert r.returncode == 2",
        "import subprocess\nr = subprocess.run(['./cmd/dupfind'])\nassert r.returncode == 2",
    ],
)
def test_go_repair_still_using_an_invalid_launcher_is_reverted(tmp_path, proof):
    from drydock.technology_stack import StackEntry, write

    target = _target(tmp_path, FEATURE_Cli=_GO_BROKEN)
    write(target, [StackEntry("Go", "go.md")])
    response = _fixed_block("FEATURE_Cli.md", "usage", "Intent: Usage.\n" + proof)
    result = repair("Demo", target, runner=_runner(response))
    assert not result.ok
    assert result.files_changed == ()
    assert (target / "blueprint/FEATURE_Cli.md").read_text() == _GO_BROKEN


def test_repair_keeps_embedded_fences_and_rejects_text_outside_a_fence():
    from drydock.plan_repair import _response_blocks

    literal = (
        'Intent: Preserve markup.\nsample = """\n```python\nassert False\n```\n"""\nassert sample\n'
    )
    body = _response_blocks(_fixed_block("FEATURE_Cli.md", "usage", literal))
    assert body[("FEATURE_Cli.md", "usage")] == literal + "\n"
    bad = "Intent: Bad.\n```python\nassert True\n```\nUnrequested explanation."
    assert (
        _response_blocks(_fixed_block("FEATURE_Cli.md", "usage", bad))[("FEATURE_Cli.md", "usage")]
        == bad + "\n"
    )


@pytest.mark.parametrize("byte_streams", [False, True])
def test_package_launch_repair_keeps_arguments_and_assertions(tmp_path, monkeypatch, byte_streams):
    import sys
    from types import SimpleNamespace

    from drydock.acceptance import parse_programmatic_acceptance

    broken = _GO_BROKEN.replace('["go", "run", "./cmd/dupfind"]', '["./cmd/dupfind"]')
    if byte_streams:
        broken = broken.replace(
            "assert result.stdout == ''",
            "print(result.stdout.decode())\nassert result.stdout == b''",
        ).replace(", text=True", "")
    from drydock.technology_stack import StackEntry, write

    target = _target(tmp_path, FEATURE_Cli=broken)
    write(target, [StackEntry("Go", "go.md")])
    output_assertion = (
        "print(out)\nassert out.encode() == b''" if byte_streams else "assert out == ''"
    )
    proof = (
        "Intent: Missing arguments exit 2 with empty stdout.\n"
        "from drydock_go import cli_runner\ncode, out, err = cli_runner()\n"
        "assert code == 2\n" + output_assertion
    )
    runner = _runner(_fixed_block("FEATURE_Cli.md", "usage", proof))
    result = repair("Demo", target, runner=runner)
    assert result.ok, result.items
    assert "go-package-launch" in runner.calls[0]["prompt"]
    calls = []

    def cli_runner(*args):
        calls.append(args)
        return 2, "", "usage"

    monkeypatch.setitem(sys.modules, "drydock_go", SimpleNamespace(cli_runner=cli_runner))
    (check,) = parse_programmatic_acceptance(target / "blueprint/FEATURE_Cli.md")
    exec(compile(check.code, "<criterion>", "exec"), {})
    assert calls == [()]


_BAD_CITATION_BODY = (
    "Intent: The banner matches the source.\n"
    "Cite: sources/spec.txt:1\n\n"
    "out = object()\n"
    'assert out == r"C:\\Users\\Welcome"\n'
)


def _citation_target(tmp_path):
    spec = (
        "# FEATURE: Cited\n\n## Programmatic Acceptance\n\n"
        "=== AC banner ===\n" + _BAD_CITATION_BODY + "=== END AC banner ===\n"
    )
    target = _target(tmp_path, FEATURE_Cited=spec)
    sources = target / "blueprint" / "sources"
    sources.mkdir()
    (sources / "spec.txt").write_text("Unrelated title\nC:\\Users\\Welcome\n", encoding="utf-8")
    (sources / "unrelated.txt").write_text("DO NOT INJECT THIS SOURCE", encoding="utf-8")
    return target


def test_citation_repair_receives_numbered_source_and_preserves_the_proof(tmp_path):
    target = _citation_target(tmp_path)
    path = target / "blueprint" / "FEATURE_Cited.md"
    original = path.read_text()
    fixed = _BAD_CITATION_BODY.replace("spec.txt:1", "spec.txt:2")
    runner = _runner(_fixed_block("FEATURE_Cited.md", "banner", fixed))

    result = repair("Demo", target, runner=runner)

    assert result.ok
    assert verify("Demo", target).ok
    assert path.read_text() == original.replace("spec.txt:1", "spec.txt:2")
    prompt = runner.calls[0]["prompt"]
    assert "1: Unrelated title\n2: C:\\Users\\Welcome" in prompt
    assert "DO NOT INJECT THIS SOURCE" not in prompt
    assert "correct only the existing `Cite:` declaration" in prompt


@pytest.mark.parametrize("cite", ["sources/spec.txt:1", "sources/spec.txt:999", ""])
def test_invalid_citation_repair_is_reverted(tmp_path, cite):
    target = _citation_target(tmp_path)
    path = target / "blueprint" / "FEATURE_Cited.md"
    original = path.read_text()
    body = _BAD_CITATION_BODY.replace("sources/spec.txt:1", cite)

    result = repair(
        "Demo", target, runner=_runner(_fixed_block("FEATURE_Cited.md", "banner", body))
    )

    assert not result.ok
    assert result.items[0].status == "unrepaired"
    assert path.read_text() == original
    assert not verify("Demo", target).ok


@pytest.mark.parametrize(
    "changed",
    [
        lambda body: body.replace('assert out == r"C:\\Users\\Welcome"', "assert True"),
        lambda body: body.replace("out = object()", "out = 0"),
        lambda body: body.replace("The banner matches the source.", "Any banner is fine."),
        lambda body: body.replace("Cite: sources/spec.txt:2\n", ""),
    ],
)
def test_citation_repair_rejects_changes_outside_the_declaration(tmp_path, changed):
    target = _citation_target(tmp_path)
    path = target / "blueprint" / "FEATURE_Cited.md"
    original = path.read_text()
    body = changed(_BAD_CITATION_BODY.replace("spec.txt:1", "spec.txt:2"))

    result = repair(
        "Demo", target, runner=_runner(_fixed_block("FEATURE_Cited.md", "banner", body))
    )

    assert not result.ok
    assert "other than Cite" in result.items[0].detail
    assert path.read_text() == original


@pytest.mark.parametrize(
    "cites", ["Cite: sources/spec.txt:2\n", "Cite: sources/spec.txt:1\nCite: sources/spec.txt:2\n"]
)
def test_citation_repair_may_rewrite_a_multi_line_declaration(tmp_path, cites):
    # FxRates 20261024.155325: only the first of two `Cite:` lines was masked, so a repair that
    # changed or dropped the second was rejected as changing content other than Cite.
    target = _citation_target(tmp_path)
    path = target / "blueprint" / "FEATURE_Cited.md"
    two_bad = "Cite: sources/spec.txt:1\nCite: sources/spec.txt:9\n"
    path.write_text(path.read_text().replace("Cite: sources/spec.txt:1\n", two_bad))
    original = path.read_text()
    fixed = _BAD_CITATION_BODY.replace("Cite: sources/spec.txt:1\n", cites)

    result = repair(
        "Demo", target, runner=_runner(_fixed_block("FEATURE_Cited.md", "banner", fixed))
    )

    assert result.ok
    assert path.read_text() == original.replace(two_bad, cites)
    assert verify("Demo", target).ok


@pytest.mark.parametrize("relative", ["sources/../private.txt", "sources/link.txt"])
def test_citation_context_never_reads_outside_sources(tmp_path, relative):
    from drydock.plan_repair import _citation_sources
    from drydock.plan_verify import Defect

    blueprint = tmp_path / "blueprint"
    sources = blueprint / "sources"
    sources.mkdir(parents=True)
    outside = blueprint / "private.txt"
    outside.write_text("PRIVATE", encoding="utf-8")
    (sources / "link.txt").symlink_to(outside)
    body = _BAD_CITATION_BODY.replace("sources/spec.txt", relative)
    jobs = [(Defect("FEATURE_Cited.md", "banner", "bad-citation", "invalid"), body)]
    assert _citation_sources(jobs, blueprint) == []


def test_invalid_citation_repair_preserves_a_successfully_repaired_sibling(tmp_path):
    target = _citation_target(tmp_path)
    path = target / "blueprint" / "FEATURE_Cited.md"
    original = path.read_text()
    sibling = original[original.index("=== AC banner ===") :].replace("AC banner", "AC sibling")
    path.write_text(original + sibling)
    runner = _runner(
        _fixed_block("FEATURE_Cited.md", "banner", _BAD_CITATION_BODY)
        + _fixed_block(
            "FEATURE_Cited.md", "sibling", _BAD_CITATION_BODY.replace("spec.txt:1", "spec.txt:2")
        )
    )
    result = repair("Demo", target, runner=runner)
    assert not result.ok
    assert len(result.repaired) == len(result.outstanding) == 1
    assert path.read_text() == original + sibling.replace("spec.txt:1", "spec.txt:2")
    assert runner.calls[0]["prompt"].count("1: Unrelated title") == 1


def test_missing_citation_source_can_report_impossible_without_writing(tmp_path):
    target = _citation_target(tmp_path)
    (target / "blueprint" / "sources" / "spec.txt").unlink()
    path = target / "blueprint" / "FEATURE_Cited.md"
    original = path.read_text()
    runner = _runner(
        "REPAIR_IMPOSSIBLE: FEATURE_Cited.md :: banner — supporting source is unavailable."
    )
    result = repair("Demo", target, runner=runner)
    assert not result.ok
    assert result.items[0].status == "impossible"
    assert path.read_text() == original
    assert "numbered source for citation repair" not in runner.calls[0]["prompt"]


_STORE_LAUNCH = """# FEATURE: Load

## Programmatic Acceptance

=== AC load-rejected ===
Intent: A rejected file leaves stored rates unchanged.

import subprocess
from persistence.testing import db_session

with db_session() as db:
    before = db.rates.list_all()
result = subprocess.run(["./fxrates", "load", "bad.csv"], capture_output=True, text=True)
assert result.returncode == 3
with db_session() as db:
    after = db.rates.list_all()
assert len(after) == len(before)
=== END AC load-rejected ===
"""


def test_a_store_launch_repair_receives_the_selected_cli_fixture_contract(tmp_path):
    """FxRates 20261024.183153: without `cli_runner`'s import the repair answered impossible."""
    from drydock.technology_stack import StackEntry, write

    target = _target(tmp_path, FEATURE_Load=_STORE_LAUNCH)
    write(target, [StackEntry("Python", "python.md"), StackEntry("CLI", "cli.md")])
    runner = _runner(_FIXED_BLOCK)

    repair("Demo", target, runner=runner)

    prompt = runner.calls[0]["prompt"]
    assert 'kind="acceptance-store"' in prompt
    assert "## Selected foundation contracts" in prompt
    assert "fixture_source: cli/testing.py" in prompt


def test_other_defects_carry_no_foundation_contracts(tmp_path):
    from drydock.technology_stack import StackEntry, write

    target = _target(tmp_path, FEATURE_Path=_BROKEN)
    write(target, [StackEntry("Python", "python.md"), StackEntry("CLI", "cli.md")])
    runner = _runner(_FIXED_BLOCK)

    repair("Demo", target, runner=runner)

    assert "## Selected foundation contracts" not in runner.calls[0]["prompt"]


def test_probe_protocol_repair_receives_runner_and_preserves_scope(tmp_path):
    from tests.test_acceptance import _JSON_CORPUS_RUNNER

    broken = _BROKEN_MISSING_PROBE.replace(
        "Intent: Selects a conformance slice through the staged runner.\n",
        "Intent: Selects a conformance slice through the staged runner.\n"
        "Suite: scoped\nProbe: --list\nProbe Count: summary\n",
    ).replace(
        '"--select", "alpha"',
        '"--program", "./missing", "--spec", "sources/corpus.json", "-P", "alpha"',
    )
    target = _probe_target(tmp_path, FEATURE_Selector=broken)
    sources = target / "blueprint" / "sources"
    (sources / "run_probe.py").write_text(_JSON_CORPUS_RUNNER)
    (sources / "corpus.json").write_text('[{"section": "alpha"}]')
    (sources / "unrelated.txt").write_text("DO NOT INJECT UNRELATED SOURCE")
    body = broken.split("=== AC select-alpha ===\n")[1].split("=== END AC")[0]
    body = body.replace("Probe: --list", "Probe: --dump-tests").replace(
        "Probe Count: summary", "Probe Count: json"
    )
    runner = _runner(_fixed_block("FEATURE_Selector.md", "select-alpha", body))

    result = repair("Demo", target, runner=runner)

    assert result.ok, [item.rendered for item in result.outstanding]
    prompt = runner.calls[0]["prompt"]
    assert "parser.add_argument('--dump-tests'" in prompt
    assert "DO NOT INJECT UNRELATED SOURCE" not in prompt
    assert verify("Demo", target).ok
    text = (target / "blueprint" / "FEATURE_Selector.md").read_text()
    assert "Suite: scoped" in text
    assert "Probe Count: json" in text
    assert '"-P", "alpha"' in text


def test_probe_repair_cannot_drop_suite_or_change_assertions(tmp_path):
    broken = _BROKEN_MISSING_PROBE.replace(
        "Intent: Selects a conformance slice through the staged runner.\n",
        "Intent: Selects a conformance slice through the staged runner.\nSuite: scoped\n",
    )
    target = _probe_target(tmp_path, FEATURE_Selector=broken)
    result = repair("Demo", target, runner=_runner(_FIXED_PROBE_BLOCK))
    assert result.ok
    result_text = (target / "blueprint" / "FEATURE_Selector.md").read_text()
    assert "Suite: scoped" in result_text
    assert "assert result.returncode == 0" in result_text


def test_unresolved_probe_arguments_do_not_spend_a_repair_call(tmp_path):
    from tests.test_acceptance import _JSON_CORPUS_RUNNER

    broken = _BROKEN_MISSING_PROBE.replace(
        "Intent: Selects a conformance slice through the staged runner.\n",
        "Intent: Selects a conformance slice through the staged runner.\n"
        "Probe: --dump-tests\nProbe Count: json\n",
    ).replace(
        '"--select", "alpha"',
        '"--program", "./missing", "--spec", str(object()), "-P", "alpha"',
    )
    target = _probe_target(tmp_path, FEATURE_Selector=broken)
    (target / "blueprint/sources/run_probe.py").write_text(_JSON_CORPUS_RUNNER)
    runner = _runner("")
    progress = []
    result = repair("Demo", target, runner=runner, on_text=progress.append)

    assert not result.ok
    assert not runner.calls
    assert not result.files_changed
    assert "declaration-only repair cannot resolve command expressions" in result.items[0].detail
    assert "runner argument 4" in "".join(progress)
    assert (target / "blueprint/FEATURE_Selector.md").read_text() == broken


_FENCED = """# FEATURE: Sizes

## Programmatic Acceptance

### size-filter
Intent: Files under the minimum size are skipped.

```python
assert (
```
"""


def test_an_undelimited_criterion_is_routed_to_replanning_without_a_model_call(tmp_path):
    """DupFind 20261024.183232: a fenced criterion reached the model with an empty body."""
    target = _target(tmp_path, FEATURE_Sizes=_FENCED)
    assert [d.check_id for d in verify("Demo", target).defects] == ["size-filter"]
    runner = _runner("")

    result = repair("Demo", target, runner=runner)

    assert runner.calls == []
    (item,) = result.items
    assert item.status == "unrepaired"
    assert "drydock plan Demo" in item.detail
    assert not result.ok


def test_an_impossible_reason_is_kept_when_the_block_cannot_be_spliced(tmp_path):
    from drydock.plan_repair import _splice_and_revert
    from drydock.plan_verify import Defect

    path = tmp_path / "FEATURE_Sizes.md"
    path.write_text(_FENCED, encoding="utf-8")
    items, changed = _splice_and_revert(
        "FEATURE_Sizes.md",
        path,
        _FENCED,
        [Defect("FEATURE_Sizes.md", "size-filter", "syntax", "x")],
        {},
        {("FEATURE_Sizes.md", "size-filter"): "the criterion source is missing"},
        source_root=tmp_path,
    )
    assert not changed
    assert [(i.status, i.detail) for i in items] == [
        ("impossible", "the criterion source is missing")
    ]


def test_full_probe_command_is_recovered_with_summary_and_original_test(tmp_path):
    target = _probe_target(tmp_path, FEATURE_Selector=_BROKEN_MISSING_PROBE)
    source = target / "blueprint" / "sources" / "run_probe.py"
    source.write_text(_PROBE_RUNNER + '\n    print(f"{len(selected)} cases, 0 excluded")\n')
    response = _FIXED_PROBE_BLOCK.replace(
        "Probe: --list", "Probe: python3 sources/run_probe.py --select alpha --list"
    )

    result = repair("Demo", target, runner=_runner(response))

    assert result.ok
    text = (target / "blueprint" / "FEATURE_Selector.md").read_text()
    assert "Probe: --list\nProbe Count: summary" in text
    assert '"--select", "alpha"' in text
    assert verify("Demo", target).ok


def test_full_probe_command_with_empty_selection_does_not_pass(tmp_path):
    broken = _BROKEN_MISSING_PROBE.replace('"alpha"', '"zzz"')
    target = _probe_target(tmp_path, FEATURE_Selector=broken)
    source = target / "blueprint" / "sources" / "run_probe.py"
    source.write_text(_PROBE_RUNNER + '\n    print(f"{len(selected)} cases, 0 excluded")\n')
    response = _FIXED_PROBE_BLOCK.replace('"alpha"', '"zzz"').replace(
        "Probe: --list", "Probe: python3 sources/run_probe.py --select zzz --list"
    )

    result = repair("Demo", target, runner=_runner(response))

    assert not result.ok
    assert "selected 0 cases" in result.items[0].detail
    assert (target / "blueprint" / "FEATURE_Selector.md").read_text() == broken


def test_full_probe_command_with_different_selector_is_rejected(tmp_path):
    target = _probe_target(tmp_path, FEATURE_Selector=_BROKEN_MISSING_PROBE)
    response = _FIXED_PROBE_BLOCK.replace(
        "Probe: --list", "Probe: python3 sources/run_probe.py --select beta --list"
    )

    result = repair("Demo", target, runner=_runner(response))

    assert not result.ok
    assert (target / "blueprint" / "FEATURE_Selector.md").read_text() == _BROKEN_MISSING_PROBE


def test_summary_footer_is_not_counted_as_a_selected_case(tmp_path):
    broken = _BROKEN_MISSING_PROBE.replace('"alpha"', '"zzz"')
    target = _probe_target(tmp_path, FEATURE_Selector=broken)
    source = target / "blueprint" / "sources" / "run_probe.py"
    source.write_text(_PROBE_RUNNER + '\n    print(f"{len(selected)} cases, 0 excluded")\n')
    response = _FIXED_PROBE_BLOCK.replace('"alpha"', '"zzz"')

    result = repair("Demo", target, runner=_runner(response))

    assert not result.ok
    assert "use Probe Count: summary" in result.items[0].detail


def test_probe_repair_preserves_original_proof_and_intent_despite_model_changes(tmp_path):
    target = _probe_target(tmp_path, FEATURE_Selector=_BROKEN_MISSING_PROBE)
    response = _FIXED_PROBE_BLOCK.replace(
        "Intent: Selects a conformance slice through the staged runner.", "Intent: Altered."
    ).replace("assert result.returncode == 0", "assert True")

    result = repair("Demo", target, runner=_runner(response))

    assert result.ok
    text = (target / "blueprint" / "FEATURE_Selector.md").read_text()
    assert "Intent: Selects a conformance slice through the staged runner." in text
    assert "assert result.returncode == 0" in text
    assert "assert True" not in text
    assert "Probe: --list" in text
