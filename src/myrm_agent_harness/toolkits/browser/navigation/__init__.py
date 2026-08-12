"""Page navigation utility — reusable across browser and web_fetch


[INPUT]
- logging::getLogger (POS: Python logging)
- time::perf_counter (POS: high-precision timer)
- urllib.parse::urlparse (POS: URL parsing)
- patchright.async_api::Page (POS: Patchright page instance)
- .pool.throttle::ThrottleStrategy (POS: throttle strategy protocol)
- .pool.config::BrowserMode, NavigationWaitConfig (POS: browser configuration)
- .wait::wait_for_page_ready, WaitStrategy, WaitMetrics (POS: smart wait strategies)
- .ssrf_guard::goto_with_ssrf_guard (POS: Playwright document navigation SSRF guard)
- .session.consent_dismisser::ConsentDismisser (POS: cookie consent auto-dismiss)

[OUTPUT]
- Navigator: page navigation manager (with throttling, smart wait, and consent dismissal)

[POS]
Page navigation utility module. Responsibilities:
1. Page navigation (goto) + throttle control
2. History navigation (back/forward/reload)
3. Smart wait (hybrid detection: DOM + network dual guarantee)
4. Timeout control + full metrics exposure
5. Cookie consent auto-dismiss (optional, for BrowserFetcher path)

Design principles:
- Independent utility module, reusable by BrowserSession and BrowserFetcher
- Integrates throttle strategy for unified navigation frequency control
- Smart wait: hybrid detection (DOM stable + network idle) dual guarantee
- Single responsibility: only handles navigation logic; does not handle tab management, snapshot, interaction, etc.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from myrm_agent_harness.core.security.redact import redact_sensitive_text

from ..wait import WaitMetrics, WaitStrategy, wait_for_page_ready

if TYPE_CHECKING:
    from patchright.async_api import Page

    from myrm_agent_harness.toolkits.web_fetch.router.domain_metrics import (
        DomainMetricsManager,
    )

    from ..pool.circuit_breaker import CircuitBreaker
    from ..pool.config import BrowserMode, NavigationWaitConfig
    from ..pool.throttle import ThrottleStrategy

logger = logging.getLogger(__name__)

_NAVIGATION_TIMEOUT_MS = 15_000
_ALLOWED_SCHEMES = frozenset(["http", "https", "about"])


class Navigator:
    """Page navigation manager — throttle, circuit breaker, and smart wait.

    Responsibilities:
    1. Page navigation (goto) + throttle control + circuit breaker protection
    2. History navigation (back/forward/reload)
    3. Smart wait (hybrid detection: DOM + network dual guarantee)
    4. Domain-level learning (SMART strategy tuned by historical data)

    Not involved: tab management, snapshot generation, element interaction.
    """

    def __init__(
        self,
        page: Page,
        throttle: ThrottleStrategy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        wait_config: NavigationWaitConfig | None = None,
        mode: BrowserMode | None = None,
        domain_metrics_manager: DomainMetricsManager | None = None,
        *,
        allow_private_networks: bool = False,
        auto_dismiss_popups: bool = True,
    ):
        """Initialize the Navigator.

        Args:
            page: Patchright Page instance.
            throttle: Throttle strategy (None = no throttling).
            circuit_breaker: Circuit breaker (None = no protection).
            wait_config: Wait configuration (None = default STANDARD config).
            mode: Browser mode used to pick the wait strategy (ignored when wait_config is set).
            domain_metrics_manager: Domain metrics manager for SMART learning.
            allow_private_networks: True in local mode — skips SSRF private-IP
                blocking while preserving URL scheme validation.
            auto_dismiss_popups: auto-dismiss cookie consent banners and overlay
                popups after navigation (default True).
        """
        self._page = page
        self._throttle = throttle
        self._circuit_breaker = circuit_breaker
        self._domain_metrics_manager = domain_metrics_manager
        self._current_domain: str | None = None
        self._allow_private_networks = allow_private_networks
        if auto_dismiss_popups:
            from ..session.consent_dismisser import ConsentDismisser

            self._consent_dismisser = ConsentDismisser(enabled=True)
        else:
            self._consent_dismisser = None

        if wait_config is None:
            from ..pool.config import BrowserMode, _navigation_wait_for_mode

            effective_mode = mode if mode is not None else BrowserMode.STANDARD
            self._wait_config = _navigation_wait_for_mode(effective_mode)
        else:
            self._wait_config = wait_config

    async def goto(self, url: str) -> tuple[str, str, int]:
        """Navigate to the given URL (with throttle and circuit breaker).

        Wait strategy:
        1. Wait for domcontentloaded (core resources loaded).
        2. Smart wait (hybrid detection: DOM stable + network idle).

        Args:
            url: Target URL.

        Returns:
            (title, final_url, status_code)

        Raises:
            ValueError: URL scheme not in the whitelist.
            CircuitBreakerOpenError: Domain circuit breaker is open.
        """
        self._validate_url_scheme(url)

        # Circuit breaker check
        if self._circuit_breaker:
            state = self._circuit_breaker.get_state(url)
            if state == "OPEN":
                from ..pool.circuit_breaker import CircuitBreakerOpenError

                raise CircuitBreakerOpenError(f"Circuit breaker is OPEN for {url}")

        if self._throttle:
            await self._throttle.before_navigate(url)

        success = False
        try:
            if self._circuit_breaker:
                # Invoke through the circuit breaker
                async def navigate_func() -> tuple[str, str, int]:
                    return await self._do_navigate(url)

                result = await self._circuit_breaker.call(url, navigate_func)
                success = True
                return result
            else:
                # Invoke directly
                result = await self._do_navigate(url)
                success = True
                return result

        finally:
            if self._throttle:
                self._throttle.record_response(url, success)

    async def _do_navigate(self, url: str) -> tuple[str, str, int]:
        """Execute the actual navigation operation."""
        self._current_domain = self._extract_domain(url)

        parsed = urlparse(url)
        if parsed.scheme in ("about", "data"):
            await self._page.goto(url, wait_until="commit", timeout=5_000)
            title = await self._page.title()
            final_url = self._page.url
            logger.info(
                "Navigator: trivial %s: navigation to %s", parsed.scheme, redact_sensitive_text(url)[:80]
            )
            return title, final_url, 200

        try:
            from .ssrf_guard import goto_with_ssrf_guard

            response = await goto_with_ssrf_guard(
                self._page,
                url,
                timeout_ms=_NAVIGATION_TIMEOUT_MS,
                allow_private_networks=self._allow_private_networks,
            )

            metrics = await self._wait_for_page_ready()
            self._log_wait_metrics(metrics)

            if self._consent_dismisser:
                await self._consent_dismisser.dismiss(self._page)
        except Exception as e:
            # Recognize timeouts from both builtins and patchright; string matching is
            # fragile because timeout text differs across pages and library versions.
            from ..utils import is_timeout_error

            if is_timeout_error(e):
                logger.warning(
                    "Navigator: timeout during navigation to %s, attempting rescue via window.stop()",
                    redact_sensitive_text(url)[:80],
                )
                try:
                    await self._page.evaluate("window.stop()")
                    from myrm_agent_harness.utils.event_utils import (
                        dispatch_custom_event,
                    )

                    await dispatch_custom_event(
                        "agent_status",
                        {
                            "event": "tool_fallback",
                            "tool": "browser_navigate_tool",
                            "fallback_type": "timeout_rescue",
                            "message": "Page resource load timed out; forcing stop and extracting visible content...",
                        },
                    )
                except Exception as stop_e:
                    logger.warning(
                        f"Navigator: failed to stop page after timeout: {stop_e}"
                    )

                # We don't have a response object, but we can still get title and url
                response = None
            else:
                raise

        title = await self._page.title()
        final_url = self._page.url
        status_code = response.status if response else 200

        logger.info(
            "Navigator: navigated to %s (status=%s)",
            redact_sensitive_text(url)[:80],
            status_code,
        )
        return title, final_url, status_code

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract the domain from a URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower() or url.lower()
        except Exception:
            return url.lower()

    async def _wait_for_page_ready(self) -> WaitMetrics:
        """Wait for the page to be ready (smart hybrid detection).

        Strategy selection (per configuration):
        - smart: adaptive detection, fast + accurate, tuned by domain history.
        - hybrid: DOM stable + network idle, dual guarantee.
        - dom_stable: DOM-only detection, fast mode.
        - networkidle: network-only detection, compatibility mode.

        Returns complete metrics for observability.
        """
        strategy_str = self._wait_config.strategy
        strategy_map = {
            "networkidle": WaitStrategy.NETWORKIDLE,
            "dom_stable": WaitStrategy.DOM_STABLE,
            "hybrid": WaitStrategy.HYBRID,
            "smart": WaitStrategy.SMART,
        }
        strategy = strategy_map.get(strategy_str, WaitStrategy.SMART)

        return await wait_for_page_ready(
            self._page,
            strategy=strategy,
            max_ms=self._wait_config.wait_timeout_ms,
            quiet_ms=self._wait_config.quiet_ms,
            grace_period_ms=self._wait_config.grace_period_ms,
            domain=self._current_domain,
            domain_metrics_manager=self._domain_metrics_manager,
        )

    def _log_wait_metrics(self, metrics: WaitMetrics) -> None:
        """Record wait metrics for full observability."""
        log_dict = metrics.to_log_dict()
        logger.debug(f"Wait metrics: {log_dict}")

        if metrics.reason == "both":
            logger.info(
                f"Page ready: DOM+Network both stable, {metrics.elapsed_ms}ms "
                f"(dom={metrics.dom_stable_ms}ms, network={metrics.network_idle_ms}ms)"
            )
        elif metrics.reason == "quiet":
            logger.info(f"Page ready: DOM stable after {metrics.elapsed_ms}ms")
        elif metrics.reason == "network_only":
            logger.info(f"Page ready: Network idle after {metrics.elapsed_ms}ms")
        elif metrics.reason == "capped":
            logger.warning(
                f"Page ready: Timeout after {metrics.elapsed_ms}ms, "
                f"mutations={metrics.dom_mutation_count}, resets={metrics.dom_reset_count}"
            )

    async def back(self) -> None:
        """Go back one page"""
        await self._page.go_back(timeout=_NAVIGATION_TIMEOUT_MS)
        logger.info("Navigator: navigated back")

    async def forward(self) -> None:
        """Go forward one page"""
        await self._page.go_forward(timeout=_NAVIGATION_TIMEOUT_MS)
        logger.info("Navigator: navigated forward")

    async def reload(self) -> None:
        """Reload the current page."""
        await self._page.reload(timeout=_NAVIGATION_TIMEOUT_MS)
        logger.info("Navigator: reloaded page")

    def get_url(self) -> str:
        """Get the current URL."""
        return self._page.url

    async def get_title(self) -> str:
        """Get the current page title."""
        return await self._page.title()

    @staticmethod
    def _validate_url_scheme(url: str) -> None:
        """Validate that the URL scheme is in the whitelist.

        Args:
            url: URL to validate.

        Raises:
            ValueError: scheme not in the whitelist (non http/https/about).

        Note:
            Whitelist mechanism, only allows secure schemes:
            - http/https: standard web protocols
            - about: browser built-in pages (e.g. about:blank)

            Rejects dangerous schemes:
            - javascript: XSS risk
            - file: local file access
            - data: inline data injection
            - blob: blob URL injection
            - ftp: non-HTTP protocol
        """
        parsed = urlparse(url)
        scheme = parsed.scheme.lower() if parsed.scheme else ""

        if not scheme:
            raise ValueError(
                f"Invalid URL: missing scheme (must be http:// or https://). Got: {url}"
            )

        if scheme not in _ALLOWED_SCHEMES:
            raise ValueError(
                f"Blocked URL scheme: '{scheme}' not allowed (only http/https/about permitted). "
                f"Rejected dangerous schemes: javascript/file/data/blob/ftp. Got: {url}"
            )
