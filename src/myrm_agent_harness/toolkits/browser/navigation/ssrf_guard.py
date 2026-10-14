"""SSRF guard for Playwright document navigation (redirect-aware).

[INPUT]
- core.security.guards.ssrf::async_pin_url (POS: DNS-validated URL checks + audit)
- core.security.redirect_hop_guard::RedirectHopEvaluator, PrivateOriginGrants (POS: literal private/metadata classification)
- utils.page_health::abort_pending_navigation (POS: bounded browser and page health primitives)

[OUTPUT]
- BrowserNavigationBlockedError: a navigation URL failed SSRF validation
- assert_browser_navigation_allowed: Validate a navigation URL
- assert_browser_redirect_chain_allowed: Walk redirect chain on a Playwright Request
- goto_with_ssrf_guard: page.goto with temporary document-level route interception

[POS]
Playwright-specific SSRF guard aligned with OpenClaw document navigation policy.
Reuses core SSRF guards; does not duplicate IP blocklists. Redirect hops are not routable under
patchright, so they are judged after the load; a document that violates policy is discarded by
resetting the tab to ``about:blank`` before the error is raised. A failed navigation is stopped
before the route handler is removed, and the removal itself is bounded, because a main frame
stuck in a stalled navigation never answers `unroute`.

Two policies share this module. Without grants (cloud) every resolved address must be public.
With grants (local mode) only the literal host is classified: private origins pass when the agent
navigated there explicitly, and cloud metadata endpoints never pass.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from myrm_agent_harness.core.security.redirect_hop_guard import (
    HopDisposition,
    PrivateOriginGrants,
    RedirectHopEvaluator,
)

from ..utils.page_health import abort_pending_navigation

if TYPE_CHECKING:
    from patchright.async_api import Page, Request, Response, Route

_NETWORK_SCHEMES = frozenset({"http", "https"})
_UNROUTE_TIMEOUT_S = 2.0
_BLANK_TIMEOUT_S = 2.0


class BrowserNavigationBlockedError(ValueError):
    """Raised when a browser navigation URL fails SSRF validation."""


async def assert_browser_navigation_allowed(url: str, grants: PrivateOriginGrants | None = None) -> None:
    """Validate URL for browser navigation.

    Without ``grants`` the host is resolved and every address must be public (audited on block).
    With ``grants`` only the literal host is classified: the user's own resolver may legitimately
    map public names to proxy or VPN ranges, so DNS answers are not second-guessed there.
    """
    parsed = urlparse(url)
    if parsed.scheme == "about":
        return
    if parsed.scheme not in _NETWORK_SCHEMES:
        raise BrowserNavigationBlockedError(f"Unsupported navigation scheme: {url}")

    if grants is not None:
        verdict = RedirectHopEvaluator(grants=grants).evaluate_hop(url)
        if verdict.disposition != HopDisposition.ALLOW:
            raise BrowserNavigationBlockedError(f"SSRF blocked: {verdict.reason}")
        return

    from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError, async_pin_url

    try:
        await async_pin_url(url)
    except SSRFSecurityError as exc:
        raise BrowserNavigationBlockedError(f"SSRF blocked: {exc}") from exc


async def assert_browser_redirect_chain_allowed(
    request: Request | None, grants: PrivateOriginGrants | None = None
) -> None:
    """Validate every hop in a Playwright redirect chain."""
    current: Request | None = request
    while current is not None:
        await assert_browser_navigation_allowed(current.url, grants)
        current = current.redirected_from


def _is_document_navigation(page: Page, request: Request) -> bool:
    if request.resource_type != "document":
        return False
    frame = request.frame
    if frame is None:
        return False
    return frame == page.main_frame or frame.parent_frame == page.main_frame


async def _continue_route_safely(route: Route) -> None:
    """Fall through to subsequent route handlers (including patchright's inject route).

    Uses ``route.fallback()`` — NOT ``route.continue_()`` — because patchright
    implements ``add_init_script`` via a network-level inject route (see
    ``domain_filter._continue_route_safely``). ``continue_()`` terminates the
    handler chain and silently disables all init scripts (dom_enhancer, stealth,
    localStorage restore) on the current context.
    """
    try:
        await route.fallback()
    except Exception as exc:
        if "Route is already handled" in str(exc):
            return
        raise


async def _discard_committed_document(page: Page) -> None:
    """Reset the tab so a document that failed validation can no longer be read.

    Best effort and bounded; cancellation still propagates.
    """
    with contextlib.suppress(Exception):
        await asyncio.wait_for(page.goto("about:blank", wait_until="commit"), timeout=_BLANK_TIMEOUT_S)


async def goto_with_ssrf_guard(
    page: Page,
    url: str,
    *,
    timeout_ms: int,
    grants: PrivateOriginGrants | None = None,
) -> Response | None:
    """Navigate with document-level SSRF route guard and post-navigation redirect checks.

    ``grants`` selects the local-mode policy; navigating to ``url`` grants its own origin. The
    requested URL is checked before anything is loaded, so a rejected request leaves the tab on
    the page it was showing instead of on Chromium's error page.
    """
    if grants is not None:
        grants.grant(url)
    await assert_browser_navigation_allowed(url, grants)

    blocked_error: BrowserNavigationBlockedError | None = None

    async def handler(route: Route, request: Request) -> None:
        nonlocal blocked_error
        if blocked_error is not None:
            with contextlib.suppress(Exception):
                await route.abort()
            return
        if not _is_document_navigation(page, request):
            await _continue_route_safely(route)
            return
        try:
            await assert_browser_navigation_allowed(request.url, grants)
        except BrowserNavigationBlockedError as exc:
            if request.frame == page.main_frame:
                blocked_error = exc
            with contextlib.suppress(Exception):
                await route.abort()
            return
        await _continue_route_safely(route)

    await page.route("**/*", handler)
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if blocked_error is not None:
            raise blocked_error
        await assert_browser_redirect_chain_allowed(response.request if response else None, grants)
        await assert_browser_navigation_allowed(page.url, grants)
        return response
    except BaseException as exc:
        await abort_pending_navigation(page)
        if isinstance(exc, Exception) and blocked_error is not None and exc is not blocked_error:
            # The abort made goto fail; report the policy decision instead of the symptom.
            raise blocked_error from exc
        if isinstance(exc, BrowserNavigationBlockedError) and exc is not blocked_error:
            # Judged after the load: the blocked document is already committed in the tab.
            await _discard_committed_document(page)
        raise
    finally:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(page.unroute("**/*", handler), timeout=_UNROUTE_TIMEOUT_S)
