"""Asynchronous ADB client for wireless pairing, device discovery, and command execution.

[INPUT]
- host: str, port: int (Wireless ADB endpoint)
- pairing_port: int, pairing_code: str (Optional Android 11+ pairing parameters)

[OUTPUT]
- AndroidAdbClient: Manages connection, heartbeat probe, shell execution, screencap, and dump.

[POS]
Network communication layer for Wireless ADB.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import NamedTuple

logger = logging.getLogger(__name__)


class DeviceConnectionState(NamedTuple):
    connected: bool
    serial: str
    model: str = "Unknown Android"
    battery_level: int = -1
    display_width: int = 1080
    display_height: int = 2400
    density_dpi: int = 420


class AndroidAdbClient:
    """Async wrapper around ADB wireless connection and protocol primitives."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5555) -> None:
        self.host = host
        self.port = port
        self.serial = f"{host}:{port}"
        self._connected = False
        self._cached_state: DeviceConnectionState | None = None

    async def run_adb(self, *args: str, timeout: float = 10.0) -> tuple[int, str, str]:
        """Execute an adb command asynchronously via subprocess with strict timeout."""
        cmd = ["adb", "-s", self.serial, *args] if self._connected else ["adb", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode if proc.returncode is not None else -1,
                stdout_bytes.decode("utf-8", errors="replace"),
                stderr_bytes.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            logger.warning("ADB command %s timed out after %ss", cmd, timeout)
            return -1, "", f"Timeout after {timeout}s"
        except FileNotFoundError:
            logger.error("ADB executable not found in system PATH.")
            return -1, "", "ADB executable not found. Please install Android Platform Tools."
        except Exception as exc:
            logger.error("Error executing ADB command %s: %s", cmd, exc)
            return -1, "", str(exc)

    async def pair(self, pairing_port: int, pairing_code: str) -> tuple[bool, str]:
        """Pair with Android 11+ Wireless Debugging service."""
        target = f"{self.host}:{pairing_port}"
        code, out, err = await self.run_adb("pair", target, pairing_code, timeout=15.0)
        output = (out + " " + err).strip()
        if code == 0 and "Successfully paired" in output:
            logger.info("Successfully paired with %s", target)
            return True, output
        return False, output or "Pairing failed."

    async def connect(self) -> tuple[bool, str]:
        """Connect to Wireless ADB host:port."""
        target = f"{self.host}:{self.port}"
        code, out, err = await self.run_adb("connect", target, timeout=10.0)
        output = (out + " " + err).strip()
        if "connected to" in output.lower() and "cannot" not in output.lower():
            self._connected = True
            logger.info("Connected to Wireless ADB at %s", target)
            return True, output
        self._connected = False
        return False, output or "Connection failed."

    async def probe(self) -> DeviceConnectionState:
        """Probe device connection, battery, model, and display resolution."""
        code, out, _ = await self.run_adb("shell", "getprop", "ro.product.model", timeout=5.0)
        model = out.strip() if code == 0 and out.strip() else "Android Device"

        width, height = 1080, 2400
        code, out, _ = await self.run_adb("shell", "wm", "size", timeout=5.0)
        if code == 0:
            match = re.search(r"(\d+)x(\d+)", out)
            if match:
                width, height = int(match.group(1)), int(match.group(2))

        dpi = 420
        code, out, _ = await self.run_adb("shell", "wm", "density", timeout=5.0)
        if code == 0:
            match = re.search(r"(\d+)", out)
            if match:
                dpi = int(match.group(1))

        battery = -1
        code, out, _ = await self.run_adb("shell", "dumpsys", "battery", timeout=5.0)
        if code == 0:
            match = re.search(r"level:\s*(\d+)", out)
            if match:
                battery = int(match.group(1))

        self._connected = True
        state = DeviceConnectionState(
            connected=True,
            serial=self.serial,
            model=model,
            battery_level=battery,
            display_width=width,
            display_height=height,
            density_dpi=dpi,
        )
        self._cached_state = state
        return state

    async def raw_screencap(self) -> bytes:
        """Capture raw screenshot PNG bytes via adb exec-out screencap -p."""
        cmd = ["adb", "-s", self.serial, "exec-out", "screencap", "-p"] if self._connected else ["adb", "exec-out", "screencap", "-p"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        return stdout_bytes

    async def dump_ui_hierarchy(self) -> str:
        """Dump UI hierarchy XML string via adb exec-out uiautomator dump /dev/tty."""
        # Use adb shell uiautomator dump /data/local/tmp/uidump.xml followed by cat for max compatibility
        await self.run_adb("shell", "uiautomator", "dump", "/data/local/tmp/uidump.xml", timeout=6.0)
        code, out, _ = await self.run_adb("shell", "cat", "/data/local/tmp/uidump.xml", timeout=4.0)
        if code == 0 and out.strip().startswith("<?xml"):
            return out
        return ""
