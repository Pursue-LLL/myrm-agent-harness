"""Tests for runtime CDP device emulation (DeviceEmulator)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
    def __init__(self, cdp: FakeCDP) -> None:
        self.context = FakeContext(cdp)


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
    async def test_emulate_success_applies_three_overrides(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
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
    async def test_emulate_unknown_device_lists_available(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
        """Unknown device returns available list and does not touch CDP."""
        emulator = DeviceEmulator(_registry(profile=None))

        result = await emulator.emulate("Nokia 3310", page)  # type: ignore[arg-type]

        assert "Unknown device 'Nokia 3310'" in result
        assert "iPhone 15 Pro" in result and "Pixel 8" in result
        assert emulator.active_device is None
        assert cdp.sent == []

    @pytest.mark.asyncio
    async def test_emulate_failure_is_contained(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
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
    async def test_reset_clears_overrides(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
        """Reset clears all three overrides and resets active device."""
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
        assert cdp.sent[1][1] == {"userAgent": ""}
        assert cdp.sent[2][1]["enabled"] is False

    @pytest.mark.asyncio
    async def test_emulate_desktop_aliases_reset(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
        """'desktop'/'default'/'pc' all route to reset."""
        emulator = DeviceEmulator(_registry())

        for alias in ("desktop", "default", "pc"):
            result = await emulator.emulate(alias, page)  # type: ignore[arg-type]
            assert "Restored desktop viewport" in result

    @pytest.mark.asyncio
    async def test_reset_failure_is_contained(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
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
    async def test_cdp_session_reused_for_same_page(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
        """CDP session is created once and reused for the same page."""
        emulator = DeviceEmulator(_registry())

        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]
        await emulator.emulate("Pixel 8", page)  # type: ignore[arg-type]

        assert page.context.new_cdp_session_calls == 1

    @pytest.mark.asyncio
    async def test_detach_releases_cdp_session(
        self, cdp: FakeCDP, page: FakePage
    ) -> None:
        """detach() detaches the CDP session (called on session close)."""
        emulator = DeviceEmulator(_registry())
        await emulator.emulate("iPhone 15 Pro", page)  # type: ignore[arg-type]

        await emulator.detach()

        assert cdp.detach_calls == 1
        assert emulator.active_device == "iPhone 15 Pro"

    @pytest.mark.asyncio
    async def test_list_devices_delegates_to_registry(self) -> None:
        """list_devices returns the registry's sorted names."""
        emulator = DeviceEmulator(_registry())

        assert emulator.list_devices() == ["iPhone 15 Pro", "Pixel 8"]
