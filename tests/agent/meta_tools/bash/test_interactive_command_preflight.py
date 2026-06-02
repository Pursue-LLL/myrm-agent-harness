"""Tests for interactive command preflight detection in bash_tool.

Validates that commands requiring stdin input are blocked before execution.
"""

import pytest

from myrm_agent_harness.agent.meta_tools.bash._preflight_checks import (
    check_interactive_command as _check_interactive_command,
)


class TestJsScaffoldDetection:
    """Test JS ecosystem scaffold command detection."""

    @pytest.mark.parametrize(
        "command",
        [
            "npm create vite@latest my-app",
            "npm init react-app my-app",
            "npx create-next-app my-app",
            "npx create-react-app my-app",
            "yarn create next-app my-app",
            "yarn init my-project",
            "pnpm create vite my-app",
            "pnpm init",
            "bun create vite my-app",
            "bunx create-next-app my-app",
            "NPM CREATE vite@latest",
        ],
    )
    def test_blocks_interactive_scaffold(self, command: str) -> None:
        result = _check_interactive_command(command)
        assert result is not None
        assert "interactive" in result.lower()

    @pytest.mark.parametrize(
        "command",
        [
            "npm create vite@latest my-app -- --template react --yes",
            "npx create-next-app my-app --yes",
            "npx create-next-app my-app -y",
            "npm init -y",
            "yarn create next-app --defaults",
            "pnpm create vite --non-interactive",
            "npm create vite --ci",
        ],
    )
    def test_allows_non_interactive_scaffold(self, command: str) -> None:
        result = _check_interactive_command(command)
        assert result is None


class TestGitInteractiveDetection:
    """Test git interactive command detection."""

    def test_blocks_git_commit_without_message(self) -> None:
        result = _check_interactive_command("git commit")
        assert result is not None
        assert "-m" in result

    def test_blocks_git_commit_with_only_flags(self) -> None:
        result = _check_interactive_command("git commit --amend")
        assert result is not None

    def test_allows_git_commit_with_message(self) -> None:
        assert _check_interactive_command('git commit -m "fix: bug"') is None

    def test_allows_git_commit_with_message_long(self) -> None:
        assert _check_interactive_command('git commit --message "fix: bug"') is None

    def test_allows_git_commit_with_file(self) -> None:
        assert _check_interactive_command("git commit -F /tmp/msg.txt") is None

    def test_allows_git_commit_with_file_long(self) -> None:
        assert _check_interactive_command("git commit --file commit_msg.txt") is None

    def test_allows_git_commit_combined_am_flag(self) -> None:
        assert _check_interactive_command('git commit -am "fix: bug"') is None

    def test_allows_git_commit_m_no_space(self) -> None:
        assert _check_interactive_command('git commit -m"no space"') is None

    def test_blocks_git_commit_a_only(self) -> None:
        assert _check_interactive_command("git commit -a") is not None

    def test_blocks_git_rebase_interactive(self) -> None:
        result = _check_interactive_command("git rebase -i HEAD~3")
        assert result is not None
        assert "interactive" in result.lower()

    def test_blocks_git_rebase_interactive_long(self) -> None:
        result = _check_interactive_command("git rebase --interactive HEAD~3")
        assert result is not None

    def test_blocks_git_add_interactive(self) -> None:
        assert _check_interactive_command("git add -i") is not None

    def test_blocks_git_add_patch(self) -> None:
        assert _check_interactive_command("git add -p") is not None

    def test_blocks_git_add_interactive_long(self) -> None:
        assert _check_interactive_command("git add --interactive") is not None

    def test_blocks_git_add_patch_long(self) -> None:
        assert _check_interactive_command("git add --patch") is not None

    def test_allows_normal_git_commands(self) -> None:
        assert _check_interactive_command("git status") is None
        assert _check_interactive_command("git diff") is None
        assert _check_interactive_command("git log --oneline -5") is None
        assert _check_interactive_command("git add .") is None
        assert _check_interactive_command("git push origin main") is None


class TestPythonScaffoldDetection:
    """Test Python ecosystem scaffold command detection."""

    def test_blocks_poetry_init(self) -> None:
        result = _check_interactive_command("poetry init")
        assert result is not None
        assert "--no-interaction" in result

    def test_allows_poetry_init_no_interaction(self) -> None:
        assert _check_interactive_command("poetry init --no-interaction") is None


class TestSafeCommands:
    """Test that normal commands are not blocked."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "cat file.txt",
            "python -c 'print(1)'",
            "pip install requests",
            "npm install express",
            "git clone https://github.com/user/repo",
            "echo hello",
            "mkdir -p /tmp/test",
            "docker ps",
            "curl https://api.example.com",
        ],
    )
    def test_allows_safe_commands(self, command: str) -> None:
        assert _check_interactive_command(command) is None
