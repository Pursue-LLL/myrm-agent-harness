"""Local Chromium-based browser discovery via DevToolsActivePort files.

[INPUT]
- OS filesystem: DevToolsActivePort files written by Chrome/Edge/Chromium/Brave/Canary
- Standard library: os, platform, pathlib, socket, urllib

[OUTPUT]
- discover_chrome_cdp_endpoint: returns discovered CDP endpoint (str) or None
- get_chromium_data_dirs: yields candidate browser data directories for current platform

[POS]
Scans known Chromium-based browser user-data directories for DevToolsActivePort files,
which Chrome writes when remote debugging is enabled (via chrome://inspect toggle or
--remote-debugging-port flag). Provides 4-phase discovery:
  1. DevToolsActivePort file scan (5 browsers × 3 platforms)
  2. HTTP probe (/json/version) to validate port and get canonical WebSocket URL
  3. TCP port liveness check (fallback for Chrome M144+ where HTTP may not respond)
  4. Fixed port 9222 fallback
Priority: Chrome > Edge > Chromium > Brave > Canary (most common → least common).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import urllib.request
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_HTTP_PROBE_TIMEOUT_S = 2.0
_TCP_PROBE_TIMEOUT_S = 1.0
_FALLBACK_PORT = 9222


def _get_home() -> Path:
    return Path.home()


def get_chromium_data_dirs() -> Iterator[Path]:
    """Yield candidate Chromium-based browser user-data directories.

    Priority order: Chrome > Edge > Chromium > Brave > Canary.
    Only yields directories that actually exist on disk.
    """
    system = platform.system()
    home = _get_home()

    if system == "Darwin":
        base = home / "Library" / "Application Support"
        candidates = [
            base / "Google" / "Chrome",
            base / "Microsoft Edge",
            base / "Chromium",
            base / "BraveSoftware" / "Brave-Browser",
            base / "Google" / "Chrome Canary",
        ]
    elif system == "Linux":
        base = home / ".config"
        candidates = [
            base / "google-chrome",
            base / "microsoft-edge",
            base / "chromium",
            base / "BraveSoftware" / "Brave-Browser",
            base / "google-chrome-unstable",
        ]
    elif system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        base = Path(local_app_data)
        candidates = [
            base / "Google" / "Chrome" / "User Data",
            base / "Microsoft" / "Edge" / "User Data",
            base / "Chromium" / "User Data",
            base / "BraveSoftware" / "Brave-Browser" / "User Data",
            base / "Google" / "Chrome SxS" / "User Data",
        ]
    else:
        return

    for d in candidates:
        if d.is_dir():
            yield d


def _read_devtools_active_port(data_dir: Path) -> tuple[int, str] | None:
    """Read DevToolsActivePort file from a browser data directory.

    Returns (port, ws_path) tuple or None if the file is missing/invalid.
    File format: line 1 = port number, line 2 = WebSocket path (optional).
    """
    port_file = data_dir / "DevToolsActivePort"
    try:
        content = port_file.read_text(encoding="utf-8").strip()
        if not content:
            return None
        lines = content.splitlines()
        port = int(lines[0].strip())
        if not (1 <= port <= 65535):
            return None
        ws_path = lines[1].strip() if len(lines) > 1 else "/devtools/browser"
        return port, ws_path
    except (OSError, ValueError, IndexError):
        return None


def _probe_http_version(port: int) -> str | None:
    """HTTP GET /json/version to validate CDP and get webSocketDebuggerUrl."""
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_HTTP_PROBE_TIMEOUT_S) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read())
            ws_url = data.get("webSocketDebuggerUrl")
            if isinstance(ws_url, str) and ws_url:
                return ws_url
            return f"ws://127.0.0.1:{port}/devtools/browser"
    except Exception:
        return None


def _port_is_open(port: int) -> bool:
    """TCP connect check — fallback for Chrome M144+ where HTTP may not respond."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(_TCP_PROBE_TIMEOUT_S)
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def discover_chrome_cdp_endpoint() -> str | None:
    """Auto-discover a local Chromium-based browser's CDP endpoint.

    Strategy (ordered by reliability):
      1. Scan DevToolsActivePort files from known browser data dirs
      2. For each found port: HTTP probe → TCP fallback
      3. Fallback: probe well-known port 9222

    Returns a CDP endpoint URL (http:// for connect_over_cdp) or None.
    """
    for data_dir in get_chromium_data_dirs():
        result = _read_devtools_active_port(data_dir)
        if result is None:
            continue

        port, _ws_path = result
        logger.debug("DevToolsActivePort found: %s (port=%d)", data_dir.name, port)

        ws_url = _probe_http_version(port)
        if ws_url:
            logger.info(
                "Chrome discovery: connected via HTTP probe (port=%d, browser=%s)",
                port,
                data_dir.name,
            )
            return f"http://127.0.0.1:{port}"

        if _port_is_open(port):
            logger.info(
                "Chrome discovery: connected via TCP fallback (port=%d, browser=%s)",
                port,
                data_dir.name,
            )
            return f"http://127.0.0.1:{port}"

        logger.debug("DevToolsActivePort stale (port=%d not reachable): %s", port, data_dir.name)

    if _probe_http_version(_FALLBACK_PORT):
        logger.info("Chrome discovery: connected via fallback port %d", _FALLBACK_PORT)
        return f"http://127.0.0.1:{_FALLBACK_PORT}"

    return None
