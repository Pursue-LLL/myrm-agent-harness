"""Tests for runtime CDP device emulation (DeviceEmulator)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig
from myrm_agent_harness.toolkits.browser.session.device_emulator import DeviceEmulator

PROFILE = EmulationConfig(
    user_agent="Mozilla/5.0 (iPhone) TestUA",
    viewport=(393, 659),
    device_scale_factor=3.0,
    is_mobile=True,
    has_touch=True,
)


class FakeCDP:
    """Minimal CDPSession double recording send() calls."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.detach_calls = 0

    async def send(self, method: str, params: dict | None = None) -> object:
        self.sent.append((method, params or {}))
        return {}

    async def detach(self) -> None:
        self.detach_calls += 1


class FakeContext:
    def __init__(self, cdp: FakeCDP) -> None:
        self._cdp = cdp
        self.new_cdp_session_calls = 0

    async def new_cdp_session(self, page: object) -> FakeCDP:
        self.new_cdp_session_calls += 1
        return self._cdp


class FakePage:
    def __init__(self, cdp: FakeCDP, ua: str = "Mozilla/5.0 (Macintosh) DefaultUA") -> None:
        self.context = FakeContext(cdp)
        self._ua = ua
        self.closed = False

    async def evaluate(self, expression: str) -> str:
        return self._ua

    def is_closed(self) -> bool:
        return self.closed


class FakeRegistry:
    def __init__(self, resolve: MagicMock, names: list[str]) -> None:
        self._resolve = resolve
        self._names = names

    def resolve(self, device: str) -> EmulationConfig | None:
        return self._resolve(device)

    def list_names(self) -> list[str]:
        return self._names


@pytest.fixture
def cdp() -> FakeCDP:
    return FakeCDP()


@pytest.fixture
def page(cdp: FakeCDP) -> FakePage:
    return FakePage(cdp)


def _registry(profile: EmulationConfig | None = PROFILE) -> FakeRegistry:
    return FakeRegistry(MagicMock(return_value=profile), ["iPhone 15 Pro", "Pixel 8"])


class TestEmulate:
    @pytest.mark.asyncio
    async def test_emulate_success_applies_three_overrides(self, cdp: FakeCDP, page: FakePage) -> None:
        """Success applies device metrics + UA + touch overrides."""
        emulator = DeviceEmulator(_registry())

        result = await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]

        assert "Emulated 'iPhone 15 Pro'" in result
        assert "393x659" in result
        assert emulator.active_device == "iPhone 15 Pro"
        methods = [method for method, _ in cdp.sent]
        assert methods == [
            "Emulation.setDeviceMetricsOverride",
            "Network.setUserAgentOverride",
            "Emulation.setTouchEmulationEnabled",
        ]
        metrics = cdp.sent[0][1]
        assert metrics["width"] == 393
        assert metrics["height"] == 659
        assert metrics["deviceScaleFactor"] == 3.0
        assert metrics["mobile"] is True
        assert cdp.sent[1][1]["userAgent"] == "Mozilla/5.0 (iPhone) TestUA"
        assert cdp.sent[2][1]["enabled"] is True

    @pytest.mark.asyncio
    async def test_emulate_unknown_device_lists_available(self, cdp: FakeCDP, page: FakePage) -> None:
        """Unknown device returns available list and does not touch CDP."""
        emulator = DeviceEmulator(_registry(profile=None))

        result = await emulator.emulate("Nokia 3310", page)  # type: ignore[arg-type]

        assert "Unknown device 'Nokia 3310'" in result
        assert "iPhone 15 Pro" in result and "Pixel 8" in result
        assert emulator.active_device is None
        assert cdp.sent == []

    @pytest.mark.asyncio
    async def test_emulate_failure_is_contained(self, cdp: FakeCDP, page: FakePage) -> None:
        """CDP failure returns honest error message instead of raising."""
        emulator = DeviceEmulator(_registry())

        async def boom(method: str, params: dict | None = None) -> object:
            raise RuntimeError("CDP down")

        cdp.send = boom  # type: ignore[method-assign]

        result = await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]

        assert result.startswith("Device emulation failed:")
        assert "CDP down" in result
        assert emulator.active_device is None


