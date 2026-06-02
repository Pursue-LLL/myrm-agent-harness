"""Cross-platform runtime detection and shell configuration.

Single source of truth for all platform-specific knowledge.
Other modules consume PlatformInfo instead of scattered ``if IS_WINDOWS`` checks.

Incorporates best practices from competitor analysis:
- openclaw: WSL multi-layer detection (env vars → /proc/version)
- zeroclaw: safe environment variable whitelist per platform
- pi-mono: shell configuration as data (shell_path, shell_args)

[INPUT]
- (none)

[OUTPUT]
- PlatformInfo: Immutable snapshot of host platform characteristics.
- detect_platform: Detect and cache the host platform info (singleton).

[POS]
Cross-platform runtime detection and shell configuration.
"""

from __future__ import annotations

import functools
import logging
import os
import platform
import sys
from dataclasses import dataclass
from typing import Literal

_logger = logging.getLogger(__name__)

OSType = Literal["windows", "macos", "linux"]
ShellType = Literal["bash", "cmd"]

_POSIX_SAFE_ENV_VARS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "USER",
        "SHELL",
        "TMPDIR",
    }
)

_WINDOWS_SAFE_ENV_VARS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "TERM",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "PATHEXT",
    }
)


def _detect_wsl() -> bool:
    """Detect Windows Subsystem for Linux via env vars then /proc/version."""
    if sys.platform != "linux":
        return False
    if any(os.environ.get(k) for k in ("WSL_INTEROP", "WSL_DISTRO_NAME", "WSLENV")):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as f:
            release = f.read().lower()
        return "microsoft" in release or "wsl" in release
    except OSError:
        return False


@dataclass(frozen=True)
class PlatformInfo:
    """Immutable snapshot of host platform characteristics.

    All platform-specific decisions should be driven by fields on this object
    rather than by inspecting ``sys.platform`` at the call site.
    """

    os_type: OSType
    os_release: str
    arch: str
    is_wsl: bool

    shell_path: str
    shell_args: tuple[str, ...]
    shell_type: ShellType
    exit_code_var: str
    env_set_template: str
    path_separator: str
    process_group_creation_flag: int
    safe_env_vars: frozenset[str]

    @property
    def is_windows(self) -> bool:
        return self.os_type == "windows"

    @property
    def is_posix(self) -> bool:
        return self.os_type in ("macos", "linux")

    @property
    def prompt_label(self) -> str:
        """Human-readable OS description for system prompt injection."""
        names: dict[OSType, str] = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}
        base = f"{names[self.os_type]} ({self.os_release}, {self.arch})"
        if self.is_wsl:
            base += " [WSL: Linux environment on Windows host]"
        return base

    @property
    def shell_hint(self) -> str:
        """Shell usage hints for system prompt injection."""
        if self.os_type == "macos":
            return "bash (BSD toolchain: use vm_stat instead of free, no GNU long options for ps/top)"
        if self.os_type == "windows":
            return "cmd.exe (use dir/type/tasklist instead of ls/cat/ps)"
        if self.is_wsl:
            return "bash (Linux on WSL, but host is Windows)"
        return "bash (GNU toolchain)"

    @property
    def environment_prompt_line(self) -> str:
        """Unified environment tag for system prompt injection.

        Combines OS, shell, and Python toolchain information into a single
        ``<environment>`` XML tag.  The Python section is omitted when the
        environment is clean (zero token cost for normal setups).

        Output is deterministic for the process lifetime — safe for
        KV-cache prefix caching.  Delegates Python toolchain detection to
        ``env_probe.get_environment_probe_line()`` (single source of truth).
        """
        parts: list[str] = [f"OS: {self.prompt_label}. Shell: {self.shell_hint}."]
        try:
            from myrm_agent_harness.toolkits.code_execution.env_probe import (
                get_environment_probe_line,
            )

            py_line = get_environment_probe_line()
            if py_line:
                parts.append(py_line)
        except Exception:
            _logger.debug("Python toolchain probe unavailable", exc_info=True)
        return "\n<environment>" + " ".join(parts) + "</environment>"


@functools.lru_cache(maxsize=1)
def detect_platform() -> PlatformInfo:
    """Detect and cache the host platform info (singleton)."""
    system = platform.system().lower()

    if system == "darwin":
        os_type: OSType = "macos"
    elif system == "windows":
        os_type = "windows"
    else:
        os_type = "linux"

    is_wsl = _detect_wsl()

    if os_type == "windows":
        return PlatformInfo(
            os_type=os_type,
            os_release=platform.release(),
            arch=platform.machine(),
            is_wsl=False,
            shell_path="cmd.exe",
            shell_args=("/Q",),
            shell_type="cmd",
            exit_code_var="%ERRORLEVEL%",
            env_set_template="set {key}={value}",
            path_separator=";",
            process_group_creation_flag=0x00000200,  # CREATE_NEW_PROCESS_GROUP
            safe_env_vars=_WINDOWS_SAFE_ENV_VARS,
        )

    return PlatformInfo(
        os_type=os_type,
        os_release=platform.release(),
        arch=platform.machine(),
        is_wsl=is_wsl,
        shell_path="/bin/bash",
        shell_args=("--norc", "--noprofile"),
        shell_type="bash",
        exit_code_var="$?",
        env_set_template="export {key}={value}",
        path_separator=":",
        process_group_creation_flag=0,
        safe_env_vars=_POSIX_SAFE_ENV_VARS,
    )
