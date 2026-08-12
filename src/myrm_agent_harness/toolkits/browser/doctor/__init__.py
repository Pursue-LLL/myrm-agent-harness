"""Browser Doctor — pre-flight diagnostics and health checks.

Validates dependencies, configuration, environment, and browser launchability
before actual operations. Provides clear fix suggestions for each failure.
Includes precise orphan process detection (matches patchright/playwright cache
paths) with safety mechanisms (dry-run default, force flag required for cleanup).

This package is the public facade for the doctor subdomain; it re-exports every
symbol from the internal ``checks``, ``orphans``, and ``report`` modules so that
``myrm_agent_harness.toolkits.browser.doctor`` remains a single import point.
"""

from __future__ import annotations

from .checks import (
    _check_browser_executable,  # noqa: F401 — re-exported for backward-compatible imports
    _check_browser_launch,  # noqa: F401
    _check_camoufox,  # noqa: F401
    _check_disk,  # noqa: F401
    _check_extension_relay,  # noqa: F401
    _check_memory,  # noqa: F401
    _check_patchright,  # noqa: F401
    _check_proxy,  # noqa: F401
    run_doctor,
)
from .orphans import (
    _extract_user_data_dir,  # noqa: F401 — re-exported for backward-compatible imports
    _is_automation_cache_path,  # noqa: F401
    _is_automation_driver_cmdline,  # noqa: F401
    check_orphan_processes,
    cleanup_orphan_processes,
    find_orphan_automation_processes,
    find_orphan_chromium_processes,
    find_orphan_driver_processes,
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
    "check_orphan_processes",
    "cleanup_orphan_processes",
    "find_orphan_automation_processes",
    "find_orphan_chromium_processes",
    "find_orphan_driver_processes",
    "format_report",
    "run_doctor",
]
