"""Zone A stack resolution and the single-build-pass ceiling."""

from __future__ import annotations

from drydock import plan_stack
from drydock.plan_stack import (
    DEFAULT_STORY_BUDGET_TOKENS,
    STORY_BUDGET_ENV,
    exceeds_build_pass,
    resolve_stack_file,
    resolve_stack_set,
    resolve_target_stack,
    stack_cost,
    story_budget_tokens,
    story_pass_tokens,
    unresolved_names,
)


def make_stack_dir(tmp_path):
    stack = tmp_path / "stack"
    stack.mkdir()
    (stack / "fastapi.md").write_text("f" * 4000, encoding="utf-8")
    (stack / "fastapi_compact.md").write_text("f" * 400, encoding="utf-8")
    (stack / "common.md").write_text("c" * 800, encoding="utf-8")
    (stack / "terraform.md").write_text("t" * 1200, encoding="utf-8")
    (stack / "terraform_compact.md").write_text("t" * 100, encoding="utf-8")
    (stack / "terraform_compact.skip.md").write_text("skip", encoding="utf-8")
    return stack


def test_stack_file_is_opened_and_measured(tmp_path):
    """TECHNOLOGY_STACK.md declares which stack is used; Zone A opens the files themselves."""
    entry = resolve_stack_file("fastapi.md", make_stack_dir(tmp_path))
    assert entry.resolved
    assert entry.tokens == 1000
    assert entry.has_compact
    assert entry.compact_tokens == 100


def test_missing_stack_file_resolves_unresolved(tmp_path):
    entry = resolve_stack_file("nonexistent.md", make_stack_dir(tmp_path))
    assert not entry.resolved
    assert entry.tokens == 0


def test_a_skip_marker_suppresses_the_compact_sibling(tmp_path):
    entry = resolve_stack_file("terraform.md", make_stack_dir(tmp_path))
    assert entry.resolved
    assert not entry.has_compact


def test_file_without_a_compact_sibling_has_none(tmp_path):
    assert not resolve_stack_file("common.md", make_stack_dir(tmp_path)).has_compact


def test_builder_gets_the_full_file_and_consumer_the_interface_view(tmp_path):
    entry = resolve_stack_file("fastapi.md", make_stack_dir(tmp_path))
    assert entry.tokens_for("builder") == 1000
    assert entry.tokens_for("consumer") == 100


def test_consumer_falls_back_to_the_full_file_without_a_compact(tmp_path):
    entry = resolve_stack_file("common.md", make_stack_dir(tmp_path))
    assert entry.tokens_for("consumer") == entry.tokens_for("builder") == 200


def test_resolve_stack_set_preserves_declaration_order_and_dedupes(tmp_path):
    resolved = resolve_stack_set(
        ["common.md", "fastapi.md", "common.md", " "], make_stack_dir(tmp_path)
    )
    assert list(resolved) == ["common.md", "fastapi.md"]


def test_unresolved_names_are_reported(tmp_path):
    resolved = resolve_stack_set(["fastapi.md", "ghost.md"], make_stack_dir(tmp_path))
    assert unresolved_names(resolved) == ("ghost.md",)


def test_stack_cost_sums_by_mode(tmp_path):
    resolved = resolve_stack_set(["fastapi.md", "common.md"], make_stack_dir(tmp_path))
    assert stack_cost(["fastapi.md", "common.md"], resolved, mode="builder") == 1200
    assert stack_cost(["fastapi.md", "common.md"], resolved, mode="consumer") == 300


def test_stack_cost_ignores_unknown_names(tmp_path):
    resolved = resolve_stack_set(["common.md"], make_stack_dir(tmp_path))
    assert stack_cost(["common.md", "ghost.md"], resolved) == 200


def test_story_pass_tokens_is_specification_plus_stack(tmp_path):
    resolved = resolve_stack_set(["common.md"], make_stack_dir(tmp_path))
    assert (
        story_pass_tokens(specification_tokens=500, stack=["common.md"], resolved=resolved) == 700
    )


def test_build_pass_ceiling_replaces_the_effort_threshold(monkeypatch):
    monkeypatch.delenv(STORY_BUDGET_ENV, raising=False)
    assert story_budget_tokens() == DEFAULT_STORY_BUDGET_TOKENS
    assert exceeds_build_pass(DEFAULT_STORY_BUDGET_TOKENS + 1)
    assert not exceeds_build_pass(DEFAULT_STORY_BUDGET_TOKENS)


def test_ceiling_is_configurable(monkeypatch):
    monkeypatch.setenv(STORY_BUDGET_ENV, "1234")
    assert story_budget_tokens() == 1234
    assert exceeds_build_pass(2000)


def test_invalid_or_nonpositive_ceiling_falls_back(monkeypatch):
    monkeypatch.setenv(STORY_BUDGET_ENV, "not-a-number")
    assert story_budget_tokens() == DEFAULT_STORY_BUDGET_TOKENS
    monkeypatch.setenv(STORY_BUDGET_ENV, "0")
    assert story_budget_tokens() == DEFAULT_STORY_BUDGET_TOKENS


def test_explicit_budget_overrides_the_environment(monkeypatch):
    monkeypatch.setenv(STORY_BUDGET_ENV, "10")
    assert not exceeds_build_pass(50, budget=100)


def test_target_stack_resolution_reads_the_declared_stack(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setattr(plan_stack.technology_stack, "stack_files", lambda _: ["fastapi.md"])
    resolved = resolve_target_stack(target, make_stack_dir(tmp_path))
    assert list(resolved) == ["fastapi.md"]
    assert resolved["fastapi.md"].resolved


def test_absent_technology_stack_is_undecided_not_forbidden(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setattr(plan_stack.technology_stack, "stack_files", lambda _: [])
    assert resolve_target_stack(target, make_stack_dir(tmp_path)) == {}
