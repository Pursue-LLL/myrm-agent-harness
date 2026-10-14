"""Document-response script injector for patchright contexts.

patchright's ``add_init_script`` relies on a network-level inject route that
silently no-ops in current releases (verified empirically; upstream issues
patchright-python#112 family). This module provides the working alternative:
intercept document responses, rewrite the HTML body to prepend ``<script>``
tags, and ``fulfill`` — scripts delivered this way execute in the page's main
world (probe-verified).

One route handler serves ALL registered scripts per context: ``route.fulfill``
terminates the Playwright route chain, so multiple handlers would be mutually
exclusive — scripts must be batched into a single rewrite.

The handler performs the document request itself, so it must stay transparent to the
browser: redirects are never followed here (a 3xx is fulfilled unchanged and Chromium
follows it, which keeps the page URL, origin, cookies and ``redirected_from`` chain
correct for the SSRF checks), and every response it does not rewrite is fulfilled from
the same single request instead of being requested again.

[INPUT]
- patchright.async_api::BrowserContext, Route, APIResponse (POS: browser context primitives)
- enhancers.dom_enhancer_loader::get_dom_enhancer_script (POS: DOM enhancer JS)
- pool.stealth::get_stealth_script (POS: stealth anti-detection JS)

[OUTPUT]
- install_document_script_injection: register per-context document rewrite handler

[POS]
Browser context script-injection fallback. Bridges the gap between Playwright's
init-script contract and patchright's broken network-level implementation by
delivering scripts inside the document response body.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import APIResponse, BrowserContext, Route

logger = logging.getLogger(__name__)

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_INSTALLED_FLAG = "__myrm_script_injection_installed"
_PROVIDER_FLAG = "__myrm_script_providers"


async def _rewrite_html(response: APIResponse, providers: list[Callable[[], str]]) -> bytes | None:
    """Return the response body with every provider's script prepended, or None to leave it untouched."""
    if 300 <= response.status < 400:
        return None
    content_type = (response.headers or {}).get("content-type", "")
    if not any(ct in content_type for ct in _HTML_CONTENT_TYPES):
        return None
    body = await response.body()
    if not body:
        return None
    # Decode with the response's declared charset (default utf-8) so the rewritten body can
    # be re-encoded to the exact original byte stream around the insertion.
    charset = "utf-8"
    for part in content_type.split(";"):
        part = part.strip().lower()
        if part.startswith("charset="):
            charset = part.removeprefix("charset=").strip().strip('"') or "utf-8"
    try:
        text = body.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return None
    script_tags = "".join(
        "<script>{}</script>".format(provider().replace("</script>", "<\\/script>")) for provider in providers
    )
    head_pos = text.find("</head>")
    if head_pos != -1:
        injected = text[:head_pos] + script_tags + text[head_pos:]
    else:
        injected = script_tags + text
    return injected.encode(charset, errors="replace")


async def _inject_handler(route: Route, providers: list[Callable[[], str]]) -> None:
    """Fulfill document requests with all registered script tags prepended to HTML bodies."""
    try:
        if route.request.resource_type != "document" or not providers:
            await route.fallback()
            return
        response = await route.fetch(max_redirects=0)
        rewritten = await _rewrite_html(response, providers)
        if rewritten is None:
            await route.fulfill(response=response)
        else:
            await route.fulfill(response=response, body=rewritten)
    except Exception:
        with contextlib.suppress(Exception):
            await route.fallback()


async def install_document_script_injection(
    context: BrowserContext,
    script_provider: Callable[[], str],
    *,
    label: str = "script",
) -> None:
    """Register a script to run on every HTML page in this context.

    Scripts accumulate in a per-context registry served by a single route
    handler (multiple fulfill-based handlers would be mutually exclusive).
    Safe to call multiple times on the same context.

    Args:
        context: patchright BrowserContext
        script_provider: Returns the JS source to inject (lazy, cached upstream)
        label: Short name for log messages
    """
    providers: list[Callable[[], str]] | None = getattr(context, _PROVIDER_FLAG, None)
    if providers is None:
        providers = []
        setattr(context, _PROVIDER_FLAG, providers)

    if not getattr(context, _INSTALLED_FLAG, False):
        registered = providers

        async def handler(route: Route) -> None:
            await _inject_handler(route, registered)

        await context.route("**/*", handler)
        setattr(context, _INSTALLED_FLAG, True)

    providers.append(script_provider)
    logger.debug("Document %s injection registered (%d scripts total)", label, len(providers))
