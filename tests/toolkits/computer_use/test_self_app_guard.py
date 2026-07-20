"""Additional self-app guard tests."""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.safety import is_self_app, is_sensitive_app, normalize_modifiers
from myrm_agent_harness.toolkits.computer_use.types import ModifierKey


def test_self_app_blocks_myrm_bundle_id() -> None:
    result = is_self_app("MyrmAgent", app_id="com.myrmagent.app")
    assert result is not None
    assert "Blocked" in result


def test_self_app_blocks_cursor_host_name() -> None:
    result = is_self_app("Cursor", app_id="com.todesktop.230313mzl4w4u92")
    assert result is not None


def test_sensitive_app_delegates_to_self_app_guard() -> None:
    result = is_sensitive_app("MyrmAgent", app_id="com.myrmagent.app")
    assert result is not None


def test_self_app_does_not_block_electron_process_name() -> None:
    assert is_self_app("Electron", app_id="") is None
    assert is_self_app("Electron Helper", app_id="") is None
    assert is_sensitive_app("Electron", app_id="") is None


def test_self_app_still_blocks_cursor_host() -> None:
    assert is_self_app("Cursor", app_id="") is not None


def test_self_app_blocks_inspector_window_title() -> None:
    result = is_self_app("Safari", window_title="Desktop Inspector — Myrm")
    assert result is not None
    assert "Desktop Inspector" in result or "agent UI" in result


def test_self_app_blocks_todesktop_bundle_with_cursor_name() -> None:
    result = is_self_app(
        "Cursor",
        app_id="com.todesktop.230313mzl4w4u92",
    )
    assert result is not None
    assert "Cursor" in result


def test_normalize_modifiers_empty() -> None:
    assert normalize_modifiers(None) is None
    assert normalize_modifiers([]) is None


def test_normalize_modifiers_returns_copy() -> None:
    mods: list[ModifierKey] = ["ctrl", "shift"]
    copied = normalize_modifiers(mods)
    assert copied == mods
    assert copied is not mods
