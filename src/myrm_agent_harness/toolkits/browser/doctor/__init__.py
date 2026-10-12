"""Browser Doctor — pre-flight diagnostics and health checks.

Validates dependencies, configuration, environment, and browser launchability
before actual operations. Provides clear fix suggestions for each failure.
Includes precise orphan process detection (matches patchright/playwright cache
paths) with safety mechanisms (dry-run default, force flag required for cleanup).

This package is the public facade for the doctor subdomain; it re-exports the
public symbols of the internal ``checks``, ``orphan_check``, ``orphans``, and
``report`` modules so that ``myrm_agent_harness.toolkits.browser.doctor``
remains a single import point.

[INPUT]
- .checks (POS: environment/dependency checks + run_doctor orchestrator)
- .orphan_check (POS: orphan process doctor check adapter)
- .orphans (POS: orphan process detection and cleanup)
- .report (POS: doctor data models and CLI rendering)

[OUTPUT]
- run_doctor: pre-flight diagnostics orchestrator (re-export)
- check_memory / check_disk: host resource checks (re-export)
- check_orphan_processes / cleanup_orphan_processes / find_orphan_*: orphan process utilities (re-export)
- CheckStatus / DoctorCheckResult / DoctorReport / format_report: report contract (re-export)

[POS]
Doctor subpackage public facade. Single import point aggregating checks,
orphan_check, orphans, and report submodules for the harness CLI and server
health endpoints.
"""

from __future__ import annotations

from .checks import check_disk, check_memory, run_doctor
from .orphan_check import check_orphan_processes
from .orphans import (
    cleanup_orphan_processes,
    cleanup_stale_automation_sandboxes,
    find_orphan_automation_processes,
    find_orphan_chromium_processes,
    find_orphan_driver_processes,
    register_browser_exit_reaper,
    unregister_browser_exit_reaper,
)
from .report import (
    CheckStatus,
    DoctorCheckResult,
    DoctorReport,
    format_report,
)

__all__ = [
    "CheckStatus",
    "DoctorCheckResult",
    "DoctorReport",
    "check_disk",
    "check_memory",
    "check_orphan_processes",
    "cleanup_orphan_processes",
    "cleanup_stale_automation_sandboxes",
    "find_orphan_automation_processes",
    "find_orphan_chromium_processes",
    "find_orphan_driver_processes",
    "format_report",
    "register_browser_exit_reaper",
    "run_doctor",
    "unregister_browser_exit_reaper",
]
