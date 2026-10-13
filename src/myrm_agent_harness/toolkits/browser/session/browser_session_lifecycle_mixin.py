"""BrowserSession restart/close and component initialization lifecycle.

[INPUT]
- navigation::Navigator, snapshot_manager, interactor, extractor (POS: per-tab components)
- session_persistence::SessionPersistence (POS: auto-save on close)
- network_logger / network_intelligence (POS: attach on init)
- ..pool.camoufox_availability::require_camoufox_ready (POS: non-downloading Camoufox readiness gate)
- ..exceptions::EngineUnavailableError (POS: engine switch refused before any state change)

[OUTPUT]
- BrowserSessionLifecycleMixin: restart (pre-flighted engine switch with rollback), close, _initialize_components, _require_* helpers

[POS]
Session lifecycle and lazy component wiring for BrowserSession. Navigation mixin
depends on _initialize_components defined here; keep Lifecycle after Navigation in MRO.
An engine switch is transactional: refused up front when it cannot apply, and rolled
back onto the previous engine when the new one fails to launch.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from urllib.parse import urlparse

from myrm_agent_harness.toolkits.browser.recording_manager import RecordingManager

from ..navigation import Navigator
from .extractor import Extractor
from .interactor import Interactor
from .session_persistence import SessionPersistence
from .snapshot_manager import SnapshotManager

logger = logging.getLogger(__name__)


class BrowserSessionLifecycleMixin:
    async def restart(self, engine: str | None = None, restore_url: bool = True) -> str:
        """Restart the browser session, optionally switching the underlying browser engine.

        Args:
            engine: Optional engine name to switch to. If None, restarts with the current engine.
            restore_url: Whether to automatically navigate to the last active URL after restart.

        Returns:
            Status message indicating successful restart.

        Raises:
            EngineUnavailableError: Switching to Camoufox was refused up front (engine not
                installed, or an attached real browser is active); the session is untouched.
            BrowserLaunchError: The switch failed after teardown. The session is rolled back
                onto its previous engine with cookies/localStorage migrated (the page is not
                reloaded), then the original error is re-raised.
        """
        from myrm_agent_harness.toolkits.browser.exceptions import EngineUnavailableError
        from myrm_agent_harness.toolkits.browser.pool.camoufox_availability import require_camoufox_ready
        from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

        target_engine: BrowserEngine | None = None
        if engine:
            try:
                target_engine = BrowserEngine(engine)
            except ValueError:
                logger.warning(f"Invalid engine '{engine}', keeping current engine preference.")

        # Pre-flight before anything is closed: a refused switch must leave the session untouched.
        if target_engine == BrowserEngine.FIREFOX_CAMOUFOX:
            if not self.is_browser_managed():
                raise EngineUnavailableError("engine switch does not apply to an attached real browser")
            require_camoufox_ready()

        previous_preference = self._engine_preference

        # Save current state before closing
        current_url = None
        current_storage_state = None
        if self._tab_controller.list_tabs():
            with contextlib.suppress(Exception):
                page = self._tab_controller.get_active_page()
                current_url = page.url
                current_storage_state = await page.context.storage_state()

        # close() releases the tabs and observers and destroys the context unless another
        # session still holds pages in it; the restarted session keeps its context identity.
        context_key = self._context_key
        await self.close()
        self._context_key = context_key

        # Also clean up the browser instance if it has no more contexts
        try:
            browsers_to_remove = []
            for browser_inst in self._browser_pool._browsers:
                if not browser_inst.contexts:
                    logger.info(f"Browser instance {browser_inst.engine} has no more contexts, closing it.")
                    # Ensure we actually close the browser process
                    if browser_inst.browser:
                        browser_inst.expected_close = True
                        try:
                            await browser_inst.browser.close()
                        except Exception as e:
                            logger.warning(f"Error closing browser process: {e}")
                    browsers_to_remove.append(browser_inst)

            for b in browsers_to_remove:
                if b in self._browser_pool._browsers:
                    self._browser_pool._browsers.remove(b)
        except Exception as e:
            logger.warning(f"Failed to close empty browser instance during restart: {e}")

        # Update session's engine preference
        if target_engine is not None:
            self._engine_preference = target_engine
            logger.info(f"Session engine preference updated to {self._engine_preference}")

        # Re-initialize the session by requesting a new page from the pool
        # This will trigger the pool to use the updated config and engine
        # We use new_tab to bootstrap the first page
        switch_error: Exception | None = None
        try:
            await self.new_tab()
        except Exception as exc:
            if self._engine_preference == previous_preference:
                raise
            # The old browser is already gone: reopen on the previous engine so the
            # session stays usable, migrate state as usual, then surface the failure.
            logger.warning(
                f"Engine switch to {self._engine_preference} failed ({exc}); restoring {previous_preference}"
            )
            self._engine_preference = previous_preference
            switch_error = exc
            await self.new_tab()

        # Migrate storage state to the new context
        if current_storage_state:
            with contextlib.suppress(Exception):
                from ..checkpoint.session_state import _build_localstorage_script, normalize_cookies

                new_page = self._tab_controller.get_active_page()

                cookies = normalize_cookies(current_storage_state.get("cookies", []))
                if cookies:
                    await new_page.context.add_cookies(cookies)
                    logger.info(f"Successfully migrated {len(cookies)} cookies to new engine.")

                local_storage_origins = current_storage_state.get("origins", [])
                if local_storage_origins:
                    injected_count = 0

                    # Evaluate on pages already open at a matching origin —
                    # context-level init-script injection silently no-ops under
                    # patchright, so storage only lands via explicit evaluation.
                    for origin_data in local_storage_origins:
                        origin = origin_data.get("origin")
                        local_storage = origin_data.get("localStorage", [])
                        if not (local_storage and origin):
                            continue

                        script = _build_localstorage_script(local_storage, origin)
                        for page in new_page.context.pages:
                            parsed = urlparse(page.url)
                            page_origin = f"{parsed.scheme}://{parsed.netloc}"
                            if page_origin != origin:
                                continue
                            try:
                                await page.evaluate(script)
                                injected_count += len(local_storage)
                            except Exception as exc:
                                logger.warning(f"localStorage evaluate failed for {origin}: {exc}")

                        await new_page.context.add_init_script(script)
                        injected_count += len(local_storage)

                    logger.info(f"Successfully migrated {injected_count} localStorage items to new engine.")

        if switch_error is not None:
            raise switch_error

        # Restore state if possible
        if restore_url and current_url and current_url != "about:blank":
            try:
                await self.navigate(current_url)
                return f"Successfully restarted browser session with engine '{engine or 'default'}' and restored URL."
            except Exception:
                return "Restarted browser session, but failed to restore URL"

        return f"Successfully restarted browser session with engine '{engine or 'default'}'."

    async def close(self) -> None:
        """Close the session (releases all resources)."""
        if self._persistence is not None:
            await self._persistence.cleanup_expired()

        if self._recording_manager is not None:
            if self._recording_manager.trace_active:
                logger.warning("Trace recording was still active during session close, cleaning up state")
            if self._recording_manager.har_active:
                logger.warning("HAR recording was still active during session close, cleaning up state")

        video_path = None
        if self._observability:
            self._observability.telemetry.mark_closed()
            if self._observability.recording_enabled:
                try:
                    page = self._tab_controller.get_active_page()
                    if page.video:
                        video_path = Path(await page.video.path())
                except Exception as e:
                    logger.warning("Failed to get video path: %s", e)

        if self._download_manager is not None:
            await self._download_manager.cleanup()

        self._network_logger.detach_current()
        self._console_logger.detach_current()
        await self._network_intelligence.detach()
        await self._device_emulator.detach()

        if self._auto_restore_domains and self._persistence:
            await self._auto_save_sessions_before_close()

        await self._tab_controller.close_all()

        # Destroy the BrowserContext to prevent memory leaks. Tabs are released above, so only
        # pages of other sessions sharing this key can still be in use: the last session out
        # destroys the context, an earlier one leaves it (and their tabs and cookies) alone.
        if self._context_key:
            try:
                await self._browser_pool.destroy_context(self._context_key, only_if_idle=True)
                self._context_key = None
            except Exception as e:
                logger.warning(f"Failed to destroy context during session close: {e}")

        if self._observability:
            self._observability.cleanup_recording(video_path)

        logger.info("BrowserSession: closed session")

    async def _auto_save_sessions_before_close(self) -> None:
        """Auto-save sessions for configured auto_restore_domains before closing.

        Only saves domains that have relevant cookies in the current context
        and haven't been saved with identical state already (hash diff).
        """
        try:
            page = self._tab_controller.get_active_page()
            context = page.context
            storage_state = await context.storage_state()
        except Exception as exc:
            logger.warning("Auto-save skipped (cannot access browser context): %s", exc)
            return

        cookies = storage_state.get("cookies", [])
        hook = getattr(self, "_session_lifecycle_hook", None)
        if hook is not None:
            from .browser_session_persistence_mixin import _fire_and_forget, _parse_counts
        for domain in self._auto_restore_domains:
            try:
                has_cookies = any(
                    SessionPersistence._is_cookie_for_domain(c.get("domain", ""), domain) for c in cookies
                )
                if not has_cookies:
                    continue

                cached_hash = self._session_hash_cache.get(domain)
                if cached_hash:
                    new_hash = await self._persistence.compute_hash(domain)
                    if new_hash == cached_hash:
                        continue

                save_result = await self._persistence.save(context, domain)
                new_hash = await self._persistence.compute_hash(domain)
                if new_hash:
                    self._session_hash_cache[domain] = new_hash
                logger.info("Auto-saved session for domain: %s", domain)

                if hook is not None:
                    cookie_count, ls_count = _parse_counts(save_result)
                    _fire_and_forget(hook.on_session_saved(domain, cookie_count, ls_count))
            except Exception as exc:
                logger.warning("Auto-save failed for %s: %s", domain, exc)

    async def _initialize_components(self) -> None:
        """Initialize components (Navigator integration rate-limiting, circuit breaker and smart wait)."""
        page = self._tab_controller.get_active_page()
        tab_id = self._tab_controller.get_active_tab_id()

        from ...web_fetch.router import get_global_domain_metrics_manager

        self._navigator = Navigator(
            page,
            throttle=self._browser_pool.throttle_strategy,
            circuit_breaker=self._browser_pool.circuit_breaker,
            wait_config=self._browser_pool.config.navigation_wait,
            domain_metrics_manager=get_global_domain_metrics_manager(),
            allow_private_networks=self._allow_private_networks,
            auto_dismiss_popups=False,
        )
        self._snapshot_manager = SnapshotManager(page)

        last_snapshot_url = self._tab_controller.get_snapshot_url(tab_id)
        self._interactor = Interactor(
            page, {}, last_snapshot_url=last_snapshot_url, humanize=self._browser_pool.config.humanize
        )
        self._extractor = Extractor(page)

        if not self._auto_restored and self._auto_restore_domains and self._persistence:
            self._auto_restored = True
            for domain in self._auto_restore_domains:
                try:
                    await self._persistence.restore(page.context, domain)
                    logger.info(f"Auto-restored session for domain: {domain}")
                except Exception as e:
                    logger.error(f"Failed to auto-restore domain {domain}: {e}")

        if self._recording_manager is None:
            self._recording_manager = RecordingManager()

        self._network_logger.start_capture(page)
        self._console_logger.start_capture(page)
        await self._network_intelligence.attach(page)

        if self._download_manager is not None:
            self._download_manager.attach(page)

        self._dialog_manager.attach(page)
        self._tab_controller.attach_popup_listener(page)

    async def _ensure_components(self) -> None:
        """Ensure components are initialized and bound to the current active page."""
        if self._navigator is None:
            await self._initialize_components()
            return
        current_page = self._tab_controller.get_active_page()
        if self._navigator._page is not current_page:
            await self._initialize_components()

    def _require_navigator(self) -> Navigator:
        """Ensure Navigator is initialized and return it.

        Returns:
            Navigator instance

        Raises:
            RuntimeError: If Navigator is not initialized
        """
        if self._navigator is None:
            raise RuntimeError("Navigator not initialized. Call new_tab() or navigate() first.")
        return self._navigator

    def _require_snapshot_manager(self) -> SnapshotManager:
        """Ensure SnapshotManager is initialized and return it.

        Returns:
            SnapshotManager instance

        Raises:
            RuntimeError: If SnapshotManager is not initialized
        """
        if self._snapshot_manager is None:
            raise RuntimeError("SnapshotManager not initialized. Call new_tab() first.")
        return self._snapshot_manager

    def _require_interactor(self) -> Interactor:
        """Ensure Interactor is initialized and return it.

        Returns:
            Interactor instance

        Raises:
            RuntimeError: If Interactor is not initialized
        """
        if self._interactor is None:
            raise RuntimeError("Interactor not initialized. Call new_tab() first.")
        return self._interactor

    def _require_extractor(self) -> Extractor:
        """Ensure Extractor is initialized and return it.

        Returns:
            Extractor instance

        Raises:
            RuntimeError: If Extractor is not initialized
        """
        if self._extractor is None:
            raise RuntimeError("Extractor not initialized. Call new_tab() first.")
        return self._extractor
