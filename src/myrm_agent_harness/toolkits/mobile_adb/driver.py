"""Device communication driver for Android Wireless ADB protocol.

[INPUT]
- types::MobileDeviceConnectionStatus, MobileActionResult (POS: result models)
- parser::MobileUIParser (POS: xml parsing engine)

[OUTPUT]
- AdbDeviceDriver: Low-level async driver executing adb commands and managing connection.

[POS]
Async device communication layer interfacing with standard adb binary for wireless control.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import shlex
import shutil
from typing import Any

from myrm_agent_harness.toolkits.mobile_adb.app_aliases import (
    COMMON_APP_ALIASES,
    resolve_package_alias,
)
from myrm_agent_harness.toolkits.mobile_adb.parser import MobileUIParser
from myrm_agent_harness.toolkits.mobile_adb.safety import MobileSafetyGuard
from myrm_agent_harness.toolkits.mobile_adb.types import (
    MobileActionResult,
    MobileDeviceConnectionStatus,
    MobileDeviceState,
    MobileUIElement,
)

logger = logging.getLogger(__name__)


class AdbDeviceDriver:
    """Encapsulates wireless ADB command execution against target Android devices."""

    def __init__(self, adb_path: str = "adb", safety_guard: MobileSafetyGuard | None = None) -> None:
        self._adb_path = shutil.which(adb_path) or adb_path
        self._safety_guard = safety_guard or MobileSafetyGuard()
        self._current_ref_map: dict[str, MobileUIElement] = {}

    async def _run_adb(self, *args: str, timeout_sec: float = 15.0) -> tuple[int, str, str]:
        """Execute adb subprocess with timeout."""
        cmd = [self._adb_path, *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            return proc.returncode or 0, stdout, stderr
        except TimeoutError:
            logger.warning("ADB command timed out: %s", " ".join(cmd))
            return -1, "", "Command timed out"
        except Exception as e:
            logger.error("ADB execution error: %s", e)
            return -1, "", str(e)

    async def pair(self, host: str, port: int, pairing_code: str) -> MobileActionResult:
        """Pair with device using Android 11+ wireless debugging pairing code."""
        target = f"{host}:{port}"
        code, out, err = await self._run_adb("pair", target, pairing_code)
        if code == 0 and "Successfully paired" in out:
            return MobileActionResult(
                success=True,
                action="pair",
                message=f"Successfully paired to {target}",
            )
        return MobileActionResult(
            success=False,
            action="pair",
            message=f"Pairing failed: {out or err}",
            error=err or out,
        )

    async def connect(self, host: str, port: int) -> MobileActionResult:
        """Connect to wireless ADB daemon on host:port."""
        target = f"{host}:{port}"
        code, out, err = await self._run_adb("connect", target)
        if code == 0 and ("connected to" in out or "already connected" in out):
            return MobileActionResult(
                success=True,
                action="connect",
                message=f"Connected to {target}",
            )
        return MobileActionResult(
            success=False,
            action="connect",
            message=f"Failed to connect to {target}",
            error=err or out,
        )

    async def disconnect(self, host: str, port: int) -> MobileActionResult:
        """Disconnect wireless ADB connection."""
        target = f"{host}:{port}"
        code, out, err = await self._run_adb("disconnect", target)
        return MobileActionResult(
            success=code == 0,
            action="disconnect",
            message=out.strip() or err.strip(),
        )

    async def list_devices(self) -> list[dict[str, Any]]:
        """Parse ``adb devices -l`` into serializable device rows."""
        code, out, err = await self._run_adb("devices", "-l")
        if code != 0:
            logger.warning("adb devices failed: %s", err or out)
            return []

        devices: list[dict[str, Any]] = []
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("List of devices"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            device_id, state = parts[0], parts[1]
            host = device_id
            port = 5555
            if ":" in device_id:
                host_part, port_part = device_id.rsplit(":", 1)
                host = host_part
                if port_part.isdigit():
                    port = int(port_part)
            model = ""
            for token in parts[2:]:
                if token.startswith("model:"):
                    model = token.removeprefix("model:")
                    break
            devices.append(
                {
                    "device_id": device_id,
                    "host": host,
                    "port": port,
                    "model": model,
                    "state": state,
                    "is_wireless": ":" in device_id,
                    "screen_info": None,
                }
            )
        return devices

    async def tap_at(self, target: str, x: int, y: int) -> MobileActionResult:
        """Tap absolute screen coordinates."""
        code, out, err = await self._run_adb(
            "-s", target, "shell", "input", "tap", str(x), str(y)
        )
        return MobileActionResult(
            success=code == 0,
            action="tap",
            message=out.strip() or f"tapped ({x},{y})",
            error=None if code == 0 else (err or out),
        )

    async def swipe(
        self,
        target: str,
        x: int,
        y: int,
        end_x: int,
        end_y: int,
    ) -> MobileActionResult:
        """Swipe from (x,y) to (end_x,end_y)."""
        code, out, err = await self._run_adb(
            "-s",
            target,
            "shell",
            "input",
            "swipe",
            str(x),
            str(y),
            str(end_x),
            str(end_y),
        )
        return MobileActionResult(
            success=code == 0,
            action="swipe",
            message=out.strip() or "swipe completed",
            error=None if code == 0 else (err or out),
        )

    async def get_device_state(self, target: str) -> MobileDeviceState:
        """Capture current device state, top activity, and parse UI tree."""
        # 1. Get current focused window/package
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "dumpsys", "window", "|", "grep", "-E", "mCurrentFocus|mFocusedApp"
        )
        current_pkg = ""
        current_act = ""
        if out:
            for part in out.split():
                if "/" in part and not part.startswith("m"):
                    pkg_act = part.strip("{}").split("/")
                    current_pkg = pkg_act[0]
                    if len(pkg_act) > 1:
                        current_act = pkg_act[1]
                    break

        # 2. Dump uiautomator XML
        # Delete stale dump file first
        await self._run_adb("-s", target, "shell", "rm", "-f", "/sdcard/window_dump.xml")
        dump_code, _, dump_err = await self._run_adb(
            "-s", target, "shell", "uiautomator", "dump", "/sdcard/window_dump.xml", timeout_sec=10.0
        )
        xml_content = ""
        elements: list[MobileUIElement] = []
        if dump_code == 0:
            cat_code, xml_out, _ = await self._run_adb(
                "-s", target, "shell", "cat", "/sdcard/window_dump.xml"
            )
            if cat_code == 0:
                xml_content = xml_out
                elements, self._current_ref_map = MobileUIParser.parse_xml_tree(xml_content)

        # 3. Get screen display size
        size_code, size_out, _ = await self._run_adb("-s", target, "shell", "wm", "size")
        width, height = 1080, 2400
        if size_code == 0 and "Physical size:" in size_out:
            try:
                res = size_out.split("Physical size:")[-1].strip().split("x")
                width, height = int(res[0]), int(res[1])
            except Exception:
                pass

        host_port = target.split(":")
        host = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 5555

        return MobileDeviceState(
            device_id=target,
            ip_address=host,
            port=port,
            connection_status=MobileDeviceConnectionStatus.CONNECTED,
            current_package=current_pkg,
            current_activity=current_act,
            screen_width=width,
            screen_height=height,
            elements=elements,
            xml_tree=xml_content,
        )

    async def execute_semantic_action(
        self,
        target: str,
        ref_id: str,
        action: str,
        text_value: str = "",
    ) -> MobileActionResult:
        """Execute semantic action targeting @mref element."""
        element = self._current_ref_map.get(ref_id)
        if not element:
            return MobileActionResult(
                success=False,
                action=action,
                message=f"Element '{ref_id}' not found in current UI snapshot. Please refresh snapshot first.",
                error="ELEMENT_NOT_FOUND",
            )

        center_x, center_y = element.center

        # Check safety guard against sensitive UI element interaction
        is_risky, risk_reason = self._safety_guard.evaluate_ui_risk(
            current_package="",
            elements=[element],
        )
        if is_risky:
            return MobileActionResult(
                success=False,
                action=action,
                message=risk_reason or "Interaction blocked by MobileSafetyGuard",
                error="SAFETY_BARRIER_TRIGGERED",
            )

        if action == "click":
            code, out, err = await self._run_adb(
                "-s", target, "shell", "input", "tap", str(center_x), str(center_y)
            )
            return MobileActionResult(
                success=code == 0,
                action="click",
                message=f"Clicked element {ref_id} at ({center_x}, {center_y})",
                data={"element": element.to_summary()},
            )

        elif action == "long_press":
            # Swipe with zero distance for 1000ms represents long press
            code, out, err = await self._run_adb(
                "-s",
                target,
                "shell",
                "input",
                "swipe",
                str(center_x),
                str(center_y),
                str(center_x),
                str(center_y),
                "1000",
            )
            return MobileActionResult(
                success=code == 0,
                action="long_press",
                message=f"Long-pressed element {ref_id} at ({center_x}, {center_y})",
            )

        elif action == "input_text":
            # 1. Click to focus
            await self._run_adb("-s", target, "shell", "input", "tap", str(center_x), str(center_y))
            await asyncio.sleep(0.3)
            # 2. Type text (escape spaces)
            safe_text = text_value.replace(" ", "%s")
            code, out, err = await self._run_adb("-s", target, "shell", "input", "text", safe_text)
            return MobileActionResult(
                success=code == 0,
                action="input_text",
                message=f"Entered text '{text_value}' into {ref_id}",
            )

        elif action == "clear_text":
            # Select and send KEYCODE_DEL multiple times
            await self._run_adb("-s", target, "shell", "input", "tap", str(center_x), str(center_y))
            # Move cursor to end and delete
            code, out, err = await self._run_adb(
                "-s", target, "shell", "input", "keyevent", "--longpress", "67", "67", "67", "67"
            )
            return MobileActionResult(
                success=code == 0,
                action="clear_text",
                message=f"Cleared text for element {ref_id}",
            )

        return MobileActionResult(
            success=False,
            action=action,
            message=f"Unsupported semantic action: {action}",
            error="UNSUPPORTED_ACTION",
        )

    async def execute_global_action(
        self,
        target: str,
        action: str,
        param: str = "",
    ) -> MobileActionResult:
        """Execute device-level global commands (back, home, launch, screencap)."""
        if action == "back":
            code, out, err = await self._run_adb("-s", target, "shell", "input", "keyevent", "4")
            return MobileActionResult(success=code == 0, action="back", message="Pressed BACK key")

        elif action == "home":
            code, out, err = await self._run_adb("-s", target, "shell", "input", "keyevent", "3")
            return MobileActionResult(success=code == 0, action="home", message="Pressed HOME key")

        elif action == "launch_app":
            package = param.strip()
            if not package:
                return MobileActionResult(
                    success=False, action="launch_app", message="Package name required", error="EMPTY_PARAM"
                )
            code, out, err = await self._run_adb(
                "-s", target, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"
            )
            return MobileActionResult(
                success=code == 0,
                action="launch_app",
                message=f"Launched application '{package}'",
                data={"output": out},
            )

        elif action == "stop_app":
            package = param.strip()
            is_risky, risk_reason = self._safety_guard.evaluate_ui_risk(
                current_package=package,
                elements=[],
            )
            if is_risky:
                return MobileActionResult(
                    success=False,
                    action="stop_app",
                    message=risk_reason or "Action blocked by MobileSafetyGuard",
                    error="SAFETY_BARRIER_TRIGGERED",
                )
            code, out, err = await self._run_adb("-s", target, "shell", "am", "force-stop", package)
            return MobileActionResult(
                success=code == 0,
                action="stop_app",
                message=f"Force stopped application '{package}'",
            )

        return MobileActionResult(
            success=False, action=action, message=f"Unknown global action: {action}", error="UNKNOWN_ACTION"
        )

    async def capture_screenshot_bytes(self, target: str) -> bytes | None:
        """Capture screenshot via 'exec-out screencap -p' returning PNG binary."""
        cmd = [self._adb_path, "-s", target, "exec-out", "screencap", "-p"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode == 0 and len(stdout_bytes) > 100:
                return stdout_bytes
            return None
        except Exception as e:
            logger.warning("Failed to capture screenshot via ADB: %s", e)
            return None
