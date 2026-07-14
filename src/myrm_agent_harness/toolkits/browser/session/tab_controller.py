"""Tab lifecycle management — single responsibility.


[INPUT]
- pool.browser_pool::GlobalBrowserPool (POS: global browser pool)
- pool.browser_pool::ContextType (POS: context type enum)

[OUTPUT]
- TabController: tab lifecycle manager
- TabHandle: tab handle (wraps Page + last_snapshot_url)

[POS]
Tab lifecycle manager. Responsibilities:
1. Create/close tabs (delegates to GlobalBrowserPool for pool-managed tabs)
2. Switch active tab
3. LRU eviction (when exceeding MAX_TABS)
4. Automatic popup capture (window.open / OAuth / target=_blank) with parent-child tracking
5. Popup close auto-recovery (switch back to parent tab)
6. Tab-level snapshot URL management (get/update_snapshot_url)
7. Origin-based tab routing (find_tab_by_origin)
8. Domain-aware tab listing (list_tabs_with_info)

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
    """Tab handle wrapping a Page and tab-level metadata (thread-safe except last_used / snapshot fields)."""

    page: Page
    tab_id: str
    context_key: str
    last_used: float = field(default_factory=time.monotonic)
    last_snapshot_url: str | None = None
    text_snapshot: str | None = None
    text_snapshot_hash: str | None = None
    is_popup: bool = False
    parent_tab_id: str | None = None


class TabController:
    """Tab lifecycle manager — single responsibility.

    Does not handle: navigation, snapshot, interaction, or other business logic.
    """

    def __init__(
        self,
        browser_pool: GlobalBrowserPool,
        context_type: ContextType,
        context_kwargs: dict[str, object] | None = None,
    ):
        """Initialize TabController.

        Args:
            browser_pool: Global browser pool for page acquisition/release.
            context_type: Default context type (CRAWL/AGENT/STEALTH).
            context_kwargs: Extra BrowserContext parameters (e.g. recording config).
        """
        self._pool = browser_pool
        self._context_type = context_type
        self._context_kwargs = context_kwargs
        self._tabs: dict[str, TabHandle] = {}
        self._active_tab_id: str | None = None
        self._tab_counter = 0
        self._popup_attached_pages: set[int] = set()

    async def create_tab(
        self,
        context_key: str | None = None,
        engine_preference: str | None = None,
        launch_mode_preference: str | None = None,
    ) -> str:
        """Create new Tab.

        Args:
            context_key: Context identifier (for session isolation)
            engine_preference: Preferred browser engine
            launch_mode_preference: Per-agent launch mode override (e.g. 'extension')

        Returns:
            Tab ID (tab0, tab1, ...)
        """
        if len(self._tabs) >= _MAX_TABS:
            await self._evict_lru()

        page, ctx_key = await self._pool.acquire_page(
            self._context_type,
            context_key,
            self._context_kwargs,
            engine_preference=engine_preference,
            launch_mode_preference=launch_mode_preference,
        )

        tab_id = f"tab{self._tab_counter}"
        self._tab_counter += 1

        handle = TabHandle(page=page, tab_id=tab_id, context_key=ctx_key)
        self._tabs[tab_id] = handle

        self._active_tab_id = tab_id

        logger.warning(f"TabController: created {tab_id} (total: {len(self._tabs)})")
        return tab_id

    async def close_tab(self, tab_id: str) -> None:
        """Close a tab. Popup tabs are closed directly; pool-managed tabs go through release_page."""
        if tab_id not in self._tabs:
            raise ValueError(f"Tab not found: {tab_id}")

        handle = self._tabs.pop(tab_id)
        self._popup_attached_pages.discard(id(handle.page))

        if handle.is_popup:
            try:
                if not handle.page.is_closed():
                    await handle.page.close()
            except Exception as exc:
                logger.warning("TabController: failed to close popup page: %s", exc)
        else:
            await self._pool.release_page(handle.page, handle.context_key)

        if self._active_tab_id == tab_id:
            if handle.parent_tab_id and handle.parent_tab_id in self._tabs:
                self._active_tab_id = handle.parent_tab_id
            else:
                self._active_tab_id = next(iter(self._tabs), None)

        logger.warning(f"TabController: closed {tab_id} (remaining: {len(self._tabs)})")

    async def switch_tab(self, tab_id: str) -> None:
        """Switch active tab.

        Args:
            tab_id: Target tab ID to switch to.
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
        """Return the active page.

        Raises:
            RuntimeError: If no active tab exists.
        """
        if self._active_tab_id is None:
            raise RuntimeError("No active tab")

        handle = self._tabs[self._active_tab_id]
        handle.last_used = time.monotonic()
        return handle.page

    def get_active_tab_id(self) -> str:
        """Return the active tab ID.

        Raises:
            RuntimeError: If no active tab exists.
        """
        if self._active_tab_id is None:
            raise RuntimeError("No active tab")
        return self._active_tab_id

    def find_tab_by_origin(self, origin: str) -> TabHandle | None:
        """Find an existing tab whose current URL shares the same origin.

        Prefers the active tab if it matches, to avoid unnecessary switching.

        Args:
            origin: Target origin (scheme + netloc, e.g. "https://google.com")

        Returns:
            TabHandle if a same-origin tab is found, None otherwise.
        """
        from urllib.parse import urlparse

        fallback: TabHandle | None = None
        for handle in self._tabs.values():
            try:
                tab_url = handle.page.url
                if not tab_url or tab_url in ("about:blank", ""):
                    continue
                parsed = urlparse(tab_url)
                tab_origin = f"{parsed.scheme}://{parsed.netloc}"
                if tab_origin == origin:
                    if handle.tab_id == self._active_tab_id:
                        return handle
                    if fallback is None:
                        fallback = handle
            except Exception:
                continue
        return fallback

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
        """Return all tab IDs."""
        return list(self._tabs.keys())

    def get_snapshot_url(self, tab_id: str) -> str | None:
        """Return the last snapshot URL for the given tab, or None.

        Raises:
            ValueError: If the tab does not exist.
        """
        if tab_id not in self._tabs:
            raise ValueError(f"Tab not found: {tab_id}")
        return self._tabs[tab_id].last_snapshot_url

    def update_snapshot_url(self, tab_id: str, url: str) -> None:
        """Update the last snapshot URL for the given tab.

        Raises:
            ValueError: If the tab does not exist.
        """
        if tab_id not in self._tabs:
            raise ValueError(f"Tab not found: {tab_id}")
        self._tabs[tab_id].last_snapshot_url = url

    def get_text_snapshot(self, tab_id: str) -> tuple[str, str] | None:
        """Return (snapshot, hash) for the given tab, or None."""
        if tab_id in self._tabs:
            handle = self._tabs[tab_id]
            if handle.text_snapshot is not None and handle.text_snapshot_hash is not None:
                return handle.text_snapshot, handle.text_snapshot_hash
        return None

    def set_text_snapshot(self, tab_id: str, snapshot: str, hash_val: str) -> None:
        """Store a text snapshot and its hash for the given tab."""
        if tab_id in self._tabs:
            self._tabs[tab_id].text_snapshot = snapshot
            self._tabs[tab_id].text_snapshot_hash = hash_val

    def clear_text_snapshot(self, tab_id: str | None = None) -> None:
        """Clear the text snapshot for the given tab (defaults to active tab)."""
        tid = tab_id or self._active_tab_id
        if tid and tid in self._tabs:
            self._tabs[tid].text_snapshot = None
            self._tabs[tid].text_snapshot_hash = None

    def attach_popup_listener(self, page: Page) -> None:
        """Register popup event handler on a page. Idempotent per page instance."""
        page_id = id(page)
        if page_id in self._popup_attached_pages:
            return
        self._popup_attached_pages.add(page_id)
        page.on("popup", self._on_popup)
        logger.debug("TabController: popup listener attached to page %d", page_id)

    async def _on_popup(self, popup_page: Page) -> None:
        """Handle a browser popup (window.open / OAuth / target=_blank)."""
        if len(self._tabs) >= _MAX_TABS:
            await self._evict_lru()

        parent_tab_id = self._active_tab_id

        tab_id = f"tab{self._tab_counter}"
        self._tab_counter += 1

        context_key = ""
        if parent_tab_id and parent_tab_id in self._tabs:
            context_key = self._tabs[parent_tab_id].context_key

        handle = TabHandle(
            page=popup_page,
            tab_id=tab_id,
            context_key=context_key,
            is_popup=True,
            parent_tab_id=parent_tab_id,
        )
        self._tabs[tab_id] = handle
        self._active_tab_id = tab_id

        popup_page.on("close", lambda: self._on_popup_close(tab_id))
        self.attach_popup_listener(popup_page)

        logger.warning(
            "TabController: captured popup %s (parent=%s, total=%d)",
            tab_id, parent_tab_id, len(self._tabs),
        )

    def _on_popup_close(self, tab_id: str) -> None:
        """Handle popup page close event — remove tab and switch back to parent."""
        if tab_id not in self._tabs:
            return

        handle = self._tabs.pop(tab_id)
        self._popup_attached_pages.discard(id(handle.page))

        if self._active_tab_id == tab_id:
            if handle.parent_tab_id and handle.parent_tab_id in self._tabs:
                self._active_tab_id = handle.parent_tab_id
            else:
                self._active_tab_id = next(iter(self._tabs), None)

        logger.warning(
            "TabController: popup %s closed, switched to %s (remaining=%d)",
            tab_id, self._active_tab_id, len(self._tabs),
        )

    async def _evict_lru(self) -> None:
        """Evict the least-recently-used non-active tab."""
        non_active = [tid for tid in self._tabs if tid != self._active_tab_id]

        if not non_active:
            logger.warning("TabController: cannot evict active tab, skipping")
            return

        lru_tab_id = min(non_active, key=lambda tid: self._tabs[tid].last_used)
        await self.close_tab(lru_tab_id)
        logger.warning(f"TabController: evicted LRU tab {lru_tab_id}")

    async def close_all(self) -> None:
        """Close all tabs (called on session teardown)."""
        tab_ids = list(self._tabs.keys())
        for tab_id in tab_ids:
            await self.close_tab(tab_id)

        logger.warning("TabController: closed all tabs")

    @property
    def stats(self) -> dict[str, object]:
        """Return tab statistics for monitoring."""
        return {
            "total_tabs": len(self._tabs),
            "active_tab": self._active_tab_id,
            "tab_ids": list(self._tabs.keys()),
        }
