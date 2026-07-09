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
  2. HTTP probe (/json/version) to validate port (full CDP API)
  3. TCP + DevToolsActivePort WebSocket path (chrome://inspect mode on Chrome M144+)
  4. Fixed port 9222 HTTP probe fallback
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


def _build_ws_endpoint(port: int, ws_path: str) -> str:
    """Build a browser-level WebSocket CDP endpoint from DevToolsActivePort fields."""
    path = ws_path if ws_path.startswith("/") else f"/{ws_path}"
    return f"ws://127.0.0.1:{port}{path}"


def _parse_local_port(endpoint: str) -> int | None:
    """Extract localhost port from http:// or ws:// CDP endpoint."""
    if endpoint.startswith("http://"):
        remainder = endpoint.removeprefix("http://")
    elif endpoint.startswith("ws://"):
        remainder = endpoint.removeprefix("ws://")
    else:
        return None
    host_port = remainder.split("/", 1)[0]
    try:
        host, port_str = host_port.rsplit(":", 1)
    except ValueError:
        return None
    if host not in ("127.0.0.1", "localhost", "[::1]"):
        return None
    try:
        port = int(port_str)
    except ValueError:
        return None
    if not (1 <= port <= 65535):
        return None
    return port


def probe_cdp_endpoint(endpoint: str) -> bool:
    """Return True when a CDP endpoint is likely attachable.

    HTTP endpoints require /json/version (full remote-debugging API).
    WebSocket endpoints (inspect-only mode) require TCP plus DevToolsActivePort path match.
    """
    port = _parse_local_port(endpoint)
    if port is None:
        return False
    if endpoint.startswith("ws://"):
        return _probe_ws_endpoint(endpoint, port)
    return _probe_http_version(port) is not None


def _probe_ws_endpoint(endpoint: str, port: int) -> bool:
    """Validate inspect-mode WebSocket endpoint (TCP + DevToolsActivePort path)."""
    if not _port_is_open(port):
        return False
    for data_dir in get_chromium_data_dirs():
        result = _read_devtools_active_port(data_dir)
        if result is None or result[0] != port:
            continue
        return _build_ws_endpoint(port, result[1]) == endpoint
    return True


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
      2. For each found port: HTTP probe → WebSocket path + TCP (inspect-only mode)
      3. Fallback: probe well-known port 9222 via HTTP

    Returns a CDP endpoint URL (http:// or ws:// for connect_over_cdp) or None.
    """
    for data_dir in get_chromium_data_dirs():
        result = _read_devtools_active_port(data_dir)
        if result is None:
            continue

        port, ws_path = result
        logger.debug("DevToolsActivePort found: %s (port=%d)", data_dir.name, port)

        if _probe_http_version(port):
            logger.info(
                "Chrome discovery: connected via HTTP probe (port=%d, browser=%s)",
                port,
                data_dir.name,
            )
            return f"http://127.0.0.1:{port}"

        if _port_is_open(port):
            ws_endpoint = _build_ws_endpoint(port, ws_path)
            logger.info(
                "Chrome discovery: connected via inspect WebSocket path (port=%d, browser=%s)",
                port,
                data_dir.name,
            )
            return ws_endpoint

        logger.debug("DevToolsActivePort stale (port=%d not reachable): %s", port, data_dir.name)

    if _probe_http_version(_FALLBACK_PORT):
        logger.info("Chrome discovery: connected via fallback port %d", _FALLBACK_PORT)
        return f"http://127.0.0.1:{_FALLBACK_PORT}"

    return None
