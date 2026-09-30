"""Tests for the shared path-pattern matcher.

Covers the semantics every path protection rule depends on: segment-scoped
wildcards, recursive ``**``, depth-independent relative patterns, dotfiles,
absolute anchoring, and the bounded filesystem sweep.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import ClassVar

import pytest

from myrm_agent_harness.core.security.path_pattern import (
    MAX_WALK_FILES,
    PathPatternMatch,
    compile_path_pattern,
    first_matching_pattern,
    iter_matching_files,
    normalise_path_pattern,
    path_matches_pattern,
)


class TestSegmentScoping:
    @pytest.mark.parametrize(
        ("path", "pattern", "expected"),
        [
            ("a/b/c.py", "a/*/c.py", True),
            ("a/b/d/c.py", "a/*/c.py", False),
            ("a/b/c.py", "a/*/*/c.py", False),
        ],
    )
    def test_single_star_stays_within_one_segment(self, path, pattern, expected):
        assert path_matches_pattern(path, pattern) is expected

    @pytest.mark.parametrize(
        ("path", "pattern", "expected"),
        [
            ("a/migrations/001.sql", "**/migrations/**", True),
            ("migrations/001.sql", "**/migrations/**", True),
            ("a/b/migrations/001.sql", "**/migrations/**", True),
            ("a/migration/001.sql", "**/migrations/**", False),
        ],
    )
    def test_recursive_star_spans_directories(self, path, pattern, expected):
        assert path_matches_pattern(path, pattern) is expected

    def test_trailing_recursive_star_covers_remainder(self):
        assert path_matches_pattern("config/deep/nested/x.py", "config/**") is True
        assert path_matches_pattern("a/b/config/x.py", "config/**") is True
        assert path_matches_pattern("a/b/x.py", "config/**") is False

    def test_mid_path_recursive_star(self):
        assert path_matches_pattern("src/app/main.py", "src/**/*.py") is True
        assert path_matches_pattern("src/main.py", "src/**/*.py") is True
        assert path_matches_pattern("lib/main.py", "src/**/*.py") is False

    def test_question_mark_matches_exactly_one_character(self):
        assert path_matches_pattern("a/b.py", "a/?.py") is True
        assert path_matches_pattern("a/b1.py", "a/?.py") is False
        assert path_matches_pattern("a/bcd/x.py", "a/?.py") is False

    def test_character_class(self):
        assert path_matches_pattern("src/a.py", "src/[ab].py") is True
        assert path_matches_pattern("src/c.py", "src/[ab].py") is False
        assert path_matches_pattern("src/a.py", "src/[!ab].py") is False

    def test_literal_dots_are_escaped(self):
        # Without escaping, "." would match any character.
        assert path_matches_pattern("a/bXpy", "b.py") is False
        assert path_matches_pattern("a/b.py", "b.py") is True


class TestDepthIndependence:
    @pytest.mark.parametrize(
        "path",
        [".env", "app/.env", "app/config/.env", "/abs/app/config/.env"],
    )
    def test_relative_pattern_applies_at_every_depth(self, path):
        assert path_matches_pattern(path, ".env") is True

    def test_relative_pattern_without_recursive_prefix(self):
        assert path_matches_pattern("app/data/x.csv", "data/*.csv") is True
        assert path_matches_pattern("data/x.csv", "data/*.csv") is True
        assert path_matches_pattern("app/other/x.csv", "data/*.csv") is False

    def test_absolute_pattern_is_anchored(self):
        assert path_matches_pattern("/etc/passwd", "/etc/*") is True
        assert path_matches_pattern("/repo/etc/passwd", "/etc/*") is False

    def test_absolute_path_matched_by_relative_pattern(self):
        assert path_matches_pattern("/srv/app/.env", "*.env") is True


class TestDotfiles:
    @pytest.mark.parametrize(
        ("path", "pattern"),
        [
            (".env", "*.env"),
            ("app/config/.env", "*.env"),
            ("app/config/.env.local", "**/.env*"),
            (".env", "**/.env*"),
            ("deploy/.npmrc", "*.npmrc"),
        ],
    )
    def test_wildcard_matches_leading_dot(self, path, pattern):
        """A ``*`` wildcard must reach dotfiles, unlike shell globbing.

        This is the class of file protection exists for; a matcher that skips
        leading dots silently protects nothing.
        """
        assert path_matches_pattern(path, pattern) is True


class TestWindowsSeparators:
    def test_backslashes_normalised(self):
        assert path_matches_pattern("app\\config\\.env", ".env") is True
        assert path_matches_pattern("app\\config\\x.csv", "data/*.csv") is False


class TestEdgeCases:
    def test_empty_path_never_matches(self):
        assert path_matches_pattern("", "*") is False

    def test_empty_pattern_raises(self):
        with pytest.raises(re.error):
            path_matches_pattern("a/b.py", "")

    def test_unterminated_character_class_raises(self):
        with pytest.raises(re.error):
            compile_path_pattern("a/[abc.py")

    def test_trailing_slash_normalised(self):
        assert normalise_path_pattern("config//") == "config"
        assert normalise_path_pattern("a\\b\\c") == "a/b/c"

    def test_recursive_star_alone_matches_any_path(self):
        assert path_matches_pattern("anything/at/all", "**") is True
        assert path_matches_pattern("x", "**") is True

    def test_absolute_recursive_pattern_stays_anchored(self):
        """``/etc/**`` covers ``/etc`` and below, never an unrelated root."""
        assert path_matches_pattern("/etc/passwd", "/etc/**") is True
        assert path_matches_pattern("/srv/etc/passwd", "/etc/**") is False

    def test_traversal_cannot_anchor_to_an_absolute_pattern(self):
        assert path_matches_pattern("../../etc/passwd", "/etc/*") is False
        assert path_matches_pattern("a/b/../../../etc/passwd", "/etc/*") is False

    def test_uri_shaped_input_is_not_a_path(self):
        assert path_matches_pattern("file:///etc/passwd", "/etc/*") is False

    def test_duplicate_slashes_collapse(self):
        assert path_matches_pattern("//a//b", "a/b") is True

    def test_windows_unc_path(self):
        assert path_matches_pattern("\\\\server\\share\\x.csv", "*.csv") is True

    def test_compiled_pattern_is_cached(self):
        first = compile_path_pattern("src/**/*.py")
        second = compile_path_pattern("src/**/*.py")
        assert first is second

    def test_case_is_ignored_by_default(self):
        assert path_matches_pattern("AGENTS.md", "**/agents.md") is True
        assert path_matches_pattern("Agents.MD", "**/agents.md") is True
        assert path_matches_pattern("agents.md", "**/AGENTS.md") is True

    def test_case_sensitivity_is_opt_in(self):
        assert path_matches_pattern("AGENTS.md", "**/agents.md", case_sensitive=True) is False
        assert path_matches_pattern("agents.md", "**/agents.md", case_sensitive=True) is True

    def test_case_insensitive_first_match(self):
        patterns = ["**/AGENTS.md", "*.env"]
        assert first_matching_pattern("a/agents.md", patterns) == "**/AGENTS.md"
        assert first_matching_pattern("a/agents.md", patterns, case_sensitive=True) is None


