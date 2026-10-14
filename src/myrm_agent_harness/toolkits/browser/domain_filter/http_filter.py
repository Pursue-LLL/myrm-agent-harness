"""HTTP/HTTPS route filter with hop-by-hop private network & metadata revalidation.

[INPUT]
- .types / pool.config::ResourceBlockConfig
- utils.private_origins::private_origin_grants (POS: per-context registry of explicitly navigated private origins)
- .context_lists::DomainListPolicy, bind_domain_lists (POS: the context's domain allow/block lists and the rule that applies them)
- core.security.redirect_hop_guard::RedirectHopEvaluator, HopDisposition (POS: literal-host private network and cloud metadata classification, no DNS)
- patchright.async_api::BrowserContext, Route
- urllib.parse::urlparse

[OUTPUT]
- install_http_filter: installs route filter on BrowserContext
- _abort_route_safely: safe route abort wrapper
- _continue_route_safely: safe route fallback wrapper

[POS]
Layer 1 network route filter. Protects browser sessions from loading internal addresses,
AWS/GCP/Azure IMDS metadata (169.254.169.254) or blocked domains in any request it is handed.
patchright does not hand over the hops of a document redirect: the navigation guard judges those
after the load, private and metadata targets by address and domain lists by the policy this filter
binds to the context (``domain_filter.context_lists``).
A local-mode session (``allow_private_networks``) keeps its own machine reachable for subresources
and for documents from origins it was sent to explicitly; any other private document, such as a
page script or link pointing the tab at loopback, is aborted like in the cloud.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from myrm_agent_harness.core.security.redirect_hop_guard import HopDisposition, RedirectHopEvaluator
from myrm_agent_harness.toolkits.browser.domain_filter.context_lists import DomainListPolicy, bind_domain_lists
from myrm_agent_harness.toolkits.browser.utils.private_origins import private_origin_grants

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
) -> None:
    """Block requests to private/metadata IPs, non-allowed domains, and unwanted resource types.

    Filtering order (security-first):
    1. Hop-by-hop private network & cloud metadata revalidation (SSRF defense). With
       ``allow_private_networks`` only documents are checked, and origins the session navigated to
       explicitly pass; cloud metadata never does. Steps 2-4 always apply.
    2. Ad/tracker domain blocklist (performance + anti-fingerprinting)
    3. Domain blocklist & allowlist validation (security boundary)
    4. Resource type filtering (performance optimization)
    """
    evaluator = RedirectHopEvaluator(grants=private_origin_grants(context) if allow_private_networks else None)
    domain_lists = DomainListPolicy(allowlist, domain_blocklist)
    if not domain_lists.is_empty:
        # The navigation guard applies the same lists to the redirect hops this filter never sees.
        bind_domain_lists(context, domain_lists)

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
        if not allow_private_networks or resource_type == "document":
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

        # 4. Explicit domain blocklist, then allowlist
        if domain_lists.violation(hostname) is not None:
            await _abort_route_safely(route)
            return

        # 5. Resource type filtering
        if resource_block:
            attr_name = _RESOURCE_TYPE_MAP.get(resource_type)
            if attr_name and getattr(resource_block, attr_name):
                await _abort_route_safely(route)
                return

        await _continue_route_safely(route)

    await context.route("**/*", _handler)
