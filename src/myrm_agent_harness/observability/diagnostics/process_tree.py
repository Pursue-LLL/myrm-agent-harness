"""[INPUT]
- (none)

[OUTPUT]
- inspect_process_lineage: Trace parent process tree (PPID chain) for causal debugging.
- detect_orphan_processes: Identify leaked orphan processes adopted by init (PPID=1).
- diagnose_process_tree_health: Summary report for agent causal root-cause reasoning.

[POS]
Process tree inspector and orphan process detector for observability and self-healing.
Provides structured causal evidence for leaked worker and browser subprocesses.
"""

from __future__ import annotations

import time
from typing import TypedDict

try:
    import psutil
except ImportError:
    psutil = None

_KNOWN_WORKER_MARKERS = (
    "camoufox",
    "firefox",
    "chrome",
    "chromium",
    "patchright",
    "playwright",
    "node",
    "python",
)


class ProcessNode(TypedDict):
    pid: int
    ppid: int
    name: str
    status: str
    elapsed_seconds: float
    memory_rss_mb: float
    cpu_percent: float
    num_fds: int | None


class ProcessTreeDiagnosis(TypedDict):
    total_processes: int
    orphan_count: int
    orphans: list[ProcessNode]
    leaked_memory_mb: float
    cause_summary: str


def _get_process_node(proc: psutil.Process) -> ProcessNode | None:
    """Safely extract structured telemetry from a psutil Process instance."""
    try:
        pid = proc.pid
        ppid = proc.ppid()
        name = proc.name() or "?"
        status = proc.status()
        create_time = proc.create_time()
        elapsed = max(0.0, time.time() - create_time)

        mem_info = proc.memory_info()
        rss_mb = round(mem_info.rss / (1024 * 1024), 2)
        cpu = round(proc.cpu_percent(interval=None), 1)

        num_fds: int | None = None
        if hasattr(proc, "num_fds"):
            try:
                num_fds = proc.num_fds()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        elif hasattr(proc, "num_handles"):
            try:
                num_fds = proc.num_handles()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

        return ProcessNode(
            pid=pid,
            ppid=ppid,
            name=name,
            status=status,
            elapsed_seconds=round(elapsed, 1),
            memory_rss_mb=rss_mb,
            cpu_percent=cpu,
            num_fds=num_fds,
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def inspect_process_lineage(pid: int, max_depth: int = 10) -> list[ProcessNode]:
    """Trace PPID lineage upwards from a given PID to root ancestor (init/launchd)."""
    if psutil is None:
        return []

    lineage: list[ProcessNode] = []
    current_pid = pid
    depth = 0

    while depth < max_depth:
        try:
            proc = psutil.Process(current_pid)
            node = _get_process_node(proc)
            if node is None:
                break
            lineage.append(node)
            parent_pid = node["ppid"]
            if parent_pid == 0 or parent_pid == current_pid:
                break
            current_pid = parent_pid
            depth += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break

    return lineage


def detect_orphan_processes(
    min_elapsed_seconds: float = 120.0,
    worker_markers: tuple[str, ...] = _KNOWN_WORKER_MARKERS,
) -> list[ProcessNode]:
    """Detect worker/browser processes whose parent process exited (adopted by PID 1/init).

    Orphans are characterized by:
    1. Parent PID == 1 (or 0 on some systems where kernel/launchd is root).
    2. Process name or command line contains known execution markers (browser/node/python).
    3. Elapsed lifetime exceeds ``min_elapsed_seconds`` (avoid flagging just-spawned daemons).
    """
    if psutil is None:
        return []

    orphans: list[ProcessNode] = []

    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        try:
            ppid = proc.info.get("ppid")
            if ppid != 1:
                continue

            name = (proc.info.get("name") or "").lower()
            cmdline_list = proc.info.get("cmdline") or []
            cmdline = " ".join(cmdline_list).lower()

            if not any(marker in name or marker in cmdline for marker in worker_markers):
                continue

            node = _get_process_node(proc)
            if node is not None and node["elapsed_seconds"] >= min_elapsed_seconds:
                orphans.append(node)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    orphans.sort(key=lambda node: node["memory_rss_mb"], reverse=True)
    return orphans


def diagnose_process_tree_health(
    min_elapsed_seconds: float = 120.0,
) -> ProcessTreeDiagnosis:
    """Generate high-density causal diagnostic report on process tree and leaked workers."""
    if psutil is None:
        return ProcessTreeDiagnosis(
            total_processes=0,
            orphan_count=0,
            orphans=[],
            leaked_memory_mb=0.0,
            cause_summary="psutil library is missing; process tree diagnostics unavailable.",
        )

    all_pids = psutil.pids()
    total_processes = len(all_pids)
    orphans = detect_orphan_processes(min_elapsed_seconds=min_elapsed_seconds)
    orphan_count = len(orphans)
    total_orphan_mem = round(sum(node["memory_rss_mb"] for node in orphans), 2)

    if orphan_count == 0:
        cause = f"Process tree healthy. Total active processes: {total_processes}. Zero leaked worker orphans."
    else:
        top_names = ", ".join(f"{o['name']}(PID {o['pid']}, {o['memory_rss_mb']}MB)" for o in orphans[:3])
        cause = (
            f"Detected {orphan_count} leaked orphan worker(s) consuming {total_orphan_mem}MB RSS. "
            f"Top offenders: {top_names}."
        )

    return ProcessTreeDiagnosis(
        total_processes=total_processes,
        orphan_count=orphan_count,
        orphans=orphans,
        leaked_memory_mb=total_orphan_mem,
        cause_summary=cause,
    )
