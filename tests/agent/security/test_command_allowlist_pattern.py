"""Tests for shell command allowlist pattern helpers."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.command_allowlist_pattern import (
    derive_command_pattern,
    is_compound_shell_command,
    matches_command_pattern,
)

# Keep aligned with myrm-agent-frontend/src/lib/approval/__tests__/shellCommandDisplay.test.ts
DERIVE_PATTERN_PARITY_VECTORS: list[tuple[str, str | None]] = [
    ("npm install lodash", "npm install *"),
    ("ls -la", "ls -la *"),
    ("curl -sS http://127.0.0.1:9/ALLOWLIST_LIVE_PROBE", "curl -sS *"),
    ("npm install && rm -rf /", None),
    ("npm install | grep foo", None),
    ("npm install; rm file", None),
    ("npm install\nrm -rf /", None),
    ("npm install\r\nrm -rf /", None),
    ("npm install & rm -rf /", None),
    ("npm install|grep foo", None),
    ("npm install > out.txt", None),
    ("npm install < in.txt", None),
    ("npm install $(rm -rf /)", None),
    ("npm install `id`", None),
    ('npm install "$(id)"', None),
    ("(npm install)", None),
    ("npm install 'oops", None),
    ("npm install 'a;b | c'", "npm install *"),
    ('npm install "a && b"', "npm install *"),
    ("npm test 2>&1", "npm test *"),
    ("npm test >/dev/null 2>&1", "npm test *"),
    ("npm test # run everything; fast", "npm test *"),
]


class TestCompoundShellDetection:
    def test_simple_command_is_not_compound(self) -> None:
        assert is_compound_shell_command("npm install") is False

    @pytest.mark.parametrize(
        "command",
        [
            "npm install && rm -rf /",
            "npm install | grep foo",
            "npm install; rm file",
            "npm install ;",
            "npm install\nrm -rf /",
            "npm install\rrm -rf /",
            "npm install & rm -rf /",
            "npm install |& tee log",
            "npm install>out.txt",
            "npm install < in.txt",
            "npm install <<< 'x'",
            "npm install `id`",
            "npm install $(id)",
            'npm install "$(id)"',
            'npm install "`id`"',
            "(npm install)",
            "npm install 'unterminated",
            "npm install trailing\\",
            "npm install 2>file",
            "npm install > /dev/null",
            "npm install 3>&1 4>&2",
            "echo a$$'\\' ; touch x '",
        ],
    )
    def test_compound_operators_detected(self, command: str) -> None:
        assert is_compound_shell_command(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "npm install lodash",
            "npm install 'a;b | c && d'",
            'npm install "a; b"',
            "npm install a\\;b",
            "npm install # one; two | three",
            "npm install \\\n --save",
            'echo "$HOME"',
            "echo $HOME ${HOME}",
            "echo $'a;b'",
            "echo a$'\\' ; touch x '",
            "npm test 2>&1",
            "npm test >&2",
            "npm test >/dev/null",
            "npm test 2>/dev/null",
            "npm test &>/dev/null",
            "npm test >/dev/null 2>&1",
            "npm test </dev/null",
            "npm test >>/dev/null",
        ],
    )
    def test_one_plain_command_is_not_compound(self, command: str) -> None:
        assert is_compound_shell_command(command) is False

    def test_blank_command_is_not_compound(self) -> None:
        assert is_compound_shell_command("") is False
        assert is_compound_shell_command("  \n ") is False


class TestDeriveCommandPattern:
    @pytest.mark.parametrize(("command", "expected"), DERIVE_PATTERN_PARITY_VECTORS)
    def test_parity_vectors(self, command: str, expected: str | None) -> None:
        assert derive_command_pattern(command) == expected

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

    @pytest.mark.parametrize(
        "command",
        [
            "npm install\nrm -rf /",
            "npm install\r\nrm -rf /",
            "npm install & rm -rf /",
            "npm install|sh",
            "npm install `rm -rf /`",
            "npm install $(rm -rf /)",
            "npm install > ~/.bashrc",
            "npm install < /etc/passwd",
        ],
    )
    def test_command_with_more_than_the_approved_command_never_matches(self, command: str) -> None:
        assert matches_command_pattern("npm install *", command) is False

    @pytest.mark.parametrize("command", ["pytest -q 2>&1", "pytest -q >/dev/null 2>&1", "pytest -q # all tests; quick"])
    def test_harmless_stream_handling_still_matches(self, command: str) -> None:
        assert matches_command_pattern("pytest *", command) is True
