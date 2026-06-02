"""Page navigation utility — reusable across browser and web_fetch


[INPUT]
- logging::getLogger (POS: Python logging)
- time::perf_counter (POS: high-precision timer)
- urllib.parse::urlparse (POS: URL parsing)
- patchright.async_api::Page (POS: Patchright page instance)
- .pool.throttle::ThrottleStrategy (POS: throttle strategy protocol)
- .pool.config::BrowserMode, NavigationWaitConfig (POS: browser configuration)
- .wait_strategies::wait_for_page_ready, WaitStrategy, WaitMetrics (POS: smart wait strategies)
- agent.security.guards.ssrf_guard::check_url, resolve_and_check (POS: SSRF protection)

[OUTPUT]
- Navigator: page navigation manager (with throttling and smart wait)

[POS]
Page navigation utility module. Responsibilities:
1. Page navigation (goto) + throttle control
2. History navigation (back/forward/reload)
3. Smart wait (hybrid detection: DOM + network dual guarantee)
4. Timeout control + full metrics exposure

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

from .wait_strategies import WaitMetrics, WaitStrategy, wait_for_page_ready

if TYPE_CHECKING:
    from patchright.async_api import Page

    from myrm_agent_harness.toolkits.web_fetch.router.domain_metrics import DomainMetricsManager

    from .pool.circuit_breaker import CircuitBreaker
    from .pool.config import BrowserMode, NavigationWaitConfig
    from .pool.throttle import ThrottleStrategy

logger = logging.getLogger(__name__)

_NAVIGATION_TIMEOUT_MS = 15_000
_ALLOWED_SCHEMES = frozenset(["http", "https", "about"])


class Navigator:
    """Page导航管理器 — 集成限流、熔断 and 智能Wait

    职责:
    1. Page跳转(goto) + 限流控制 + 熔断保护
    2. 历史导航(back/forward/reload)
    3. 智能Wait（混合检测：DOM + 网络双重保障）
    4. Domain级学习（SMART Strategy基于历史Data调整）

     not 涉 and :Tab 管理、SnapshotGenerate、Element交互 etc.。
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
    ):
        """Initialize Navigator

        Args:
            page: Patchright Page Instance
            throttle: 限流Strategy（None =  no 限流）
            circuit_breaker: 熔断器（None =  no 熔断）
            wait_config: WaitConfigure（None =  using DefaultSTANDARDConfigure）
            mode: BrowserMode（ for 确定WaitStrategy，wait_config优先）
            domain_metrics_manager: DomainMetricsManager Instance（ for Domain级学习）
            allow_private_networks: True in local mode — skips SSRF private-IP
                blocking while preserving URL scheme validation.
        """
        self._page = page
        self._throttle = throttle
        self._circuit_breaker = circuit_breaker
        self._domain_metrics_manager = domain_metrics_manager
        self._current_domain: str | None = None
        self._allow_private_networks = allow_private_networks

        if wait_config is None:
            from .pool.config import BrowserMode, _navigation_wait_for_mode

            effective_mode = mode if mode is not None else BrowserMode.STANDARD
            self._wait_config = _navigation_wait_for_mode(effective_mode)
        else:
            self._wait_config = wait_config

    async def goto(self, url: str) -> tuple[str, str, int]:
        """导航 to 指定 URL（带限流控制 and 熔断保护）

        WaitStrategy:
        1. Wait domcontentloaded（core资源LoadComplete）
        2. 智能Wait（混合检测：DOMstable + 网络Empty闲）

        Args:
            url: 目标 URL

        Returns:
            (title, final_url, status_code)

        Raises:
            ValueError: URL scheme  not  in Whitelist in
            CircuitBreakerOpenError: Domain熔断器打开
        """
        self._validate_url_scheme(url)
        if not self._allow_private_networks:
            self._validate_ssrf(url)

        # 熔断器Check
        if self._circuit_breaker:
            state = self._circuit_breaker.get_state(url)
            if state == "OPEN":
                from .pool.circuit_breaker import CircuitBreakerOpenError

                raise CircuitBreakerOpenError(f"Circuit breaker is OPEN for {url}")

        if self._throttle:
            await self._throttle.before_navigate(url)

        success = False
        try:
            if self._circuit_breaker:
                #  via 熔断器Call
                async def navigate_func() -> tuple[str, str, int]:
                    return await self._do_navigate(url)

                result = await self._circuit_breaker.call(url, navigate_func)
                success = True
                return result
            else:
                #  directly Call
                result = await self._do_navigate(url)
                success = True
                return result

        finally:
            if self._throttle:
                self._throttle.record_response(url, success)

    async def _do_navigate(self, url: str) -> tuple[str, str, int]:
        """Execute实际 导航操作"""
        self._current_domain = self._extract_domain(url)

        try:
            response = await self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=_NAVIGATION_TIMEOUT_MS,
            )

            metrics = await self._wait_for_page_ready()
            self._log_wait_metrics(metrics)
        except Exception as e:
            # Catch TimeoutError (Playwright throws playwright.async_api.TimeoutError, which inherits from Exception)
            from patchright.async_api import TimeoutError as PlaywrightTimeoutError
            if isinstance(e, PlaywrightTimeoutError) or "Timeout" in str(e) or "timeout" in str(e).lower():
                logger.warning(f"Navigator: timeout during navigation to {url}, attempting rescue via window.stop()")
                try:
                    await self._page.evaluate("window.stop()")
                    from myrm_agent_harness.utils.event_utils import dispatch_custom_event
                    await dispatch_custom_event(
                        "agent_status",
                        {
                            "event": "tool_fallback",
                            "tool": "browser_navigate_tool",
                            "fallback_type": "timeout_rescue",
                            "message": "页面部分资源加载超时，正在强制终止并提取现有可见内容..."
                        }
                    )
                except Exception as stop_e:
                    logger.warning(f"Navigator: failed to stop page after timeout: {stop_e}")

                # We don't have a response object, but we can still get title and url
                response = None
            else:
                raise

        title = await self._page.title()
        final_url = self._page.url
        status_code = response.status if response else 200

        logger.info(f"Navigator: navigated to {url} (status={status_code})")
        return title, final_url, status_code

    @staticmethod
    def _extract_domain(url: str) -> str:
        """ExtractDomain"""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower() or url.lower()
        except Exception:
            return url.lower()

    async def _wait_for_page_ready(self) -> WaitMetrics:
        """WaitPage准备就绪（智能混合检测）

        Strategy选择（按Configure）：
        - smart（推荐）：自适应检测，fast+准确，基于Domain历史Data
        - hybrid：DOMstable + 网络Empty闲，双重保障
        - dom_stable：OnlyDOM检测，fastMode
        - networkidle：Only网络检测，compatibleMode

        Returncomplete metrics 便于可观测性。
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
        """RecordWaitMetrics（complete可观测性）"""
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
        """RefreshCurrent页"""
        await self._page.reload(timeout=_NAVIGATION_TIMEOUT_MS)
        logger.info("Navigator: reloaded page")

    def get_url(self) -> str:
        """GetCurrent URL"""
        return self._page.url

    async def get_title(self) -> str:
        """GetCurrentPageHeading"""
        return await self._page.title()

    @staticmethod
    def _validate_url_scheme(url: str) -> None:
        """Validate URL scheme Whether in Whitelist in

        Args:
            url: To validate  URL

        Raises:
            ValueError: scheme  not  in Whitelist in (非 http/https/about)

        Note:
            WhitelistMechanism,只 allow Security  scheme:
            - http/https: standard Web Protocol
            - about: Browserbuilt-inPage(如 about:blank)

            拒绝危险 scheme:
            - javascript: XSS 风险
            - file: LocalFile访问
            - data: 内联Data注入
            - blob: Blob URL 注入
            - ftp: 非 HTTP Protocol
        """
        parsed = urlparse(url)
        scheme = parsed.scheme.lower() if parsed.scheme else ""

        if not scheme:
            raise ValueError(f"Invalid URL: missing scheme (must be http:// or https://). Got: {url}")

        if scheme not in _ALLOWED_SCHEMES:
            raise ValueError(
                f"Blocked URL scheme: '{scheme}' not allowed (only http/https/about permitted). "
                f"Rejected dangerous schemes: javascript/file/data/blob/ftp. Got: {url}"
            )

    @staticmethod
    def _validate_ssrf(url: str) -> None:
        """Validate URL against SSRF attacks (private/internal network access).

        Checks both the URL itself and DNS-resolved IP addresses.
        Skips validation for about: scheme URLs.

        Raises:
            ValueError: URL targets a private/internal network
        """
        parsed = urlparse(url)
        if parsed.scheme == "about":
            return

        from myrm_agent_harness.core.security.guards.ssrf_guard import check_url, resolve_and_check

        url_verdict = check_url(url)
        if not url_verdict.allowed:
            raise ValueError(f"SSRF blocked: {url_verdict.reason}")

        hostname = parsed.hostname
        if hostname:
            dns_verdict = resolve_and_check(hostname)
            if not dns_verdict.allowed:
                raise ValueError(f"SSRF blocked: {dns_verdict.reason}")
