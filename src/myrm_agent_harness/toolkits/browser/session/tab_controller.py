"""Tab lifecycle management — single responsibility.


[INPUT]
- pool.browser_pool::GlobalBrowserPool (POS: global browser pool)
- pool.browser_pool::ContextType (POS: context type enum)

[OUTPUT]
- TabController: tab lifecycle manager
- TabHandle: tab handle (wraps Page + last_snapshot_url)

[POS]
Tab lifecycle manager. Responsibilities:
1. Create/close tabs
2. Switch active tab
3. LRU eviction (when exceeding MAX_TABS)
4. Automatic popup capture
5. Tab-level snapshot URL management (get/update_snapshot_url)

Single responsibility: only manages tab lifecycle and tab-level metadata; does not handle navigation, snapshot, interaction, or other business logic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Page

    from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool

logger = logging.getLogger(__name__)

_MAX_TABS = 10


@dataclass
class TabHandle:
    """Tab 句柄 — 封装 Page  and 元Data

    immutable(除了 last_used  and  last_snapshot_url),thread-safe。
    """

    page: Page
    tab_id: str
    context_key: str
    last_used: float = field(default_factory=time.monotonic)
    last_snapshot_url: str | None = None
    text_snapshot: str | None = None
    text_snapshot_hash: str | None = None


class TabController:
    """Tab 生命周期管理器 — 单一职责

    职责:
    1. Create/Close Tab(委托 GlobalBrowserPool)
    2. 切换活跃 Tab(Update last_used)
    3. LRU 驱逐(超过 MAX_TABS)
    4. Popup Auto捕获(optional)

     not 涉 and :导航、Snapshot、交互、Extract etc.业务逻辑。
    """

    def __init__(
        self,
        browser_pool: GlobalBrowserPool,
        context_type: ContextType,
        context_kwargs: dict[str, object] | None = None,
    ):
        """Initialize TabController

        Args:
            browser_pool: GlobalBrowser池
            context_type: Default Context Type(CRAWL/AGENT/STEALTH)
            context_kwargs: BrowserContext 额外Parameter(如录制Configure)
        """
        self._pool = browser_pool
        self._context_type = context_type
        self._context_kwargs = context_kwargs
        self._tabs: dict[str, TabHandle] = {}
        self._active_tab_id: str | None = None
        self._tab_counter = 0

    async def create_tab(self, context_key: str | None = None, engine_preference: str | None = None) -> str:
        """Createnew  Tab

        Args:
            context_key: Context 标识符( for  session 隔离)
            engine_preference: Preferred browser engine

        Returns:
            Tab ID(tab0, tab1, ...)
        """
        if len(self._tabs) >= _MAX_TABS:
            await self._evict_lru()

        page, ctx_key = await self._pool.acquire_page(
            self._context_type, context_key, self._context_kwargs, engine_preference=engine_preference
        )

        tab_id = f"tab{self._tab_counter}"
        self._tab_counter += 1

        handle = TabHandle(page=page, tab_id=tab_id, context_key=ctx_key)
        self._tabs[tab_id] = handle

        self._active_tab_id = tab_id

        logger.warning(f"TabController: created {tab_id} (total: {len(self._tabs)})")
        return tab_id

    async def close_tab(self, tab_id: str) -> None:
        """Close指定 Tab

        Args:
            tab_id: 要Close  Tab ID
        """
        if tab_id not in self._tabs:
            raise ValueError(f"Tab not found: {tab_id}")

        handle = self._tabs.pop(tab_id)
        await self._pool.release_page(handle.page, handle.context_key)

        if self._active_tab_id == tab_id:
            self._active_tab_id = next(iter(self._tabs), None)

        logger.warning(f"TabController: closed {tab_id} (remaining: {len(self._tabs)})")

    async def switch_tab(self, tab_id: str) -> None:
        """切换活跃 Tab

        Args:
            tab_id: 要切换 to   Tab ID
        """
        if tab_id not in self._tabs:
            raise ValueError(f"Tab not found: {tab_id}")

        self._active_tab_id = tab_id
        page = self._tabs[tab_id].page
        try:
            await page.bring_to_front()
        except Exception as exc:
            logger.warning("Failed to bring tab to front: %s", exc)
        self._tabs[tab_id].last_used = time.monotonic()
        logger.warning(f"TabController: switched to {tab_id}")

    def get_active_page(self) -> Page:
        """GetCurrent活跃  Page

        Returns:
            Current活跃  Page Instance

        Raises:
            RuntimeError: If没 has 活跃 Tab
        """
        if self._active_tab_id is None:
            raise RuntimeError("No active tab")

        handle = self._tabs[self._active_tab_id]
        handle.last_used = time.monotonic()
        return handle.page

    def get_active_tab_id(self) -> str:
        """GetCurrent活跃  Tab ID

        Returns:
            Current活跃  Tab ID

        Raises:
            RuntimeError: If没 has 活跃 Tab
        """
        if self._active_tab_id is None:
            raise RuntimeError("No active tab")
        return self._active_tab_id

    def find_tab_by_origin(self, origin: str) -> TabHandle | None:
        """Find an existing tab whose current URL shares the same origin.

        Args:
            origin: Target origin (scheme + netloc, e.g. "https://google.com")

        Returns:
            TabHandle if a same-origin tab is found, None otherwise.
        """
        from urllib.parse import urlparse

        for handle in self._tabs.values():
            try:
                tab_url = handle.page.url
                if not tab_url or tab_url in ("about:blank", ""):
                    continue
                parsed = urlparse(tab_url)
                tab_origin = f"{parsed.scheme}://{parsed.netloc}"
                if tab_origin == origin:
                    return handle
            except Exception:
                continue
        return None

    def list_tabs_with_info(self) -> list[dict[str, str]]:
        """List all tabs with domain info for display.

        Returns:
            List of dicts with tab_id, domain, and active status.
        """
        from urllib.parse import urlparse

        result = []
        for tab_id, handle in self._tabs.items():
            try:
                url = handle.page.url
                domain = urlparse(url).netloc if url and url != "about:blank" else "(blank)"
            except Exception:
                domain = "(unavailable)"
            result.append({
                "tab_id": tab_id,
                "domain": domain,
                "active": tab_id == self._active_tab_id,
            })
        return result

    def list_tabs(self) -> list[str]:
        """列出All Tab ID

        Returns:
            Tab ID List
        """
        return list(self._tabs.keys())

    def get_snapshot_url(self, tab_id: str) -> str | None:
        """Get指定 Tab  最后 snapshot URL

        Args:
            tab_id: Tab ID

        Returns:
            最后 snapshot   URL，If not yet  snapshot 则Return None

        Raises:
            ValueError: If Tab  not Exists
        """
        if tab_id not in self._tabs:
            raise ValueError(f"Tab not found: {tab_id}")
        return self._tabs[tab_id].last_snapshot_url

    def update_snapshot_url(self, tab_id: str, url: str) -> None:
        """Update指定 Tab  最后 snapshot URL

        Args:
            tab_id: Tab ID
            url: CurrentPage URL

        Raises:
            ValueError: If Tab  not Exists
        """
        if tab_id not in self._tabs:
            raise ValueError(f"Tab not found: {tab_id}")
        self._tabs[tab_id].last_snapshot_url = url

    def get_text_snapshot(self, tab_id: str) -> tuple[str, str] | None:
        """Get指定 Tab  textSnapshot and  Hash。Return (snapshot, hash)"""
        if tab_id in self._tabs:
            handle = self._tabs[tab_id]
            if handle.text_snapshot is not None and handle.text_snapshot_hash is not None:
                return handle.text_snapshot, handle.text_snapshot_hash
        return None

    def set_text_snapshot(self, tab_id: str, snapshot: str, hash_val: str) -> None:
        """Set指定 Tab  textSnapshot and  Hash"""
        if tab_id in self._tabs:
            self._tabs[tab_id].text_snapshot = snapshot
            self._tabs[tab_id].text_snapshot_hash = hash_val

    def clear_text_snapshot(self, tab_id: str | None = None) -> None:
        """清Empty指定 Tab  textSnapshot。If not 指定 tab_id，清EmptyCurrent活跃 Tab。"""
        tid = tab_id or self._active_tab_id
        if tid and tid in self._tabs:
            self._tabs[tid].text_snapshot = None
            self._tabs[tid].text_snapshot_hash = None

    async def _evict_lru(self) -> None:
        """LRU 驱逐 — Close最久 not yet  using  非活跃 Tab"""
        non_active = [tid for tid in self._tabs if tid != self._active_tab_id]

        if not non_active:
            logger.warning("TabController: cannot evict active tab, skipping")
            return

        lru_tab_id = min(non_active, key=lambda tid: self._tabs[tid].last_used)
        await self.close_tab(lru_tab_id)
        logger.warning(f"TabController: evicted LRU tab {lru_tab_id}")

    async def close_all(self) -> None:
        """CloseAll Tab(session End时Call)"""
        tab_ids = list(self._tabs.keys())
        for tab_id in tab_ids:
            await self.close_tab(tab_id)

        logger.warning("TabController: closed all tabs")

    @property
    def stats(self) -> dict[str, object]:
        """GetStatisticsinformation( for 监控)"""
        return {
            "total_tabs": len(self._tabs),
            "active_tab": self._active_tab_id,
            "tab_ids": list(self._tabs.keys()),
        }
