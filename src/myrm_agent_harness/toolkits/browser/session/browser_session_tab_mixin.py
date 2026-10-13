"""BrowserSession tab management APIs.

[INPUT]
- session.tab_controller::TabController (POS: tab lifecycle, provided by the BrowserSession aggregate root)
- device emulation, loggers, dialog manager and component binding (POS: provided by the aggregate root and lifecycle mixin)
- utils.page_health::abort_pending_navigation, probe_alive (POS: bounded protocol-level page health checks)

[OUTPUT]
- BrowserSessionTabMixin: new_tab, list_tabs, list_tabs_with_info, get_active_tab_id, close_tab, switch_tab, recover_active_tab

[POS]
Tab-management APIs for BrowserSession. Every tab change rebinds the per-page components
(Navigator / Snapshot / Interactor / Extractor, loggers, dialog manager) and keeps device
emulation consistent across tabs. `recover_active_tab` replaces an active tab whose page stopped
answering (stalled navigation, spinning renderer) with a blank one, so the session never keeps
handing a dead page to the next tool call. Inherited by BrowserSessionNavigationMixin, so it sits
right after it in the MRO and before BrowserSessionLifecycleMixin.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
from urllib.parse import urlparse

from ..utils.page_health import abort_pending_navigation, probe_alive

logger = logging.getLogger(__name__)

_RECOVERY_BUDGET_S = 10.0
_PAGE_CLOSE_TIMEOUT_S = 2.0


class BrowserSessionTabMixin:
    async def new_tab(self, url: str | None = None) -> str:
        """Create new Tab or reuse existing same-origin Tab, return Tab ID."""
        if hasattr(self, "_ensure_not_user_takeover"):
            await self._ensure_not_user_takeover()
        if url:
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"

            existing = self._tab_controller.find_tab_by_origin(origin)
            if existing is not None:
                await self._tab_controller.switch_tab(existing.tab_id)
                await self._initialize_components()
                await self.navigate(url)
                return existing.tab_id

        tab_id = await self._open_blank_tab()

        if url:
            await self.navigate(url)

        return tab_id

    async def _open_blank_tab(self) -> str:
        """Create a tab, make it active and bind the per-page components to it."""
        tab_id = await self._tab_controller.create_tab(
            self._context_key,
            engine_preference=self._engine_preference,
            launch_mode_preference=self._launch_mode_preference,
        )
        await self._initialize_components()
        # Keep mobile emulation session-consistent: a new tab inherits the
        # active device profile (no-op when desktop is emulated).
        await self._device_emulator.reapply(self._tab_controller.get_active_page())
        return tab_id

    def list_tabs(self) -> list[str]:
        """List all Tabs ID"""
        return self._tab_controller.list_tabs()

    def list_tabs_with_info(self) -> list[dict[str, str]]:
        """List all tabs with domain info for display."""
        return self._tab_controller.list_tabs_with_info()

    def get_active_tab_id(self) -> str:
        """Get the ID of the currently active tab."""
        return self._tab_controller.get_active_tab_id()

    async def close_tab(self, tab_id: str) -> str:
        """Close specified Tab; if still has Tab, bind Component to Current active page."""
        if self._tab_controller.list_tabs() and tab_id == self._tab_controller.get_active_tab_id():
            try:
                page = self._tab_controller.get_active_page()
                self._network_logger.detach_page(page)
                self._console_logger.detach_page(page)
                self._dialog_manager.detach(page)
            except RuntimeError:
                pass
        # Clear device emulation state bound to the closing page so pool-
        # recycled pages never keep stale mobile overrides.
        closing_page = self._tab_controller.get_page(tab_id)
        await self._device_emulator.forget_page(closing_page)
        await self._tab_controller.close_tab(tab_id)
        if self._tab_controller.list_tabs():
            await self._initialize_components()
            # Keep mobile emulation session-consistent: the new active tab
            # inherits the active device profile (no-op when desktop is emulated).
            await self._device_emulator.reapply(self._tab_controller.get_active_page())
        else:
            self._navigator = None
            self._snapshot_manager = None
            self._interactor = None
            self._extractor = None
            self._network_logger.stop_capture()
            self._console_logger.stop_capture()
            await self._network_intelligence.detach()
            # No tabs remain: drop device emulation state so a fresh tab
            # starts from native desktop instead of inheriting stale overrides.
            await self._device_emulator.detach()
        return f"Closed tab {tab_id}"

    async def switch_tab(self, tab_id: str) -> str:
        """Switch active Tab and rebind Navigator / Snapshot / Interactor / Extract etc. Component."""
        await self._tab_controller.switch_tab(tab_id)
        await self._initialize_components()
        # Keep mobile emulation session-consistent: the newly activated tab
        # inherits the active device profile (no-op when desktop is emulated).
        await self._device_emulator.reapply(self._tab_controller.get_active_page())
        return f"Switched to tab {tab_id}"

    @functools.cached_property
    def _tab_recovery_lock(self) -> asyncio.Lock:
        return asyncio.Lock()

    async def recover_active_tab(self) -> str | None:
        """Replace the active tab with a blank one when its page stopped answering.

        A stalled navigation is stopped first (that alone revives most pages); a page that still
        does not answer is closed and its tab swapped for a fresh one. Callers racing on the same
        dead page are serialized, and the loser finds the healthy replacement and does nothing.
        Never raises: a failed recovery is logged and leaves the session usable, because
        `navigate` opens a tab when none is left.

        Returns:
            The id of the replacement tab, or None when nothing was replaced (page healthy,
            user takeover active, no tab, or recovery failed).
        """
        if self._user_takeover_active:
            # The user is driving this tab by hand; closing it would destroy their work.
            return None
        async with self._tab_recovery_lock:
            try:
                async with asyncio.timeout(_RECOVERY_BUDGET_S):
                    return await self._replace_active_tab_if_unresponsive()
            except Exception:
                logger.warning("BrowserSession: tab recovery failed", exc_info=True)
                return None

    async def _replace_active_tab_if_unresponsive(self) -> str | None:
        try:
            tab_id = self._tab_controller.get_active_tab_id()
            page = self._tab_controller.get_active_page()
        except RuntimeError:
            return None
        await abort_pending_navigation(page)
        if await probe_alive(page):
            return None

        logger.warning("BrowserSession: %s stopped responding, replacing it", tab_id)
        # Closing the page is what frees a renderer stuck in a script loop; the tab teardown
        # below then runs against a closed page instead of one that never answers.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(page.close(), timeout=_PAGE_CLOSE_TIMEOUT_S)
        await self.close_tab(tab_id)
        return await self._open_blank_tab()
