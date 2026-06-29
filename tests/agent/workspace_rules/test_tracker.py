"""Tests for subdirectory context tracker."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.workspace_rules.tracker import (
    SubdirectoryContextTracker,
    _PATH_ARG_KEYS,
    check_and_append_rules,
    get_subdirectory_tracker,
    init_subdirectory_tracker,
    reset_subdirectory_tracker,
)


@pytest.fixture()
def workspace_dir(tmp_path: Path) -> Path:
    """Create a temporary workspace with .git marker and an AGENTS.md."""
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestSubdirectoryContextTracker:
    def test_init_marks_workspace_root_checked(self, workspace_dir: Path) -> None:
        tracker = SubdirectoryContextTracker(str(workspace_dir))
        resolved = str(workspace_dir.resolve())
        assert resolved in tracker._checked_dirs

    def test_init_empty_workspace_root(self) -> None:
        tracker = SubdirectoryContextTracker("")
        assert len(tracker._checked_dirs) == 0

    def test_skips_already_checked_directories(self, workspace_dir: Path) -> None:
        subdir = workspace_dir / "src"
        subdir.mkdir()
        (subdir / "AGENTS.md").write_text("# Subdirectory rules")

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result1 = tracker.check_tool_call("read_file", {"path": str(subdir / "main.py")}, "")
        result2 = tracker.check_tool_call("read_file", {"path": str(subdir / "other.py")}, "")

        assert result2 is None

    def test_discovers_rules_in_new_subdirectory(self, workspace_dir: Path) -> None:
        subdir = workspace_dir / "packages" / "core"
        subdir.mkdir(parents=True)
        (subdir / "AGENTS.md").write_text("# Core package rules")

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call("read_file", {"path": str(subdir / "index.ts")}, "")

        assert result is not None
        assert "Core package rules" in result
        assert "Workspace Rules" in result

    def test_returns_none_when_no_rules(self, workspace_dir: Path) -> None:
        subdir = workspace_dir / "empty"
        subdir.mkdir()

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call("read_file", {"path": str(subdir / "file.txt")}, "")
        assert result is None

    def test_returns_none_with_empty_workspace_root(self) -> None:
        tracker = SubdirectoryContextTracker("")
        result = tracker.check_tool_call("read_file", {"path": "/some/path"}, "")
        assert result is None

    def test_rejects_outside_workspace(self, workspace_dir: Path) -> None:
        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call("read_file", {"path": "/etc/passwd"}, "")
        assert result is None

    def test_extracts_from_multiple_arg_keys(self, workspace_dir: Path) -> None:
        subdir = workspace_dir / "target"
        subdir.mkdir()
        (subdir / "AGENTS.md").write_text("# Target rules")

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call("copy_file", {"destination": str(subdir / "out.txt")}, "")
        assert result is not None
        assert "Target rules" in result

    def test_extracts_from_shell_cd_command(self, workspace_dir: Path) -> None:
        subdir = workspace_dir / "deploy"
        subdir.mkdir()
        (subdir / "AGENTS.md").write_text("# Deploy rules")

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call(
            "bash_code_execute_tool",
            {"command": f"cd {subdir} && ls"},
            "",
        )
        assert result is not None
        assert "Deploy rules" in result

    def test_handles_relative_path(self, workspace_dir: Path) -> None:
        subdir = workspace_dir / "lib"
        subdir.mkdir()
        (subdir / "AGENTS.md").write_text("# Lib rules")

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call("read_file", {"path": "lib/util.py"}, "")
        assert result is not None
        assert "Lib rules" in result

    def test_budget_enforcement_per_call(self, workspace_dir: Path) -> None:
        """_MAX_APPEND_CHARS (16000) limits total content per single check_tool_call."""
        subdir = workspace_dir / "bigpkg"
        subdir.mkdir()
        for i in range(5):
            nested = subdir / f"sub{i}"
            nested.mkdir()
            (nested / "AGENTS.md").write_text("R" * 5000)

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call("read_file", {"path": str(subdir / "sub0" / "f.py")}, "")
        if result:
            rule_content = result.split("--- Workspace Rules", 1)[-1]
            assert len(rule_content) <= 18000

    def test_ancestor_walk_discovers_parent_rules(self, workspace_dir: Path) -> None:
        (workspace_dir / "AGENTS.md").write_text("# Root rules")
        deep = workspace_dir / "a" / "b"
        deep.mkdir(parents=True)

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        tracker._checked_dirs.discard(str(workspace_dir.resolve()))
        result = tracker.check_tool_call("read_file", {"path": str(deep / "main.py")}, "")
        assert result is not None
        assert "Root rules" in result


class TestContextVarManagement:
    def test_get_returns_none_before_init(self) -> None:
        reset_subdirectory_tracker()
        tracker = get_subdirectory_tracker()
        assert tracker is None or isinstance(tracker, SubdirectoryContextTracker)

    def test_init_and_get(self, workspace_dir: Path) -> None:
        tracker = init_subdirectory_tracker(str(workspace_dir))
        assert tracker is not None
        got = get_subdirectory_tracker()
        assert got is tracker

    def test_reset(self, workspace_dir: Path) -> None:
        init_subdirectory_tracker(str(workspace_dir))
        reset_subdirectory_tracker()
        tracker = get_subdirectory_tracker()
        assert tracker is not None
        assert tracker._workspace_root == ""


class TestCheckAndAppendRules:
    def test_returns_none_when_no_tracker(self) -> None:
        reset_subdirectory_tracker()
        result = check_and_append_rules("read_file", {"path": "/some/path"}, "")
        assert result is None

    def test_delegates_to_tracker(self, workspace_dir: Path) -> None:
        subdir = workspace_dir / "src"
        subdir.mkdir()
        (subdir / "AGENTS.md").write_text("# Src rules")

        init_subdirectory_tracker(str(workspace_dir))
        result = check_and_append_rules("read_file", {"path": str(subdir / "main.py")}, "")
        assert result is not None
        assert "Src rules" in result


class TestEdgeCases:
    def test_extract_from_shell_with_bad_quotes(self, workspace_dir: Path) -> None:
        """shlex.split fails on malformed quotes, falls back to str.split."""
        subdir = workspace_dir / "data"
        subdir.mkdir()
        (subdir / "AGENTS.md").write_text("# Data rules")

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call(
            "shell_exec",
            {"command": f"cd {subdir} 'unclosed"},
            "",
        )
        if result:
            assert "Data rules" in result

    def test_nonexistent_path_in_args(self, workspace_dir: Path) -> None:
        """Non-existent path in args is silently skipped."""
        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace_dir / "nonexistent" / "deep" / "file.py")},
            "",
        )
        assert result is None

    def test_non_string_arg_values_ignored(self, workspace_dir: Path) -> None:
        """Non-string arg values are silently ignored."""
        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call(
            "read_file",
            {"path": 12345, "directory": None},
            "",
        )
        assert result is None

    def test_empty_arg_values_ignored(self, workspace_dir: Path) -> None:
        """Empty string arg values are silently ignored."""
        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call("read_file", {"path": ""}, "")
        assert result is None

    def test_command_flag_args_skipped(self, workspace_dir: Path) -> None:
        """Shell command flags (starting with -) are not treated as paths."""
        subdir = workspace_dir / "src"
        subdir.mkdir()

        tracker = SubdirectoryContextTracker(str(workspace_dir))
        result = tracker.check_tool_call(
            "bash_code_execute_tool",
            {"command": "ls -la"},
            "",
        )
        assert result is None


class TestPathArgKeys:
    def test_contains_expected_keys(self) -> None:
        expected = {"path", "file_path", "filepath", "directory", "working_directory", "command"}
        assert expected.issubset(_PATH_ARG_KEYS)

    def test_is_frozenset(self) -> None:
        assert isinstance(_PATH_ARG_KEYS, frozenset)
