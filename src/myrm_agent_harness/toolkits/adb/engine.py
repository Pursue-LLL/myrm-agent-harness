"""Wireless ADB Bridge Engine.

[INPUT]
- types::*
- safety::AdbSafetyGuard

[OUTPUT]
- AdbBridgeEngine: handles Wi-Fi ADB pairing, state tracking, screencap, UI dump, and input injection

[POS]
Core executor for wireless Android debugging and mobile automation.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import shutil
import time
import xml.etree.ElementTree as ET

from myrm_agent_harness.toolkits.adb.safety import AdbSafetyGuard
from myrm_agent_harness.toolkits.adb.types import (
    AdbCommandResult,
    AdbDeviceSnapshot,
    AdbElementNode,
    AdbTouchAction,
    DeviceConnectionState,
)

logger = logging.getLogger(__name__)

_BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


class AdbBridgeEngine:
    """Manages wireless ADB pairing, command execution, screen perception, and touch inputs."""

    def __init__(
        self,
        device_address: str = "",
        adb_binary_path: str = "",
    ) -> None:
        self.device_address = device_address.strip()
        self.adb_bin = adb_binary_path or shutil.which("adb") or "adb"
        self._state = DeviceConnectionState.DISCONNECTED
        self._lock = asyncio.Lock()
        self._last_snapshot: AdbDeviceSnapshot | None = None

    @property
    def state(self) -> DeviceConnectionState:
        return self._state

    async def execute_raw(self, *args: str, timeout: float = 15.0) -> AdbCommandResult:
        """Execute a raw ADB command with explicit timeout and safety checks."""
        cmd: list[str] = [self.adb_bin]
        if self.device_address:
            cmd.extend(["-s", self.device_address])
        cmd.extend(args)

        start_t = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            elapsed = int((time.perf_counter() - start_t) * 1000)
            out = stdout_data.decode("utf-8", errors="replace").strip()
            err = stderr_data.decode("utf-8", errors="replace").strip()
            success = (proc.returncode == 0)
            return AdbCommandResult(
                success=success,
                output=out,
                error=err,
                elapsed_ms=elapsed,
            )
        except asyncio.TimeoutError:
            elapsed = int((time.perf_counter() - start_t) * 1000)
            logger.warning("ADB command %s timed out after %ss", args, timeout)
            return AdbCommandResult(
                success=False,
                error=f"Command timed out after {timeout}s",
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.perf_counter() - start_t) * 1000)
            logger.exception("ADB execution failed: %s", e)
            return AdbCommandResult(
                success=False,
                error=str(e),
                elapsed_ms=elapsed,
            )

    async def pair_wireless(self, host_port: str, pairing_code: str) -> AdbCommandResult:
        """Perform Android 11+ wireless debugging pairing."""
        async with self._lock:
            self._state = DeviceConnectionState.PAIRING
            res = await self.execute_raw("pair", host_port, pairing_code)
            if res.success and "Successfully paired" in res.output:
                self._state = DeviceConnectionState.CONNECTED
            else:
                self._state = DeviceConnectionState.ERROR
            return res

    async def connect_wireless(self, host_port: str) -> AdbCommandResult:
        """Connect to an already paired wireless Android device."""
        async with self._lock:
            self.device_address = host_port.strip()
            res = await self.execute_raw("connect", host_port)
            if res.success and ("connected to" in res.output.lower() or "already connected" in res.output.lower()):
                self._state = DeviceConnectionState.CONNECTED
            else:
                self._state = DeviceConnectionState.ERROR
            return res

    async def capture_screenshot(self) -> tuple[bytes, str]:
        """Capture screen bitmap directly as raw bytes and base64 string."""
        cmd: list[str] = [self.adb_bin]
        if self.device_address:
            cmd.extend(["-s", self.device_address])
        cmd.extend(["exec-out", "screencap", "-p"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode == 0 and len(stdout_data) > 0:
                b64 = base64.b64encode(stdout_data).decode("ascii")
                return stdout_data, b64
        except Exception as e:
            logger.warning("screencap failed: %s", e)
        return b"", ""

    async def dump_ui_hierarchy(self) -> list[AdbElementNode]:
        """Extract and parse accessibility XML tree via uiautomator dump."""
        # 1. Trigger dump on device
        dump_res = await self.execute_raw("exec-out", "uiautomator", "dump", "/dev/tty")
        xml_content = dump_res.output
        if not xml_content or "<hierarchy" not in xml_content:
            return []

        elements: list[AdbElementNode] = []
        try:
            # Clean possible noise before xml root
            start_idx = xml_content.find("<hierarchy")
            if start_idx > 0:
                xml_content = xml_content[start_idx:]
            root = ET.fromstring(xml_content)
            idx = 1
            for node in root.iter("node"):
                bounds_str = node.attrib.get("bounds", "")
                m = _BOUNDS_PATTERN.match(bounds_str)
                bounds = (0, 0, 0, 0)
                if m:
                    bounds = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))

                text = node.attrib.get("text", "").strip()
                desc = node.attrib.get("content-desc", "").strip()
                res_id = node.attrib.get("resource-id", "").strip()
                cls_name = node.attrib.get("class", "").strip()
                clickable = node.attrib.get("clickable", "false") == "true"
                editable = (cls_name.endswith("EditText") or node.attrib.get("focusable", "false") == "true")
                scrollable = node.attrib.get("scrollable", "false") == "true"

                if text or desc or clickable or editable:
                    elements.append(
                        AdbElementNode(
                            ref_id=f"@mref_{idx}",
                            resource_id=res_id,
                            class_name=cls_name,
                            text=text,
                            content_desc=desc,
                            bounds=bounds,
                            clickable=clickable,
                            editable=editable,
                            scrollable=scrollable,
                        )
                    )
                    idx += 1
        except Exception as e:
            logger.warning("Failed to parse uiautomator XML: %s", e)

        return elements

    async def get_device_snapshot(self, include_screenshot: bool = False) -> AdbDeviceSnapshot:
        """Capture full semantic and visual snapshot of current device state."""
        elements = await self.dump_ui_hierarchy()
        pkg_res = await self.execute_raw("shell", "dumpsys", "window", "displays")
        
        package_name = "unknown"
        activity_name = "unknown"
        for line in pkg_res.output.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                parts = line.strip().split()
                for p in parts:
                    if "/" in p and "." in p:
                        clean_p = p.strip("{}/")
                        if "/" in clean_p:
                            pkg, act = clean_p.split("/", 1)
                            package_name = pkg
                            activity_name = act
                            break

        raw_bytes, b64_str = (b"", "")
        if include_screenshot:
            raw_bytes, b64_str = await self.capture_screenshot()

        snapshot = AdbDeviceSnapshot(
            package_name=package_name,
            activity_name=activity_name,
            elements=elements,
            screenshot_base64=b64_str,
            screenshot_bytes=raw_bytes,
        )
        self._last_snapshot = snapshot
        return snapshot

    async def send_input(
        self,
        action: AdbTouchAction,
        x: int = 0,
        y: int = 0,
        end_x: int = 0,
        end_y: int = 0,
        text: str = "",
        keycode: str = "",
        duration_ms: int = 300,
    ) -> AdbCommandResult:
        """Inject touch, text, or key inputs to the Android device with security gate."""
        if action == AdbTouchAction.TAP:
            return await self.execute_raw("shell", "input", "tap", str(x), str(y))

        elif action == AdbTouchAction.SWIPE:
            return await self.execute_raw(
                "shell", "input", "swipe",
                str(x), str(y), str(end_x), str(end_y), str(duration_ms)
            )

        elif action == AdbTouchAction.TEXT_INPUT:
            safe, reason = AdbSafetyGuard.is_input_safe(text)
            if not safe:
                return AdbCommandResult(success=False, error=reason)
            escaped_text = text.replace(" ", "%s").replace("'", "\\'")
            return await self.execute_raw("shell", "input", "text", escaped_text)

        elif action == AdbTouchAction.PRESS_KEY:
            safe, reason = AdbSafetyGuard.is_key_safe(keycode)
            if not safe:
                return AdbCommandResult(success=False, error=reason)
            return await self.execute_raw("shell", "input", "keyevent", keycode)

        return AdbCommandResult(success=False, error=f"Unsupported touch action: {action}")

    async def launch_app(self, package_name: str, activity_name: str = "") -> AdbCommandResult:
        """Launch an application package via monkey or intent with safety checks."""
        safe, reason = AdbSafetyGuard.is_package_allowed(package_name)
        if not safe:
            return AdbCommandResult(success=False, error=reason)

        if activity_name:
            target = f"{package_name}/{activity_name}"
            return await self.execute_raw("shell", "am", "start", "-n", target)
        return await self.execute_raw("shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1")
