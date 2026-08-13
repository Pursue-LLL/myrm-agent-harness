"""Runtime CDP device emulation for browser pages.

[INPUT]
- patchright.async_api::CDPSession, Page (POS: Chrome DevTools Protocol session)
- pool.emulation::EmulationConfig (POS: resolved device dimensions)
- pool.device_profiles::resolve_device, list_device_names (POS: device registry)

[OUTPUT]
- DeviceEmulator: runtime CDP mobile device emulation (per-page, idempotent)

[POS]
Applies mobile-device simulation to a live page via CDP without recreating
the browser context: ``Emulation.setDeviceMetricsOverride`` (layout viewport +
device pixel ratio + mobile flag), ``Network.setUserAgentOverride`` (mobile UA)
and ``Emulation.setTouchEmulationEnabled`` (touch events). ``desktop`` restores
the browser's native desktop behavior by clearing all three overrides.

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
    """Runtime CDP device emulation for the active browser page."""

    def __init__(self, registry: DeviceRegistry | None = None) -> None:
        self._registry: DeviceRegistry = registry or _BuiltinRegistry()
        self._cdp_session: CDPSession | None = None
        self._bound_page: Page | None = None
        self._active_device: str | None = None

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
            cdp = await self._ensure_cdp(page)
            await self._apply(cdp, profile)
            self._active_device = device
            return (
                f"Emulated '{device}' ({profile.viewport[0]}x{profile.viewport[1]} "
                f"@ {profile.device_scale_factor}x, mobile UA + touch). "
                "Re-navigate the page to apply the new mobile layout."
            )
        except Exception as exc:
            logger.warning("DeviceEmulator: emulation failed for '%s': %s", device, exc)
            self._cdp_session = None
            self._bound_page = None
            return f"Device emulation failed: {exc}"

    async def reset(self, page: Page) -> str:
        """Restore the browser's native desktop behavior on the page.

        Returns:
            Confirmation message.

        """
        try:
            cdp = await self._ensure_cdp(page)
            await cdp.send("Emulation.clearDeviceMetricsOverride")
            # CDP has no Network.clearUserAgentOverride; an empty userAgent
            # restores the browser's default UA (verified on real Chromium).
            await cdp.send("Network.setUserAgentOverride", {"userAgent": ""})
            await cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
            self._active_device = None
            return "Restored desktop viewport (cleared device emulation)."
        except Exception as exc:
            logger.warning("DeviceEmulator: reset failed: %s", exc)
            self._cdp_session = None
            self._bound_page = None
            return f"Failed to restore desktop viewport: {exc}"

    def list_devices(self) -> list[str]:
        """Return the sorted list of emulatable device names."""
        return self._registry.list_names()

    async def detach(self) -> None:
        """Release the CDP session (called when the owning session closes)."""
        await self._detach()

    async def _ensure_cdp(self, page: Page) -> CDPSession:
        """Return a CDP session bound to the page, re-creating if stale."""
        if self._cdp_session is not None and self._bound_page is page:
            return self._cdp_session
        await self._detach()
        cdp = await page.context.new_cdp_session(page)
        self._cdp_session = cdp
        self._bound_page = page
        return cdp

    async def _detach(self) -> None:
        if self._cdp_session is not None:
            with contextlib.suppress(Exception):
                await self._cdp_session.detach()
        self._cdp_session = None
        self._bound_page = None

    @staticmethod
    async def _apply(cdp: CDPSession, profile: EmulationConfig) -> None:
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
