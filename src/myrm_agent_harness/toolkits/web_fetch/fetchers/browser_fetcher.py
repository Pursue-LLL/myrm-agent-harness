"""Browser Fetcher — 基于 Patchright + GlobalBrowserPool  Browser抓取

 using  GlobalBrowserPool 零拷贝Page复用。
Patchright  from 源码层面修补了 CDP 泄露，provides in  etc.反检测能力。
复用 Navigator implements导航逻辑，Auto获得限流能力。

[INPUT]
- toolkits.browser.pool::GlobalBrowserPool (POS: Runtime pool management layer. Provides multi-backend unified management, concurrency control, health monitoring, and config-driven registration — the central dispatcher of the runtime system.)
- toolkits.browser.navigation::Navigator (POS: Page navigation utility module. Responsibilities: 1. Page navigation (goto) + throttle control 2. History navigation (back/forward/reload) 3. Smart wait (hybrid detection: DOM + network dual guarantee) 4. Timeout control + full metrics exposure Design principles: Independent utility module, reusable by BrowserSession and BrowserFetcher Integrates throttle strategy for unified navigation frequency control Smart wait: hybrid detection (DOM stable + network idle) dual guarantee Single responsibility: only handles navigation logic; does not handle tab management, snapshot, interaction, etc.)

[OUTPUT]
- BrowserFetcher: class — Browser Fetcher

[POS]
Provides BrowserFetcher.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .protocols import FetcherType, FetchResult

if TYPE_CHECKING:
    from patchright.async_api import Page  # type: ignore[import-untyped]

    from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault

logger = logging.getLogger(__name__)


class BrowserFetcher:
    """L2 层：Patchright + GlobalBrowserPool

    using  GlobalBrowserPool implements零拷贝Page复用，消除资源分裂。
    via  DomainMetricsManager 共享Domain级学习Data，使 SMART WaitStrategy能基于历史DataDynamic调整。
    """

    fetcher_type = FetcherType.BROWSER

    def __init__(
        self,
        browser_pool: GlobalBrowserPool | None = None,
        *,
        allow_private_networks: bool = False,
        session_vault: SessionVault | None = None,
    ):
        """Initialize BrowserFetcher

        Args:
            browser_pool: GlobalBrowserPool Instance（optional，Default using Globalsingleton）
            allow_private_networks: Skip SSRF private-IP blocking in Navigator (local mode).
            session_vault: Optional SessionVault for cookie/state sharing.
        """
        from myrm_agent_harness.toolkits.browser.pool import get_global_browser_pool

        self._pool = browser_pool or get_global_browser_pool()
        self._allow_private_networks = allow_private_networks
        self._session_vault = session_vault

    async def fetch(self, url: str) -> FetchResult | None:
        """抓取 URL Content（复用 Navigator，Auto获得限流 and Domain学习能力）

        Args:
            url: 目标 URL

        Returns:
            FetchResult  or  None（Failure时）
        """
        from urllib.parse import urlparse

        from myrm_agent_harness.toolkits.browser.navigation import Navigator
        from myrm_agent_harness.toolkits.browser.pool import ContextType

        from ..router.domain_metrics import get_global_domain_metrics_manager

        page: Page | None = None
        context_key: str | None = None

        try:
            # 尝试从 SessionVault 加载 domain 的 storage_state
            context_kwargs = None
            if self._session_vault:
                try:
                    domain = urlparse(url).hostname or ""
                    # 简化处理：去除 www. 前缀以匹配主域名
                    if domain.startswith("www."):
                        domain = domain[4:]
                    entry = await self._session_vault.load(domain)
                    if entry and entry.storage_state:
                        context_kwargs = {"storage_state": entry.storage_state}
                        # 使用独立的 context_key 以避免 storage_state 污染全局 CRAWL context
                        context_key = f"crawl_{domain}"
                except Exception as exc:
                    logger.warning(f"BrowserFetcher failed to load session for {url}: {exc}")

            page, context_key = await self._pool.acquire_page(
                ContextType.CRAWL, context_key=context_key, context_kwargs=context_kwargs
            )

            navigator = Navigator(
                page,
                throttle=self._pool.throttle_strategy,
                circuit_breaker=self._pool.circuit_breaker,
                domain_metrics_manager=get_global_domain_metrics_manager(),
                allow_private_networks=self._allow_private_networks,
            )
            _title, final_url, status_code = await navigator.goto(url)

            html = await page.content()

            return FetchResult(
                html=html,
                url=final_url,
                status_code=status_code,
                fetcher_type=FetcherType.BROWSER,
            )

        except Exception as exc:
            logger.warning(f"BrowserFetcher failed: {url} — {exc}")
            return None

        finally:
            if page is not None and context_key is not None:
                try:
                    await self._pool.release_page(page, context_key)
                except Exception as exc:
                    logger.warning(f"BrowserFetcher release failed: {exc}")

    async def shutdown(self) -> None:
        """Close资源（V2 架构由 GlobalBrowserPool 统一管理， no 需ManualClose）"""
        pass
