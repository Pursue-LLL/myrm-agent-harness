"""Mobile screen inspector and UI Automator hierarchy extractor.

[INPUT]
- types::MobileHierarchy, MobileNode, ElementBounds, ScreencapResult, Point2D
- protocols::MobileInspectorProtocol
- device_manager::MobileDeviceManager

[OUTPUT]
- MobileInspector: Screencap and Accessibility Tree parser

[POS]
Perception and visual/hierarchy inspector in toolkits/mobile.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import xml.etree.ElementTree as ET

from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.protocols import MobileInspectorProtocol
from myrm_agent_harness.toolkits.mobile.types import (
    ElementBounds,
    MobileHierarchy,
    MobileNode,
    Point2D,
    ScreencapResult,
)

logger = logging.getLogger(__name__)

BOUNDS_REGEX = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


class MobileInspector(MobileInspectorProtocol):
    """Inspects Android screen state via ADB."""

    def __init__(self, device_manager: MobileDeviceManager) -> None:
        self.device_manager = device_manager

    def _parse_bounds(self, bounds_str: str) -> ElementBounds:
        """Parse `[left,top][right,bottom]` string into ElementBounds."""
        match = BOUNDS_REGEX.match(bounds_str.strip())
        if match:
            l, t, r, b = match.groups()
            return ElementBounds(int(l), int(t), int(r), int(b))
        return ElementBounds(0, 0, 0, 0)

    def _parse_xml_node(self, elem: ET.Element) -> MobileNode:
        """Recursively convert XML element into MobileNode."""
        node = MobileNode(
            index=int(elem.attrib.get("index", 0)),
            text=elem.attrib.get("text", ""),
            resource_id=elem.attrib.get("resource-id", ""),
            class_name=elem.attrib.get("class", ""),
            package=elem.attrib.get("package", ""),
            content_desc=elem.attrib.get("content-desc", ""),
            checkable=elem.attrib.get("checkable", "false") == "true",
            checked=elem.attrib.get("checked", "false") == "true",
            clickable=elem.attrib.get("clickable", "false") == "true",
            enabled=elem.attrib.get("enabled", "true") == "true",
            focusable=elem.attrib.get("focusable", "false") == "true",
            focused=elem.attrib.get("focused", "false") == "true",
            scrollable=elem.attrib.get("scrollable", "false") == "true",
            long_clickable=elem.attrib.get("long-clickable", "false") == "true",
            password=elem.attrib.get("password", "false") == "true",
            selected=elem.attrib.get("selected", "false") == "true",
            bounds=self._parse_bounds(elem.attrib.get("bounds", "")),
        )

        for child_elem in elem:
            if child_elem.tag == "node":
                node.children.append(self._parse_xml_node(child_elem))

        return node

    async def get_screen_resolution(self, serial: str | None = None) -> Point2D:
        """Extract physical display dimensions via `wm size`."""
        device = await self.device_manager.ensure_active_device(serial)
        code, stdout, stderr = await self.device_manager._run_adb("-s", device.serial, "shell", "wm", "size")
        if code == 0 and "Physical size:" in stdout:
            match = re.search(r"Physical size:\s*(\d+)x(\d+)", stdout)
            if match:
                return Point2D(int(match.group(1)), int(match.group(2)))
        return Point2D(1080, 2400)

    async def screencap(
        self,
        serial: str | None = None,
        max_dimension: int | None = 1920,
        quality: int = 80,
    ) -> ScreencapResult:
        """Capture screenshot via `adb exec-out screencap -p` with low latency."""
        device = await self.device_manager.ensure_active_device(serial)
        cmd = [self.device_manager.adb_path, "-s", device.serial, "exec-out", "screencap", "-p"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            if proc.returncode != 0 or not stdout_data:
                raise RuntimeError(f"Screencap failed: {stderr_data.decode('utf-8', errors='replace')}")

            raw_bytes = stdout_data
            b64_str = base64.b64encode(raw_bytes).decode("ascii")
            res = await self.get_screen_resolution(device.serial)

            return ScreencapResult(
                raw_bytes=raw_bytes,
                format="png",
                width=res.x,
                height=res.y,
                base64_data=b64_str,
            )
        except Exception as e:
            logger.error("Failed to capture mobile screen: %s", e)
            raise

    async def dump_hierarchy(
        self,
        serial: str | None = None,
        compressed: bool = True,
    ) -> MobileHierarchy:
        """Dump UI Automator accessibility tree."""
        device = await self.device_manager.ensure_active_device(serial)
        remote_path = "/data/local/tmp/uidump.xml"

        # Execute dump command
        dump_cmd = ["shell", "uiautomator", "dump", remote_path]
        if compressed:
            dump_cmd = ["shell", "uiautomator", "dump", "--compressed", remote_path]

        code, stdout, stderr = await self.device_manager._run_adb("-s", device.serial, *dump_cmd, timeout=10.0)
        if code != 0 or "dumped to" not in (stdout + stderr):
            # Fallback retry once without --compressed
            code, stdout, stderr = await self.device_manager._run_adb(
                "-s", device.serial, "shell", "uiautomator", "dump", remote_path, timeout=10.0
            )

        # Pull XML content via cat
        code, xml_content, _ = await self.device_manager._run_adb(
            "-s", device.serial, "shell", "cat", remote_path, timeout=8.0
        )
        if not xml_content or "<hierarchy" not in xml_content:
            raise RuntimeError(f"Failed to read UI Automator dump: {stderr}")

        res = await self.get_screen_resolution(device.serial)
        hierarchy = MobileHierarchy(
            screen_width=res.x,
            screen_height=res.y,
        )

        try:
            root_elem = ET.fromstring(xml_content.strip())
            for child in root_elem:
                if child.tag == "node":
                    hierarchy.root_nodes.append(self._parse_xml_node(child))
        except Exception as e:
            logger.error("Failed to parse UI Automator XML: %s", e)
            raise

        return hierarchy
