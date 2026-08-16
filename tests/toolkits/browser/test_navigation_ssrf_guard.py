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


@patch("myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed")
async def test_goto_with_ssrf_guard_blocks_subresource_request(
    mock_assert: AsyncMock,
) -> None:
    """Non-document requests are continued without SSRF assertion."""
    from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
        goto_with_ssrf_guard,
    )

    page = AsyncMock()
    request = MagicMock()
    request.resource_type = "script"
    request.url = "https://cdn.example.com/app.js"
    request.frame = AsyncMock()
    response = MagicMock()
    response.request = MagicMock()
    response.request.redirected_from = None
    page.goto.return_value = response
    page.main_frame = MagicMock()
    page.url = "https://example.com/"

    captured: list = []

    async def capture_route(pattern, handler):
        captured.append(handler)

    page.route = capture_route
    page.unroute = AsyncMock()

    await goto_with_ssrf_guard(
        page,
        "https://example.com/",
        timeout_ms=1000,
        allow_private_networks=False,
    )
    assert captured, "route handler should be captured"
    handler = captured[0]
    route = AsyncMock()
    assert await handler(route=route, request=request) is None
    route.continue_.assert_awaited_once()
    route.abort.assert_not_awaited()


@patch("myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed")
async def test_goto_with_ssrf_guard_route_handler_blocks_private(
    mock_assert: AsyncMock,
) -> None:
    """SSRF assertion failure inside route handler aborts the request."""
    from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
        BrowserNavigationBlockedError,
        goto_with_ssrf_guard,
    )

    page = AsyncMock()
    request = MagicMock()
    request.resource_type = "document"
    request.url = "http://169.254.169.254/"
    page.main_frame = MagicMock()
    request.frame = page.main_frame
    response = MagicMock()
    response.request = MagicMock()
    response.request.redirected_from = None
    page.goto.return_value = response
    page.url = "https://example.com/"
    mock_assert.side_effect = BrowserNavigationBlockedError(
        "SSRF blocked: metadata service"
    )

    captured: list = []

    async def capture_route(pattern, handler):
        captured.append(handler)

    page.route = capture_route
    page.unroute = AsyncMock()

    with pytest.raises(BrowserNavigationBlockedError):
        await goto_with_ssrf_guard(
            page,
            "https://example.com/",
            timeout_ms=1000,
            allow_private_networks=False,
        )
    handler = captured[0]
    route = AsyncMock()
    assert await handler(route=route, request=request) is None
    route.abort.assert_awaited_once()
    route.continue_.assert_not_awaited()

    # A second request while the block is recorded is also aborted.
    route2 = AsyncMock()
    assert await handler(route=route2, request=request) is None
    route2.abort.assert_awaited_once()

    # Subresource requests after a block are still aborted (cleanup).
    sub_request = MagicMock()
    sub_request.resource_type = "script"
    sub_request.url = "https://cdn.example.com/app.js"
    sub_request.frame = page.main_frame
    route3 = AsyncMock()
    assert await handler(route=route3, request=sub_request) is None
    route3.abort.assert_awaited_once()


@patch("myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed")
async def test_goto_with_ssrf_guard_route_handler_blocks_after_first(
    mock_assert: AsyncMock,
) -> None:
    """Once a main-frame block is recorded, subsequent requests are aborted."""
    from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
        BrowserNavigationBlockedError,
        goto_with_ssrf_guard,
    )

    page = AsyncMock()
    document_request = MagicMock()
    document_request.resource_type = "document"
    document_request.url = "http://169.254.169.254/"
    page.main_frame = MagicMock()
    document_request.frame = page.main_frame
    response = MagicMock()
    response.request = MagicMock()
    response.request.redirected_from = None
    page.goto.return_value = response
    page.url = "https://example.com/"
    mock_assert.side_effect = BrowserNavigationBlockedError(
        "SSRF blocked: metadata service"
    )

    captured: list = []

    async def capture_route(pattern, handler):
        captured.append(handler)

    page.route = capture_route
    page.unroute = AsyncMock()

    with pytest.raises(BrowserNavigationBlockedError):
        await goto_with_ssrf_guard(
            page,
            "https://example.com/",
            timeout_ms=1000,
            allow_private_networks=False,
        )
    handler = captured[0]
    route = AsyncMock()
    assert await handler(route=route, request=document_request) is None
    assert await handler(route=route, request=document_request) is None
    assert route.abort.await_count == 2


