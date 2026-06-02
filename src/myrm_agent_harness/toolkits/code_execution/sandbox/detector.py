"""Auto-detect the best available sandbox provider.

Detection strategy (mode=AUTO):
1. Check if running inside a container → NullProvider (container is the sandbox)
2. Check platform-specific tools (bwrap on Linux, sandbox-exec on macOS)
3. Fallback to NullProvider with a warning

Container detection uses heuristics (/.dockerenv, /run/.containerenv,
cgroup v2 container markers) — does NOT read DEPLOY_MODE or any
business-layer config, preserving the "no deployment-mode awareness" principle.

[INPUT]
- toolkits.code_execution.platform::PlatformInfo (POS: Cross-platform runtime detection and shell configuration.)

[OUTPUT]
- detect_sandbox_provider: Select the best sandbox provider for the current environm...

[POS]
Auto-detect the best available sandbox provider.
"""

from __future__ import annotations

import logging
import os

from myrm_agent_harness.toolkits.code_execution.platform import PlatformInfo, detect_platform
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.bwrap import BwrapProvider
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import NullProvider
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.seatbelt import SeatbeltProvider
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxMode,
    SandboxProvider,
    SandboxStatus,
)

logger = logging.getLogger(__name__)


def _is_inside_container() -> bool:
    """Heuristic check for running inside a Docker/Podman/LXC container."""
    if os.path.exists("/.dockerenv"):
        return True
    if os.path.exists("/run/.containerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as f:
            content = f.read()
            if "docker" in content or "kubepods" in content or "containerd" in content:
                return True
    except (OSError, PermissionError):
        pass
    return False


def detect_sandbox_provider(
    mode: SandboxMode = SandboxMode.AUTO,
    platform_info: PlatformInfo | None = None,
) -> tuple[SandboxProvider, SandboxStatus]:
    """Select the best sandbox provider for the current environment.

    Args:
        mode: Activation strategy (AUTO/ENABLE/DISABLE).
        platform_info: Override platform detection (for testing).

    Returns:
        (provider, status) tuple.

    Raises:
        RuntimeError: if mode=ENABLE but no provider is available.
    """
    if mode == SandboxMode.DISABLE:
        return NullProvider(), SandboxStatus(
            enabled=False,
            provider_name="null",
            reason="sandbox disabled by configuration",
        )

    p = platform_info or detect_platform()

    if mode == SandboxMode.AUTO and _is_inside_container():
        logger.info(" Container detected — OS-level sandbox skipped (container is the sandbox)")
        return NullProvider(), SandboxStatus(
            enabled=False,
            provider_name="null",
            reason="container environment detected",
        )

    if p.is_windows:
        if mode == SandboxMode.ENABLE:
            raise RuntimeError("OS-level sandbox not supported on Windows")
        return NullProvider(), SandboxStatus(
            enabled=False,
            provider_name="null",
            reason="Windows: no OS-level sandbox available",
        )

    if p.os_type == "linux":
        candidate = BwrapProvider()
        if candidate.is_available():
            logger.info(" OS-level sandbox: bwrap (Linux)")
            return candidate, SandboxStatus(enabled=True, provider_name="bwrap")
    elif p.os_type == "macos":
        candidate = SeatbeltProvider()
        if candidate.is_available():
            logger.info(" OS-level sandbox: seatbelt (macOS)")
            return candidate, SandboxStatus(enabled=True, provider_name="seatbelt")

    if mode == SandboxMode.ENABLE:
        tool = "bubblewrap (bwrap)" if p.os_type == "linux" else "sandbox-exec"
        raise RuntimeError(
            f"OS-level sandbox required but {tool} not found. Install it or set sandbox mode to AUTO/DISABLE."
        )

    logger.warning(" No OS-level sandbox tool available — running without sandbox")
    return NullProvider(), SandboxStatus(
        enabled=False,
        provider_name="null",
        reason=f"no sandbox tool available on {p.os_type}",
    )
