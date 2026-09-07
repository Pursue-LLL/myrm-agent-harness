"""Mobile Perception and Screen/Accessibility Inspection Engine.

[INPUT]
- myrm_agent_harness.toolkits.mobile_adb.executor::ADBExecutor
- myrm_agent_harness.toolkits.mobile_adb.types::MobileScreenInfo, MobileUIElement

[OUTPUT]
- MobilePerceptionEngine: Captures screenshots (base64) and parses UIAutomator XML into semantic UI elements.

[POS]
Extracts visual and accessibility structure from Android devices.
"""

from __future__ import annotations

import base64
import logging
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.mobile_adb.executor import ADBExecutor
    from myrm_agent_harness.toolkits.mobile_adb.types import (
        MobileScreenInfo,
        MobileUIElement,
    )

logger = logging.getLogger(__name__)


class MobilePerceptionEngine:
    """Perception engine for mobile screen capture and UI hierarchy parsing."""

    def __init__(self, executor: ADBExecutor) -> None:
        self.executor = executor

    async def get_screen_info(self, device_id: str) -> MobileScreenInfo | None:
        """Fetch screen resolution and DPI via wm size and wm density."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileScreenInfo

        # 1. Size
        rc, out, _ = await self.executor.run_adb(["shell", "wm", "size"], target_device=device_id)
        if rc != 0 or not out:
            return None

        # Example: Physical size: 1080x2400
        size_match = re.search(r"(\d+)\s*x\s*(\d+)", out)
        if not size_match:
            return None
        width, height = int(size_match.group(1)), int(size_match.group(2))

        # 2. Density
        density = 420
        rc_d, out_d, _ = await self.executor.run_adb(["shell", "wm", "density"], target_device=device_id)
        if rc_d == 0 and out_d:
            density_match = re.search(r"(\d+)", out_d)
            if density_match:
                density = int(density_match.group(1))

        return MobileScreenInfo(width=width, height=height, density_dpi=density)

    async def capture_screenshot_base64(self, device_id: str) -> str | None:
        """Capture screenshot via adb exec-out screencap -p and return base64 encoded PNG."""
        adb_bin = self.executor.resolve_adb()
        import asyncio

        cmd = [adb_bin]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["exec-out", "screencap", "-p"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            raw_png, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.executor.config.command_timeout_seconds,
            )
            if proc.returncode == 0 and raw_png.startswith(b"\x89PNG\r\n\x1a\n"):
                return base64.b64encode(raw_png).decode("ascii")
            return None
        except Exception as err:
            logger.warning("Failed to capture screenshot for device %s: %s", device_id, err)
            return None

    async def dump_ui_hierarchy(self, device_id: str) -> list[MobileUIElement]:
        """Dump UIAutomator XML and parse into structured MobileUIElement nodes."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileUIElement

        # 1. Dump to /data/local/tmp/uidump.xml
        dump_path = "/data/local/tmp/uidump.xml"
        rc, _, err = await self.executor.run_adb(
            ["shell", "uiautomator", "dump", dump_path],
            target_device=device_id,
        )
        if rc != 0:
            logger.warning("uiautomator dump failed on %s: %s", device_id, err)
            return []

        # 2. Read dump file
        rc_cat, xml_content, _ = await self.executor.run_adb(
            ["shell", "cat", dump_path],
            target_device=device_id,
        )
        if rc_cat != 0 or not xml_content:
            return []

        # Clean up dump file in background
        asyncio.create_task(
            self.executor.run_adb(["shell", "rm", "-f", dump_path], target_device=device_id)
        )

        elements: list[MobileUIElement] = []
        try:
            root = ET.fromstring(xml_content)
            idx = 1
            for node in root.iter("node"):
                bounds_str = node.attrib.get("bounds", "")
                # Example: [0,0][1080,2400]
                m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
                if not m:
                    continue

                left, top, right, bottom = (
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    int(m.group(4)),
                )
                if right <= left or bottom <= top:
                    continue

                text = node.attrib.get("text", "").strip()
                desc = node.attrib.get("content-desc", "").strip()
                res_id = node.attrib.get("resource-id", "").strip()
                cls_name = node.attrib.get("class", "").strip()
                pkg_name = node.attrib.get("package", "").strip()
                clickable = node.attrib.get("clickable", "false").lower() == "true"
                editable = (
                    node.attrib.get("editable", "false").lower() == "true"
                    or "EditText" in cls_name
                )
                scrollable = node.attrib.get("scrollable", "false").lower() == "true"
                focused = node.attrib.get("focused", "false").lower() == "true"

                # Filter meaningful interactive or labeled elements
                if not (text or desc or res_id or clickable or editable):
                    continue

                center_x = (left + right) // 2
                center_y = (top + bottom) // 2

                elements.append(
                    MobileUIElement(
                        ref_id=f"@m{idx}",
                        resource_id=res_id,
                        class_name=cls_name,
                        package_name=pkg_name,
                        text=text,
                        content_desc=desc,
                        bounds=(left, top, right, bottom),
                        center_x=center_x,
                        center_y=center_y,
                        is_clickable=clickable,
                        is_editable=editable,
                        is_scrollable=scrollable,
                        is_focused=focused,
                    )
                )
                idx += 1
        except Exception as err:
            logger.warning("Failed to parse UIAutomator XML for device %s: %s", device_id, err)

        return elements
