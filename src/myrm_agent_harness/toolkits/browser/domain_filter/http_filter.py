"""HTTP/HTTPS route filter with hop-by-hop private network & metadata revalidation.

[INPUT]
- .types / pool.config::ResourceBlockConfig
- core.security.redirect_hop_guard::RedirectHopEvaluator, HopDisposition
- patchright.async_api::BrowserContext, Route
- urllib.parse::urlparse

[OUTPUT]
- install_http_filter: installs route filter on BrowserContext
- _abort_route_safely: safe route abort wrapper
- _continue_route_safely: safe route fallback wrapper

[POS]
Layer 1 network route filter. Protects browser sessions from navigating or redirecting
to internal addresses, AWS/GCP/Azure IMDS metadata (169.254.169.254), or blocked domains.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from myrm_agent_harness.core.security.redirect_hop_guard import (
    HopDisposition,
    RedirectHopEvaluator,
    RedirectHopGuardConfig,
)

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext, Route

    from myrm_agent_harness.toolkits.browser.domain_filter import (
        DomainAllowlist,
        DomainBlocklist,
    )
    from myrm_agent_harness.toolkits.browser.pool.config import ResourceBlockConfig

logger = logging.getLogger(__name__)

_RESOURCE_TYPE_MAP: dict[str, str] = {
    "image": "block_images",
    "stylesheet": "block_stylesheets",
    "script": "block_scripts",
    "font": "block_fonts",
    "media": "block_media",
}


async def _continue_route_safely(route: Route) -> None:
    """Continue route; ignore duplicate handling when page+context handlers overlap.

    Uses ``route.fallback()`` so requests flow through subsequent handlers
    such as init script injection.
    """
    try:
        await route.fallback()
    except Exception as exc:
        if "Route is already handled" in str(exc):
            return
        raise


async def _abort_route_safely(route: Route, *, error_code: str = "blockedbyclient") -> None:
    """Safely abort route without raising if already handled."""
    try:
        await route.abort(error_code)
    except Exception as exc:
        if "Route is already handled" in str(exc):
            return
        raise


def _is_ad_domain(hostname: str, blocklist: frozenset[str]) -> bool:
    """Check if hostname matches any blocked ad domain via suffix walking."""
    if hostname in blocklist:
        return True
    idx = hostname.find(".")
    while idx != -1:
        suffix = hostname[idx + 1 :]
        if "." in suffix and suffix in blocklist:
            return True
        idx = hostname.find(".", idx + 1)
    return False


async def install_http_filter(
    context: BrowserContext,
    allowlist: DomainAllowlist,
    resource_block: ResourceBlockConfig | None = None,
    ad_blocklist: frozenset[str] | None = None,
    domain_blocklist: DomainBlocklist | None = None,
    *,
    allow_private_networks: bool = False,
    hop_evaluator: RedirectHopEvaluator | None = None,
) -> None:
    """Block requests to private/metadata IPs, non-allowed domains, and unwanted resource types.

    Filtering order (security-first):
    1. Hop-by-hop private network & cloud metadata revalidation (SSRF defense)
    2. Ad/tracker domain blocklist (performance + anti-fingerprinting)
    3. Domain blocklist & allowlist validation (security boundary)
    4. Resource type filtering (performance optimization)
    """
    evaluator = hop_evaluator or RedirectHopEvaluator(
        RedirectHopGuardConfig(allow_private_networks=allow_private_networks)
    )

    async def _handler(route: Route) -> None:
        url = route.request.url
        resource_type: str = route.request.resource_type

        # 1. Non-http protocols
        if not url.startswith(("http://", "https://")):
            if resource_type == "document" and not url.startswith("about:"):
                await _abort_route_safely(route)
            else:
                await _continue_route_safely(route)
            return

        # 2. Hop-by-hop private address & cloud metadata IMDS revalidation
        if not allow_private_networks:
            hop_eval = evaluator.evaluate_hop(url, resource_type=resource_type)
            if hop_eval.disposition != HopDisposition.ALLOW:
                logger.warning(
                    "SECURITY INTERCEPTION: Blocked private/metadata hop [%s] -> %s (Rule: %s, Reason: %s)",
                    hop_eval.disposition.value,
                    url,
                    hop_eval.matched_rule,
                    hop_eval.reason,
                )
                if hop_eval.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT:
                    # Attempt resetting page to about:blank if frame and page are accessible
                    try:
                        frame = route.request.frame
                        if frame and frame.page and not frame.page.is_closed():
                            await frame.page.goto("about:blank")
                    except Exception as reset_exc:
                        logger.debug("Failed to reset tab to about:blank: %s", reset_exc)

                await _abort_route_safely(route)
                return

        hostname = urlparse(url).hostname or ""

        # 3. Ad / tracker blocklist
        if ad_blocklist and _is_ad_domain(hostname, ad_blocklist):
            await _abort_route_safely(route)
            return

        # 4. Explicit domain blocklist
        if domain_blocklist and not domain_blocklist.is_empty and domain_blocklist.is_blocked(hostname):
            await _abort_route_safely(route)
            return

        # 5. Domain allowlist
        if not allowlist.is_empty and not allowlist.is_allowed(hostname):
            await _abort_route_safely(route)
            return

        # 6. Resource type filtering
        if resource_block:
            attr_name = _RESOURCE_TYPE_MAP.get(resource_type)
            if attr_name and getattr(resource_block, attr_name):
                await _abort_route_safely(route)
                return

        await _continue_route_safely(route)

    await context.route("**/*", _handler)
