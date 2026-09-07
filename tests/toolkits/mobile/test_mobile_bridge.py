"""Tests for mobile wireless debugging and Android automation toolkit.

[INPUT]
- toolkits.mobile (MobileBridge, MobileDeviceManager, MobileInspector, MobileInputController, MobileAppManager, MobileSafetyBarrier)

[OUTPUT]
- Unit tests verifying device management, XML parsing, coordinate normalization, safety gating, and LangChain tools
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from myrm_agent_harness.toolkits.mobile.app_manager import MobileAppManager
from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.input_controller import MobileInputController
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.mobile_agent_tools import create_mobile_tools
from myrm_agent_harness.toolkits.mobile.mobile_bridge import MobileBridge
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyBarrier
from myrm_agent_harness.toolkits.mobile.types import (
    DeviceConnectionMode,
    DeviceState,
    ElementBounds,
    KeyCode,
    MobileDevice,
    MobileHierarchy,
    MobileNode,
    Point2D,
)


class TestMobileSafetyBarrier(unittest.TestCase):
    def setUp(self) -> None:
        self.barrier = MobileSafetyBarrier(strict_mode=True)

    def test_safe_screen_evaluation(self) -> None:
        hierarchy = MobileHierarchy(
            screen_width=1080,
            screen_height=2400,
            root_nodes=[
                MobileNode(
                    text="Welcome to Myrm Agent",
                    clickable=True,
                    bounds=ElementBounds(100, 200, 500, 300),
                )
            ],
        )
        verdict = self.barrier.evaluate_hierarchy(hierarchy)
        self.assertFalse(verdict.is_sensitive)
        self.assertEqual(verdict.risk_level, "LOW")
        self.assertFalse(verdict.requires_confirmation)

    def test_critical_password_screen_evaluation(self) -> None:
        hierarchy = MobileHierarchy(
            screen_width=1080,
            screen_height=2400,
            root_nodes=[
                MobileNode(
                    text="请输入支付密码",
                    password=True,
                    clickable=True,
                    bounds=ElementBounds(100, 500, 980, 600),
                )
            ],
        )
        verdict = self.barrier.evaluate_hierarchy(hierarchy)
        self.assertTrue(verdict.is_sensitive)
        self.assertEqual(verdict.risk_level, "CRITICAL")
        self.assertTrue(verdict.requires_confirmation)

    def test_sensitive_action_evaluation(self) -> None:
        verdict = self.barrier.evaluate_action(
            action="tap",
            target_text="确认微信支付",
        )
        self.assertTrue(verdict.is_sensitive)
        self.assertEqual(verdict.risk_level, "CRITICAL")


class TestMobileHierarchyAndBounds(unittest.TestCase):
    def test_bounds_calculation(self) -> None:
        bounds = ElementBounds(left=100, top=200, right=500, bottom=400)
        self.assertEqual(bounds.width, 400)
        self.assertEqual(bounds.height, 200)
        self.assertEqual(bounds.center, Point2D(300, 300))

        norm = bounds.to_normalized_center(screen_width=1000, screen_height=2000)
        self.assertEqual(norm, (0.3, 0.15))

    def test_hierarchy_search(self) -> None:
        root = MobileNode(
            text="Root",
            children=[
                MobileNode(
                    text="Settings",
                    resource_id="com.android.settings:id/title",
                    clickable=True,
                    bounds=ElementBounds(0, 100, 1080, 200),
                ),
                MobileNode(
                    text="Display",
                    resource_id="com.android.settings:id/display",
                    clickable=False,
                    bounds=ElementBounds(0, 200, 1080, 300),
                ),
            ],
        )
        hierarchy = MobileHierarchy(root_nodes=[root])
        interactive = hierarchy.find_all_interactive()
        self.assertEqual(len(interactive), 1)
        self.assertEqual(interactive[0].text, "Settings")

        matches = hierarchy.find_by_text("settings")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].resource_id, "com.android.settings:id/title")


class TestMobileBridgeEngine(unittest.IsolatedAsyncioTestCase):
    async def test_device_discovery(self) -> None:
        dev_mgr = MobileDeviceManager()
        raw_output = """List of devices attached
192.168.1.105:5555     device product:redfin model:Pixel_5 device:redfin transport_id:1
emulator-5554          device product:sdk_gphone64_arm64 model:sdk_gphone64_arm64 device:emulator transport_id:2
"""
        with patch.object(dev_mgr, "_run_adb", new_callable=AsyncMock) as mock_adb:
            mock_adb.return_value = (0, raw_output, "")
            devices = await dev_mgr.list_devices()
            self.assertEqual(len(devices), 2)
            self.assertTrue(devices[0].is_wireless)
            self.assertEqual(devices[0].ip_address, "192.168.1.105")
            self.assertEqual(devices[0].port, 5555)
            self.assertFalse(devices[1].is_wireless)

    async def test_touch_and_input(self) -> None:
        bridge = MobileBridge()
        active_dev = MobileDevice(
            serial="192.168.1.105:5555",
            state=DeviceState.ONLINE,
            mode=DeviceConnectionMode.WIRELESS,
        )

        with patch.object(bridge.device_manager, "ensure_active_device", new_callable=AsyncMock) as mock_dev, \
             patch.object(bridge.device_manager, "_run_adb", new_callable=AsyncMock) as mock_adb:
            mock_dev.return_value = active_dev
            mock_adb.return_value = (0, "Success", "")

            # Test tap
            res = await bridge.tap(x=100, y=200)
            self.assertTrue(res.success)
            self.assertEqual(res.data["x"], 100)
            self.assertEqual(res.data["y"], 200)

            # Test swipe
            res_swipe = await bridge.swipe(x1=100, y1=500, x2=100, y2=100)
            self.assertTrue(res_swipe.success)

            # Test key
            res_key = await bridge.press_key(KeyCode.HOME)
            self.assertTrue(res_key.success)

    async def test_safety_blocked_action(self) -> None:
        bridge = MobileBridge(strict_safety=True)
        res = await bridge.type_text("确认支付密码123456")
        self.assertFalse(res.success)
        self.assertEqual(res.exit_code, -2)
        self.assertIn("MobileSafetyBarrier", res.message)

    async def test_langchain_tools_creation(self) -> None:
        tools = create_mobile_tools()
        self.assertEqual(len(tools), 5)
        names = [getattr(t, "name", "") for t in tools]
        self.assertIn("mobile_device_tool", names)
        self.assertIn("mobile_snapshot_tool", names)
        self.assertIn("mobile_touch_tool", names)
        self.assertIn("mobile_input_tool", names)
        self.assertIn("mobile_app_tool", names)


if __name__ == "__main__":
    unittest.main()
