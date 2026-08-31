"""Unified-diff parsing and application for the amendments ``drydock diagnose`` proposes."""

from __future__ import annotations

from drydock.patch import parse_amendments, parse_hunks

FILE = "# Compass\n\nOne.\nTwo.\nThree.\n"


def _amendment(diff: str, file: str = "COMPASS.md"):
    section = f"#### 1. Change it\n\nFile: `{file}`\nWhy: because.\n\n```diff\n{diff}\n```\n"
    amendments = parse_amendments(section)
    assert amendments, "the fixture itself failed to parse"
    return amendments[0]


# ── parsing ──────────────────────────────────────────────────────────────────────────


def test_parses_summary_file_reason_and_diff():
    amendment = _amendment(
        "--- a/COMPASS.md\n+++ b/COMPASS.md\n@@ -1,1 +1,2 @@\n # Compass\n+Added."
    )
    assert amendment.summary == "Change it"
    assert amendment.file == "COMPASS.md"
    assert amendment.why == "because."
    assert len(amendment.hunks) == 1


def test_parses_a_bold_markdown_field_form():
    section = (
        "#### 1. Change it\n\n**File:** `COMPASS.md`\n**Why:** reasons\n\n"
        "```diff\n@@ -1,1 +1,2 @@\n # Compass\n+Added.\n```\n"
    )
    amendment = parse_amendments(section)[0]
    assert amendment.file == "COMPASS.md"
    assert amendment.why == "reasons"


def test_parses_several_amendments_in_order():
    section = "".join(
        f"#### {n}. Item {n}\n\nFile: `COMPASS.md`\nWhy: w\n\n"
        f"```diff\n@@ -1,1 +1,2 @@\n # Compass\n+L{n}\n```\n\n"
        for n in (1, 2, 3)
    )
    assert [item.summary for item in parse_amendments(section)] == ["Item 1", "Item 2", "Item 3"]


def test_an_entry_without_a_diff_is_skipped():
    assert parse_amendments("#### 1. Nothing\n\nFile: `COMPASS.md`\nWhy: w\n") == ()


def test_an_entry_without_a_file_is_skipped():
    assert (
        parse_amendments("#### 1. Nothing\n\nWhy: w\n\n```diff\n@@ -1,1 +1,1 @@\n x\n```\n") == ()
    )


def test_an_empty_section_yields_nothing():
    assert parse_amendments("") == ()
    assert parse_amendments("None.") == ()


def test_a_leading_ab_path_prefix_is_stripped():
    assert _amendment("@@ -1,1 +1,2 @@\n # Compass\n+x", file="a/COMPASS.md").file == "COMPASS.md"


# ── hunks ────────────────────────────────────────────────────────────────────────────


def test_hunk_separates_expected_lines_from_produced_lines():
    hunk = parse_hunks("@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three")[0]
    assert hunk.before == ("one", "two", "three")
    assert hunk.after == ("one", "TWO", "three")


def test_commentary_after_a_hunk_does_not_become_file_content():
    hunk = parse_hunks("@@ -1,1 +1,2 @@\n one\n+two\nThis explains the change.")[0]
    assert "This explains the change." not in hunk.after


def test_a_no_newline_marker_is_ignored():
    hunk = parse_hunks("@@ -1,1 +1,1 @@\n-one\n+two\n\\ No newline at end of file")[0]
    assert hunk.after == ("two",)


def test_multiple_hunks_are_kept_in_order():
    hunks = parse_hunks("@@ -1,1 +1,2 @@\n one\n+A\n@@ -5,1 +6,2 @@\n five\n+B")
    assert [hunk.old_start for hunk in hunks] == [1, 5]


def test_a_diff_with_no_hunk_header_parses_to_nothing():
    assert parse_hunks("--- a/x\n+++ b/x\njust some text") == ()


# ── application ──────────────────────────────────────────────────────────────────────


def test_applying_an_addition():
    amendment = _amendment("@@ -3,3 +3,4 @@\n One.\n Two.\n Three.\n+Four.")
    assert amendment.apply_to(FILE) == "# Compass\n\nOne.\nTwo.\nThree.\nFour.\n"


def test_applying_a_replacement():
    amendment = _amendment("@@ -3,3 +3,3 @@\n One.\n-Two.\n+TWO.\n Three.")
    assert amendment.apply_to(FILE) == "# Compass\n\nOne.\nTWO.\nThree.\n"


def test_applying_a_deletion():
    amendment = _amendment("@@ -3,3 +3,2 @@\n One.\n-Two.\n Three.")
    assert amendment.apply_to(FILE) == "# Compass\n\nOne.\nThree.\n"


def test_context_that_does_not_exist_does_not_apply():
    assert _amendment("@@ -1,2 +1,3 @@\n nowhere\n nothing\n+x").apply_to(FILE) is None


def test_a_hunk_may_slide_when_line_numbers_drift():
    """Content is authority; the stated line number is a hint."""
    amendment = _amendment("@@ -30,3 +30,4 @@\n One.\n Two.\n Three.\n+Four.")
    assert amendment.apply_to(FILE) == "# Compass\n\nOne.\nTwo.\nThree.\nFour.\n"


def test_a_hunk_beyond_the_slide_window_does_not_apply():
    assert _amendment("@@ -900,3 +900,4 @@\n One.\n Two.\n Three.\n+Four.").apply_to(FILE) is None


def test_a_second_failing_hunk_abandons_the_whole_amendment():
    """Half an amendment is a corruption, not a smaller change."""
    amendment = _amendment("@@ -3,1 +3,2 @@\n One.\n+A\n@@ -20,1 +21,2 @@\n absent\n+B")
    assert amendment.apply_to(FILE) is None


def test_later_hunks_account_for_earlier_growth():
    amendment = _amendment("@@ -3,1 +3,2 @@\n One.\n+A\n@@ -5,1 +6,2 @@\n Three.\n+B")
    assert amendment.apply_to(FILE) == "# Compass\n\nOne.\nA\nTwo.\nThree.\nB\n"


def test_an_amendment_with_no_hunks_never_applies():
    from drydock.patch import Amendment

    assert Amendment(summary="s", file="COMPASS.md", why="w", diff="").apply_to(FILE) is None


def test_a_file_without_a_trailing_newline_keeps_not_having_one():
    amendment = _amendment("@@ -1,1 +1,2 @@\n # Compass\n+Added.")
    assert amendment.apply_to("# Compass").endswith("Added.")


def test_rejected_carries_the_reason_and_changes_nothing_else():
    amendment = _amendment("@@ -3,3 +3,4 @@\n One.\n Two.\n Three.\n+Four.")
    marked = amendment.rejected("does not apply")
    assert marked.rejection == "does not apply"
    assert marked.file == amendment.file
    assert marked.diff == amendment.diff


def test_a_blank_context_line_is_accepted_with_or_without_its_leading_space():
    """Providers emit both forms for an empty context line; both mean the same line."""
    spaced = parse_hunks("@@ -1,3 +1,3 @@\n one\n" + " " + "\n three")[0]
    bare = parse_hunks("@@ -1,3 +1,3 @@\n one\n\n three")[0]
    assert spaced.before == ("one", "", "three")
    assert bare.before == ("one", "", "three")