class TestReset:
    @pytest.mark.asyncio
    async def test_reset_clears_overrides(self, cdp: FakeCDP, page: FakePage) -> None:
        """Reset clears all three overrides and restores the baseline UA."""
        emulator = DeviceEmulator(_registry())
        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        cdp.sent.clear()

        result = await emulator.reset(page)  # type: ignore[arg-type]

        assert "Restored desktop viewport" in result
        assert emulator.active_device is None
        methods = [method for method, _ in cdp.sent]
        assert methods == [
            "Emulation.clearDeviceMetricsOverride",
            "Network.setUserAgentOverride",
            "Emulation.setTouchEmulationEnabled",
        ]
        # Baseline UA captured before emulation is restored (not empty string).
        assert cdp.sent[1][1] == {"userAgent": "Mozilla/5.0 (Macintosh) DefaultUA"}
        assert cdp.sent[2][1]["enabled"] is False

    @pytest.mark.asyncio
    async def test_reset_without_prior_emulation_preserves_ua(self, cdp: FakeCDP, page: FakePage) -> None:
        """Reset with no prior emulation leaves the context UA untouched."""
        emulator = DeviceEmulator(_registry())

        result = await emulator.reset(page)  # type: ignore[arg-type]

        assert "Restored desktop viewport" in result
        methods = [method for method, _ in cdp.sent]
        assert methods == [
            "Emulation.clearDeviceMetricsOverride",
            "Emulation.setTouchEmulationEnabled",
        ]

    @pytest.mark.asyncio
    async def test_emulate_desktop_aliases_reset(self, cdp: FakeCDP, page: FakePage) -> None:
        """'desktop'/'default'/'pc' all route to reset."""
        emulator = DeviceEmulator(_registry())

        for alias in ("desktop", "default", "pc"):
            result = await emulator.emulate(alias, page)  # type: ignore[arg-type]
            assert "Restored desktop viewport" in result

    @pytest.mark.asyncio
    async def test_reset_failure_is_contained(self, cdp: FakeCDP, page: FakePage) -> None:
        """Reset failure returns honest error message."""
        emulator = DeviceEmulator(_registry())

        async def boom(method: str, params: dict | None = None) -> object:
            raise RuntimeError("CDP down")

        cdp.send = boom  # type: ignore[method-assign]

        result = await emulator.reset(page)  # type: ignore[arg-type]

        assert result.startswith("Failed to restore desktop viewport:")
        assert "CDP down" in result


class TestCdpSessionLifecycle:
    @pytest.mark.asyncio
    async def test_cdp_session_reused_for_same_page(self, cdp: FakeCDP, page: FakePage) -> None:
        """CDP session is created once and reused for the same page."""
        emulator = DeviceEmulator(_registry())

        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        await emulator.emulate("Pixel 8", page)  # type: ignore[arg-type]

        assert page.context.new_cdp_session_calls == 1

    @pytest.mark.asyncio
    async def test_detach_releases_cdp_session(self, cdp: FakeCDP, page: FakePage) -> None:
        """detach() detaches the CDP session and clears session state."""
        emulator = DeviceEmulator(_registry())
        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]

        await emulator.detach()

        assert cdp.detach_calls == 1
        assert emulator.active_device is None

    @pytest.mark.asyncio
    async def test_list_devices_delegates_to_registry(self) -> None:
        """list_devices returns the registry's sorted names."""
        emulator = DeviceEmulator(_registry())

        assert emulator.list_devices() == ["iPhone 15 Pro", "Pixel 8"]


