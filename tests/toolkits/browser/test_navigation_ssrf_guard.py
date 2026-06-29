"""Tests for browser navigation SSRF guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.browser.navigation_ssrf_guard import (
    BrowserNavigationBlockedError,
    assert_browser_navigation_allowed,
    assert_browser_redirect_chain_allowed,
    goto_with_ssrf_guard,
)


@pytest.mark.asyncio
async def test_assert_browser_navigation_allowed_blocks_private() -> None:
    with patch(
        "myrm_agent_harness.core.security.guards.ssrf.async_pin_url",
        side_effect=SSRFSecurityError("blocked"),
    ):
        with pytest.raises(BrowserNavigationBlockedError, match="SSRF blocked"):
            await assert_browser_navigation_allowed("http://169.254.169.254/")


@pytest.mark.asyncio
async def test_assert_browser_redirect_chain_walks_hops() -> None:
    hop1 = MagicMock()
    hop1.url = "http://evil.example/1"
    hop1.redirected_from = None
    hop2 = MagicMock()
    hop2.url = "http://evil.example/2"
    hop2.redirected_from = hop1

    with patch(
        "myrm_agent_harness.toolkits.browser.navigation_ssrf_guard.assert_browser_navigation_allowed",
        new_callable=AsyncMock,
    ) as mock_assert:
        await assert_browser_redirect_chain_allowed(hop2)
        assert mock_assert.await_count == 2


@pytest.mark.asyncio
async def test_goto_with_ssrf_guard_skips_when_local_mode() -> None:
    page = AsyncMock()
    page.goto.return_value = MagicMock(status=200, request=MagicMock(return_value=None))

    await goto_with_ssrf_guard(
        page,
        "http://127.0.0.1:3000",
        timeout_ms=1000,
        allow_private_networks=True,
    )

    page.route.assert_not_called()
    page.goto.assert_awaited_once()


@pytest.mark.asyncio
async def test_goto_with_ssrf_guard_installs_route_handler() -> None:
    page = AsyncMock()
    request = MagicMock()
    request.url = "https://example.com/"
    request.redirected_from = None
    response = MagicMock()
    response.request = request
    page.goto.return_value = response
    page.url = "https://example.com/"

    with patch(
        "myrm_agent_harness.core.security.guards.ssrf.async_pin_url",
        return_value=("https://example.com/", {}),
    ):
        await goto_with_ssrf_guard(
            page,
            "https://example.com/",
            timeout_ms=1000,
            allow_private_networks=False,
        )

    page.route.assert_awaited_once()
    page.unroute.assert_awaited_once()
