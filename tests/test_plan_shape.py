"""Shape conformance is a checker, not an instruction — the deterministic post-checker."""

from __future__ import annotations

from drydock.plan_shape import (
    OutputContract,
    check_contract,
    check_delimiters,
    render_defects,
    second_pass_instruction,
)

CONTRACT = OutputContract(
    required=("MANIFEST.md",),
    terminal="MANIFEST.md",
    untyped=frozenset({"MANIFEST.md"}),
)

WELL_FORMED = (
    "=== ARCHITECTURE.md ===\n"
    "# ARCHITECTURE: Demo\n"
    "body\n"
    "=== END ARCHITECTURE.md ===\n"
    "=== MANIFEST.md ===\n"
    "# MANIFEST: Demo\n"
    "=== END MANIFEST.md ===\n"
)


def parsed(text: str) -> dict[str, str]:
    """Minimal block extraction mirroring the planning parser, for checker input."""
    blocks: dict[str, str] = {}
    name: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("=== END ") and stripped.endswith(" ==="):
            if name is not None:
                blocks[name] = "\n".join(body).strip()
            name, body = None, []
            continue
        if stripped.startswith("=== ") and stripped.endswith(" ==="):
            name, body = stripped[4:-4].strip(), []
            continue
        if name is not None:
            body.append(line)
    return blocks


def codes(defects) -> list[str]:
    return [defect.code for defect in defects]


def test_well_formed_response_satisfies_the_contract():
    assert check_contract(WELL_FORMED, parsed(WELL_FORMED), CONTRACT) == ()


def test_unclosed_block_is_detected():
    text = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: Demo\n"
    assert codes(check_delimiters(text)) == ["unclosed"]


def test_orphan_end_delimiter_is_detected():
    text = "=== END ARCHITECTURE.md ===\n"
    assert codes(check_delimiters(text)) == ["orphan-end"]


def test_duplicate_open_is_detected():
    text = "=== A.md ===\nx\n=== END A.md ===\n=== A.md ===\ny\n=== END A.md ===\n"
    assert "duplicate-open" in codes(check_delimiters(text))


def test_balanced_delimiters_produce_no_defect():
    assert check_delimiters(WELL_FORMED) == ()


def test_missing_required_artifact_is_detected():
    text = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: Demo\n=== END ARCHITECTURE.md ===\n"
    assert "missing-artifact" in codes(check_contract(text, parsed(text), CONTRACT))


def test_terminal_artifact_must_be_last():
    text = (
        "=== MANIFEST.md ===\n# MANIFEST: Demo\n=== END MANIFEST.md ===\n"
        "=== ARCHITECTURE.md ===\n# ARCHITECTURE: Demo\n=== END ARCHITECTURE.md ===\n"
    )
    assert "terminal-artifact" in codes(check_contract(text, parsed(text), CONTRACT))


LEADING_CONTRACT = OutputContract(
    required=("TOPOLOGY.md",),
    leading="TOPOLOGY.md",
    untyped=frozenset({"TOPOLOGY.md"}),
)


def test_leading_artifact_must_be_first():
    text = (
        "=== ARCHITECTURE.md ===\n# ARCHITECTURE: Demo\n=== END ARCHITECTURE.md ===\n"
        "=== TOPOLOGY.md ===\n## story a\n=== END TOPOLOGY.md ===\n"
    )
    assert "leading-artifact" in codes(check_contract(text, parsed(text), LEADING_CONTRACT))


def test_declaration_emitted_first_satisfies_the_leading_contract():
    text = (
        "=== TOPOLOGY.md ===\n## story a\n=== END TOPOLOGY.md ===\n"
        "=== ARCHITECTURE.md ===\n# ARCHITECTURE: Demo\n=== END ARCHITECTURE.md ===\n"
    )
    assert check_contract(text, parsed(text), LEADING_CONTRACT) == ()


def test_leading_check_is_silent_when_the_artifact_is_absent():
    """A contract fixing a leading artifact must not fire on a response that omits it —
    the missing-artifact defect owns that case."""
    text = "=== ARCHITECTURE.md ===\n# ARCHITECTURE: Demo\n=== END ARCHITECTURE.md ===\n"
    assert "leading-artifact" not in codes(check_contract(text, parsed(text), LEADING_CONTRACT))


def test_short_response_keeps_a_usable_declaration():
    """The point of declaring first: a response that ends early still carries the count of
    what should exist, which is what makes it resumable."""
    text = (
        "=== TOPOLOGY.md ===\n## story a\n## story b\n## story c\n=== END TOPOLOGY.md ===\n"
        "=== ARCHITECTURE.md ===\n# ARCHITECTURE: Demo\n=== END ARCHITECTURE.md ===\n"
    )
    blocks = parsed(text)
    assert check_contract(text, blocks, LEADING_CONTRACT) == ()
    assert blocks["TOPOLOGY.md"].count("## story ") == 3


def test_empty_artifact_is_detected():
    text = "=== A.md ===\n=== END A.md ===\n=== MANIFEST.md ===\nx\n=== END MANIFEST.md ===\n"
    assert "empty-artifact" in codes(check_contract(text, parsed(text), CONTRACT))


def test_untyped_heading_is_detected():
    text = (
        "=== ARCHITECTURE.md ===\nplain prose\n=== END ARCHITECTURE.md ===\n"
        "=== MANIFEST.md ===\n# MANIFEST: Demo\n=== END MANIFEST.md ===\n"
    )
    assert "untyped-heading" in codes(check_contract(text, parsed(text), CONTRACT))


def test_exempt_artifact_needs_no_typed_heading():
    defects = check_contract(WELL_FORMED, parsed(WELL_FORMED), CONTRACT)
    assert "untyped-heading" not in codes(defects)


def test_typed_heading_check_can_be_disabled():
    text = "=== NOTE.md ===\nplain prose\n=== END NOTE.md ===\n"
    contract = OutputContract(require_typed_headings=False)
    assert check_contract(text, parsed(text), contract) == ()


def test_second_pass_names_only_the_failed_artifacts():
    text = "=== ARCHITECTURE.md ===\nplain prose\n=== END ARCHITECTURE.md ===\n"
    defects = check_contract(text, parsed(text), CONTRACT)
    instruction = second_pass_instruction(defects)
    assert "ARCHITECTURE.md" in instruction
    assert "Re-emit only these artifacts" in instruction


def test_second_pass_without_a_named_artifact_falls_back():
    instruction = second_pass_instruction(())
    assert "nothing outside the delimited artifact blocks" in instruction


def test_render_defects_is_one_line_per_defect():
    text = "=== END A.md ===\n"
    assert render_defects(check_delimiters(text)).count("\n") == 0
