"""Tests for cua-driver MCP spawn ``--no-overlay`` policy."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends import cua_driver_spawn as spawn


@pytest.fixture(autouse=True)
def _clear_spawn_caches() -> None:
    spawn.reset_cua_driver_spawn_caches()
    yield
    spawn.reset_cua_driver_spawn_caches()


class TestDefaultCuaNoOverlay:
    def test_explicit_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_CUA_NO_OVERLAY", "true")
        assert spawn.default_cua_no_overlay() is True

    def test_explicit_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_CUA_NO_OVERLAY", "0")
        assert spawn.default_cua_no_overlay() is False

    def test_macos_defaults_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_CUA_NO_OVERLAY", raising=False)
        with patch.object(spawn.sys, "platform", "darwin"):
            assert spawn.default_cua_no_overlay() is True

    def test_linux_wayland_defaults_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_CUA_NO_OVERLAY", raising=False)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        with patch.object(spawn.sys, "platform", "linux"):
            with patch.object(spawn, "_detect_wsl", return_value=False):
                assert spawn.default_cua_no_overlay() is False

    def test_linux_x11_defaults_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_CUA_NO_OVERLAY", raising=False)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        with patch.object(spawn.sys, "platform", "linux"):
            with patch.object(spawn, "_detect_wsl", return_value=False):
                assert spawn.default_cua_no_overlay() is True


class TestMcpStdioArgs:
    def test_appends_flag_when_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_CUA_NO_OVERLAY", "1")
        with patch.object(spawn, "cua_driver_supports_no_overlay", return_value=True):
            assert spawn.mcp_stdio_args("cua-driver") == ["mcp", "--no-overlay"]

    def test_skips_flag_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_CUA_NO_OVERLAY", "0")
        with patch.object(spawn, "cua_driver_supports_no_overlay", return_value=True):
            assert spawn.mcp_stdio_args("cua-driver") == ["mcp"]

    def test_skips_flag_when_driver_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_CUA_NO_OVERLAY", "1")
        with patch.object(spawn, "cua_driver_supports_no_overlay", return_value=False):
            assert spawn.mcp_stdio_args("cua-driver") == ["mcp"]
