"""ADB device discovery, pairing, and connection management.

[INPUT]
- types::MobileDevice, DeviceState, DeviceConnectionMode, MobileActionResult

[OUTPUT]
- MobileDeviceManager: Handles wireless pairing and adb connect lifecycle

[POS]
Device connectivity manager in toolkits/mobile.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil

from myrm_agent_harness.toolkits.mobile.protocols import MobileDeviceManagerProtocol
from myrm_agent_harness.toolkits.mobile.types import (
    DeviceConnectionMode,
    DeviceState,
    MobileActionResult,
    MobileDevice,
)

logger = logging.getLogger(__name__)


class MobileDeviceManager(MobileDeviceManagerProtocol):
    """Manages wireless and USB ADB connections."""

    def __init__(self, adb_path: str | None = None) -> None:
        self.adb_path = adb_path or shutil.which("adb") or "adb"
        self._active_serial: str | None = None

    async def _run_adb(self, *args: str, timeout: float = 15.0) -> tuple[int, str, str]:
        """Execute ADB subprocess command safely."""
        cmd = [self.adb_path, *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode or 0,
                stdout_data.decode("utf-8", errors="replace"),
                stderr_data.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            logger.warning("ADB command %s timed out after %.1fs", cmd, timeout)
            return (-1, "", f"ADB command timed out after {timeout}s")
        except FileNotFoundError:
            logger.error("ADB executable '%s' not found in system PATH", self.adb_path)
            return (-1, "", f"ADB executable not found at '{self.adb_path}'")
        except Exception as e:
            logger.error("ADB command %s failed with exception: %s", cmd, e)
            return (-1, "", str(e))

    async def list_devices(self) -> list[MobileDevice]:
        """Parse `adb devices -l` to discover connected devices."""
        code, stdout, stderr = await self._run_adb("devices", "-l")
        if code != 0:
            logger.warning("Failed to list ADB devices: %s", stderr)
            return []

        devices: list[MobileDevice] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices attached"):
                continue

            parts = re.split(r"\s+", line)
            if len(parts) < 2:
                continue

            serial = parts[0]
            raw_state = parts[1].lower()

            state = DeviceState.UNKNOWN
            if "device" in raw_state:
                state = DeviceState.ONLINE
            elif "unauthorized" in raw_state:
                state = DeviceState.UNAUTHORIZED
            elif "offline" in raw_state:
                state = DeviceState.OFFLINE

            # Parse key:value metadata (product:xxx model:yyy device:zzz transport_id:nnn)
            meta: dict[str, str] = {}
            for token in parts[2:]:
                if ":" in token:
                    k, v = token.split(":", 1)
                    meta[k] = v

            is_wireless = ":" in serial
            mode = DeviceConnectionMode.WIRELESS if is_wireless else DeviceConnectionMode.USB
            ip = ""
            port = 5555
            if is_wireless:
                host_port = serial.split(":", 1)
                ip = host_port[0]
                if len(host_port) > 1 and host_port[1].isdigit():
                    port = int(host_port[1])

            devices.append(
                MobileDevice(
                    serial=serial,
                    state=state,
                    model=meta.get("model", "Unknown"),
                    product=meta.get("product", "Unknown"),
                    device=meta.get("device", "Unknown"),
                    transport_id=meta.get("transport_id", ""),
                    mode=mode,
                    ip_address=ip,
                    port=port,
                )
            )

        return devices

    async def pair_device(self, host: str, port: int, pairing_code: str) -> MobileActionResult:
        """Android 11+ one-time pairing via `adb pair host:port pairing_code`."""
        target = f"{host}:{port}"
        code, stdout, stderr = await self._run_adb("pair", target, pairing_code, timeout=20.0)
        output = (stdout + "\n" + stderr).strip()
        success = code == 0 and "Successfully paired" in output

        return MobileActionResult(
            success=success,
            action="pair_device",
            message=output,
            exit_code=code,
            data={"target": target, "paired": success},
        )

    async def connect_device(self, host: str, port: int = 5555) -> MobileActionResult:
        """Connect to device via `adb connect host:port`."""
        target = f"{host}:{port}"
        code, stdout, stderr = await self._run_adb("connect", target, timeout=15.0)
        output = (stdout + "\n" + stderr).strip()
        success = code == 0 and ("connected to" in output.lower() or "already connected" in output.lower())

        if success:
            self._active_serial = target

        return MobileActionResult(
            success=success,
            action="connect_device",
            message=output,
            exit_code=code,
            data={"target": target, "connected": success},
        )

    async def disconnect_device(self, host_or_serial: str) -> MobileActionResult:
        """Disconnect wireless device."""
        code, stdout, stderr = await self._run_adb("disconnect", host_or_serial)
        output = (stdout + "\n" + stderr).strip()
        success = code == 0

        if self._active_serial == host_or_serial:
            self._active_serial = None

        return MobileActionResult(
            success=success,
            action="disconnect_device",
            message=output,
            exit_code=code,
        )

    async def ensure_active_device(self, preferred_serial: str | None = None) -> MobileDevice:
        """Resolve active target device, raising RuntimeError if none found."""
        devices = await self.list_devices()
        online_devices = [d for d in devices if d.state == DeviceState.ONLINE]

        if not online_devices:
            raise RuntimeError(
                "No online Android device found. Please connect via USB or run `connect_device(host, port)`."
            )

        target_serial = preferred_serial or self._active_serial
        if target_serial:
            for d in online_devices:
                if d.serial == target_serial:
                    return d

        # Default to first online device
        selected = online_devices[0]
        self._active_serial = selected.serial
        return selected