class TestSessionConsistency:
    @pytest.mark.asyncio
    async def test_reset_clears_every_injected_page(self, cdp: FakeCDP, page: FakePage) -> None:
        """Reset clears overrides on ALL emulated pages, not just the active one."""
        page_b = FakePage(cdp, ua="Mozilla/5.0 (Pixel) PageBUA")
        emulator = DeviceEmulator(_registry())

        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        await emulator.emulate("Pixel 8", page_b)  # type: ignore[arg-type]
        cdp.sent.clear()

        result = await emulator.reset(page)  # type: ignore[arg-type]

        assert "Restored desktop viewport" in result
        assert emulator.active_device is None
        # Each page gets its own clear triple (2 pages = 6 commands).
        methods = [method for method, _ in cdp.sent]
        assert methods == [
            "Emulation.clearDeviceMetricsOverride",
            "Network.setUserAgentOverride",
            "Emulation.setTouchEmulationEnabled",
            "Emulation.clearDeviceMetricsOverride",
            "Network.setUserAgentOverride",
            "Emulation.setTouchEmulationEnabled",
        ]

    @pytest.mark.asyncio
    async def test_reset_skips_closed_page(self, cdp: FakeCDP, page: FakePage) -> None:
        """Reset ignores a page that was closed, without raising."""
        page_b = FakePage(cdp, ua="Mozilla/5.0 (Pixel) PageBUA")
        emulator = DeviceEmulator(_registry())
        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        await emulator.emulate("Pixel 8", page_b)  # type: ignore[arg-type]
        page_b.closed = True

        result = await emulator.reset(page)  # type: ignore[arg-type]

        assert "Restored desktop viewport" in result
        # Only the live page receives clear commands.
        methods = [method for method, _ in cdp.sent]
        assert methods.count("Emulation.clearDeviceMetricsOverride") == 1

    @pytest.mark.asyncio
    async def test_reapply_applies_active_profile_to_new_page(self, cdp: FakeCDP, page: FakePage) -> None:
        """reapply() injects the active device profile into a new tab."""
        new_page = FakePage(cdp, ua="Mozilla/5.0 (Blank) NewTabUA")
        emulator = DeviceEmulator(_registry())
        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        cdp.sent.clear()

        await emulator.reapply(new_page)  # type: ignore[arg-type]

        methods = [method for method, _ in cdp.sent]
        assert "Emulation.setDeviceMetricsOverride" in methods
        assert cdp.sent[0][1]["width"] == 393
        # Session state still reflects the active device.
        assert emulator.active_device == "iPhone 15 Pro"

    @pytest.mark.asyncio
    async def test_reapply_noop_when_no_active_device(self, cdp: FakeCDP, page: FakePage) -> None:
        """reapply() is a no-op when no device is currently emulated."""
        emulator = DeviceEmulator(_registry())

        await emulator.reapply(page)  # type: ignore[arg-type]

        assert cdp.sent == []

    @pytest.mark.asyncio
    async def test_forget_page_clears_single_page_state(self, cdp: FakeCDP, page: FakePage) -> None:
        """forget_page() clears one page's emulation and drops it from tracking."""
        page_b = FakePage(cdp, ua="Mozilla/5.0 (Pixel) PageBUA")
        emulator = DeviceEmulator(_registry())
        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        await emulator.emulate("Pixel 8", page_b)  # type: ignore[arg-type]
        cdp.sent.clear()

        await emulator.forget_page(page_b)  # type: ignore[arg-type]

        methods = [method for method, _ in cdp.sent]
        assert methods.count("Emulation.clearDeviceMetricsOverride") == 1
        # Remaining tracked page survives; reset clears only the surviving page.
        cdp.sent.clear()
        await emulator.reset(page)  # type: ignore[arg-type]
        assert cdp.sent.count(("Emulation.clearDeviceMetricsOverride", {})) == 1

    @pytest.mark.asyncio
    async def test_detach_resets_tracking_and_state(self, cdp: FakeCDP, page: FakePage) -> None:
        """detach() drops tracking, CDP sessions, and active device/profile."""
        page_b = FakePage(cdp, ua="Mozilla/5.0 (Pixel) PageBUA")
        emulator = DeviceEmulator(_registry())
        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        await emulator.emulate("Pixel 8", page_b)  # type: ignore[arg-type]

        await emulator.detach()

        assert emulator.active_device is None
        # Tracking was reset: reset clears only the given page, and state stays
        # desktop afterwards.
        cdp.sent.clear()
        result = await emulator.reset(page)  # type: ignore[arg-type]
        assert "Restored desktop viewport" in result
        methods = [method for method, _ in cdp.sent]
        assert methods.count("Emulation.clearDeviceMetricsOverride") == 1
        assert emulator.active_device is None
