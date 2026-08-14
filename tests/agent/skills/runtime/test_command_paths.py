"""Tests for skill command path utilities.

Covers:
- rewrite_skill_paths()
- detect_skill_script_command()
"""

from __future__ import annotations

import logging

import pytest

from myrm_agent_harness.agent.skills.runtime.command_paths import (
    detect_skill_script_command,
    rewrite_skill_paths,
)

# ── rewrite_skill_paths() ────────────────────────────────────────────────


class TestRewriteSkillPaths:
    def test_no_skill_path_unchanged(self) -> None:
        cmd = "python3 scripts/run.py"
        result, name = rewrite_skill_paths(cmd)
        assert result == cmd
        assert name is None

    def test_single_skill_path_rewritten(self) -> None:
        cmd = "python3 .claude/skills/my-tool/scripts/run.py"
        result, name = rewrite_skill_paths(cmd)
        assert result == "python3 scripts/run.py"
        assert name == "my-tool"

    def test_multiple_same_skill_paths(self) -> None:
        cmd = "python3 .claude/skills/tool/a.py .claude/skills/tool/b.py"
        result, name = rewrite_skill_paths(cmd)
        assert "a.py" in result
        assert "b.py" in result
        assert ".claude/skills" not in result
        assert name == "tool"

    def test_multiple_different_skills_logs_warning_and_uses_first(self, caplog: pytest.LogCaptureFixture) -> None:
        cmd = "python3 .claude/skills/alpha/a.py .claude/skills/beta/b.py"
        with caplog.at_level(logging.WARNING):
            result, name = rewrite_skill_paths(cmd)
        assert result == "python3 a.py b.py"
        assert name == "alpha"
        assert "Multiple skills detected in command" in caplog.text
        assert "alpha" in caplog.text
        assert "beta" in caplog.text


# ── detect_skill_script_command() ────────────────────────────────────────


class TestDetectSkillScriptCommand:
    def test_skill_path_detected(self) -> None:
        detected, name = detect_skill_script_command("python3 .claude/skills/my-tool/run.py")
        assert detected is True
        assert name == "my-tool"

    def test_no_skill_path(self) -> None:
        detected, name = detect_skill_script_command("echo hello")
        assert detected is False
        assert name is None

    def test_hyphenated_skill_name(self) -> None:
        detected, name = detect_skill_script_command(
            "python3 .claude/skills/google-workspace/scripts/google_api.py calendar-today"
        )
        assert detected is True
        assert name == "google-workspace"
