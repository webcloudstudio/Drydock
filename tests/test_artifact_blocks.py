from __future__ import annotations

import pytest

from drydock.artifact_blocks import parse_artifact_blocks
from drydock.errors import DrydockError


def test_parse_artifact_blocks_recovers_missing_first_delimiter():
    text = "alpha\n=== END A.md ===\n=== B.md ===\nbeta\n=== END B.md ===\n"

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


def test_parse_artifact_blocks_recovers_missing_final_end_delimiter():
    text = "=== A.md ===\nalpha\n=== END A.md ===\n=== B.md ===\nbeta\n"

    blocks = parse_artifact_blocks(text, label="Test")

    assert blocks == {"A.md": "alpha", "B.md": "beta"}


def test_parse_artifact_blocks_recovers_write_transcript():
    text = """\
<function_calls>
<invoke name="Write">
<parameter name="path">/tmp/docs/DOC-OVERVIEW.md</parameter>
<parameter name="content"># Overview</parameter>
</invoke>
<invoke name="Write">
<parameter name="file_path">/tmp/docs/DOC-FEATURES.md</parameter>
<parameter name="content"># Features</parameter>
</invoke>
</function_calls>"""

    blocks = parse_artifact_blocks(
        text,
        label="Test",
        allowed_names=("DOC-OVERVIEW.md", "DOC-FEATURES.md"),
    )

    assert blocks == {"DOC-OVERVIEW.md": "# Overview", "DOC-FEATURES.md": "# Features"}


def test_parse_artifact_blocks_still_rejects_preamble():
    with pytest.raises(DrydockError, match="Text appeared outside"):
        parse_artifact_blocks(
            "Here is the plan.\n=== A.md ===\nalpha\n=== END A.md ===\n",
            label="Test",
        )
