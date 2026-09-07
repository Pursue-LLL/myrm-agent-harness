"""Android Device Manager with Wireless ADB pairing and auto-reconnection sentinel.

[INPUT]
- types::DeviceInfo, DeviceConnectionStatus (POS: shared mobile types)
- protocols::MobileDeviceManagerProtocol (POS: device management contract)

[OUTPUT]
- MobileDeviceManager: Implementation of Android ADB device discovery and lifecycle management

[POS]
Core ADB transport and device lifecycle orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Any

from myrm_agent_harness.toolkits.mobile.types import (
    DeviceConnectionStatus,
    DeviceInfo,
)

logger = logging.getLogger(__name__)

_DEVICE_LINE_PATTERN = re.compile(r"^([^\s]+)\s+([^\s]+)(?:\s+(.*))?$")
_PROP_PATTERN = re.compile(r"^\[(.*?)\]:\s*\[(.*?)\]$")


class MobileDeviceManager:
    """Manages ADB processes, device enumeration, pairing and dynamic reconnection."""

    def __init__(self, adb_path: str = "adb") -> None:
        self._adb_path = adb_path
        self._default_serial: str | None = None
        self._known_devices: dict[str, DeviceInfo] = {}

    @property
    def adb_available(self) -> bool:
        """Check if adb executable is available in PATH or specified location."""
        return shutil.which(self._adb_path) is not None

    async def execute_adb_command(
        self,
        args: list[str],
        serial: str | None = None,
        timeout_s: float = 15.0,
    ) -> tuple[int, bytes, bytes]:
        """Execute raw adb command."""
        if not self.adb_available:
            return 1, b"", b"ADB executable not found. Please install Android Platform Tools."

        cmd = [self._adb_path]
        target_serial = serial or self._default_serial
        if target_serial:
            cmd.extend(["-s", target_serial])
        cmd.extend(args)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_s
            )
            return process.returncode or 0, stdout, stderr
        except asyncio.TimeoutError:
            logger.warning("ADB command %s timed out after %.1fs", cmd, timeout_s)
            return 124, b"", b"Command timed out"
        except Exception as exc:
            logger.error("Failed to execute ADB command %s: %s", cmd, exc)
            return 1, b"", str(exc).encode("utf-8")

    async def list_devices(self) -> list[DeviceInfo]:
        """Enumerate all connected USB and wireless devices."""
        code, stdout, stderr = await self.execute_adb_command(["devices", "-l"])
        if code != 0:
            logger.warning("adb devices failed: %s", stderr.decode("utf-8", errors="ignore"))
            return []

        devices: list[DeviceInfo] = []
        lines = stdout.decode("utf-8", errors="ignore").splitlines()
        for line in lines[1:]:  # Skip "List of devices attached"
            line = line.strip()
            if not line:
                continue
            match = _DEVICE_LINE_PATTERN.match(line)
            if not match:
                continue
            serial, state_str, extra = match.groups()
            status = DeviceConnectionStatus.UNKNOWN
            if state_str == "device":
                status = DeviceConnectionStatus.CONNECTED
            elif state_str == "unauthorized":
                status = DeviceConnectionStatus.UNAUTHORIZED
            elif state_str == "offline":
                status = DeviceConnectionStatus.OFFLINE

            is_wireless = ":" in serial
            ip_addr = serial.split(":")[0] if is_wireless else ""
            port = int(serial.split(":")[1]) if is_wireless and serial.split(":")[1].isdigit() else 5555

            dev = DeviceInfo(
                serial=serial,
                status=status,
                is_wireless=is_wireless,
                ip_address=ip_addr,
                port=port,
            )
            devices.append(dev)
            self._known_devices[serial] = dev

        if devices and not self._default_serial:
            self._default_serial = devices[0].serial

        return devices

    async def pair_wireless(self, host: str, port: int, pairing_code: str) -> bool:
        """Pair with an Android 11+ device."""
        target = f"{host}:{port}"
        code, stdout, stderr = await self.execute_adb_command(["pair", target, pairing_code])
        out_text = stdout.decode("utf-8", errors="ignore") + stderr.decode("utf-8", errors="ignore")
        if "Successfully paired" in out_text or code == 0:
            logger.info("Successfully paired with %s", target)
            return True
        logger.warning("Pairing failed with %s: %s", target, out_text)
        return False

    async def connect_wireless(self, host: str, port: int = 5555) -> bool:
        """Connect to an Android device over Wi-Fi."""
        target = f"{host}:{port}"
        code, stdout, stderr = await self.execute_adb_command(["connect", target])
        out_text = stdout.decode("utf-8", errors="ignore") + stderr.decode("utf-8", errors="ignore")
        if "connected to" in out_text.lower():
            logger.info("Connected to %s", target)
            self._default_serial = target
            await self.list_devices()
            return True
        logger.warning("Connection failed to %s: %s", target, out_text)
        return False

    async def disconnect(self, serial: str) -> bool:
        """Disconnect wireless device."""
        code, _, _ = await self.execute_adb_command(["disconnect", serial])
        if serial in self._known_devices:
            del self._known_devices[serial]
        if self._default_serial == serial:
            self._default_serial = None
        return code == 0

    async def get_device_info(self, serial: str | None = None) -> DeviceInfo | None:
        """Query detailed device hardware properties and resolution."""
        target_serial = serial or self._default_serial
        if not target_serial:
            devs = await self.list_devices()
            if not devs:
                return None
            target_serial = devs[0].serial

        code, stdout, _ = await self.execute_adb_command(["shell", "getprop"], serial=target_serial)
        model = "Unknown"
        mfg = "Unknown"
        version = "Unknown"
        sdk = 0

        if code == 0:
            for line in stdout.decode("utf-8", errors="ignore").splitlines():
                m = _PROP_PATTERN.match(line.strip())
                if m:
                    k, v = m.groups()
                    if k == "ro.product.model":
                        model = v
                    elif k == "ro.product.manufacturer":
                        mfg = v
                    elif k == "ro.build.version.release":
                        version = v
                    elif k == "ro.build.version.sdk" and v.isdigit():
                        sdk = int(v)

        # Get screen dimensions
        w, h = 1080, 2400
        size_code, size_out, _ = await self.execute_adb_command(
            ["shell", "wm", "size"], serial=target_serial
        )
        if size_code == 0:
            match = re.search(r"Physical size:\s*(\d+)x(\d+)", size_out.decode("utf-8", errors="ignore"))
            if match:
                w, h = int(match.group(1)), int(match.group(2))

        # Get screen density
        dpi = 440
        dpi_code, dpi_out, _ = await self.execute_adb_command(
            ["shell", "wm", "density"], serial=target_serial
        )
        if dpi_code == 0:
            match = re.search(r"Physical density:\s*(\d+)", dpi_out.decode("utf-8", errors="ignore"))
            if match:
                dpi = int(match.group(1))

        info = DeviceInfo(
            serial=target_serial,
            model=model,
            manufacturer=mfg,
            android_version=version,
            sdk_level=sdk,
            screen_width=w,
            screen_height=h,
            density_dpi=dpi,
            status=DeviceConnectionStatus.CONNECTED,
            is_wireless=":" in target_serial,
            ip_address=target_serial.split(":")[0] if ":" in target_serial else "",
            port=int(target_serial.split(":")[1]) if ":" in target_serial and target_serial.split(":")[1].isdigit() else 5555,
        )
        self._known_devices[target_serial] = info
        return info
