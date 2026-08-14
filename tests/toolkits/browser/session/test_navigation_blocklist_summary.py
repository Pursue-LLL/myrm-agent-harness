"""Tests for navigate blocklist enforcement and compact interactive summary."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist
from myrm_agent_harness.toolkits.browser.pool.extension_bridge import (
    ExtensionBridgeNotAvailableError,
    ExtensionTab,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    _NAVIGATE_INTERACTIVE_SUMMARY_MAX_LINES,
    BrowserSessionNavigationMixin,
)
from myrm_agent_harness.utils.errors import ToolError


class _NavigationProbe(BrowserSessionNavigationMixin):
    def __init__(self, blocklist: DomainAllowlist | None = None) -> None:
        self._domain_blocklist = blocklist
        self.snapshot = AsyncMock()


class _ExtensionNavigationProbe(BrowserSessionNavigationMixin):
    def __init__(self, bridge: MagicMock) -> None:
        self._extension_bridge = bridge


def test_hostname_blocked_by_policy_matches_blocklist() -> None:
    probe = _NavigationProbe(DomainAllowlist.from_strings(["facebook.com"]))
    blocked = probe._hostname_blocked_by_policy("https://facebook.com/login")
    assert blocked == "facebook.com"


def test_hostname_blocked_by_policy_empty_blocklist() -> None:
    probe = _NavigationProbe(DomainAllowlist.from_strings([]))
    assert probe._hostname_blocked_by_policy("https://example.com") is None


@pytest.mark.asyncio
async def test_append_navigate_interactive_summary_caps_lines() -> None:
    probe = _NavigationProbe()
    lines = [f'- button "B{i}" [ref=e{i}]' for i in range(30)]
    snap = MagicMock()
    snap.aria_tree = "\n".join(lines)
    probe.snapshot = AsyncMock(return_value=snap)

    result = await probe._append_navigate_interactive_summary("Navigated OK")

    assert "Navigated OK" in result
    assert f"max {_NAVIGATE_INTERACTIVE_SUMMARY_MAX_LINES}" in result
    assert "10 more refs" in result


@pytest.mark.asyncio
async def test_append_navigate_interactive_summary_snapshot_failure_returns_base() -> None:
    probe = _NavigationProbe()
    probe.snapshot = AsyncMock(side_effect=RuntimeError("snapshot failed"))

    result = await probe._append_navigate_interactive_summary("Navigated OK")

    assert result == "Navigated OK"


@pytest.mark.asyncio
async def test_navigate_raises_when_domain_blocked() -> None:
    probe = _NavigationProbe(DomainAllowlist.from_strings(["evil.com"]))
    probe._ensure_components = AsyncMock()
    tab_ctrl = MagicMock()
    tab_ctrl.list_tabs.return_value = ["existing-tab"]
    probe._tab_controller = tab_ctrl
    probe._terminal_challenges = {}

    with pytest.raises(ToolError) as exc_info:
        await probe.navigate("https://evil.com/page")

    assert exc_info.value.error_code == "BROWSER_URL_BLOCKLIST"
    probe._ensure_components.assert_awaited_once()


@pytest.mark.asyncio
async def test_navigate_via_extension_prefers_navigate_url_path() -> None:
    bridge = MagicMock()
    bridge.is_connected.return_value = True
    bridge.navigate_to_url = AsyncMock(
        return_value=ExtensionTab(
            tab_id=11,
            url="http://portal.corp.local/dashboard",
            title="Dashboard",
            domain="portal.corp.local",
            active=False,
        )
    )
    bridge.connect_to_domain = AsyncMock()

    probe = _ExtensionNavigationProbe(bridge)
    result = await probe._navigate_via_extension("http://portal.corp.local/dashboard")

    assert "via extension bridge — private network" in result
    bridge.connect_to_domain.assert_not_awaited()


@pytest.mark.asyncio
async def test_navigate_via_extension_unknown_action_requires_extension_upgrade() -> None:
    bridge = MagicMock()
    bridge.is_connected.return_value = True
    bridge.navigate_to_url = AsyncMock(side_effect=ExtensionBridgeNotAvailableError("Unknown action: navigate_url"))
    bridge.connect_to_domain = AsyncMock()

    probe = _ExtensionNavigationProbe(bridge)
    with pytest.raises(ToolError) as exc_info:
        await probe._navigate_via_extension("http://portal.corp.local/health")

    assert exc_info.value.error_code == "PRIVATE_URL_EXTENSION_UPGRADE_REQUIRED"
    bridge.connect_to_domain.assert_not_awaited()


@pytest.mark.asyncio
async def test_navigate_via_extension_maps_disconnected_to_extension_lost() -> None:
    bridge = MagicMock()
    bridge.is_connected.return_value = True
    bridge.navigate_to_url = AsyncMock(
        side_effect=ExtensionBridgeNotAvailableError("Browser extension is not connected")
    )
    bridge.connect_to_domain = AsyncMock()

    probe = _ExtensionNavigationProbe(bridge)
    with pytest.raises(ToolError) as exc_info:
        await probe._navigate_via_extension("http://portal.corp.local/health")

    assert exc_info.value.error_code == "PRIVATE_URL_EXTENSION_LOST"
    bridge.connect_to_domain.assert_not_awaited()