@patch("myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed")
async def test_goto_with_ssrf_guard_redirect_chain_checked(
    mock_assert: AsyncMock,
) -> None:
    """Redirect hops are validated after navigation completes."""
    from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
        goto_with_ssrf_guard,
    )

    page = AsyncMock()
    hop1 = MagicMock()
    hop1.url = "http://example.com/1"
    hop1.redirected_from = None
    response = MagicMock()
    response.request = hop1
    page.goto.return_value = response
    page.main_frame = MagicMock()
    page.url = "https://final.example.com/"
    mock_assert.return_value = None

    await goto_with_ssrf_guard(
        page,
        "http://example.com/",
        timeout_ms=1000,
        allow_private_networks=False,
    )

    called_urls = [call.args[0] for call in mock_assert.await_args_list]
    assert "https://final.example.com/" in called_urls
    assert "http://example.com/1" in called_urls


@patch("myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed")
async def test_goto_with_ssrf_guard_route_continue_already_handled(
    mock_assert: AsyncMock,
) -> None:
    """continue_ failing with 'already handled' is swallowed, not raised."""
    from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
        goto_with_ssrf_guard,
    )

    page = AsyncMock()
    request = MagicMock()
    request.resource_type = "script"
    request.url = "https://cdn.example.com/app.js"
    request.frame = page.main_frame
    response = MagicMock()
    response.request = MagicMock()
    response.request.redirected_from = None
    page.goto.return_value = response
    page.main_frame = MagicMock()
    page.url = "https://example.com/"
    mock_assert.return_value = None

    captured: list = []

    async def capture_route(pattern, handler):
        captured.append(handler)

    page.route = capture_route
    page.unroute = AsyncMock()

    await goto_with_ssrf_guard(
        page,
        "https://example.com/",
        timeout_ms=1000,
        allow_private_networks=False,
    )
    handler = captured[0]
    route = AsyncMock()
    route.continue_.side_effect = RuntimeError("Route is already handled.")
    # Swallowed because the route was already handled by a previous interception.
    assert await handler(route=route, request=request) is None


@patch("myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed")
async def test_goto_with_ssrf_guard_route_continue_other_error_raises(
    mock_assert: AsyncMock,
) -> None:
    """Non-'already handled' continue_ failures propagate."""
    from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
        goto_with_ssrf_guard,
    )

    page = AsyncMock()
    request = MagicMock()
    request.resource_type = "script"
    request.url = "https://cdn.example.com/app.js"
    request.frame = page.main_frame
    response = MagicMock()
    response.request = MagicMock()
    response.request.redirected_from = None
    page.goto.return_value = response
    page.main_frame = MagicMock()
    page.url = "https://example.com/"
    mock_assert.return_value = None

    captured: list = []

    async def capture_route(pattern, handler):
        captured.append(handler)

    page.route = capture_route
    page.unroute = AsyncMock()

    await goto_with_ssrf_guard(
        page,
        "https://example.com/",
        timeout_ms=1000,
        allow_private_networks=False,
    )
    handler = captured[0]
    route = AsyncMock()
    route.continue_.side_effect = RuntimeError("unexpected failure")
    with pytest.raises(RuntimeError, match="unexpected failure"):
        await handler(route=route, request=request)


async def test_assert_browser_navigation_allowed_about_blank() -> None:
    """about: scheme is allowed without SSRF pinning."""
    with patch(
        "myrm_agent_harness.core.security.guards.ssrf.async_pin_url",
    ) as mock_pin:
        await assert_browser_navigation_allowed("about:blank")
        mock_pin.assert_not_awaited()


async def test_assert_browser_navigation_allowed_unsupported_scheme() -> None:
    """Non-network schemes are rejected as navigation blocks."""
    with pytest.raises(BrowserNavigationBlockedError, match="Unsupported navigation scheme"):
        await assert_browser_navigation_allowed("ftp://example.com/file")


async def test_assert_browser_redirect_chain_allowed_none() -> None:
    """None request short-circuits the redirect chain walk."""
    with patch(
        "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.assert_browser_navigation_allowed",
        new_callable=AsyncMock,
    ) as mock_assert:
        await assert_browser_redirect_chain_allowed(None)
        mock_assert.assert_not_awaited()
