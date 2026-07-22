"""Tests for shell command allowlist pattern helpers."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.command_allowlist_pattern import (
    derive_command_pattern,
    is_compound_shell_command,
    matches_command_pattern,
)


class TestCompoundShellDetection:
    def test_simple_command_is_not_compound(self) -> None:
        assert is_compound_shell_command("npm install") is False

    @pytest.mark.parametrize(
        "command",
        [
            "npm install && rm -rf /",
            "npm install | grep foo",
            "npm install; rm file",
        ],
    )
    def test_compound_operators_detected(self, command: str) -> None:
        assert is_compound_shell_command(command) is True


class TestDeriveCommandPattern:
    def test_two_token_prefix(self) -> None:
        assert derive_command_pattern("npm install lodash") == "npm install *"

    def test_flagged_command_uses_first_two_tokens(self) -> None:
        assert derive_command_pattern("ls -la") == "ls -la *"

    def test_compound_command_returns_none(self) -> None:
        assert derive_command_pattern("npm install && rm -rf /") is None


class TestMatchesCommandPattern:
    def test_prefix_pattern_matches_variants(self) -> None:
        assert matches_command_pattern("npm install *", "npm install --legacy-peer-deps")

    def test_compound_command_never_matches_pattern(self) -> None:
        assert matches_command_pattern("npm install *", "npm install && rm -rf /") is False

    def test_unrelated_command_does_not_match(self) -> None:
        assert matches_command_pattern("npm install *", "git status") is False
