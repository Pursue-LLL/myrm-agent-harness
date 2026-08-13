"""Runtime CDP device emulation for browser pages.

[INPUT]
- patchright.async_api::CDPSession, Page (POS: Chrome DevTools Protocol session)
- pool.emulation::EmulationConfig (POS: browser environment emulation config with type safety and parameter validation)
- pool.device_profiles::resolve_device, list_device_names (POS: curated mobile device profile registry)

[OUTPUT]
- DeviceEmulator: runtime CDP mobile device emulation (session-consistent, per-page idempotent)

[POS]
Applies mobile-device simulation to live pages via CDP without recreating
the browser context: ``Emulation.setDeviceMetricsOverride`` (layout viewport +
device pixel ratio + mobile flag), ``Network.setUserAgentOverride`` (mobile UA)
and ``Emulation.setTouchEmulationEnabled`` (touch events). Emulation is
session-consistent: every injected page is tracked, tabs created or activated
inherit the active profile via ``reapply``, and ``desktop`` clears every
tracked page so no tab silently keeps mobile overrides. The UA captured before
the first emulation is restored rather than the browser default, so context-
level UA configuration survives a reset.

The page must be re-navigated after a switch for the new viewport to drive a
full re-layout; the returned message tells the agent exactly that. Every
injection failure is contained (try/except → honest error message), so a
browser engine without full CDP support (e.g. Camoufox/Firefox) degrades
gracefully instead of crashing the session.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Protocol

from ..pool.device_profiles import list_device_names, resolve_device

if TYPE_CHECKING:
    from patchright.async_api import CDPSession, Page

    from ..pool.emulation import EmulationConfig

logger = logging.getLogger(__name__)


class DeviceRegistry(Protocol):
    """Lookup surface for device profiles (decouples emulator from registry)."""

    def resolve(self, device: str) -> EmulationConfig | None:
        """Resolve a device name into its emulation config."""

    def list_names(self) -> list[str]:
        """Return the sorted list of available device names."""


class _BuiltinRegistry:
    """Default registry backed by ``pool.device_profiles``."""

    def resolve(self, device: str) -> EmulationConfig | None:
        return resolve_device(device)

    def list_names(self) -> list[str]:
        return list_device_names()


class DeviceEmulator:
    """Runtime CDP device emulation, consistent across the session's tabs."""

    def __init__(self, registry: DeviceRegistry | None = None) -> None:
        self._registry: DeviceRegistry = registry or _BuiltinRegistry()
        self._cdp_sessions: dict[Page, CDPSession] = {}
        self._injected_pages: set[Page] = set()
        self._active_device: str | None = None
        self._active_profile: EmulationConfig | None = None
        self._baseline_ua: str | None = None

    @property
    def active_device(self) -> str | None:
        """Name of the currently emulated device (None = desktop)."""
        return self._active_device

    async def emulate(self, device: str, page: Page) -> str:
        """Emulate a mobile device on the given page.

        Args:
            device: Device name (see ``list_devices``) or ``"desktop"`` to
                restore the native desktop behavior.
            page: Page to emulate.

        Returns:
            Human-readable confirmation or error message.

        """
        if device.strip().lower() in ("desktop", "default", "pc"):
            return await self.reset(page)

        profile = self._registry.resolve(device)
        if profile is None:
            available = ", ".join(self.list_devices())
            return (
                f"Unknown device '{device}'. Available devices: {available}. "
                "Use 'desktop' to restore the native viewport."
            )

        try:
            if self._baseline_ua is None:
                self._baseline_ua = await page.evaluate("navigator.userAgent")
            await self._apply(page, profile)
            self._active_device = device
            self._active_profile = profile
            return (
                f"Emulated '{device}' ({profile.viewport[0]}x{profile.viewport[1]} "
                f"@ {profile.device_scale_factor}x, mobile UA + touch). "
                "Re-navigate the page to apply the new mobile layout."
            )
        except Exception as exc:
            logger.warning("DeviceEmulator: emulation failed for '%s': %s", device, exc)
            await self._discard_session(page)
            # Keep the page tracked: a mid-sequence failure may have partially
            # injected overrides, so a later reset must still be able to clean it.
            return f"Device emulation failed: {exc}"

    async def reapply(self, page: Page) -> None:
        """Re-apply the active device profile to a fresh tab (tab inheritance).

        No-op when no device is currently emulated or the target page already
        carries emulation. Called when a tab is created so new tabs inherit the
        active profile, while pages emulated independently keep their own
        device.
        """
        profile = self._active_profile
        if profile is None or page in self._injected_pages:
            return
        try:
            await self._apply(page, profile)
        except Exception as exc:
            logger.warning("DeviceEmulator: failed to re-apply emulation: %s", exc)
            await self._discard_session(page)

    async def reset(self, page: Page) -> str:
        """Restore the browser's native desktop behavior on every tracked page.

        Args:
            page: Active page (included even when not previously tracked).

        Returns:
            Confirmation message.

        """
        self._injected_pages.add(page)
        errors: list[str] = []
        for tracked in list(self._injected_pages):
            try:
                await self._clear(tracked)
            except Exception as exc:
                logger.warning("DeviceEmulator: reset failed on a page: %s", exc)
                errors.append(str(exc))
        self._injected_pages.clear()
        self._active_device = None
        self._active_profile = None
        self._baseline_ua = None
        if errors:
            return f"Failed to restore desktop viewport: {'; '.join(errors)}"
        return "Restored desktop viewport (cleared device emulation)."

    def list_devices(self) -> list[str]:
        """Return the sorted list of emulatable device names."""
        return self._registry.list_names()

    async def detach(self) -> None:
        """Release all CDP sessions and clear emulation state.

        Called when the owning session closes or restarts; the session is
        rebuilt from scratch, so all tracked pages and the active profile
        are dropped.
        """
        for cdp in list(self._cdp_sessions.values()):
            with contextlib.suppress(Exception):
                await cdp.detach()
        self._cdp_sessions.clear()
        self._injected_pages.clear()
        self._active_device = None
        self._active_profile = None
        self._baseline_ua = None

    async def forget_page(self, page: Page) -> None:
        """Clear a closing page's emulation and release its CDP session.

        Called when a tab is closed so no pool-recycled page keeps stale
        mobile overrides, and so `active_device` stays truthful.
        """
        if page in self._injected_pages and not page.is_closed():
            try:
                await self._clear(page)
            except Exception as exc:
                logger.warning("DeviceEmulator: failed to clear page on close: %s", exc)
        self._injected_pages.discard(page)
        await self._discard_session(page)

    async def _ensure_cdp(self, page: Page) -> CDPSession:
        """Return the CDP session bound to the page, creating one if missing."""
        cdp = self._cdp_sessions.get(page)
        if cdp is not None:
            return cdp
        cdp = await page.context.new_cdp_session(page)
        self._cdp_sessions[page] = cdp
        return cdp

    async def _discard_session(self, page: Page) -> None:
        cdp = self._cdp_sessions.pop(page, None)
        if cdp is not None:
            with contextlib.suppress(Exception):
                await cdp.detach()

    async def _apply(self, page: Page, profile: EmulationConfig) -> None:
        # Track the page before injecting so a mid-sequence CDP failure still
        # leaves it registered for later reset cleanup.
        self._injected_pages.add(page)
        cdp = await self._ensure_cdp(page)
        width, height = profile.viewport
        await cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": profile.device_scale_factor,
                "mobile": bool(profile.is_mobile),
            },
        )
        if profile.user_agent is not None:
            await cdp.send(
                "Network.setUserAgentOverride", {"userAgent": profile.user_agent}
            )
        await cdp.send(
            "Emulation.setTouchEmulationEnabled",
            {"enabled": bool(profile.has_touch)},
        )

    async def _clear(self, page: Page) -> None:
        if page.is_closed():
            self._injected_pages.discard(page)
            return
        cdp = await self._ensure_cdp(page)
        await cdp.send("Emulation.clearDeviceMetricsOverride")
        # CDP has no Network.clearUserAgentOverride; restore the UA captured
        # before the first emulation. When never emulated, leave the UA intact
        # so a context-level custom UA is preserved.
        if self._baseline_ua is not None:
            await cdp.send(
                "Network.setUserAgentOverride",
                {"userAgent": self._baseline_ua},
            )
        await cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
        self._injected_pages.discard(page)
