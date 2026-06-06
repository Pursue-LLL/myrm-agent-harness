"""Tests for workspace rules subdirectory tracker."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.workspace_rules.tracker import (
    SubdirectoryContextTracker,
    check_and_append_rules,
    init_subdirectory_tracker,
    reset_subdirectory_tracker,
)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Create a workspace with .git and subdirectory structure."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "lib").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "src" / "components").mkdir(parents=True)
    return tmp_path


class TestSubdirectoryContextTracker:
    def test_skips_workspace_root(self, workspace: Path) -> None:
        (workspace / "AGENTS.md").write_text("# Root rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "README.md")},
            "file content",
        )
        assert result is None

    def test_discovers_subdir_rules(self, workspace: Path) -> None:
        (workspace / "src" / "AGENTS.md").write_text("# Src rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "src" / "main.py")},
            "file content",
        )
        assert result is not None
        assert "Src rules" in result

    def test_no_duplicate_discovery(self, workspace: Path) -> None:
        (workspace / "src" / "AGENTS.md").write_text("# Src rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result1 = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "src" / "main.py")},
            "content",
        )
        result2 = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "src" / "other.py")},
            "content",
        )
        assert result1 is not None
        assert result2 is None

    def test_ancestor_traversal_discovers_parent_rules(
        self, workspace: Path
    ) -> None:
        """Reading a deep file should discover rules in parent directories."""
        (workspace / "apps" / "web" / "AGENTS.md").write_text("# Web rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "apps" / "web" / "src" / "components" / "Button.tsx")},
            "component code",
        )
        assert result is not None
        assert "Web rules" in result

    def test_respects_workspace_boundary(self, workspace: Path) -> None:
        outside_dir = workspace.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "AGENTS.md").write_text("# Outside rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(outside_dir / "file.py")},
            "content",
        )
        assert result is None

    def test_rejects_prefix_matched_sibling_directory(self, workspace: Path) -> None:
        """Path prefix attack: /workspace-backup must not match /workspace."""
        sibling = workspace.parent / (workspace.name + "-backup")
        sibling.mkdir(exist_ok=True)
        (sibling / "AGENTS.md").write_text("# Malicious rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(sibling / "file.py")},
            "content",
        )
        assert result is None

    def test_handles_relative_paths(self, workspace: Path) -> None:
        (workspace / "src" / "AGENTS.md").write_text("# Relative rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": "src/main.py"},
            "content",
        )
        assert result is not None
        assert "Relative rules" in result

    def test_extracts_from_shell_commands(self, workspace: Path) -> None:
        (workspace / "src" / "AGENTS.md").write_text("# Shell discovered")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "shell_exec",
            {"command": f"cat {workspace / 'src' / 'main.py'}"},
            "output",
        )
        assert result is not None
        assert "Shell discovered" in result

    def test_respects_max_append_chars(self, workspace: Path) -> None:
        # Create 3 directories
        (workspace / "dir0").mkdir()
        (workspace / "dir0" / "AGENTS.md").write_text("X" * 8000)
        
        (workspace / "dir1").mkdir()
        (workspace / "dir1" / "AGENTS.md").write_text("X" * 2000)
        
        (workspace / "dir2").mkdir()
        (workspace / "dir2" / "AGENTS.md").write_text("X" * 8000)

        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {
                "path": str(workspace / "dir0"),
                "file_path": str(workspace / "dir1"),
                "directory": str(workspace / "dir2"),
            },
            "content",
        )
        assert result is not None
        assert "truncated AGENTS.md: exceeded total append budget" in result
        assert len(result) <= 17000

    def test_discovers_claude_subdir_in_subdirectory(self, workspace: Path) -> None:
        """Tracker discovers .claude/CLAUDE.md in newly accessed subdirectories."""
        claude_dir = workspace / "src" / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# Claude subdir rules in src")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "src" / "main.py")},
            "content",
        )
        assert result is not None
        assert "Claude subdir rules in src" in result
        assert "CLAUDE.md" in result

    def test_claude_subdir_overridden_by_root_rules(self, workspace: Path) -> None:
        """AGENTS.md overrides .claude/CLAUDE.md in same subdir (First-Match-Wins)."""
        subdir = workspace / "src"
        claude_dir = subdir / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# Claude rules")
        (subdir / "AGENTS.md").write_text("# Agent rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(subdir / "main.py")},
            "content",
        )
        assert result is not None
        assert "Claude rules" not in result
        assert "Agent rules" in result

    def test_discovers_windsurfrules_in_subdirectory(self, workspace: Path) -> None:
        """Tracker discovers .windsurfrules in newly accessed subdirectories."""
        (workspace / "src" / ".windsurfrules").write_text("# Windsurf subdir rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "src" / "main.py")},
            "content",
        )
        assert result is not None
        assert "Windsurf subdir rules" in result

    def test_discovers_copilot_instructions_in_subdirectory(self, workspace: Path) -> None:
        """Tracker discovers .github/copilot-instructions.md in subdirectories."""
        github_dir = workspace / "src" / ".github"
        github_dir.mkdir()
        (github_dir / "copilot-instructions.md").write_text("# Copilot subdir rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(workspace / "src" / "main.py")},
            "content",
        )
        assert result is not None
        assert "Copilot subdir rules" in result
        assert "copilot-instructions.md" in result

    def test_copilot_overridden_by_windsurfrules(self, workspace: Path) -> None:
        """copilot-instructions.md is overridden by .windsurfrules (First-Match-Wins)."""
        subdir = workspace / "src"
        github_dir = subdir / ".github"
        github_dir.mkdir()
        (github_dir / "copilot-instructions.md").write_text("# Copilot rules")
        (subdir / ".windsurfrules").write_text("# Windsurf rules")
        tracker = SubdirectoryContextTracker(str(workspace))
        result = tracker.check_tool_call(
            "read_file",
            {"path": str(subdir / "main.py")},
            "content",
        )
        assert result is not None
        assert "Copilot rules" not in result
        assert "Windsurf rules" in result

    def test_empty_workspace_root(self) -> None:
        tracker = SubdirectoryContextTracker("")
        result = tracker.check_tool_call(
            "read_file", {"path": "/some/path.py"}, "content"
        )
        assert result is None


class TestContextVarManagement:
    def test_init_and_check(self, workspace: Path) -> None:
        (workspace / "src" / "AGENTS.md").write_text("# Context var rules")
        init_subdirectory_tracker(str(workspace))
        result = check_and_append_rules(
            "read_file",
            {"path": str(workspace / "src" / "main.py")},
            "content",
        )
        assert result is not None
        assert "Context var rules" in result

    def test_reset_clears_tracker(self, workspace: Path) -> None:
        init_subdirectory_tracker(str(workspace))
        reset_subdirectory_tracker()
        result = check_and_append_rules(
            "read_file",
            {"path": str(workspace / "src" / "main.py")},
            "content",
        )
        assert result is None
