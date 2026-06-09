"""Unit tests for Extension Bridge Protocol and LaunchMode.EXTENSION routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import (
    BrowserInstance,
    BrowserLauncher,
)
from myrm_agent_harness.toolkits.browser.pool.config import LaunchMode
from myrm_agent_harness.toolkits.browser.pool.extension_bridge import (
    ExtensionBridge,
    ExtensionBridgeNotAvailable,
    ExtensionStatus,
    ExtensionTab,
)


class MockExtensionBridge:
    """Mock implementation of ExtensionBridge Protocol."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self._should_fail = should_fail
        self._connected = True
        self.connect_called = False
        self.connect_domain_called = False

    async def connect(self, *, timeout: float = 10.0) -> BrowserInstance:
        self.connect_called = True
        if self._should_fail:
            raise ExtensionBridgeNotAvailable("Extension not connected")
        browser = MagicMock()
        browser.contexts = []
        return BrowserInstance(browser=browser, engine="chromium-patchright", is_managed=False)

    async def connect_to_domain(self, domain: str, *, timeout: float = 10.0) -> BrowserInstance:
        self.connect_domain_called = True
        browser = MagicMock()
        browser.contexts = []
        return BrowserInstance(browser=browser, engine="chromium-patchright", is_managed=False)

    async def get_status(self) -> ExtensionStatus:
        return ExtensionStatus(connected=self._connected)

    def is_connected(self) -> bool:
        return self._connected

    async def list_tabs(self) -> list[ExtensionTab]:
        return [
            ExtensionTab(tab_id=1, url="https://github.com", title="GitHub", domain="github.com", active=True),
        ]

    async def disconnect(self) -> None:
        self._connected = False


class TestExtensionBridgeProtocol:
    """Test that ExtensionBridge Protocol works with runtime_checkable."""

    def test_mock_satisfies_protocol(self) -> None:
        bridge = MockExtensionBridge()
        assert isinstance(bridge, ExtensionBridge)

    def test_non_bridge_does_not_satisfy(self) -> None:
        assert not isinstance(object(), ExtensionBridge)

    def test_dict_does_not_satisfy(self) -> None:
        assert not isinstance({}, ExtensionBridge)


class TestExtensionTab:
    def test_frozen_dataclass(self) -> None:
        tab = ExtensionTab(tab_id=1, url="https://example.com", title="Test", domain="example.com")
        assert tab.tab_id == 1
        assert tab.domain == "example.com"
        assert tab.active is False

    def test_active_tab(self) -> None:
        tab = ExtensionTab(tab_id=2, url="https://github.com", title="GH", domain="github.com", active=True)
        assert tab.active is True


class TestExtensionStatus:
    def test_default_values(self) -> None:
        status = ExtensionStatus()
        assert status.connected is False
        assert status.extension_version == ""
        assert status.authorized_domains == []
        assert status.available_tabs == []

    def test_populated_status(self) -> None:
        tab = ExtensionTab(tab_id=1, url="https://x.com", title="X", domain="x.com")
        status = ExtensionStatus(
            connected=True,
            extension_version="1.0.0",
            browser_name="Chrome",
            authorized_domains=["x.com"],
            available_tabs=[tab],
        )
        assert status.connected is True
        assert len(status.available_tabs) == 1


class TestLaunchModeExtension:
    """Test BrowserLauncher routing to EXTENSION mode."""

    @pytest.mark.asyncio
    async def test_extension_mode_calls_bridge_connect(self) -> None:
        bridge = MockExtensionBridge()
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.EXTENSION,
            extension_bridge=bridge,
        )
        instance = await launcher.create_browser()
        assert bridge.connect_called
        assert instance.is_managed is False

    @pytest.mark.asyncio
    async def test_extension_mode_no_bridge_raises(self) -> None:
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.EXTENSION,
            extension_bridge=None,
        )
        with pytest.raises(BrowserLaunchError, match="extension_bridge is required"):
            await launcher.create_browser()

    @pytest.mark.asyncio
    async def test_extension_mode_bridge_failure(self) -> None:
        bridge = MockExtensionBridge(should_fail=True)
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.EXTENSION,
            extension_bridge=bridge,
        )
        with pytest.raises(BrowserLaunchError, match="Extension not connected"):
            await launcher.create_browser()

    @pytest.mark.asyncio
    async def test_extension_mode_invalid_bridge_type(self) -> None:
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.EXTENSION,
            extension_bridge="not_a_bridge",
        )
        with pytest.raises(BrowserLaunchError, match="must implement ExtensionBridge Protocol"):
            await launcher.create_browser()


class TestExtensionBridgeNotAvailable:
    def test_default_message(self) -> None:
        exc = ExtensionBridgeNotAvailable()
        assert "not connected" in str(exc)

    def test_custom_message(self) -> None:
        exc = ExtensionBridgeNotAvailable("Custom error")
        assert str(exc) == "Custom error"
