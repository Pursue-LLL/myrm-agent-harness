"""ADB Command Executor and Transport Protocol.

[INPUT]
- myrm_agent_harness.toolkits.mobile_adb.types

[OUTPUT]
- ADBExecutor: Executes raw ADB commands safely via async subprocesses with timeout and error handling.

[POS]
Async subprocess transport for Android Debug Bridge commands.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.mobile_adb.types import MobileBridgeConfig

logger = logging.getLogger(__name__)


class ADBExecutor:
    """Safely executes ADB commands via asyncio subprocess."""

    def __init__(self, config: MobileBridgeConfig | None = None) -> None:
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileBridgeConfig

        self.config = config or MobileBridgeConfig()
        self._resolved_adb_path: str | None = None

    def resolve_adb(self) -> str:
        """Resolve ADB executable path."""
        if self._resolved_adb_path:
            return self._resolved_adb_path
        path = shutil.which(self.config.adb_path)
        if not path:
            # Fallback to default
            path = self.config.adb_path
        self._resolved_adb_path = path
        return path

    async def run_adb(
        self,
        args: list[str],
        target_device: str | None = None,
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        """Execute an ADB command with arguments and optional target device."""
        adb_bin = self.resolve_adb()
        cmd: list[str] = [adb_bin]
        if target_device:
            cmd.extend(["-s", target_device])
        cmd.extend(args)

        timeout_sec = timeout or self.config.command_timeout_seconds

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_sec,
            )
            stdout_str = stdout_data.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_data.decode("utf-8", errors="replace").strip()
            return process.returncode or 0, stdout_str, stderr_str
        except asyncio.TimeoutError:
            logger.warning("ADB command %s timed out after %.1fs", cmd, timeout_sec)
            return -1, "", f"Command timed out after {timeout_sec}s"
        except FileNotFoundError:
            logger.error("ADB binary not found at %s", adb_bin)
            return -2, "", f"ADB binary not found: {adb_bin}"
        except Exception as err:
            logger.error("Failed to run ADB command %s: %s", cmd, err)
            return -3, "", str(err)
