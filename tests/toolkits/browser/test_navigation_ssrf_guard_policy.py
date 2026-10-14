"""Unit tests for the navigation guard's local-mode policy, error precedence and tab reset.

The real-Chromium behavior is covered by ``test_local_mode_navigation_policy_integration.py``;
these tests pin the guard's decisions with scripted pages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.redirect_hop_guard import PrivateOriginGrants
from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import (
    BrowserNavigationBlockedError,
    assert_browser_navigation_allowed,
    assert_browser_redirect_chain_allowed,
    goto_with_ssrf_guard,
)

_ABORT = "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.abort_pending_navigation"
_PIN = "myrm_agent_harness.core.security.guards.ssrf.async_pin_url"


def _page(final_url: str, *, redirected_from: str | None = None) -> AsyncMock:
    """A page whose navigation ends on ``final_url`` (optionally after one redirect hop)."""
    page = AsyncMock()
    page.main_frame = MagicMock()
    page.url = final_url
    request = MagicMock()
    request.url = final_url
    request.redirected_from = None
    if redirected_from is not None:
        hop = MagicMock()
        hop.url = redirected_from
        hop.redirected_from = None
        request.redirected_from = hop
    response = MagicMock()
    response.request = request
    page.goto.return_value = response
    return page


def _document_request(page: AsyncMock, url: str) -> MagicMock:
    request = MagicMock()
    request.resource_type = "document"
    request.url = url
    request.frame = page.main_frame
    return request


class TestLocalModePolicy:
    @pytest.mark.asyncio
    async def test_private_origin_passes_only_when_granted(self) -> None:
        grants = PrivateOriginGrants()
        with pytest.raises(BrowserNavigationBlockedError, match="SSRF blocked"):
            await assert_browser_navigation_allowed("http://localhost:3000/", grants)
        grants.grant("http://localhost:3000/anything")
        await assert_browser_navigation_allowed("http://localhost:3000/app", grants)
        with pytest.raises(BrowserNavigationBlockedError):
            await assert_browser_navigation_allowed("http://localhost:3001/", grants)

    @pytest.mark.asyncio
    async def test_cloud_metadata_is_blocked_even_when_granted(self) -> None:
        grants = PrivateOriginGrants()
        grants.grant("http://169.254.169.254/")
        with pytest.raises(BrowserNavigationBlockedError):
            await assert_browser_navigation_allowed("http://169.254.169.254/latest/", grants)

    @pytest.mark.asyncio
    async def test_public_hosts_are_not_resolved_in_local_mode(self) -> None:
        """The user's resolver may map public names to proxy ranges; DNS answers are not judged locally."""
        with patch(_PIN, new_callable=AsyncMock) as pin:
            await assert_browser_navigation_allowed("https://example.com/", PrivateOriginGrants())
        pin.assert_not_called()

    @pytest.mark.asyncio
    async def test_cloud_policy_still_resolves_and_pins(self) -> None:
        with patch(_PIN, new_callable=AsyncMock) as pin:
            await assert_browser_navigation_allowed("https://example.com/")
        pin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redirect_chain_is_judged_per_hop_with_grants(self) -> None:
        grants = PrivateOriginGrants()
        grants.grant("http://localhost:3000/")
        page = _page("http://localhost:3000/home", redirected_from="http://localhost:3000/start")
        await assert_browser_redirect_chain_allowed(page.goto.return_value.request, grants)

        elsewhere = _page("http://localhost:3000/home", redirected_from="http://localhost:9999/start")
        with pytest.raises(BrowserNavigationBlockedError):
            await assert_browser_redirect_chain_allowed(elsewhere.goto.return_value.request, grants)

    @pytest.mark.asyncio
    async def test_navigating_explicitly_grants_the_origin_without_resolving_dns(self) -> None:
        grants = PrivateOriginGrants()
        page = _page("http://localhost:3000/app")
        with patch(_PIN, new_callable=AsyncMock) as pin:
            await goto_with_ssrf_guard(page, "http://localhost:3000/app", timeout_ms=1000, grants=grants)
        pin.assert_not_called()
        assert grants.permits("http://localhost:3000/other-path")
        assert not grants.permits("http://localhost:3001/")


