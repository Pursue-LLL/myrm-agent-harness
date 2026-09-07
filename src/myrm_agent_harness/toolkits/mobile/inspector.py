"""Mobile UI inspector and Accessibility tree extractor.

[INPUT]
- types::UIElementNode, MobileScreenshotResult, MobileUIDumpResult, DeviceInfo (POS: shared mobile types)
- protocols::MobileInspectorProtocol (POS: inspection contract)
- safety::MobileSafetyGuard (POS: UI sensitive barrier)

[OUTPUT]
- MobileInspector: Implementation of screencap and accessibility XML hierarchy analysis

[POS]
Vision and accessibility semantic perception engine for mobile screens.
"""

from __future__ import annotations

import base64
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyGuard
from myrm_agent_harness.toolkits.mobile.types import (
    MobileScreenshotResult,
    MobileUIDumpResult,
    UIElementNode,
)

logger = logging.getLogger(__name__)

_BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_ACTIVITY_PATTERN = re.compile(r"mResumedActivity:\s*ActivityRecord\{[^\s]+\s+[^\s]+\s+([^\s/]+)/([^\s]+)")
_TOP_FOCUSED_PATTERN = re.compile(r"mCurrentFocus=Window\{[^\s]+\s+[^\s]+\s+([^\s/]+)/([^\s\}]+)")


class MobileInspector:
    """Extracts screenshots and parses UIAutomator accessibility XML trees."""

    def __init__(
        self,
        device_manager: MobileDeviceManager,
        safety_guard: MobileSafetyGuard | None = None,
    ) -> None:
        self._device_manager = device_manager
        self._safety_guard = safety_guard or MobileSafetyGuard()

    async def screencap(
        self, serial: str | None = None, quality: int = 80
    ) -> MobileScreenshotResult:
        """Capture screen as raw PNG bytes with fallback."""
        code, stdout, stderr = await self._device_manager.execute_adb_command(
            ["exec-out", "screencap", "-p"], serial=serial, timeout_s=10.0
        )
        if code != 0 or not stdout:
            # Fallback to file-based capture
            await self._device_manager.execute_adb_command(
                ["shell", "screencap", "-p", "/data/local/tmp/myrm_cap.png"], serial=serial
            )
            code, stdout, _ = await self._device_manager.execute_adb_command(
                ["exec-out", "cat", "/data/local/tmp/myrm_cap.png"], serial=serial
            )

        info = await self._device_manager.get_device_info(serial)
        w = info.screen_width if info else 1080
        h = info.screen_height if info else 2400

        b64 = base64.b64encode(stdout).decode("utf-8") if stdout else ""
        return MobileScreenshotResult(
            image_bytes=stdout,
            format="png",
            width=w,
            height=h,
            base64_data=b64,
        )

    async def get_top_activity(self, serial: str | None = None) -> tuple[str, str]:
        """Detect current foreground (package, activity)."""
        code, stdout, _ = await self._device_manager.execute_adb_command(
            ["shell", "dumpsys", "activity", "activities"], serial=serial, timeout_s=5.0
        )
        text = stdout.decode("utf-8", errors="ignore")
        match = _ACTIVITY_PATTERN.search(text)
        if match:
            return match.group(1), match.group(2)

        # Fallback to window focus
        code_win, stdout_win, _ = await self._device_manager.execute_adb_command(
            ["shell", "dumpsys", "window", "windows"], serial=serial, timeout_s=5.0
        )
        text_win = stdout_win.decode("utf-8", errors="ignore")
        match_win = _TOP_FOCUSED_PATTERN.search(text_win)
        if match_win:
            return match_win.group(1), match_win.group(2)

        return "", ""

    async def dump_ui_hierarchy(
        self, serial: str | None = None, timeout_s: float = 6.0
    ) -> MobileUIDumpResult:
        """Extract XML view tree and calculate normalized coordinates for clickable elements."""
        # 1. Dump UI to local temp file on device
        dump_code, _, _ = await self._device_manager.execute_adb_command(
            ["shell", "uiautomator", "dump", "/data/local/tmp/ui_dump.xml"],
            serial=serial,
            timeout_s=timeout_s,
        )

        xml_data = ""
        if dump_code == 0:
            read_code, stdout, _ = await self._device_manager.execute_adb_command(
                ["shell", "cat", "/data/local/tmp/ui_dump.xml"],
                serial=serial,
                timeout_s=5.0,
            )
            if read_code == 0:
                xml_data = stdout.decode("utf-8", errors="ignore").strip()

        pkg, act = await self.get_top_activity(serial=serial)
        info = await self._device_manager.get_device_info(serial=serial)
        w = float(info.screen_width) if info else 1080.0
        h = float(info.screen_height) if info else 2400.0

        if not xml_data:
            return MobileUIDumpResult(
                root=None,
                clickable_elements=[],
                raw_xml="",
                top_activity=act,
                top_package=pkg,
            )

        clickable_nodes: list[UIElementNode] = []
        try:
            root_elem = ET.fromstring(xml_data)
            root_node = self._parse_node(root_elem, 0, w, h, clickable_nodes)
        except Exception as exc:
            logger.warning("Failed to parse uiautomator XML: %s", exc)
            return MobileUIDumpResult(
                root=None,
                clickable_elements=[],
                raw_xml=xml_data,
                top_activity=act,
                top_package=pkg,
            )

        return MobileUIDumpResult(
            root=root_node,
            clickable_elements=clickable_nodes,
            raw_xml=xml_data,
            top_activity=act,
            top_package=pkg,
        )

    def _parse_node(
        self,
        elem: ET.Element,
        index: int,
        screen_w: float,
        screen_h: float,
        clickable_accumulator: list[UIElementNode],
    ) -> UIElementNode:
        attrib = elem.attrib
        bounds_str = attrib.get("bounds", "[0,0][0,0]")
        bounds = (0, 0, 0, 0)
        cx, cy = 0, 0
        norm_x, norm_y = 0.0, 0.0

        m = _BOUNDS_PATTERN.match(bounds_str)
        if m:
            l, t, r, b = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
            bounds = (l, t, r, b)
            cx = (l + r) // 2
            cy = (t + b) // 2
            norm_x = min(max(cx / max(screen_w, 1.0), 0.0), 1.0)
            norm_y = min(max(cy / max(screen_h, 1.0), 0.0), 1.0)

        clickable = attrib.get("clickable") == "true"
        password = attrib.get("password") == "true"
        scrollable = attrib.get("scrollable") == "true"

        node = UIElementNode(
            index=index,
            text=attrib.get("text", ""),
            resource_id=attrib.get("resource-id", ""),
            class_name=attrib.get("class", ""),
            package=attrib.get("package", ""),
            content_desc=attrib.get("content-desc", ""),
            checkable=attrib.get("checkable") == "true",
            checked=attrib.get("checked") == "true",
            clickable=clickable,
            enabled=attrib.get("enabled") == "true",
            focusable=attrib.get("focusable") == "true",
            focused=attrib.get("focused") == "true",
            scrollable=scrollable,
            long_clickable=attrib.get("long-clickable") == "true",
            password=password,
            selected=attrib.get("selected") == "true",
            bounds=bounds,
            center_x=cx,
            center_y=cy,
            norm_x=norm_x,
            norm_y=norm_y,
            children=[],
        )

        if (clickable or scrollable or node.text or node.content_desc) and (bounds[2] > bounds[0] and bounds[3] > bounds[1]):
            clickable_accumulator.append(node)

        for child_idx, child_elem in enumerate(elem):
            node.children.append(
                self._parse_node(child_elem, child_idx, screen_w, screen_h, clickable_accumulator)
            )

        return node
