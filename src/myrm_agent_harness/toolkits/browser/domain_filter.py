"""Domain deep filtering — four-layer defense-in-depth for browser network egress.

Prevents pages from exfiltrating data through non-HTTP channels (WebSocket,
EventSource, sendBeacon, WebRTC, WebTransport) that bypass Playwright's
``context.route()``.

Architecture
~~~~~~~~~~~~

Layer 0 — CSP Core Defense (``<meta http-equiv="Content-Security-Policy">``)
    Browser-native policy enforcement via Content Security Policy.
    Restricts network connections (fetch/XHR/WebSocket/EventSource/sendBeacon) and
    script/iframe loading in main thread AND all Web Workers.
    Does NOT restrict img/style/font/media (allows CDN resources for compatibility).

Layer 1 — Protocol Interception (``context.route('**/*')``)
    Hard-blocks all HTTP/HTTPS requests to non-allowed domains.
    Supports resource type filtering (image/stylesheet/script/font/media).
    Fallback defense if CSP is disabled.

Layer 2 — Main Thread Hardening (``context.add_init_script()``)
    Hardens RTCPeerConnection and WebTransport (not covered by CSP).
    Disables Service Worker registration (offline cache not needed for agents).
    Does NOT harden Web Workers to avoid anti-bot detection.

Layer 3 — CDP Audit Monitor (``Network.webSocketCreated``)
    Detects WebSocket connections at the Chrome DevTools Protocol level.
    Does not block — provides audit visibility for all layers.


[INPUT]
- pool.config::ResourceBlockConfig (POS: resource blocking config, includes block_ad_domains flag)
- ad_domains::AD_DOMAINS (POS: frozenset of ~3500 ad/tracker domains, lazy-loaded when block_ad_domains=True)

[OUTPUT]
- DomainAllowlist: immutable domain pattern matcher
- install_domain_filter: async installer for all four layers with resource blocking

[POS]
Deep domain filtering, resource blocking, and ad/tracker domain blocking module for the browser toolkit.
Called by ContextFactory during context creation. Covers HTTP + WebSocket + EventSource + sendBeacon +
WebRTC + WebTransport across all channels, with resource type blocking (image/stylesheet/script/font/media)
and ad/tracker domain blocklist (~3500 domains via ad_domains.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext, Page, Route

    from myrm_agent_harness.toolkits.browser.pool.config import ResourceBlockConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core data structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DomainAllowlist:
    """Immutable domain allowlist with exact and wildcard matching.

    Patterns:
    - ``"example.com"`` — exact match
    - ``"*.example.com"`` — matches ``example.com`` and all subdomains
    """

    patterns: tuple[str, ...]

    def is_allowed(self, hostname: str) -> bool:
        """Check whether *hostname* matches any allowed pattern."""
        hostname = hostname.lower()
        for pattern in self.patterns:
            if pattern.startswith("*."):
                suffix = pattern[1:]  # ".example.com"
                bare = pattern[2:]  # "example.com"
                if hostname == bare or hostname.endswith(suffix):
                    return True
            elif hostname == pattern:
                return True
        return False

    @classmethod
    def from_strings(cls, domains: Sequence[str]) -> DomainAllowlist:
        """Create from a sequence of domain pattern strings."""
        cleaned = tuple(d.strip().lower() for d in domains if d.strip())
        return cls(patterns=cleaned)

    @property
    def is_empty(self) -> bool:
        return len(self.patterns) == 0


# Blocklist uses the same pattern matcher as allowlist; ``is_allowed`` means "matches block rule".
DomainBlocklist = DomainAllowlist


# ---------------------------------------------------------------------------
# Layer 0: CSP policy generation
# ---------------------------------------------------------------------------


def build_csp_meta_script(allowlist: DomainAllowlist) -> str:
    """Generate script that injects CSP meta tag before page loads.

    CSP covers main thread AND all Web Workers (fetch/XHR/WebSocket/EventSource/
    sendBeacon/importScripts). Enforced at browser kernel level, cannot be
    bypassed by page scripts.

    CSP directives:
    - connect-src: Restricts network connections (fetch/XHR/WebSocket/EventSource/sendBeacon)
    - script-src: Restricts script loading (allows inline/eval for compatibility)
    - frame-src: Restricts iframe loading
    - object-src: Blocks plugins (Flash/Java)

    Note: img-src/style-src/font-src/media-src are not restricted (allow CDN resources).
    """
    normalized_domains = []
    for p in allowlist.patterns:
        if p.startswith("*."):
            bare = p[2:]
            normalized_domains.append(bare)
            normalized_domains.append(p)
        else:
            normalized_domains.append(p)

    domains_list = " ".join(normalized_domains) if normalized_domains else ""

    directives = ["object-src 'none'"]
    if domains_list:
        directives.extend(
            [
                f"connect-src 'self' {domains_list}",
                f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {domains_list}",
                f"frame-src 'self' {domains_list}",
            ]
        )
    else:
        directives.extend(
            [
                "connect-src 'self'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
                "frame-src 'self'",
            ]
        )

    csp_content = "; ".join(directives)

    return f"""(function() {{
  'use strict';
  if (!document.head) {{
    document.documentElement.appendChild(document.createElement('head'));
  }}
  var meta = document.createElement('meta');
  meta.httpEquiv = 'Content-Security-Policy';
  meta.content = {json.dumps(csp_content)};
  document.head.insertBefore(meta, document.head.firstChild);
}})();"""


# ---------------------------------------------------------------------------
# Layer 2: Main thread hardening
# ---------------------------------------------------------------------------


def build_init_script() -> str:
    """Generate JavaScript IIFE that hardens special APIs not covered by CSP.

    Hardens:
    - RTCPeerConnection/webkitRTCPeerConnection (WebRTC Data Channel)
    - WebTransport (new standard)
    - Service Worker registration

    Web Workers are not hardened (CSP Layer 0 handles Worker network restrictions).
    """
    return """(function() {
  'use strict';

  function _harden(obj, prop, value) {
    try {
      Object.defineProperty(obj, prop, {
        value: value,
        writable: false,
        configurable: false,
        enumerable: true
      });
    } catch(e) {
      obj[prop] = value;
    }
  }

  if (typeof RTCPeerConnection !== 'undefined') {
    _harden(window, 'RTCPeerConnection', function() {
      throw new DOMException(
        'RTCPeerConnection blocked by domain policy', 'SecurityError'
      );
    });
  }
  if (typeof webkitRTCPeerConnection !== 'undefined') {
    _harden(window, 'webkitRTCPeerConnection', function() {
      throw new DOMException(
        'RTCPeerConnection blocked by domain policy', 'SecurityError'
      );
    });
  }

  if (typeof WebTransport !== 'undefined') {
    _harden(window, 'WebTransport', function() {
      throw new DOMException(
        'WebTransport blocked by domain policy', 'SecurityError'
      );
    });
  }

  if (typeof navigator !== 'undefined' && navigator.serviceWorker) {
    _harden(navigator.serviceWorker, 'register', function() {
      return Promise.reject(new DOMException(
        'Service Worker registration blocked by domain policy', 'SecurityError'
      ));
    });
  }
})();"""


# ---------------------------------------------------------------------------
# Orchestrator: install all four layers
# ---------------------------------------------------------------------------


async def install_domain_filter(
    context: BrowserContext,
    allowlist: DomainAllowlist,
    *,
    domain_blocklist: DomainBlocklist | None = None,
    enable_cdp_audit: bool = True,
    resource_block: ResourceBlockConfig | None = None,
) -> None:
    """Install four-layer domain filtering on a BrowserContext.

    Does nothing if *allowlist* is empty, *domain_blocklist* is empty, and no resource blocking is configured.

    Args:
        context: Patchright BrowserContext to protect.
        allowlist: Domains the page is allowed to connect to.
        domain_blocklist: Domains always blocked (checked before allowlist).
        enable_cdp_audit: Whether to install CDP WebSocket audit monitoring.
        resource_block: Resource blocking configuration (images/css/js/fonts/media/ad-domains).
    """
    has_resource_block = False
    if resource_block:
        has_resource_block = any(
            getattr(resource_block, k) for k in _RESOURCE_TYPE_MAP.values()
        )

    ad_blocklist: frozenset[str] | None = None
    if resource_block and resource_block.block_ad_domains:
        from myrm_agent_harness.toolkits.browser.ad_domains import AD_DOMAINS

        ad_blocklist = AD_DOMAINS

    if allowlist.is_empty and not has_resource_block and not ad_blocklist and (
        domain_blocklist is None or domain_blocklist.is_empty
    ):
        return

    if not allowlist.is_empty:
        await _install_csp_policy(context, allowlist)
        await _install_main_thread_hardening(context)

    await _install_http_filter(context, allowlist, resource_block, ad_blocklist, domain_blocklist)

    if enable_cdp_audit and not allowlist.is_empty:
        context.on("page", lambda page: _schedule_cdp_audit(page, allowlist))

    logger.warning(
        "Domain filter / Resource block installed: %d allow patterns, %d block patterns, CDP audit=%s, resource_block=%s, ad_blocklist=%d",
        len(allowlist.patterns) if allowlist else 0,
        len(domain_blocklist.patterns) if domain_blocklist else 0,
        enable_cdp_audit and not allowlist.is_empty,
        resource_block is not None,
        len(ad_blocklist) if ad_blocklist else 0,
    )


# ---------------------------------------------------------------------------
# Layer 0: CSP policy injection
# ---------------------------------------------------------------------------


async def _install_csp_policy(context: BrowserContext, allowlist: DomainAllowlist) -> None:
    """Inject CSP meta tag to restrict network access in main thread and Workers."""
    await context.add_init_script(build_csp_meta_script(allowlist))


# ---------------------------------------------------------------------------
# Layer 1: Protocol interception
# ---------------------------------------------------------------------------


_RESOURCE_TYPE_MAP: dict[str, str] = {
    "image": "block_images",
    "stylesheet": "block_stylesheets",
    "script": "block_scripts",
    "font": "block_fonts",
    "media": "block_media",
}


def _is_ad_domain(hostname: str, blocklist: frozenset[str]) -> bool:
    """Check if hostname matches any blocked ad domain via suffix walking.

    Walks up the hostname's suffix chain with O(1) frozenset lookups per level:
    e.g. "tracker.ads.doubleclick.net" checks "tracker.ads.doubleclick.net",
    then "ads.doubleclick.net", then "doubleclick.net".
    """
    if hostname in blocklist:
        return True
    idx = hostname.find(".")
    while idx != -1:
        suffix = hostname[idx + 1:]
        if "." in suffix and suffix in blocklist:
            return True
        idx = hostname.find(".", idx + 1)
    return False


async def _install_http_filter(
    context: BrowserContext,
    allowlist: DomainAllowlist,
    resource_block: ResourceBlockConfig | None = None,
    ad_blocklist: frozenset[str] | None = None,
    domain_blocklist: DomainBlocklist | None = None,
) -> None:
    """Block HTTP/HTTPS requests to non-allowed domains, ad domains, and unwanted resource types via context.route.

    Filtering order (security-first):
    1. Ad/tracker domain blocklist (performance + anti-fingerprinting)
    2. Domain allowlist validation (security)
    3. Resource type filtering (performance optimization)
    """

    async def _handler(route: Route) -> None:
        url = route.request.url
        resource_type: str = route.request.resource_type

        if not url.startswith(("http://", "https://")):
            if resource_type == "document":
                await route.abort("blockedbyclient")
            else:
                await route.continue_()
            return

        hostname = urlparse(url).hostname or ""

        if ad_blocklist and _is_ad_domain(hostname, ad_blocklist):
            await route.abort("blockedbyclient")
            return

        if domain_blocklist and not domain_blocklist.is_empty and domain_blocklist.is_allowed(hostname):
            await route.abort("blockedbyclient")
            return

        if not allowlist.is_empty and not allowlist.is_allowed(hostname):
            await route.abort("blockedbyclient")
            return

        if resource_block:
            attr_name = _RESOURCE_TYPE_MAP.get(resource_type)
            if attr_name and getattr(resource_block, attr_name):
                await route.abort("blockedbyclient")
                return

        await route.continue_()

    await context.route("**/*", _handler)


# ---------------------------------------------------------------------------
# Layer 2: Main thread hardening
# ---------------------------------------------------------------------------


async def _install_main_thread_hardening(context: BrowserContext) -> None:
    """Inject init script that hardens special APIs not covered by CSP."""
    await context.add_init_script(build_init_script())


# ---------------------------------------------------------------------------
# Layer 3: CDP audit monitor
# ---------------------------------------------------------------------------


def _schedule_cdp_audit(page: Page, allowlist: DomainAllowlist) -> None:
    """Schedule CDP audit installation for a new page (non-async callback)."""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_install_cdp_audit(page, allowlist))
        task.add_done_callback(_log_task_exception)
    except RuntimeError:
        pass


def _log_task_exception(task: asyncio.Task[None]) -> None:
    """Log unhandled exceptions from fire-and-forget CDP audit tasks."""
    if not task.cancelled() and task.exception():
        logger.warning("CDP audit task failed: %s", task.exception())


async def _install_cdp_audit(page: Page, allowlist: DomainAllowlist) -> None:
    """Listen for WebSocket creation events via CDP and log violations."""
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable")

        def _on_ws_created(params: dict[str, object]) -> None:
            url = str(params.get("url", ""))
            hostname = urlparse(url).hostname or ""
            if not allowlist.is_allowed(hostname):
                logger.warning(
                    "SECURITY AUDIT: Unexpected WebSocket connection to non-allowed domain: %s",
                    url,
                )

        cdp.on("Network.webSocketCreated", _on_ws_created)
    except Exception as exc:
        logger.warning("CDP audit monitor setup failed (non-critical): %s", exc)
