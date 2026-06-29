"""SSRF guard for Playwright document navigation (redirect-aware).

[INPUT]
- core.security.guards.ssrf::async_pin_url (POS: DNS-validated URL checks + audit)

[OUTPUT]
- assert_browser_navigation_allowed: Validate a navigation URL
- assert_browser_redirect_chain_allowed: Walk redirect chain on a Playwright Request
- goto_with_ssrf_guard: page.goto with temporary document-level route interception

[POS]
Playwright-specific SSRF guard aligned with OpenClaw document navigation policy.
Reuses core SSRF guards; does not duplicate IP blocklists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from patchright.async_api import Page, Request, Response, Route

_NETWORK_SCHEMES = frozenset({"http", "https"})


class BrowserNavigationBlockedError(ValueError):
    """Raised when a browser navigation URL fails SSRF validation."""


async def assert_browser_navigation_allowed(url: str) -> None:
    """Validate URL for browser navigation (async DNS + audit on block)."""
    parsed = urlparse(url)
    if parsed.scheme == "about":
        return
    if parsed.scheme not in _NETWORK_SCHEMES:
        raise BrowserNavigationBlockedError(f"Unsupported navigation scheme: {url}")

    from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError, async_pin_url

    try:
        await async_pin_url(url)
    except SSRFSecurityError as exc:
        raise BrowserNavigationBlockedError(f"SSRF blocked: {exc}") from exc


async def assert_browser_redirect_chain_allowed(request: Request | None) -> None:
    """Validate every hop in a Playwright redirect chain."""
    if request is None:
        return
    current: Request | None = request
    while current is not None:
        await assert_browser_navigation_allowed(current.url)
        current = current.redirected_from


def _is_document_navigation(page: Page, request: Request) -> bool:
    if request.resource_type != "document":
        return False
    frame = request.frame
    if frame is None:
        return False
    return frame == page.main_frame or frame.parent_frame == page.main_frame


async def _continue_route_safely(route: Route) -> None:
    try:
        await route.continue_()
    except Exception as exc:
        if "Route is already handled" in str(exc):
            return
        raise


async def goto_with_ssrf_guard(
    page: Page,
    url: str,
    *,
    timeout_ms: int,
    allow_private_networks: bool,
) -> Response | None:
    """Navigate with document-level SSRF route guard and post-navigation redirect checks."""
    if allow_private_networks:
        return await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    blocked_error: BaseException | None = None

    async def handler(route: Route, request: Request) -> None:
        nonlocal blocked_error
        if blocked_error is not None:
            try:
                await route.abort()
            except Exception:
                pass
            return
        if not _is_document_navigation(page, request):
            await _continue_route_safely(route)
            return
        try:
            await assert_browser_navigation_allowed(request.url)
        except BrowserNavigationBlockedError as exc:
            if request.frame == page.main_frame:
                blocked_error = exc
            try:
                await route.abort()
            except Exception:
                pass
            return
        await _continue_route_safely(route)

    await page.route("**/*", handler)
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if blocked_error is not None:
            raise blocked_error
        await assert_browser_redirect_chain_allowed(response.request if response else None)
        await assert_browser_navigation_allowed(page.url)
        return response
    finally:
        await page.unroute("**/*", handler)
