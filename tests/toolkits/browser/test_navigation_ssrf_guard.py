"""Tests for browser navigation SSRF guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
    BrowserNavigationBlockedError,
    assert_browser_navigation_allowed,
    assert_browser_redirect_chain_allowed,
    goto_with_ssrf_guard,
)


@pytest.mark.asyncio
async def test_assert_browser_navigation_allowed_blocks_private() -> None:
    with (
        patch(
            "myrm_agent_harness.core.security.guards.ssrf.async_pin_url",
            side_effect=SSRFSecurityError("blocked"),
        ),
        pytest.raises(BrowserNavigationBlockedError, match="SSRF blocked"),
    ):
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
        "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed",
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


@pytest.mark.asyncio
async def test_navigation_failure_wraps_browser_navigation_error() -> None:
    """Non-timeout navigation failures should raise BrowserNavigationError."""
    from myrm_agent_harness.toolkits.browser.exceptions import BrowserNavigationError
    from myrm_agent_harness.toolkits.browser.navigation import Navigator

    page = AsyncMock()
    navigator = Navigator(page=page)

    raw_err = ConnectionError("net::ERR_NAME_NOT_RESOLVED")
    with (
        patch(
            "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.goto_with_ssrf_guard",
            side_effect=raw_err,
        ),
        pytest.raises(BrowserNavigationError) as exc_info,
    ):
        await navigator.goto("https://invalid-domain-xyz.com")

    wrapped = exc_info.value
    assert wrapped.diagnostic_info["url"] == "https://invalid-domain-xyz.com"
    assert "net::ERR_NAME_NOT_RESOLVED" in wrapped.diagnostic_info["error_text"]
    assert wrapped.__cause__ is raw_err


@pytest.mark.asyncio
async def test_navigation_timeout_uses_rescue_not_wrap() -> None:
    """Timeouts should be rescued (window.stop) instead of raising BrowserNavigationError."""
    from myrm_agent_harness.toolkits.browser.navigation import Navigator

    page = AsyncMock()
    page.evaluate.return_value = None
    page.title.return_value = "page title"
    page.url = "https://example.com/"
    navigator = Navigator(page=page)

    with patch(
        "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.goto_with_ssrf_guard",
        side_effect=TimeoutError("Navigation timeout"),
    ):
        title, final_url, status_code = await navigator.goto("https://example.com/")

    assert title == "page title"
    assert status_code == 200
    page.evaluate.assert_awaited_once()


@pytest.mark.asyncio
async def test_ssrf_block_propagates_unwrapped() -> None:
    """SSRF security blocks must propagate as-is, never wrapped as navigation failures."""
    from myrm_agent_harness.toolkits.browser.navigation import Navigator
    from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
        BrowserNavigationBlockedError,
    )

    navigator = Navigator(page=AsyncMock())

    block = BrowserNavigationBlockedError("SSRF blocked: internal network")
    with (
        patch(
            "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.goto_with_ssrf_guard",
            side_effect=block,
        ),
        pytest.raises(BrowserNavigationBlockedError),
    ):
        await navigator.goto("http://192.168.1.1/api")
