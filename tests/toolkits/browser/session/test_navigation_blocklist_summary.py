"""Tests for navigate blocklist enforcement and compact interactive summary."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist
from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    BrowserSessionNavigationMixin,
    _NAVIGATE_INTERACTIVE_SUMMARY_MAX_LINES,
)
from myrm_agent_harness.utils.errors import ToolError


class _NavigationProbe(BrowserSessionNavigationMixin):
    def __init__(self, blocklist: DomainAllowlist | None = None) -> None:
        self._domain_blocklist = blocklist
        self.snapshot = AsyncMock()


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
