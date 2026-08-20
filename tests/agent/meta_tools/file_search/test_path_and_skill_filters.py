"""Tests for path_hint and skill_path_filter."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_search.path_hint import (
    find_existing_unicode_path,
    format_path_not_found_hint,
    generate_unicode_path_candidates,
    levenshtein_distance_bounded,
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


def test_generate_unicode_path_candidates() -> None:
    # Test curly quotes, NBSP, fullwidth slashes
    raw = "‘src／components／button.tsx’"
    candidates = generate_unicode_path_candidates(raw)
    assert len(candidates) > 0
    assert any("src/components/button.tsx" in c for c in candidates)


def test_find_existing_unicode_path(tmp_path) -> None:
    # Create an on-disk file with ASCII name
    file_path = tmp_path / "app_config.json"
    file_path.write_text("{}", encoding="utf-8")

    # Probe with curly quotes and NBSP
    probed = find_existing_unicode_path("“app_config.json”", base_dir=str(tmp_path))
    assert probed is not None
    assert "app_config.json" in probed


def test_find_existing_unicode_path_blocked_devices(tmp_path) -> None:
    assert find_existing_unicode_path("/dev/zero") is None
    assert find_existing_unicode_path("CON.txt", base_dir=str(tmp_path)) is None


def test_levenshtein_distance_bounded() -> None:
    assert levenshtein_distance_bounded("readme.md", "readme.md", max_dist=2) == 0
    assert levenshtein_distance_bounded("redme.md", "readme.md", max_dist=2) == 1
    assert levenshtein_distance_bounded("readm.md", "readme.md", max_dist=2) == 1
    assert levenshtein_distance_bounded("rdme.md", "readme.md", max_dist=2) == 2
    # Distance > 2 returns max_dist + 1
    assert levenshtein_distance_bounded("completely_different.py", "readme.md", max_dist=2) == 3


def test_suggest_similar_paths_levenshtein_ranking(tmp_path) -> None:
    (tmp_path / "main_controller.py").write_text("", encoding="utf-8")
    (tmp_path / "main_controller_test.py").write_text("", encoding="utf-8")

    # 1-edit typo
    suggestions = suggest_similar_paths(str(tmp_path / "main_contorller.py"))
    assert len(suggestions) > 0
    assert suggestions[0].endswith("main_controller.py")


def test_path_hint_edge_cases(tmp_path) -> None:
    # Empty path
    assert generate_unicode_path_candidates("") == []
    assert find_existing_unicode_path("") is None

    # Direct probe without base_dir
    file_p = tmp_path / "direct.txt"
    file_p.write_text("hello", encoding="utf-8")
    assert find_existing_unicode_path(str(file_p)) == str(file_p)

    # Bounded distance with longer s1
    assert levenshtein_distance_bounded("longstringtest", "short", max_dist=2) == 3
    assert levenshtein_distance_bounded("abcde", "abxye", max_dist=1) == 2

    # Grandparent search
    sub = tmp_path / "level1" / "level2"
    sub.mkdir(parents=True)
    (tmp_path / "level1" / "root_target.py").write_text("", encoding="utf-8")
    suggs = suggest_similar_paths(str(sub / "root_targt.py"))
    assert any("root_target.py" in s for s in suggs)

    # Fallback to SequenceMatcher when distance > 2
    (tmp_path / "complex_algorithm_solver.py").write_text("", encoding="utf-8")
    fallback_suggs = suggest_similar_paths(str(tmp_path / "complex_algorithm_engine.py"))
    assert isinstance(fallback_suggs, list)

    # Non-existent directory
    assert suggest_similar_paths("/non/existent/deep/dir/file.py") == []

    # Levenshtein distance longer s1 shorter s2
    assert levenshtein_distance_bounded("a", "abcde", max_dist=2) == 3
    assert levenshtein_distance_bounded("abc", "a", max_dist=1) == 2


