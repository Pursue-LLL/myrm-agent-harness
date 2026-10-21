"""[INPUT]
- observability.diagnostics.protocols::HealthReport (POS: Structured probe report contract.)
- observability.diagnostics.manager::register_diagnostic (POS: Probe auto-registration.)

[OUTPUT]
- check_system_resources: Monitor CPU, memory, and process (PID) usage.

[POS]
Host-level resource probe (CPU / memory / PID utilization). Reads cgroup v1/v2 pids
counters when running inside a container with a pids limit, and falls back to psutil
process sampling for local single-machine deployments. Registered into the global
diagnostic manager and executed by /health/doctor.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

from myrm_agent_harness.observability.diagnostics.manager import register_diagnostic
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

_CGROUP_PIDS_FILES = (
    ("/sys/fs/cgroup/pids.current", "/sys/fs/cgroup/pids.max"),  # cgroup v2
    ("/sys/fs/cgroup/pids/pids.current", "/sys/fs/cgroup/pids/pids.max"),  # cgroup v1
)
_BROWSER_PROCESS_MARKERS = ("camoufox", "firefox", "chrome", "chromium")
_PID_USAGE_WARN_THRESHOLD = 70.0
_PID_USAGE_FAIL_THRESHOLD = 90.0


def _read_cgroup_pid_file(path: str) -> int | None:
    """Read a cgroup pid counter file. Returns None when absent or unlimited ('max')."""
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or raw == "max":
        return None
    return int(raw)


def _read_pid_usage() -> tuple[int | None, int | None]:
    """Read current and maximum process counts from the enclosing cgroup.

    Returns ``(None, None)`` when no cgroup pids limit applies (local single machine).
    """
    for current_path, max_path in _CGROUP_PIDS_FILES:
        current = _read_cgroup_pid_file(current_path)
        limit = _read_cgroup_pid_file(max_path)
        if current is not None:
            return current, limit
    return None, None


def _sample_process_tree() -> tuple[int, int]:
    """Count child processes and browser-related children for PID attribution."""
    if psutil is None:
        return 0, 0
    total = 0
    browser = 0
    try:
        for proc in psutil.Process().children(recursive=True):
            total += 1
            try:
                name = (proc.name() or "").lower()
                command = " ".join(proc.cmdline()).lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if any(marker in name or marker in command for marker in _BROWSER_PROCESS_MARKERS):
                browser += 1
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return total, browser


def _top_memory_processes(limit: int = 5) -> str:
    """Summarize the most memory-hungry live processes for diagnostics."""
    if psutil is None:
        return ""
    ranked: list[tuple[float, str]] = []
    for proc in psutil.process_iter(["name", "memory_percent"]):
        try:
            name = proc.info["name"] or "?"
            percent = float(proc.info["memory_percent"] or 0.0)
            ranked.append((percent, name))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ", ".join(f"{name} {percent:.1f}%" for percent, name in ranked[:limit])


async def check_system_resources() -> HealthReport:
    """Monitor CPU, memory, and process (PID) usage."""
    if psutil is None:
        return HealthReport(
            component_name="SystemResources",
            status="warn",
            message="System resource monitoring is unavailable.",
            detail="psutil library is missing, cannot perform system resource probe.",
            fix_suggestion="Install psutil to enable resource monitoring.",
        )

    try:
        cpu_percent = await asyncio.to_thread(psutil.cpu_percent, 0.0)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_used_gb = memory.used / (1024**3)
        memory_total_gb = memory.total / (1024**3)

        pid_current, pid_limit = await asyncio.to_thread(_read_pid_usage)
        pid_percent = 0.0
        if pid_limit is not None:
            pid_percent = (pid_current / pid_limit * 100) if pid_limit else 0.0
        child_count, browser_count = await asyncio.to_thread(_sample_process_tree)

        stats = f"CPU: {cpu_percent:.1f}%, Memory: {memory_percent:.1f}% ({memory_used_gb:.1f}/{memory_total_gb:.1f}GB)"
        if pid_limit is not None:
            stats += f", PID: {pid_current}/{pid_limit} ({pid_percent:.0f}%, browser {browser_count})"
        else:
            stats += f", Processes: {child_count} (browser {browser_count})"
        top_processes = await asyncio.to_thread(_top_memory_processes)
        if top_processes:
            stats += f"; top memory: {top_processes}"

        # PID saturation is the most critical check: fork() failures stall task execution.
        if pid_limit is not None and pid_current is not None:
            if pid_percent >= _PID_USAGE_FAIL_THRESHOLD:
                return HealthReport(
                    component_name="SystemResources",
                    status="fail",
                    message="Process count is critically high. New tasks may fail to start.",
                    detail=stats,
                    fix_suggestion="Reduce concurrent browser or executor tasks, then retry.",
                    measured=f"PID {pid_current}/{pid_limit} ({pid_percent:.0f}%)",
                    expected=f"PID <{_PID_USAGE_FAIL_THRESHOLD:.0f}% of {pid_limit}",
                    cause="Process count near the container pids limit blocks process creation (fork EAGAIN).",
                )
            if pid_percent > _PID_USAGE_WARN_THRESHOLD:
                return HealthReport(
                    component_name="SystemResources",
                    status="warn",
                    message="Process count is high.",
                    detail=stats,
                    fix_suggestion="Reduce concurrent browser or executor tasks.",
                    measured=f"PID {pid_current}/{pid_limit} ({pid_percent:.0f}%)",
                    expected=f"PID <{_PID_USAGE_WARN_THRESHOLD:.0f}% of {pid_limit}",
                    cause="High process usage may hit the container pids limit under load spikes.",
                )

        if memory_percent >= 95:
            return HealthReport(
                component_name="SystemResources",
                status="fail",
                message="System memory is critically low. Performance may be degraded.",
                detail=stats,
                fix_suggestion="Close unused applications to free memory.",
                measured=f"Memory {memory_percent:.1f}%",
                expected="Memory <95%",
                cause="Physical memory exhaustion may cause OOM kills or severe swapping.",
            )
        if memory_percent > 80:
            return HealthReport(
                component_name="SystemResources",
                status="warn",
                message="System memory usage is high.",
                detail=stats,
                fix_suggestion="Close unused applications to free memory.",
                measured=f"Memory {memory_percent:.1f}%",
                expected="Memory <80%",
                cause="High memory usage may lead to degraded performance under load.",
            )
        if cpu_percent >= 95:
            return HealthReport(
                component_name="SystemResources",
                status="fail",
                message="CPU usage is critically high. Performance may be degraded.",
                detail=stats,
                fix_suggestion="Check for resource-intensive processes.",
                measured=f"CPU {cpu_percent:.1f}%",
                expected="CPU <95%",
                cause="CPU saturation will cause request timeouts and agent stalls.",
            )
        if cpu_percent > 80:
            return HealthReport(
                component_name="SystemResources",
                status="warn",
                message="CPU usage is high.",
                detail=stats,
                fix_suggestion="Check for resource-intensive processes.",
                measured=f"CPU {cpu_percent:.1f}%",
                expected="CPU <80%",
                cause="Elevated CPU usage may cause latency spikes during peak loads.",
            )
        return HealthReport(
            component_name="SystemResources",
            status="pass",
            message="System resources are healthy.",
            detail=stats,
        )
    except Exception as e:
        return HealthReport(
            component_name="SystemResources",
            status="fail",
            message="System resource check failed.",
            detail=f"System resource check failed: {e}",
            fix_suggestion="Check if psutil is properly installed.",
        )


register_diagnostic(check_system_resources)
