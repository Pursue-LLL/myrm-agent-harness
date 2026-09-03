"""[INPUT]
- observability.diagnostics.protocols::HealthReport (POS: Structured probe report contract.)
- observability.diagnostics.manager::register_diagnostic (POS: Probe auto-registration.)

[OUTPUT]
- check_system_exhaustion: Monitor Swap/Pagefile pressure, memory commit limits, and FD exhaustion.
- get_system_exhaustion_snapshot: Compact structured telemetry snapshot for agent causal reasoning.

[POS]
Host-level system resource exhaustion probe. Detects virtual memory (Swap / Pagefile)
saturation, system commit limit exhaustion (Linux Committed_AS / CommitLimit), and file
descriptor (FD / Handle) leaks. Registered into diagnostic manager and doctor API.
"""

from __future__ import annotations

import asyncio
import os
import platform
import resource
import sys
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

from myrm_agent_harness.observability.diagnostics.manager import register_diagnostic
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

_SWAP_WARN_THRESHOLD = 70.0
_SWAP_FAIL_THRESHOLD = 90.0
_FD_WARN_THRESHOLD = 75.0
_FD_FAIL_THRESHOLD = 90.0


def _read_linux_commit_info() -> tuple[int | None, int | None]:
    """Read Linux memory commit limits from /proc/meminfo (in KB)."""
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return None, None
    committed_as: int | None = None
    commit_limit: int | None = None
    try:
        lines = meminfo_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.startswith("Committed_AS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    committed_as = int(parts[1])
            elif line.startswith("CommitLimit:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    commit_limit = int(parts[1])
    except (OSError, ValueError):
        return None, None
    return committed_as, commit_limit


def _read_system_fd_usage() -> tuple[int | None, int | None, float | None]:
    """Read system-wide or process-level file descriptor consumption."""
    allocated_fds: int | None = None
    max_fds: int | None = None

    if sys.platform.startswith("linux"):
        file_nr_path = Path("/proc/sys/fs/file-nr")
        if file_nr_path.exists():
            try:
                parts = file_nr_path.read_text(encoding="utf-8").strip().split()
                if len(parts) >= 3 and parts[0].isdigit() and parts[2].isdigit():
                    allocated_fds = int(parts[0])
                    max_fds = int(parts[2])
            except (OSError, ValueError):
                pass

    if max_fds is None or max_fds <= 0:
        try:
            soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
            if soft_limit > 0 and soft_limit != resource.RLIM_INFINITY:
                max_fds = soft_limit
        except (ValueError, OSError, AttributeError):
            max_fds = None

    if allocated_fds is None and psutil is not None:
        try:
            current_proc = psutil.Process()
            if hasattr(current_proc, "num_fds"):
                allocated_fds = current_proc.num_fds()
            elif hasattr(current_proc, "num_handles"):
                allocated_fds = current_proc.num_handles()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            allocated_fds = None

    ratio: float | None = None
    if allocated_fds is not None and max_fds is not None and max_fds > 0:
        ratio = (allocated_fds / max_fds) * 100.0

    return allocated_fds, max_fds, ratio


def get_system_exhaustion_snapshot() -> dict[str, object]:
    """Generate a compact structured telemetry snapshot for agent causal root-cause reasoning."""
    snapshot: dict[str, object] = {
        "platform": platform.system(),
        "swap_total_mb": 0.0,
        "swap_used_mb": 0.0,
        "swap_percent": 0.0,
        "commit_exhausted": False,
        "fd_allocated": None,
        "fd_max": None,
        "fd_usage_percent": None,
    }

    if psutil is not None:
        try:
            swap = psutil.swap_memory()
            snapshot["swap_total_mb"] = round(swap.total / (1024 * 1024), 1)
            snapshot["swap_used_mb"] = round(swap.used / (1024 * 1024), 1)
            snapshot["swap_percent"] = round(swap.percent, 1)
        except (OSError, RuntimeError):
            pass

    committed, limit = _read_linux_commit_info()
    if committed is not None and limit is not None and limit > 0:
        snapshot["committed_as_mb"] = round(committed / 1024, 1)
        snapshot["commit_limit_mb"] = round(limit / 1024, 1)
        snapshot["commit_exhausted"] = committed > limit

    alloc_fd, max_fd, fd_ratio = _read_system_fd_usage()
    snapshot["fd_allocated"] = alloc_fd
    snapshot["fd_max"] = max_fd
    snapshot["fd_usage_percent"] = round(fd_ratio, 1) if fd_ratio is not None else None

    return snapshot


async def check_system_exhaustion() -> HealthReport:
    """Monitor Swap/Pagefile pressure, memory commit limits, and FD exhaustion."""
    if psutil is None:
        return HealthReport(
            component_name="SystemExhaustion",
            status="warn",
            message="System exhaustion monitoring is unavailable.",
            detail="psutil library is missing, cannot inspect swap or descriptor pressure.",
            fix_suggestion="Install psutil to enable deep exhaustion telemetry.",
        )

    try:
        snapshot = await asyncio.to_thread(get_system_exhaustion_snapshot)
        swap_percent = float(snapshot.get("swap_percent", 0.0) or 0.0)
        swap_used_mb = float(snapshot.get("swap_used_mb", 0.0) or 0.0)
        swap_total_mb = float(snapshot.get("swap_total_mb", 0.0) or 0.0)
        commit_exhausted = bool(snapshot.get("commit_exhausted", False))
        fd_ratio = snapshot.get("fd_usage_percent")
        fd_allocated = snapshot.get("fd_allocated")
        fd_max = snapshot.get("fd_max")

        detail = (
            f"Swap/Pagefile: {swap_percent:.1f}% ({swap_used_mb:.1f}/{swap_total_mb:.1f}MB)"
        )
        if fd_allocated is not None and fd_max is not None:
            detail += f", FD/Handles: {fd_allocated}/{fd_max}"
            if fd_ratio is not None:
                detail += f" ({float(fd_ratio):.1f}%)"
        if commit_exhausted:
            detail += ", Linux CommitLimit Exceeded!"

        # 1. Critical Failure: FD exhaustion (EMFILE risk) or severe Swap saturation
        if fd_ratio is not None and float(fd_ratio) >= _FD_FAIL_THRESHOLD:
            return HealthReport(
                component_name="SystemExhaustion",
                status="fail",
                message="File descriptor usage is critically high (EMFILE risk).",
                detail=detail,
                fix_suggestion="Close idle sockets and unclosed file handles in long-running tasks.",
                measured=f"FD Usage {float(fd_ratio):.1f}%",
                expected=f"FD Usage <{_FD_FAIL_THRESHOLD:.0f}%",
                cause="File descriptors near OS limit cause socket/file open failures (EMFILE).",
            )

        if swap_total_mb > 0 and swap_percent >= _SWAP_FAIL_THRESHOLD:
            return HealthReport(
                component_name="SystemExhaustion",
                status="fail",
                message="Swap/Pagefile is critically saturated. System thrashing imminent.",
                detail=detail,
                fix_suggestion="Terminate orphan worker processes or increase available RAM/Swap.",
                measured=f"Swap {swap_percent:.1f}%",
                expected=f"Swap <{_SWAP_FAIL_THRESHOLD:.0f}%",
                cause="Severe virtual memory exhaustion leads to excessive disk paging and agent stall.",
            )

        if commit_exhausted:
            return HealthReport(
                component_name="SystemExhaustion",
                status="fail",
                message="System memory commit limit is exceeded. OOM killer may trigger.",
                detail=detail,
                fix_suggestion="Reduce concurrent task memory allocations immediately.",
                measured="Committed_AS > CommitLimit",
                expected="Committed_AS <= CommitLimit",
                cause="Memory allocations exceeded strict OS overcommit accounting limit.",
            )

        # 2. Warning: Elevated Swap or FD usage
        if fd_ratio is not None and float(fd_ratio) > _FD_WARN_THRESHOLD:
            return HealthReport(
                component_name="SystemExhaustion",
                status="warn",
                message="File descriptor usage is elevated.",
                detail=detail,
                fix_suggestion="Inspect processes for unclosed file handles or connection leaks.",
                measured=f"FD Usage {float(fd_ratio):.1f}%",
                expected=f"FD Usage <{_FD_WARN_THRESHOLD:.0f}%",
                cause="Elevated FD consumption may exhaust file handles under high concurrency.",
            )

        if swap_total_mb > 0 and swap_percent > _SWAP_WARN_THRESHOLD:
            return HealthReport(
                component_name="SystemExhaustion",
                status="warn",
                message="Swap/Pagefile usage is high.",
                detail=detail,
                fix_suggestion="Inspect orphan worker processes consuming virtual memory.",
                measured=f"Swap {swap_percent:.1f}%",
                expected=f"Swap <{_SWAP_WARN_THRESHOLD:.0f}%",
                cause="High swap usage causes elevated I/O wait latency and slower response times.",
            )

        return HealthReport(
            component_name="SystemExhaustion",
            status="pass",
            message="System virtual memory and descriptor limits are healthy.",
            detail=detail,
        )
    except Exception as e:
        return HealthReport(
            component_name="SystemExhaustion",
            status="fail",
            message="System exhaustion diagnostic check failed.",
            detail=f"Telemetry probe exception: {e}",
            fix_suggestion="Verify psutil and OS access permissions.",
        )


register_diagnostic(check_system_exhaustion)
