"""Browser instance launcher with CDP connect and intelligent retry.


[INPUT]
- patchright.async_api::Playwright (POS: Patchright launcher)
- patchright.async_api::Browser (POS: Patchright browser instance)
- .config::LaunchMode, _DEFAULT_CDP_ENDPOINT (POS: launch method enum and default CDP endpoint)
- .chrome_discovery::discover_chrome_cdp_endpoint (POS: DevToolsActivePort-based browser discovery)

[OUTPUT]
- BrowserLauncher: browser instance launcher (supports launch/connect/auto modes)
- BrowserInstance: browser instance metadata container (includes is_managed, last_active_at, _disconnected)

[POS]
Dedicated to browser instance launching, including:
1. Playwright startup and management
2. New browser launch (chromium.launch)
3. CDP connection to existing Chrome (chromium.connect_over_cdp)
4. Automatic CDP port detection (HTTP GET /json/version)
5. Auto mode: DevToolsActivePort discovery → probe → connect → fallback to launch
6. Smart retry strategy (3 retries + exponential backoff)
7. Zero-config auto-install: detects missing Chromium and installs via patchright
8. Camoufox fingerprint persistence: generates full config via launch_options(), saves/reloads via from_options, self-heals corrupted JSON
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..exceptions import BrowserLaunchError
from .config import _DEFAULT_CDP_ENDPOINT, BrowserEngine, LaunchMode

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext, Playwright

    from .page_pool import PagePool

logger = logging.getLogger(__name__)

_CDP_PROBE_TIMEOUT_S = 2.0
_INSTALL_TIMEOUT_S = 600  # 10 minutes max for Chromium download
_INSTALL_COOLDOWN_S = 1800  # 30 minutes cooldown after failed install

_install_lock: asyncio.Lock | None = None
_last_install_failure_at: float = 0.0


def _is_executable_missing(error: Exception) -> bool:
    """Detect if a launch failure is caused by missing browser executable."""
    msg = str(error).lower()
    return "executable doesn't exist" in msg or "no such file or directory" in msg


async def _auto_install_chromium() -> bool:
    """Install Chromium via patchright with cooldown protection.

    Returns True if installation succeeded, False otherwise.
    Prevents repeated attempts within _INSTALL_COOLDOWN_S after a failure.
    """
    global _last_install_failure_at, _install_lock  # noqa: PLW0603

    if _last_install_failure_at and (time.monotonic() - _last_install_failure_at) < _INSTALL_COOLDOWN_S:
        remaining = int(_INSTALL_COOLDOWN_S - (time.monotonic() - _last_install_failure_at))
        logger.warning("Chromium auto-install skipped: previous failure cooldown (%ds remaining)", remaining)
        return False

    if _install_lock is None:
        _install_lock = asyncio.Lock()

    async with _install_lock:
        # Double-check after acquiring lock
        if _last_install_failure_at and (time.monotonic() - _last_install_failure_at) < _INSTALL_COOLDOWN_S:
            return False

        logger.info("Auto-installing Chromium via patchright (this may take a few minutes)...")
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "patchright", "install", "chromium",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=_INSTALL_TIMEOUT_S,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_INSTALL_TIMEOUT_S)

            if proc.returncode == 0:
                logger.info("Chromium auto-install succeeded")
                _last_install_failure_at = 0.0
                return True

            _last_install_failure_at = time.monotonic()
            logger.error(
                "Chromium auto-install failed (exit %d): %s",
                proc.returncode,
                (stderr or stdout or b"").decode(errors="replace")[:500],
            )
            return False

        except TimeoutError:
            _last_install_failure_at = time.monotonic()
            logger.error("Chromium auto-install timed out after %ds", _INSTALL_TIMEOUT_S)
            return False
        except FileNotFoundError:
            _last_install_failure_at = time.monotonic()
            logger.error("'patchright' CLI not found — cannot auto-install Chromium")
            return False
        except Exception as exc:
            _last_install_failure_at = time.monotonic()
            logger.error("Chromium auto-install unexpected error: %s", exc)
            return False


def _build_install_failure_message(original_error: Exception) -> str:
    """Build a user-friendly error message when auto-install fails.

    Includes diagnostic hints (disk space, network, permissions) to help
    GUI users who cannot easily run terminal commands.
    """
    lines = [
        "Browser engine (Chromium) is not installed and automatic installation failed.",
        "",
        "To fix this manually, open a terminal and run:",
        "  patchright install chromium",
        "",
        "Common causes:",
        "  - Insufficient disk space (Chromium requires ~400 MB)",
        "  - No internet connection (download required)",
        "  - Permission issues (try running with elevated privileges)",
        "",
        f"Original error: {original_error}",
    ]
    return "\n".join(lines)


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
    """Browser instance launcher with launch/connect/auto/remote/extension modes."""

    def __init__(
        self,
        launch_options: dict[str, object],
        launch_mode: LaunchMode = LaunchMode.LAUNCH,
        engine: BrowserEngine = BrowserEngine.CHROMIUM_PATCHRIGHT,
        cdp_endpoint: str | None = None,
        remote_ws_endpoint: str | None = None,
        remote_ws_headers: dict[str, str] | None = None,
        extension_bridge: object | None = None,
        fingerprint_dir: Path | None = None,
    ) -> None:
        self._launch_options = launch_options
        self._launch_mode = launch_mode
        self._engine = engine
        self._cdp_endpoint = cdp_endpoint or _DEFAULT_CDP_ENDPOINT
        self._remote_ws_endpoint = remote_ws_endpoint
        self._remote_ws_headers = remote_ws_headers
        self._extension_bridge = extension_bridge
        self._fingerprint_dir = fingerprint_dir
        self._playwright: Playwright | None = None
        self._total_browsers = 0

    async def _ensure_playwright(self) -> Playwright:
        if not self._playwright:
            from patchright.async_api import async_playwright

            self._playwright = await async_playwright().start()
        return self._playwright

    async def create_browser(self, headers: dict[str, str] | None = None) -> BrowserInstance:
        """Create Browser via configured launch_mode (launch/connect/auto/remote/extension).

        AUTO mode: probe CDP → connect if available → fallback to launch.
        REMOTE mode: connect to remote WebSocket endpoint.
        EXTENSION mode: connect through browser extension's CDP proxy.

        Returns:
            BrowserInstance with initialized browser

        Raises:
            BrowserLaunchError: If all strategies fail

        """
        if self._launch_mode == LaunchMode.EXTENSION:
            return await self._connect_extension()

        if self._launch_mode == LaunchMode.REMOTE:
            if not self._remote_ws_endpoint:
                raise BrowserLaunchError("remote_ws_endpoint is required for REMOTE launch mode")
            merged_headers = dict(self._remote_ws_headers or {})
            if headers:
                merged_headers.update(headers)
            return await self._connect_existing(self._remote_ws_endpoint, headers=merged_headers)

        if self._launch_mode == LaunchMode.CONNECT:
            return await self._connect_existing(self._cdp_endpoint, headers=headers)

        if self._launch_mode == LaunchMode.AUTO:
            discovered = await self._discover_local_chrome()
            endpoint_to_try = discovered or self._cdp_endpoint

            if await self._probe_cdp(endpoint_to_try):
                try:
                    inst = await self._connect_existing(endpoint_to_try, headers=headers)
                    logger.info(
                        "AUTO mode: connected to existing Chrome via CDP at %s%s",
                        endpoint_to_try,
                        " (discovered)" if discovered else "",
                    )
                    return inst
                except Exception as exc:
                    logger.warning("AUTO mode: CDP connect failed, falling back to launch: %s", exc)

        return await self._launch_new_browser()

    async def _discover_local_chrome(self) -> str | None:
        """Discover a locally running Chrome via DevToolsActivePort file scan.

        Runs the synchronous discovery in a thread executor to avoid blocking
        the event loop (filesystem I/O + TCP/HTTP probes).
        """
        from .chrome_discovery import discover_chrome_cdp_endpoint

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, discover_chrome_cdp_endpoint)

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
        """Launch new browser with intelligent retry (3 attempts + exponential backoff).

        When the Chromium executable is missing (common for first-time Tauri desktop
        users), automatically installs it via ``patchright install chromium`` and retries.
        A cooldown prevents repeated install attempts after failure.
        """
        last_exc: Exception | None = None
        auto_installed = False

        for attempt in range(3):
            try:
                if self._engine == BrowserEngine.FIREFOX_CAMOUFOX:
                    try:
                        from camoufox.async_api import AsyncCamoufox
                        from camoufox.utils import launch_options as build_camoufox_options
                    except ImportError as e:
                        raise BrowserLaunchError(
                            "camoufox is not installed. Please install it with: pip install camoufox[async]"
                        ) from e

                    fp_file = self._fingerprint_dir / "camoufox_fingerprint.json" if self._fingerprint_dir else None
                    camoufox_config: dict[str, object] | None = None
                    if fp_file and fp_file.is_file():
                        try:
                            camoufox_config = json.loads(fp_file.read_text(encoding="utf-8"))
                            if not isinstance(camoufox_config, dict):
                                raise ValueError("expected dict, got " + type(camoufox_config).__name__)
                            logger.debug("Loaded Camoufox fingerprint from %s", fp_file)
                        except (json.JSONDecodeError, ValueError):
                            logger.warning(
                                "Corrupted Camoufox fingerprint at %s — deleting and regenerating", fp_file,
                            )
                            fp_file.unlink(missing_ok=True)
                            camoufox_config = None

                    if camoufox_config is None:
                        build_kwargs: dict[str, object] = {
                            "headless": self._launch_options.get("headless", True),
                            "fingerprint_preset": True,
                        }
                        proxy = self._launch_options.get("proxy")
                        if proxy is not None:
                            build_kwargs["proxy"] = proxy

                        loop = asyncio.get_running_loop()
                        camoufox_config = await loop.run_in_executor(
                            None, lambda: build_camoufox_options(**build_kwargs),
                        )

                        if fp_file:
                            fp_file.parent.mkdir(parents=True, exist_ok=True)
                            fp_file.write_text(
                                json.dumps(camoufox_config, default=str, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            logger.info("Camoufox fingerprint saved to %s", fp_file)

                    browser = await AsyncCamoufox(from_options=camoufox_config).start()

                    pid = None
                    with contextlib.suppress(Exception):
                        if hasattr(browser, "_impl_obj") and hasattr(browser._impl_obj, "_process"):
                            pid = browser._impl_obj._process.pid

                    logger.info(f"Launched new Camoufox Browser instance (attempt {attempt + 1}/3, PID: {pid})")
                else:
                    pw = await self._ensure_playwright()
                    browser = await pw.chromium.launch(**self._launch_options)  # type: ignore[arg-type]

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

                if (
                    not auto_installed
                    and _is_executable_missing(exc)
                    and self._engine != BrowserEngine.FIREFOX_CAMOUFOX
                ):
                    logger.info("Chromium executable not found — attempting auto-install")
                    if await _auto_install_chromium():
                        auto_installed = True
                        # Reset playwright so the new executable is picked up
                        if self._playwright:
                            with contextlib.suppress(Exception):
                                await self._playwright.stop()
                            self._playwright = None
                        continue  # retry immediately after install

                if attempt < 2:
                    await asyncio.sleep(2**attempt)

        error_msg = f"Failed to create Browser after 3 attempts: {last_exc}"
        if last_exc and _is_executable_missing(last_exc):
            error_msg = _build_install_failure_message(last_exc)
        logger.error(error_msg)
        raise BrowserLaunchError(error_msg) from last_exc

    async def _connect_extension(self) -> BrowserInstance:
        """Connect through browser extension's CDP proxy.

        The extension_bridge (injected from business layer) handles:
        - WebSocket connection management
        - Tab selection and domain authorization
        - chrome.debugger attachment and CDP message routing

        Returns:
            BrowserInstance with is_managed=False (extension owns the browser lifecycle).

        Raises:
            BrowserLaunchError: If extension bridge is not available or connection fails.
        """
        from .extension_bridge import ExtensionBridge, ExtensionBridgeNotAvailable

        if self._extension_bridge is None:
            raise BrowserLaunchError(
                "extension_bridge is required for EXTENSION launch mode. "
                "Ensure the browser extension is installed and connected."
            )

        if not isinstance(self._extension_bridge, ExtensionBridge):
            raise BrowserLaunchError(
                f"extension_bridge must implement ExtensionBridge Protocol, "
                f"got {type(self._extension_bridge).__name__}"
            )

        try:
            instance = await self._extension_bridge.connect(timeout=10.0)
            self._total_browsers += 1
            logger.info("EXTENSION mode: connected to user's browser via extension bridge")
            return instance
        except ExtensionBridgeNotAvailable as exc:
            raise BrowserLaunchError(str(exc)) from exc
        except Exception as exc:
            raise BrowserLaunchError(
                f"Extension bridge connection failed: {exc}"
            ) from exc

    async def shutdown(self) -> None:
        """Shutdown Playwright."""
        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
