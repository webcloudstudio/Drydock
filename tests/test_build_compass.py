"""Unit tests for BUILD_COMPASS.md parsing, rendering, seeding, and costing."""

from __future__ import annotations

from drydock.build_compass import (
    BuildCompass,
    CompassGroup,
    parse_build_compass,
    recompute_token_costs,
    render_build_compass,
    seed_from_specs,
    story_points_for,
)

_SAMPLE = """# Foundational
FEATURE-Schema.md
FEATURE-Auth.md

# Screens
SCREEN-Dashboard.md
"""


class TestParse:
    def test_groups_and_order_preserved(self):
        compass = parse_build_compass(_SAMPLE)
        assert [g.name for g in compass.groups] == ["Foundational", "Screens"]
        assert compass.groups[0].files == ["FEATURE-Schema.md", "FEATURE-Auth.md"]
        assert compass.groups[1].files == ["SCREEN-Dashboard.md"]

    def test_blank_lines_ignored(self):
        compass = parse_build_compass("# G\n\n\nA.md\n\nB.md\n")
        assert compass.groups[0].files == ["A.md", "B.md"]

    def test_lines_before_first_header_ignored(self):
        compass = parse_build_compass("stray.md\n# G\nA.md\n")
        assert [g.name for g in compass.groups] == ["G"]
        assert compass.groups[0].files == ["A.md"]

    def test_optional_bullet_prefix_stripped(self):
        compass = parse_build_compass("# G\n- A.md\n- B.md\n")
        assert compass.groups[0].files == ["A.md", "B.md"]

    def test_h2_is_not_a_group_header(self):
        compass = parse_build_compass("# G\n## Not a group\nA.md\n")
        assert [g.name for g in compass.groups] == ["G"]
        assert compass.groups[0].files == ["## Not a group", "A.md"]


class TestRoundTrip:
    def test_render_parse_round_trips(self):
        compass = parse_build_compass(_SAMPLE)
        assert parse_build_compass(render_build_compass(compass)) == compass

    def test_render_has_no_numbers(self):
        compass = parse_build_compass(_SAMPLE)
        rendered = render_build_compass(compass)
        assert "Story Points" not in rendered
        assert "Token Count" not in rendered
        assert rendered == _SAMPLE

    def test_empty_compass_renders_empty(self):
        assert render_build_compass(BuildCompass()) == ""


class TestSeed:
    def test_seed_is_one_flat_group_in_order(self):
        compass = seed_from_specs(["B.md", "A.md", "C.md"])
        assert len(compass.groups) == 1
        assert compass.groups[0].files == ["B.md", "A.md", "C.md"]

    def test_seed_dedupes_preserving_order(self):
        compass = seed_from_specs(["A.md", "B.md", "A.md"])
        assert compass.groups[0].files == ["A.md", "B.md"]

    def test_seed_empty_is_empty(self):
        assert seed_from_specs([]).groups == []


class TestStoryPoints:
    def test_bytes_over_four_rounded_up(self):
        assert story_points_for(0) == 0
        assert story_points_for(4) == 1
        assert story_points_for(4000) == 1000
        assert story_points_for(4001) == 1001


class TestRecompute:
    def _write(self, root, name, size):
        (root / name).write_bytes(b"x" * size)

    def test_per_file_group_and_total_rollups(self, tmp_path):
        self._write(tmp_path, "FEATURE-Schema.md", 4000)
        self._write(tmp_path, "FEATURE-Auth.md", 800)
        self._write(tmp_path, "SCREEN-Dashboard.md", 400)
        compass = parse_build_compass(_SAMPLE)

        cost = recompute_token_costs(compass, file_root=tmp_path)

        foundational = cost.groups[0]
        assert foundational.files[0].token_count == 4000
        assert foundational.files[0].story_points == 1000
        assert foundational.story_points == 1000 + 200  # 4000/4 + 800/4
        assert cost.groups[1].story_points == 100  # 400/4
        assert cost.total_token_count == 5200
        assert cost.total_story_points == 1300

    def test_missing_file_is_zero_and_flagged(self, tmp_path):
        compass = BuildCompass(groups=[CompassGroup(name="G", files=["ghost.md"])])
        cost = recompute_token_costs(compass, file_root=tmp_path)
        fc = cost.groups[0].files[0]
        assert fc.missing is True
        assert fc.token_count == 0
        assert fc.story_points == 0
        assert cost.total_story_points == 0

    def test_costs_are_not_written_back(self, tmp_path):
        self._write(tmp_path, "A.md", 16)
        compass = BuildCompass(groups=[CompassGroup(name="G", files=["A.md"])])
        recompute_token_costs(compass, file_root=tmp_path)
        # The authored file (if any) and render stay clean — no numbers leak in.
        assert "Story Points" not in render_build_compass(compass)
