"""cua-driver MCP spawn argv — ``--no-overlay`` policy for stdio sessions.

The cosmetic cursor overlay can idle-burn CPU on macOS (#47032-class) and wedge
Linux/X11 desktops when a session ends uncleanly. Default suppress it on those
platforms; keep it on Windows and Linux Wayland where the compositor owns the surface.

[INPUT]
- MYRM_CUA_NO_OVERLAY env (POS: explicit override when set to a recognized boolean)
- sys.platform / DISPLAY / XDG_SESSION_TYPE / WAYLAND_DISPLAY (POS: auto-detect)
- code_execution.platform._detect_wsl (POS: WSL2 headless-class detection on Linux)

[OUTPUT]
- default_cua_no_overlay: whether spawn should pass ``--no-overlay``
- cua_driver_supports_no_overlay: probe ``--help`` once per driver command
- mcp_stdio_args: base ``mcp`` argv with optional ``--no-overlay``

[POS]
Spawn policy only — no MCP session lifecycle. Used by ``cua_driver._McpSession``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache

from myrm_agent_harness.toolkits.code_execution.platform import _detect_wsl

_ENV_NO_OVERLAY = "MYRM_CUA_NO_OVERLAY"
_MCP_SUBCOMMAND = "mcp"
_NO_OVERLAY_FLAG = "--no-overlay"
_HELP_TIMEOUT_SEC = 3.0


def _parse_env_bool(raw: str) -> bool | None:
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return None


def default_cua_no_overlay() -> bool:
    """True when MCP spawn should append ``--no-overlay`` (unless driver lacks the flag)."""
    override = os.environ.get(_ENV_NO_OVERLAY)
    if override is not None and (parsed := _parse_env_bool(override)) is not None:
        return parsed

    if sys.platform == "darwin":
        return True

    if sys.platform != "linux":
        return False

    if _detect_wsl() or not os.environ.get("DISPLAY"):
        return True

    session_type = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if session_type == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return False

    return True


@lru_cache(maxsize=8)
def cua_driver_supports_no_overlay(driver_cmd: str) -> bool:
    """True if ``driver_cmd --help`` advertises ``--no-overlay`` (cached per command)."""
    if not driver_cmd.strip():
        return False
    try:
        proc = subprocess.run(
            [driver_cmd, "--help"],
            capture_output=True,
            text=True,
            timeout=_HELP_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    combined = (proc.stdout or "") + (proc.stderr or "")
    return _NO_OVERLAY_FLAG in combined


def mcp_stdio_args(driver_cmd: str, *, base_args: list[str] | None = None) -> list[str]:
    """Argv for cua-driver stdio MCP after optional ``--no-overlay``."""
    args = list(base_args if base_args is not None else [_MCP_SUBCOMMAND])
    if default_cua_no_overlay() and cua_driver_supports_no_overlay(driver_cmd):
        return [*args, _NO_OVERLAY_FLAG]
    return args


def reset_cua_driver_spawn_caches() -> None:
    """Clear help-probe cache (tests only)."""
    cua_driver_supports_no_overlay.cache_clear()