class TestFirstMatchingPattern:
    PATTERNS: ClassVar[list[str]] = ["**/migrations/**", "*.env", "config/**"]

    def test_returns_the_rule_that_fired(self):
        assert first_matching_pattern("a/b/.env", self.PATTERNS) == "*.env"

    def test_returns_none_when_unprotected(self):
        assert first_matching_pattern("a/b/main.py", self.PATTERNS) is None

    def test_malformed_pattern_is_skipped(self):
        assert first_matching_pattern("a/b.py", ["[bad", "b.py"]) == "b.py"

    def test_consecutive_recursive_segments_collapse(self):
        """Stacked ``**/`` must not nest quantifiers.

        Left uncollapsed, ``a/**/**/**/x`` compiles to three nested
        ``(?:[^/]+/)*`` groups and degrades to exponential backtracking,
        stalling every write-time check that evaluates the rule.
        """
        collapsed = compile_path_pattern("a/**/x").pattern
        for stacked in ("a/**/**/x", "a/**/**/**/x", "a/**/**/**/**/**/**/x"):
            assert compile_path_pattern(stacked).pattern == collapsed

    def test_empty_pattern_list(self):
        assert first_matching_pattern("a/b.py", []) is None


class TestBacktrackingSafety:
    """A rule typed into a protection field must never stall the write path."""

    @pytest.mark.parametrize("depth", [4, 8, 16, 32])
    def test_stacked_recursive_pattern_stays_linear(self, depth: int):
        pattern = "a/**/**/**/x"
        path = "a/" + "bb/" * depth + "zzz"
        started = time.perf_counter()
        assert path_matches_pattern(path, pattern) is False
        assert time.perf_counter() - started < 0.05


class TestIterMatchingFiles:
    @pytest.fixture
    def tree(self, tmp_path: Path) -> Path:
        (tmp_path / "app" / "config").mkdir(parents=True)
        (tmp_path / "data").mkdir()
        (tmp_path / "app" / "config" / ".env").write_text("SECRET=1")
        (tmp_path / "data" / "x.csv").write_text("a,b")
        (tmp_path / "app" / "main.py").write_text("print('hi')")
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "leaked.env").write_text("X")
        return tmp_path

    def _relatives(self, root: Path, found: list[PathPatternMatch]) -> set[str]:
        return {Path(m.path).relative_to(root).as_posix() for m in found}

    def test_finds_dotfiles_at_depth(self, tree: Path):
        found = list(iter_matching_files(tree, ["*.env"]))
        assert self._relatives(tree, found) == {"app/config/.env"}

    def test_reports_the_covering_rule(self, tree: Path):
        found = list(iter_matching_files(tree, ["data/*.csv", "*.env"]))
        by_path = {Path(m.path).name: m.pattern for m in found}
        assert by_path["x.csv"] == "data/*.csv"
        assert by_path[".env"] == "*.env"

    def test_finds_relative_prefixed_pattern(self, tree: Path):
        found = list(iter_matching_files(tree, ["data/*.csv"]))
        assert self._relatives(tree, found) == {"data/x.csv"}

    def test_skips_dependency_directories(self, tree: Path):
        found = list(iter_matching_files(tree, ["*.env"]))
        assert not any("node_modules" in m.path for m in found)

    def test_empty_patterns_yield_nothing(self, tree: Path):
        assert list(iter_matching_files(tree, [])) == []

    def test_missing_root_yields_nothing(self, tmp_path: Path):
        assert list(iter_matching_files(tmp_path / "absent", ["*"])) == []

    def test_file_root_yields_nothing(self, tree: Path):
        assert list(iter_matching_files(tree / "data" / "x.csv", ["*"])) == []

    def test_walk_budget_stops_the_sweep(self, tree: Path, caplog):
        with caplog.at_level("WARNING"):
            found = list(iter_matching_files(tree, ["*"], max_files=1))
        assert len(found) <= 1
        assert "stopped after 1 files" in caplog.text

    def test_default_budget_is_bounded(self):
        assert MAX_WALK_FILES > 0

    def test_broad_pattern_does_not_sweep_dependency_trees(self, tree: Path):
        """A pattern matching everything must still stay off node_modules."""
        found = list(iter_matching_files(tree, ["*"]))
        assert found
        assert not any("node_modules" in m.path for m in found)
