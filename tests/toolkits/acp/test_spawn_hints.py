"""Tests for CLI/ACP spawn failure hints."""

from __future__ import annotations

from myrm_agent_harness.toolkits.acp.runtime._spawn_hints import format_cli_spawn_failure_message


def test_codex_bare_binary_includes_adapter_hint() -> None:
    message = format_cli_spawn_failure_message(
        "codex",
        return_code=1,
        stderr="command not found",
    )
    assert "codex-acp" in message
    assert "Hint:" in message


def test_unknown_binary_no_extra_hint() -> None:
    message = format_cli_spawn_failure_message(
        "/usr/bin/custom-agent",
        return_code=2,
        stderr="failed",
    )
    assert "Hint:" not in message
    assert "code 2" in message
