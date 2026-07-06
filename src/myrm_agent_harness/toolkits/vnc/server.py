"""VNC server manager — lazy-start x11vnc + websockify on the existing Xvfb display.

[INPUT]
- os::getenv (POS: DISPLAY env var for Xvfb discovery)
- shutil::which (POS: binary availability check)
- asyncio (POS: subprocess lifecycle management)
- secrets (POS: one-time VNC password generation)

[OUTPUT]
- VncServer: lifecycle manager for x11vnc + websockify pair
- get_environment_hint: VNC awareness line for system prompt injection

[POS]
Lazy-started VNC infrastructure that captures the existing Xvfb virtual display
and exposes it as a WebSocket stream for noVNC frontend consumption.
Only starts when explicitly requested; zero resource cost when idle.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile

logger = logging.getLogger(__name__)

_VNC_PORT = 5900
_WEBSOCKIFY_PORT = 6080
_HEALTH_CHECK_INTERVAL_S = 30
_MAX_RESTART_ATTEMPTS = 5

_ENV_HINT_LOCK = threading.Lock()
_ENV_HINT_CACHE: str | None = None


def _probe_xvfb_resolution() -> str:
    """Detect Xvfb screen resolution via xdpyinfo. Returns e.g. '1280x720' or ''."""
    if not shutil.which("xdpyinfo"):
        return ""
    try:
        result = subprocess.run(
            ["xdpyinfo"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode != 0:
            return ""
        match = re.search(r"dimensions:\s+(\d+x\d+)\s+pixels", result.stdout)
        return match.group(1) if match else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def get_environment_hint() -> str:
    """Return a VNC environment awareness line for system prompt injection.

    Process-level cache — deterministic output safe for KV-cache prefix caching.
    Returns '' when VNC is unavailable (macOS, Windows, no Xvfb), meaning zero
    token cost for non-sandbox environments.
    """
    global _ENV_HINT_CACHE  # noqa: PLW0603
    if _ENV_HINT_CACHE is not None:
        return _ENV_HINT_CACHE

    with _ENV_HINT_LOCK:
        if _ENV_HINT_CACHE is not None:
            return _ENV_HINT_CACHE

        if not VncServer.is_available():
            _ENV_HINT_CACHE = ""
            return ""

        resolution = _probe_xvfb_resolution()
        res_part = f" ({resolution})" if resolution else ""
        _ENV_HINT_CACHE = (
            f"Visual Desktop: Xvfb virtual display{res_part} with VNC streaming is available. "
            "You can safely generate and run GUI applications (Pygame, Tkinter, Qt, etc.) "
            "— the user sees the output in real-time via the Visual Desktop panel."
        )
        return _ENV_HINT_CACHE


class VncStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass
class VncInfo:
    """Public VNC connection info exposed to the business layer."""

    status: VncStatus
    websocket_port: int = _WEBSOCKIFY_PORT
    password: str = ""
    display_num: int | None = None
    error: str | None = None


@dataclass
class VncServer:
    """Lazy-started VNC server that captures the existing Xvfb display.

    Architecture:
        Xvfb (already running for browser/computer_use)
          └─ x11vnc captures DISPLAY → RFB protocol on port 5900
              └─ websockify proxies RFB → WebSocket on port 6080
                  └─ noVNC (frontend) connects via WebSocket
    """

    vnc_port: int = _VNC_PORT
    websockify_port: int = _WEBSOCKIFY_PORT
    _status: VncStatus = field(default=VncStatus.STOPPED, init=False)
    _password: str = field(default="", init=False)
    _display_num: int | None = field(default=None, init=False)
    _x11vnc_proc: asyncio.subprocess.Process | None = field(default=None, init=False, repr=False)
    _websockify_proc: asyncio.subprocess.Process | None = field(default=None, init=False, repr=False)
    _health_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _passwd_file: Path | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def get_info(self) -> VncInfo:
        return VncInfo(
            status=self._status,
            websocket_port=self.websockify_port,
            password=self._password,
            display_num=self._display_num,
            error=None,
        )

    @staticmethod
    def is_available() -> bool:
        """Check if VNC can run on this platform (Linux with X11 + required binaries)."""
        if os.name != "posix":
            return False
        display = os.getenv("DISPLAY", "")
        if not display:
            return False
        return shutil.which("x11vnc") is not None and shutil.which("websockify") is not None

    async def start(self) -> VncInfo:
        """Lazily start VNC server. Idempotent — returns existing info if already running."""
        async with self._lock:
            if self._status == VncStatus.RUNNING:
                return self.get_info()

            if not self.is_available():
                self._status = VncStatus.UNAVAILABLE
                return VncInfo(
                    status=VncStatus.UNAVAILABLE,
                    error="VNC requires Linux with DISPLAY, x11vnc, and websockify",
                )

            self._status = VncStatus.STARTING
            try:
                self._display_num = self._parse_display()
                self._password = secrets.token_urlsafe(16)
                await self._create_passwd_file()
                await self._start_x11vnc()
                await self._start_websockify()
                self._status = VncStatus.RUNNING
                self._health_task = asyncio.create_task(self._health_loop())
                logger.info(
                    "VNC server started on DISPLAY=:%s, websocket port %d",
                    self._display_num,
                    self.websockify_port,
                )
                return self.get_info()
            except Exception as exc:
                self._status = VncStatus.ERROR
                logger.error("Failed to start VNC server: %s", exc)
                await self._cleanup_processes()
                return VncInfo(status=VncStatus.ERROR, error=str(exc))

    async def stop(self) -> None:
        """Stop VNC server and release resources."""
        async with self._lock:
            if self._health_task and not self._health_task.done():
                self._health_task.cancel()
                self._health_task = None
            await self._cleanup_processes()
            if self._passwd_file and self._passwd_file.exists():
                self._passwd_file.unlink(missing_ok=True)
                self._passwd_file = None
            self._status = VncStatus.STOPPED
            self._password = ""
            logger.info("VNC server stopped")

    def _parse_display(self) -> int:
        display = os.getenv("DISPLAY", "")
        if ":" not in display:
            raise RuntimeError(f"Invalid DISPLAY env var: {display!r}")
        try:
            return int(display.split(":")[1].split(".")[0])
        except (ValueError, IndexError) as exc:
            raise RuntimeError(f"Cannot parse DISPLAY number from {display!r}") from exc

    async def _create_passwd_file(self) -> None:
        tmp = NamedTemporaryFile(suffix=".vnc_passwd", delete=False)
        tmp.close()
        os.chmod(tmp.name, 0o600)
        self._passwd_file = Path(tmp.name)
        proc = await asyncio.create_subprocess_exec(
            "x11vnc", "-storepasswd", self._password, str(self._passwd_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            raise RuntimeError("Failed to create VNC password file")

    async def _start_x11vnc(self) -> None:
        cmd = [
            "x11vnc",
            "-display", f":{self._display_num}",
            "-rfbport", str(self.vnc_port),
            "-rfbauth", str(self._passwd_file),
            "-shared",
            "-forever",
            "-noxdamage",
            "-cursor", "arrow",
            "-nopw",
            "-quiet",
        ]
        self._x11vnc_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(0.5)
        if self._x11vnc_proc.returncode is not None:
            stderr = await self._x11vnc_proc.stderr.read() if self._x11vnc_proc.stderr else b""
            raise RuntimeError(f"x11vnc exited immediately: {stderr.decode()}")

    async def _start_websockify(self) -> None:
        cmd = [
            "websockify",
            "--web", "/usr/share/novnc" if Path("/usr/share/novnc").exists() else "/dev/null",
            str(self.websockify_port),
            f"localhost:{self.vnc_port}",
        ]
        self._websockify_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(0.5)
        if self._websockify_proc.returncode is not None:
            stderr = await self._websockify_proc.stderr.read() if self._websockify_proc.stderr else b""
            raise RuntimeError(f"websockify exited immediately: {stderr.decode()}")

    async def _cleanup_processes(self) -> None:
        for proc in (self._x11vnc_proc, self._websockify_proc):
            if proc and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        self._x11vnc_proc = None
        self._websockify_proc = None

    async def _health_loop(self) -> None:
        """Periodically check if x11vnc and websockify are still alive."""
        consecutive_failures = 0
        try:
            while True:
                backoff = _HEALTH_CHECK_INTERVAL_S * (2 ** min(consecutive_failures, 4))
                await asyncio.sleep(backoff)
                for name, proc in [("x11vnc", self._x11vnc_proc), ("websockify", self._websockify_proc)]:
                    if proc and proc.returncode is not None:
                        logger.warning("%s exited unexpectedly (code %d), restarting VNC", name, proc.returncode)
                        async with self._lock:
                            await self._cleanup_processes()
                            try:
                                await self._start_x11vnc()
                                await self._start_websockify()
                                self._status = VncStatus.RUNNING
                                consecutive_failures = 0
                            except Exception as exc:
                                consecutive_failures += 1
                                self._status = VncStatus.ERROR
                                if consecutive_failures >= _MAX_RESTART_ATTEMPTS:
                                    logger.error(
                                        "VNC restart failed %d times, giving up: %s",
                                        consecutive_failures, exc,
                                    )
                                    return
                                logger.warning(
                                    "VNC restart failed (%d/%d), next retry in %ds: %s",
                                    consecutive_failures, _MAX_RESTART_ATTEMPTS,
                                    _HEALTH_CHECK_INTERVAL_S * (2 ** min(consecutive_failures, 4)),
                                    exc,
                                )
                        break
        except asyncio.CancelledError:
            pass
