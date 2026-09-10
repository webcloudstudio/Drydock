"""Terminal rendering for ``drydock diagnose``: sections, wrapping, the amendment card."""

from __future__ import annotations

from drydock.diagnose_console import (
    Style,
    _details,
    _prose,
    render_amendment,
    render_diff,
    render_ladder_lines,
)
from drydock.diagnose_ladder import LadderRow
from drydock.patch import Amendment, parse_hunks

DIFF = """--- a/blueprint/FEATURE-WORKSPACE.md
+++ b/blueprint/FEATURE-WORKSPACE.md
@@ -165,1 +165,1 @@
-    assert rows[0]["id"] == ids[1]
+    assert [row["id"] for row in rows] == expected_ids
"""


def _amendment(diff: str = DIFF) -> Amendment:
    return Amendment(
        summary="Verify an adjacent swap against the complete pre-move order",
        file="blueprint/FEATURE-WORKSPACE.md",
        why="The assertion at line 165 assumes an empty collection.",
        diff=diff,
        hunks=parse_hunks(diff),
    )


def test_wrapping_never_splits_a_code_span():
    style = Style(width=40)
    lines = style.wrap("The check `assert rows[0] == ids[1]` fails on a populated table.")
    assert any("`assert rows[0] == ids[1]`" in line for line in lines)
    assert all(len(line) <= 40 or "`" in line for line in lines)


def test_soft_wrapped_bullets_rejoin_before_wrapping():
    lines = _prose(Style(width=200), "- first half\n  second half\n- next")
    assert lines == ["  • first half second half", "  • next"]


def test_details_put_wreckage_under_its_own_heading():
    text = "- `a.md:1` fact.\n- Not a defect: retried once.\n- `b.md:2` fact."
    lines = _details(Style(width=200), text)
    assert lines == [
        "  • `a.md:1` fact.",
        "  • `b.md:2` fact.",
        "",
        "  Not defects",
        "  · retried once.",
    ]


def test_amendment_card_shows_the_diff_and_ends_in_the_question():
    card = render_amendment(1, 2, _amendment(), Style(width=100))
    assert "Amendment 1 of 2" in card
    assert "  File  blueprint/FEATURE-WORKSPACE.md   +1 -1" in card
    assert "  Why   The assertion at line 165 assumes an empty collection." in card
    assert '    -    assert rows[0]["id"] == ids[1]' in card
    assert '    +    assert [row["id"] for row in rows] == expected_ids' in card
    assert card.endswith("\n  Apply? [y/N] ")


def test_a_long_diff_is_cut_with_a_pointer_to_the_report():
    body = "@@ -1,80 +1,80 @@\n" + "\n".join(f" line {n}" for n in range(80))
    lines = render_diff(body, Style(), limit=10)
    assert len(lines) == 11
    assert lines[-1].endswith("71 more lines in the report")


def test_plain_style_writes_no_escapes_and_colour_does():
    rows = (
        LadderRow(milestone="BUILD", state="fail"),
        LadderRow(milestone="SCORE", state="not run"),
    )
    assert "\x1b[" not in render_ladder_lines(rows, Style())
    assert "\x1b[" not in render_amendment(1, 1, _amendment(), Style())
    painted = render_amendment(1, 1, _amendment(), Style(color=True))
    assert "\x1b[31m-" in painted and "\x1b[32m+" in painted
    assert "\x1b[31;1m[FAIL]\x1b[0m" in render_ladder_lines(rows, Style(color=True))


def test_colour_drops_the_backticks_plain_text_keeps_them():
    assert Style().code("run `pytest`") == "run `pytest`"
    assert Style(color=True).code("run `pytest`") == "run \x1b[36mpytest\x1b[0m"