class TestBlockedNavigation:
    @pytest.mark.asyncio
    async def test_redirect_into_another_private_origin_resets_the_loaded_tab(self) -> None:
        grants = PrivateOriginGrants()
        page = _page("http://localhost:9999/secret", redirected_from="http://localhost:3000/go")
        with patch(_ABORT, new_callable=AsyncMock), pytest.raises(BrowserNavigationBlockedError):
            await goto_with_ssrf_guard(page, "http://localhost:3000/go", timeout_ms=1000, grants=grants)
        assert [call.args[0] for call in page.goto.await_args_list] == ["http://localhost:3000/go", "about:blank"]

    @pytest.mark.asyncio
    async def test_a_rejected_request_is_not_navigated_to_and_the_tab_is_untouched(self) -> None:
        page = _page("https://example.com/")
        with pytest.raises(BrowserNavigationBlockedError):
            await goto_with_ssrf_guard(page, "http://169.254.169.254/", timeout_ms=1000, grants=PrivateOriginGrants())
        page.goto.assert_not_awaited()
        page.route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_block_is_reported_as_policy_error_not_as_the_driver_failure(self) -> None:
        """An aborted main-frame request makes goto fail; the caller must see why, not 'ERR_FAILED'."""
        grants = PrivateOriginGrants()
        page = _page("http://localhost:3000/start")
        handlers: list[Callable[..., Awaitable[None]]] = []

        async def capture(_pattern: str, handler: Callable[..., Awaitable[None]]) -> None:
            handlers.append(handler)

        async def goto_aborted_by_the_guard(*_args: object, **_kwargs: object) -> None:
            await handlers[0](AsyncMock(), _document_request(page, "http://localhost:9999/api"))
            raise RuntimeError("net::ERR_FAILED")

        page.route = capture
        page.goto.side_effect = goto_aborted_by_the_guard
        with patch(_ABORT, new_callable=AsyncMock), pytest.raises(BrowserNavigationBlockedError) as caught:
            await goto_with_ssrf_guard(page, "http://localhost:3000/start", timeout_ms=1000, grants=grants)
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert page.goto.await_count == 1

    @pytest.mark.asyncio
    async def test_cancellation_is_never_turned_into_a_policy_error(self) -> None:
        grants = PrivateOriginGrants()
        page = _page("http://localhost:3000/start")
        handlers: list[Callable[..., Awaitable[None]]] = []

        async def capture(_pattern: str, handler: Callable[..., Awaitable[None]]) -> None:
            handlers.append(handler)

        async def goto_blocked_then_cancelled(*_args: object, **_kwargs: object) -> None:
            await handlers[0](AsyncMock(), _document_request(page, "http://localhost:9999/api"))
            raise asyncio.CancelledError

        page.route = capture
        page.goto.side_effect = goto_blocked_then_cancelled
        with patch(_ABORT, new_callable=AsyncMock), pytest.raises(asyncio.CancelledError):
            await goto_with_ssrf_guard(page, "http://localhost:3000/start", timeout_ms=1000, grants=grants)

    @pytest.mark.asyncio
    async def test_reset_failure_never_masks_the_policy_error(self) -> None:
        page = _page("http://localhost:9999/secret", redirected_from="http://localhost:3000/go")
        page.goto.side_effect = [page.goto.return_value, RuntimeError("page crashed")]
        with patch(_ABORT, new_callable=AsyncMock), pytest.raises(BrowserNavigationBlockedError):
            await goto_with_ssrf_guard(page, "http://localhost:3000/go", timeout_ms=1000, grants=PrivateOriginGrants())


class TestNavigatorGrantsWiring:
    """Which grants the navigator hands to the guard: none in cloud mode, a private set if given, else the context's."""

    @staticmethod
    async def _navigate(page: AsyncMock, **navigator_kwargs: object) -> PrivateOriginGrants | None:
        """Navigate once and return the grants the guard received (the guard itself is stubbed to refuse)."""
        from myrm_agent_harness.toolkits.browser.navigation import Navigator

        navigator = Navigator(page=page, auto_dismiss_popups=False, **navigator_kwargs)  # type: ignore[arg-type]
        guard = AsyncMock(side_effect=BrowserNavigationBlockedError("stub"))
        with (
            patch("myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.goto_with_ssrf_guard", guard),
            pytest.raises(BrowserNavigationBlockedError),
        ):
            await navigator.goto("http://localhost:3000/")
        return guard.await_args.kwargs["grants"]

    @pytest.mark.asyncio
    async def test_cloud_mode_passes_no_grants(self) -> None:
        assert await self._navigate(AsyncMock()) is None

    @pytest.mark.asyncio
    async def test_private_origins_are_ignored_in_cloud_mode(self) -> None:
        assert await self._navigate(AsyncMock(), private_origins=PrivateOriginGrants()) is None

    @pytest.mark.asyncio
    async def test_explicit_grants_are_used_as_given(self) -> None:
        own = PrivateOriginGrants()

        assert await self._navigate(AsyncMock(), allow_private_networks=True, private_origins=own) is own

    @pytest.mark.asyncio
    async def test_default_is_the_registry_shared_by_the_pages_context(self) -> None:
        from myrm_agent_harness.toolkits.browser.utils.private_origins import private_origin_grants

        page = AsyncMock()

        passed = await self._navigate(page, allow_private_networks=True)

        assert passed is private_origin_grants(page.context)
