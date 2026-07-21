"""Tests for path_hint and skill_path_filter."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_search.path_hint import (
    format_path_not_found_hint,
    suggest_similar_paths,
)
from myrm_agent_harness.agent.meta_tools.file_search.skill_path_filter import (
    filter_disabled_skill_paths,
    get_disabled_skill_roots,
    is_under_disabled_skill_root,
)


def test_suggest_similar_paths_finds_close_name(tmp_path) -> None:
    target = tmp_path / "redme.md"
    (tmp_path / "readme.md").write_text("hello", encoding="utf-8")
    suggestions = suggest_similar_paths(str(target))
    assert any("readme.md" in s for s in suggestions)


def test_format_path_not_found_hint_without_suggestions() -> None:
    hint = format_path_not_found_hint("/a/missing.py", [])
    assert "does not exist" in hint
    assert "Did you mean" not in hint


def test_format_path_not_found_hint_with_suggestions() -> None:
    hint = format_path_not_found_hint("/a/missing.py", ["/a/main.py"])
    assert "Did you mean" in hint
    assert "/a/main.py" in hint


def test_suggest_similar_paths_empty_basename() -> None:
    assert suggest_similar_paths("/") == []


def test_is_under_disabled_skill_root_empty_roots() -> None:
    assert not is_under_disabled_skill_root("/any/path", [])


def test_filter_disabled_skill_paths_passthrough_when_no_roots() -> None:
    paths = ["/workspace/a.py", "/workspace/b.py"]
    assert filter_disabled_skill_paths(paths, []) == paths



def test_is_under_disabled_skill_root_prefix() -> None:
    roots = ["/workspace/skills/disabled-skill"]
    assert is_under_disabled_skill_root("/workspace/skills/disabled-skill/SKILL.md", roots)
    assert not is_under_disabled_skill_root("/workspace/src/main.py", roots)


def test_filter_disabled_skill_paths() -> None:
    paths = ["/workspace/skills/off/a.md", "/workspace/src/b.py"]
    roots = ["/workspace/skills/off"]
    filtered = filter_disabled_skill_paths(paths, roots)
    assert filtered == ["/workspace/src/b.py"]


def test_get_disabled_skill_roots_from_config() -> None:
    config = {"configurable": {"context": {"disabled_skill_roots": ["/skills/off"]}}}
    assert get_disabled_skill_roots(config) == ["/skills/off"]


def test_get_disabled_skill_roots_empty_when_missing() -> None:
    assert get_disabled_skill_roots(None) == []
    assert get_disabled_skill_roots({"configurable": {"context": {}}}) == []


def test_is_under_disabled_skill_root_exact_match() -> None:
    roots = ["/workspace/skills/off"]
    assert is_under_disabled_skill_root("/workspace/skills/off", roots)

