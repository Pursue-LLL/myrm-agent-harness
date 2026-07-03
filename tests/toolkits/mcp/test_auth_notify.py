"""Unit tests for MCP auth-expiry notification hook."""

from __future__ import annotations

import myrm_agent_harness.toolkits.mcp.auth_notify as auth_notify


def test_register_and_notify_invokes_handler() -> None:
    auth_notify._handlers.clear()
    calls: list[tuple[str, str]] = []

    def _handler(server_name: str, error_detail: str) -> None:
        calls.append((server_name, error_detail))

    auth_notify.register_mcp_auth_expired_handler(_handler)
    auth_notify.notify_mcp_auth_expired("github-mcp", "401 Unauthorized")

    assert calls == [("github-mcp", "401 Unauthorized")]


def test_notify_skips_failing_handlers() -> None:
    auth_notify._handlers.clear()
    calls: list[str] = []

    def _bad(_server: str, _detail: str) -> None:
        raise RuntimeError("handler boom")

    def _good(server_name: str, _detail: str) -> None:
        calls.append(server_name)

    auth_notify.register_mcp_auth_expired_handler(_bad)
    auth_notify.register_mcp_auth_expired_handler(_good)
    auth_notify.notify_mcp_auth_expired("linear-mcp", "token expired")

    assert calls == ["linear-mcp"]


def test_wire_mcp_auth_expired_handler_registers_callback() -> None:
    from myrm_agent_harness.runtime.events import _wire_mcp_auth_expired_handler

    auth_notify._handlers.clear()
    _wire_mcp_auth_expired_handler()
    assert len(auth_notify._handlers) == 1
