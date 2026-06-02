"""Tests for security preflight checks extracted to _preflight_checks.py.

Covers:
- check_command_url_exfiltration: URL data exfiltration detection
- check_sensitive_paths: Sensitive directory access blocking
- check_interactive_command: Interactive command detection (already covered
  by test_interactive_command_preflight.py, included here for completeness)
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.bash._preflight_checks import (
    check_command_url_exfiltration,
    check_interactive_command,
    check_sensitive_paths,
)
from myrm_agent_harness.utils.errors import ToolError


class TestCheckSensitivePaths:
    """Test sensitive path preflight detection."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat ~/.ssh/id_rsa",
            "ls .ssh/",
            "cat .aws/credentials",
            'rm -rf "/home/user/.gnupg"',
            "cat ~/.npmrc",
            "ls ~/.docker/config.json",
            "cat ~/.kube/config",
            "cat ~/.bash_history",
            "cat ~/.zsh_history",
            "cp .ssh/id_rsa /tmp/",
        ],
    )
    def test_blocks_sensitive_paths(self, command: str) -> None:
        with pytest.raises(ToolError, match="security"):
            check_sensitive_paths(command)

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "cat /etc/hosts",
            "echo hello",
            "ssh user@host",
            "git push",
            "python script.py",
            "cat nossh_file.txt",
            "echo .ssh_simulation",
        ],
    )
    def test_allows_safe_commands(self, command: str) -> None:
        check_sensitive_paths(command)


class TestCheckCommandUrlExfiltration:
    """Test URL data exfiltration detection."""

    def test_safe_url_passes(self) -> None:
        check_command_url_exfiltration("curl https://api.example.com/data")

    def test_safe_wget_passes(self) -> None:
        check_command_url_exfiltration("wget https://releases.example.com/v1.0.tar.gz")

    def test_no_url_passes(self) -> None:
        check_command_url_exfiltration("echo hello world")

    def test_local_url_passes(self) -> None:
        check_command_url_exfiltration("curl http://localhost:8080/health")


class TestCheckInteractiveCommand:
    """Minimal smoke tests for interactive command detection.

    Full coverage is in test_interactive_command_preflight.py.
    """

    def test_safe_command_returns_none(self) -> None:
        assert check_interactive_command("ls -la") is None

    def test_scaffold_without_flag_returns_message(self) -> None:
        result = check_interactive_command("npx create-next-app my-app")
        assert result is not None
        assert "interactive" in result.lower()

    def test_scaffold_with_yes_flag_returns_none(self) -> None:
        assert check_interactive_command("npx create-next-app my-app --yes") is None

    def test_git_commit_without_message_detected(self) -> None:
        result = check_interactive_command("git commit")
        assert result is not None

    def test_git_commit_with_message_passes(self) -> None:
        assert check_interactive_command('git commit -m "fix"') is None
