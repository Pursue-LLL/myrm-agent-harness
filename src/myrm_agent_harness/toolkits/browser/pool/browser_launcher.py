"""Browser instance launcher with CDP connect and intelligent retry.


[INPUT]
- patchright.async_api::Playwright (POS: Patchright launcher)
- patchright.async_api::Browser (POS: Patchright browser instance)
- .config::LaunchMode, _DEFAULT_CDP_ENDPOINT (POS: launch method enum and default CDP endpoint)

[OUTPUT]
- BrowserLauncher: browser instance launcher (supports launch/connect/auto modes)
- BrowserInstance: browser instance metadata container (includes is_managed, last_active_at, _disconnected)

[POS]
Dedicated to browser instance launching, including:
1. Playwright startup and management
2. New browser launch (chromium.launch)
3. CDP connection to existing Chrome (chromium.connect_over_cdp)
4. Automatic CDP port detection (HTTP GET /json/version)
5. Auto mode: probe → connect → fallback to launch
6. Smart retry strategy (3 retries + exponential backoff)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..exceptions import BrowserLaunchError
from .config import _DEFAULT_CDP_ENDPOINT, BrowserEngine, LaunchMode

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext, Playwright

    from .page_pool import PagePool

logger = logging.getLogger(__name__)

_CDP_PROBE_TIMEOUT_S = 2.0


@dataclass
class BrowserInstance:
    """Browser instance metadata for pool scheduling and session preservation.

    is_managed: True when launched by BrowserLauncher; False when attached via CDP.
    _disconnected: Set on browser disconnect to avoid duplicate semaphore release.
    _pid: Underlying browser process PID for orphan cleanup when managed.
    """

    browser: Browser
    engine: str = "chromium_patchright"
    contexts: dict[str, BrowserContext] = field(default_factory=dict)
    page_pools: dict[str, PagePool] = field(default_factory=dict)
    load: int = 0
    last_active_at: float = field(default_factory=time.monotonic)
    _disconnected: bool = False
    is_managed: bool = True
    _pid: int | None = None

    def force_kill(self) -> None:
        """Force kill the underlying browser process.

        This is a fallback mechanism to prevent zombie processes if browser.close() hangs or fails.
        Only attempts to kill if the process is managed by us and we have its PID.
        """
        if not self.is_managed or not self._pid:
            return

        import os
        import signal

        try:
            # Send SIGKILL (9) to force terminate the process
            os.kill(self._pid, signal.SIGKILL)
            logger.warning(f"Force killed zombie browser process (PID: {self._pid})")
        except ProcessLookupError:
            # Process already dead, which is fine
            pass
        except Exception as e:
            logger.error(f"Failed to force kill browser process (PID: {self._pid}): {e}")


class BrowserLauncher:
    """Browser instance launcher with launch/connect/auto modes."""

    def __init__(
        self,
        launch_options: dict[str, object],
        launch_mode: LaunchMode = LaunchMode.LAUNCH,
        engine: BrowserEngine = BrowserEngine.CHROMIUM_PATCHRIGHT,
        cdp_endpoint: str | None = None,
        remote_ws_endpoint: str | None = None,
        remote_ws_headers: dict[str, str] | None = None,
    ) -> None:
        self._launch_options = launch_options
        self._launch_mode = launch_mode
        self._engine = engine
        self._cdp_endpoint = cdp_endpoint or _DEFAULT_CDP_ENDPOINT
        self._remote_ws_endpoint = remote_ws_endpoint
        self._remote_ws_headers = remote_ws_headers
        self._playwright: Playwright | None = None
        self._total_browsers = 0

    async def _ensure_playwright(self) -> Playwright:
        if not self._playwright:
            from patchright.async_api import async_playwright

            self._playwright = await async_playwright().start()
        return self._playwright

    async def create_browser(self, headers: dict[str, str] | None = None) -> BrowserInstance:
        """Create Browser via configured launch_mode (launch/connect/auto/remote).

        AUTO mode: probe CDP → connect if available → fallback to launch.
        REMOTE mode: connect to remote WebSocket endpoint.

        Returns:
            BrowserInstance with initialized browser

        Raises:
            BrowserLaunchError: If all strategies fail

        """
        if self._launch_mode == LaunchMode.REMOTE:
            if not self._remote_ws_endpoint:
                raise BrowserLaunchError("remote_ws_endpoint is required for REMOTE launch mode")
            merged_headers = dict(self._remote_ws_headers or {})
            if headers:
                merged_headers.update(headers)
            return await self._connect_existing(self._remote_ws_endpoint, headers=merged_headers)

        if self._launch_mode == LaunchMode.CONNECT:
            return await self._connect_existing(self._cdp_endpoint, headers=headers)

        if self._launch_mode == LaunchMode.AUTO and await self._probe_cdp(self._cdp_endpoint):
            try:
                inst = await self._connect_existing(self._cdp_endpoint, headers=headers)
                logger.info("AUTO mode: connected to existing Chrome via CDP")
                return inst
            except Exception as exc:
                logger.warning(f"AUTO mode: CDP connect failed, falling back to launch: {exc}")

        return await self._launch_new_browser()

    async def _probe_cdp(self, endpoint: str) -> bool:
        """Probe CDP endpoint availability via HTTP GET /json/version."""
        import urllib.error
        import urllib.request

        version_url = f"{endpoint}/json/version"

        def _sync_probe() -> bool:
            try:
                req = urllib.request.Request(version_url, method="GET")
                with urllib.request.urlopen(req, timeout=_CDP_PROBE_TIMEOUT_S) as resp:
                    return resp.status == 200
            except Exception:
                return False

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_probe)

    async def _connect_existing(self, endpoint: str, headers: dict[str, str] | None = None) -> BrowserInstance:
        """Connect to an existing Chrome instance via CDP with retry.

        Retries up to 3 times with exponential backoff (1s, 2s) to handle
        transient CDP unavailability (e.g. Chrome still initializing).

        The returned BrowserInstance has is_managed=False.
        Calling browser.close() on a CDP-connected browser only
        disconnects the CDP session — it does NOT kill the Chrome process.
        """
        pw = await self._ensure_playwright()
        last_exc: Exception | None = None

        for attempt in range(3):
            try:
                browser = await pw.chromium.connect_over_cdp(endpoint, headers=headers)
                self._total_browsers += 1
                logger.info(
                    f"Connected to existing Chrome via CDP at {endpoint} "
                    f"(total: {self._total_browsers}, contexts: {len(browser.contexts)})"
                )
                return BrowserInstance(browser=browser, engine=self._engine.value, is_managed=False)

            except Exception as exc:
                last_exc = exc
                logger.warning(f"CDP connect failed (attempt {attempt + 1}/3): {exc}")
                if attempt < 2:
                    await asyncio.sleep(2**attempt)

        error_msg = f"Failed to connect to Chrome via CDP at {endpoint} after 3 attempts: {last_exc}"
        logger.error(error_msg)
        raise BrowserLaunchError(error_msg) from last_exc

    async def _launch_new_browser(self) -> BrowserInstance:
        """Launch new browser with intelligent retry (3 attempts + exponential backoff)."""
        last_exc: Exception | None = None

        for attempt in range(3):
            try:
                if self._engine == BrowserEngine.FIREFOX_CAMOUFOX:
                    try:
                        from camoufox.async_api import AsyncCamoufox
                    except ImportError as e:
                        raise BrowserLaunchError(
                            "camoufox is not installed. Please install it with: pip install camoufox[async]"
                        ) from e

                    # Camoufox has its own launch signature, we extract common options
                    camoufox_opts = {
                        "headless": self._launch_options.get("headless", True),
                        "proxy": self._launch_options.get("proxy"),
                    }
                    # Filter out None values
                    camoufox_opts = {k: v for k, v in camoufox_opts.items() if v is not None}

                    # AsyncCamoufox is an async context manager, but we need the browser instance
                    # We use start() to get the browser instance without entering the context
                    camoufox_launcher = AsyncCamoufox(**camoufox_opts)
                    browser = await camoufox_launcher.start()

                    # Try to get PID from Camoufox (it uses Playwright under the hood)
                    pid = None
                    with contextlib.suppress(Exception):
                        if hasattr(browser, "_impl_obj") and hasattr(browser._impl_obj, "_process"):
                            pid = browser._impl_obj._process.pid

                    logger.info(f"Launched new Camoufox Browser instance (attempt {attempt + 1}/3, PID: {pid})")
                else:
                    pw = await self._ensure_playwright()
                    browser = await pw.chromium.launch(**self._launch_options)  # type: ignore[arg-type]

                    # Try to get PID from Playwright Chromium
                    pid = None
                    with contextlib.suppress(Exception):
                        if hasattr(browser, "_impl_obj") and hasattr(browser._impl_obj, "_process"):
                            pid = browser._impl_obj._process.pid

                    logger.info(f"Launched new Patchright Chromium instance (attempt {attempt + 1}/3, PID: {pid})")

                self._total_browsers += 1
                return BrowserInstance(browser=browser, engine=self._engine.value, is_managed=True, _pid=pid)

            except TimeoutError as exc:
                last_exc = exc
                logger.warning(f"Browser launch timeout (attempt {attempt + 1}/3): {exc}")
                if attempt < 2:
                    await asyncio.sleep(2**attempt)

            except ConnectionError as exc:
                last_exc = exc
                logger.warning(f"Browser launch connection error (attempt {attempt + 1}/3): {exc}")
                if attempt < 2:
                    await asyncio.sleep(2**attempt)

            except Exception as exc:
                last_exc = exc
                logger.warning(f"Browser launch failed (attempt {attempt + 1}/3): {exc}")
                if attempt < 2:
                    await asyncio.sleep(2**attempt)

        error_msg = f"Failed to create Browser after 3 attempts: {last_exc}"
        logger.error(error_msg)
        raise BrowserLaunchError(error_msg) from last_exc

    async def shutdown(self) -> None:
        """Shutdown Playwright."""
        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
