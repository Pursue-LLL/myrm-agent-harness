"""BrowserSession navigation, tab switching, and CAPTCHA coordination APIs.

[INPUT]
- navigation::Navigator (POS: throttled page navigation)
- captcha protocols and coordinator (POS: blocking CAPTCHA detection/handling)
- web_fetch site experience store (POS: post-navigation experience injection)

[OUTPUT]
- BrowserSessionNavigationMixin: new_tab, navigate, tab switch/close, CAPTCHA helpers

[POS]
Navigation and tab-management APIs for BrowserSession. Calls lifecycle mixin for
component initialization; must appear before BrowserSessionLifecycleMixin in MRO.
"""

from __future__ import annotations

import asyncio
import logging

from myrm_agent_harness.toolkits.browser.captcha.protocols import CaptchaHandleResult

logger = logging.getLogger(__name__)

_CAMOUFOX_INSTALL_HINT = (
    "Camoufox stealth engine is unavailable. "
    "Install the browser stack: pip install 'myrm-agent-harness[browser]' "
    "(includes camoufox[async]). Retry navigation after install."
)


def _domain_from_url(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc


def _clear_engine_affinity_for_url(url: str) -> None:
    domain = _domain_from_url(url)
    if domain:
        from myrm_agent_harness.toolkits.browser.pool.engine_affinity import get_engine_affinity_store

        get_engine_affinity_store().clear(domain)


def _camoufox_launch_tool_error(exc: Exception) -> None:
    from myrm_agent_harness.utils.errors import ToolError

    raise ToolError(
        message=f"Camoufox stealth engine unavailable: {exc}",
        user_hint=_CAMOUFOX_INSTALL_HINT,
        error_code="BROWSER_CAMOUFOX_UNAVAILABLE",
        recovery_suggestions=[
            "Install myrm-agent-harness[browser] and retry",
            "Use Chromium (Patchright) for sites without advanced anti-bot",
        ],
    ) from exc


class BrowserSessionNavigationMixin:
    async def new_tab(self, url: str | None = None) -> str:
        """Create new Tab or reuse existing same-origin Tab, return Tab ID."""
        if url:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"

            existing = self._tab_controller.find_tab_by_origin(origin)
            if existing is not None:
                await self._tab_controller.switch_tab(existing.tab_id)
                await self._initialize_components()
                await self.navigate(url)
                return existing.tab_id

        tab_id = await self._tab_controller.create_tab(
            self._context_key,
            engine_preference=self._engine_preference,
            launch_mode_preference=self._launch_mode_preference,
        )
        await self._initialize_components()

        if url:
            await self.navigate(url)

        return tab_id

    async def navigate(self, url: str, verify_goal: str | None = None) -> str:
        """Navigate to URL (auto-injects site experience, auto-detects CAPTCHA)."""
        await self._ensure_components()

        # Fast-fail: skip 240s timeout if domain is already known as terminal challenge
        from urllib.parse import urlparse

        _nav_domain = urlparse(url).netloc
        if _nav_domain and _nav_domain in self._terminal_challenges:
            import time as _time

            elapsed = _time.monotonic() - self._terminal_challenges[_nav_domain]
            if elapsed < self._TERMINAL_CHALLENGE_TTL_S:
                from myrm_agent_harness.utils.errors import ToolError

                raise ToolError(
                    f"[TERMINAL_CHALLENGE] Navigation to {_nav_domain} skipped — "
                    f"this domain was blocked by an unsolvable verification challenge "
                    f"{elapsed:.0f}s ago (TTL {self._TERMINAL_CHALLENGE_TTL_S:.0f}s).",
                    user_hint=(
                        "This domain is protected by anti-bot verification that cannot be bypassed. "
                        "Do NOT retry. Report this to the user and suggest alternative sources."
                    ),
                    error_code="BROWSER_TERMINAL_CHALLENGE_CACHED",
                )
            else:
                del self._terminal_challenges[_nav_domain]

        from myrm_agent_harness.toolkits.browser.utils.proxy_error import is_blocked_response, is_proxy_error

        if not self._allow_private_networks and self._extension_bridge is not None:
            from myrm_agent_harness.toolkits.browser.url_routing import is_private_url

            is_private = await asyncio.to_thread(is_private_url, url)
            if is_private:
                return await self._navigate_via_extension(url, verify_goal=verify_goal)

        # Engine affinity: use remembered engine for this domain if available
        if self._engine_preference is None:
            from urllib.parse import urlparse

            from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
            from myrm_agent_harness.toolkits.browser.pool.engine_affinity import get_engine_affinity_store

            domain = urlparse(url).netloc
            if domain:
                remembered = get_engine_affinity_store().get(domain)
                if remembered is not None:
                    logger.info("Engine affinity hit for %s → %s", domain, remembered.value)
                    self._engine_preference = remembered
                    try:
                        await self.restart(engine=remembered.value, restore_url=False)
                    except Exception as exc:
                        from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError

                        get_engine_affinity_store().clear(domain)
                        if remembered == BrowserEngine.FIREFOX_CAMOUFOX and isinstance(exc, BrowserLaunchError):
                            _camoufox_launch_tool_error(exc)
                        raise

        max_attempts = 3
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            navigator = self._require_navigator()
            snapshot_manager = self._require_snapshot_manager()
            page = self._tab_controller.get_active_page()

            baseline_screenshot = None
            if verify_goal:
                try:
                    from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

                    password_locator = page.locator(PASSWORD_FIELD_SELECTOR)
                    baseline_screenshot = await page.screenshot(type="png", full_page=False, mask=[password_locator])
                except Exception as e:
                    logger.warning("Failed to take baseline screenshot for navigation verification: %s", e)

            try:
                title, final_url, status_code = await navigator.goto(url)

                if is_blocked_response(status_code):
                    raise Exception(f"Blocked response detected: HTTP {status_code}")

                break  # Success, exit retry loop

            except Exception as e:
                if (is_proxy_error(e) or "Blocked response" in str(e)) and attempt < max_attempts:
                    logger.warning(
                        f"Proxy error or block detected during navigation to {url}: {e}. "
                        f"Quarantining proxy and retrying (attempt {attempt}/{max_attempts})..."
                    )

                    if self._context_key and self._browser_pool._proxy_pool:
                        # Quarantine the bad proxy and release the sticky session
                        # We use duck typing/hasattr in case it's not RoundRobinProxyPool
                        if hasattr(self._browser_pool._proxy_pool, "report_failure"):
                            self._browser_pool._proxy_pool.report_failure(self._context_key)
                        else:
                            self._browser_pool._proxy_pool.release_session(self._context_key)

                    # Restart session to get a new proxy and migrate state losslessly
                    await self.restart(restore_url=False)
                    continue

                # If not a proxy error or out of retries, re-raise
                raise

        # CAPTCHA detection: inspect the loaded page for blocking CAPTCHAs
        captcha_result: CaptchaHandleResult | None = None
        if self._captcha_coordinator is not None:
            captcha_result = await self._handle_captcha_if_detected()
            if captcha_result is not None:
                if not captcha_result.success:
                    # Auto-fallback to CAMOUFOX if Chromium is blocked
                    from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

                    current_engine = self._engine_preference or BrowserEngine.CHROMIUM_PATCHRIGHT
                    if current_engine != BrowserEngine.FIREFOX_CAMOUFOX:
                        logger.warning(
                            f"CAPTCHA not resolved with {current_engine.value}. Auto-upgrading to CAMOUFOX and retrying..."
                        )
                        await self.notify_progress(
                            "Detected advanced anti-bot protection. Upgrading browser engine to stealth mode..."
                        )
                        try:
                            await self.restart(engine=BrowserEngine.FIREFOX_CAMOUFOX.value, restore_url=False)
                        except Exception as exc:
                            from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError

                            _clear_engine_affinity_for_url(url)
                            if isinstance(exc, BrowserLaunchError):
                                _camoufox_launch_tool_error(exc)
                            raise
                        navigator = self._require_navigator()
                        snapshot_manager = self._require_snapshot_manager()
                        page = self._tab_controller.get_active_page()
                        title, final_url, status_code = await navigator.goto(url)
                        captcha_result = await self._handle_captcha_if_detected()
                        if captcha_result is None or captcha_result.success:
                            # CAMOUFOX succeeded — record affinity for this domain
                            from urllib.parse import urlparse

                            from myrm_agent_harness.toolkits.browser.pool.engine_affinity import get_engine_affinity_store

                            upgrade_domain = urlparse(url).netloc
                            if upgrade_domain:
                                get_engine_affinity_store().record(upgrade_domain, BrowserEngine.FIREFOX_CAMOUFOX)
                        else:
                            title = await self._tab_controller.get_active_page().title()
                            final_url = self._tab_controller.get_active_page().url

                    # After all attempts, if CAPTCHA still unresolved → terminal challenge
                    if captcha_result is not None and not captcha_result.success:
                        import time as _time
                        from urllib.parse import urlparse

                        domain = urlparse(url).netloc
                        _clear_engine_affinity_for_url(url)
                        self._terminal_challenges[domain] = _time.monotonic()
                        logger.warning(
                            "Terminal challenge recorded for domain %s (%s)",
                            domain,
                            captcha_result.challenge_type,
                        )
                        from myrm_agent_harness.utils.errors import ToolError

                        raise ToolError(
                            f"[TERMINAL_CHALLENGE] Navigation to {domain} blocked by unsolvable "
                            f"{captcha_result.challenge_type} verification challenge. "
                            f"The page shows a bot-detection challenge instead of real content.",
                            user_hint=(
                                "Do NOT retry navigation to this domain — it will fail again. "
                                "Report this access issue to the user and suggest alternatives."
                            ),
                            error_code="BROWSER_TERMINAL_CHALLENGE",
                        )
                else:
                    title = await self._tab_controller.get_active_page().title()
                    final_url = self._tab_controller.get_active_page().url

        # Auto-dismiss cookie consent banners (post-CAPTCHA, before snapshot baseline)
        consent_msg: str | None = None
        if self._consent_dismisser.enabled:
            page = self._tab_controller.get_active_page()
            consent_msg = await self._consent_dismisser.dismiss(page)

        snapshot_manager.reset_diff_baseline()
        self._tab_controller.clear_text_snapshot()

        captcha_msg = captcha_result.message if captcha_result is not None else None
        result = f"Navigated to {final_url} (status={status_code}, title={title})"
        if captcha_msg:
            result = f"{result}\n{captcha_msg}"
        if consent_msg:
            result = f"{result}\n{consent_msg}"

        experience_hint = self._get_site_experience_hint(final_url)
        if experience_hint:
            result = f"{result}\n{experience_hint}"

        if verify_goal and baseline_screenshot:
            await self.notify_progress(f"Verifying navigation goal: '{verify_goal}'...")
            _success, verify_msg = await self._vision_verifier.verify_action(
                page=page,
                baseline_screenshot=baseline_screenshot,
                verify_goal=verify_goal,
            )
            result = f"{result}\n\n{verify_msg}"

        return result

    async def _navigate_via_extension(self, url: str, *, verify_goal: str | None = None) -> str:
        """Navigate to a private URL via the Extension Bridge (user's local browser).

        Called when a private URL is detected and extension_bridge is available.
        Falls back to a descriptive ToolError if the bridge is disconnected.
        """
        from urllib.parse import urlparse

        from myrm_agent_harness.toolkits.browser.pool.extension_bridge import ExtensionBridgeNotAvailable
        from myrm_agent_harness.utils.errors import ToolError

        assert self._extension_bridge is not None  # noqa: S101 — guaranteed by caller

        if not self._extension_bridge.is_connected():
            raise ToolError(
                message=f"Cannot navigate to private URL '{url}': browser extension is not connected.",
                user_hint=(
                    "This URL points to a private/local network address that is unreachable from "
                    "the cloud sandbox. Install and connect the browser extension to access local services."
                ),
                error_code="PRIVATE_URL_NO_EXTENSION",
                recovery_suggestions=[
                    "Ask the user to install the browser extension and connect it",
                    "Alternatively, use a publicly accessible URL",
                ],
            )

        domain = urlparse(url).hostname or ""
        try:
            instance = await self._extension_bridge.connect_to_domain(domain, timeout=15.0)
        except ExtensionBridgeNotAvailable:
            raise ToolError(
                message=f"Extension bridge lost connection while navigating to '{url}'.",
                user_hint="The browser extension disconnected. Please reconnect it and retry.",
                error_code="PRIVATE_URL_EXTENSION_LOST",
                recovery_suggestions=["Retry navigation after extension reconnects"],
            )

        browser = instance.browser
        contexts = browser.contexts
        if not contexts:
            raise ToolError(
                message=f"Extension bridge returned browser with no contexts for '{url}'.",
                user_hint="The extension-connected browser has no usable context. Reconnect and retry.",
                error_code="PRIVATE_URL_NO_CONTEXT",
            )
        pages = contexts[0].pages
        page = pages[0] if pages else await contexts[0].new_page()

        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            title = await page.title()
            final_url = page.url
            status_code = response.status if response else 0
        except Exception as exc:
            raise ToolError(
                message=f"Navigation to private URL '{url}' via extension failed: {exc}",
                user_hint="The private URL may be unreachable from the user's browser as well.",
                error_code="PRIVATE_URL_NAV_FAILED",
            ) from exc

        return f"Navigated to {final_url} (status={status_code}, title={title}) [via extension bridge — private network]"

    async def _handle_captcha_if_detected(self) -> CaptchaHandleResult | None:
        """Detect and handle blocking CAPTCHAs on the current page.

        Called after navigate() and after click/dblclick interactions.

        Returns:
            Structured result if a CAPTCHA was detected, otherwise ``None``.
        """
        if self._captcha_coordinator is None:
            return None

        from myrm_agent_harness.toolkits.browser.captcha import detect_captcha

        page = self._tab_controller.get_active_page()
        captcha_info = await detect_captcha(page)

        if captcha_info is None or not captcha_info.blocking:
            return None

        solve_result = await self._captcha_coordinator.handle_captcha(captcha_info, page)
        self._captcha_coordinator.reset()

        if solve_result.success:
            return CaptchaHandleResult(
                success=True,
                challenge_type=captcha_info.captcha_type.value,
                message=f"CAPTCHA resolved ({captcha_info.captcha_type.value}) via {solve_result.method}",
            )
        return CaptchaHandleResult(
            success=False,
            challenge_type=captcha_info.captcha_type.value,
            message=f"CAPTCHA not resolved ({captcha_info.reason}): {solve_result.message}",
        )

    def list_tabs(self) -> list[str]:
        """List all Tabs ID"""
        return self._tab_controller.list_tabs()

    def list_tabs_with_info(self) -> list[dict[str, str]]:
        """List all tabs with domain info for display."""
        return self._tab_controller.list_tabs_with_info()

    def get_active_tab_id(self) -> str:
        """GetCurrent活跃 Tab ID"""
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
        await self._tab_controller.close_tab(tab_id)
        if self._tab_controller.list_tabs():
            await self._initialize_components()
        else:
            self._navigator = None
            self._snapshot_manager = None
            self._interactor = None
            self._extractor = None
            self._network_logger.stop_capture()
            self._console_logger.stop_capture()
            await self._network_intelligence.detach()
        return f"Closed tab {tab_id}"

    async def switch_tab(self, tab_id: str) -> str:
        """Switch active Tab and rebind Navigator / Snapshot / Interactor / Extract etc. Component."""
        await self._tab_controller.switch_tab(tab_id)
        await self._initialize_components()
        return f"Switched to tab {tab_id}"
    @staticmethod
    def _get_site_experience_hint(url: str) -> str:
        """Query site experience and format as injected text (cross-validate with DomainMetrics)."""
        try:
            from urllib.parse import urlparse

            from ...web_fetch.router import (
                get_global_domain_metrics_manager,
                get_global_site_experience_store,
            )

            domain = urlparse(url).netloc.lower()
            if not domain:
                return ""

            store = get_global_site_experience_store()
            metrics_manager = get_global_domain_metrics_manager()
            experience, possibly_stale = store.get(domain, domain_metrics_manager=metrics_manager)

            if experience is None or experience.is_empty():
                return ""

            return experience.format_for_injection(possibly_stale=possibly_stale)
        except Exception:
            return ""
