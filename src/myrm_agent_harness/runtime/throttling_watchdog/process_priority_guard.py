"""Cross-platform process priority degradation guard for background intensive tasks.

Protects host desktop responsiveness during heavy ffmpeg or ML workloads:
- Adjusts operating system process scheduling priority (Nice values).
- Degrades background tasks to lowest priority to ensure desktop UI and mouse remain smooth.
- Gracefully handles permission or platform discrepancies without throwing exceptions.

[OUTPUT]
- ProcessPriorityGuard: Utility ensuring heavy subprocesses run at low scheduling priority.

[INPUT]
- __future__
- os

[OUTPUT]
- ProcessPriorityGuard

[POS]
Cross-platform process priority degradation guard for background intensive tasks.
"""

from __future__ import annotations

import os

from myrm_agent_harness.runtime.throttling_watchdog.throttling_types import (
    ProcessPriorityLevel,
)


class ProcessPriorityGuard:
    """Manages process priority degradation to safeguard host desktop responsiveness."""

    @staticmethod
    def set_priority(pid: int, level: ProcessPriorityLevel) -> bool:
        """Set process priority level for a given process identifier.

        Args:
            pid: Process ID to adjust.
            level: Desired priority level (FOREGROUND_NORMAL, BACKGROUND_LOW, IDLE_LOWEST).

        Returns:
            True if priority was successfully updated, False if platform or permissions disallow.
        """
        if not hasattr(os, "setpriority") or not hasattr(os, "PRIO_PROCESS"):
            return False

        try:
            # os.setpriority accepts (which, who, priority)
            os.setpriority(os.PRIO_PROCESS, pid, level.value)
            return True
        except (PermissionError, OSError, OverflowError):
            # Graceful degradation: never crash calling agent when priority cannot be altered
            return False

    @staticmethod
    def get_priority(pid: int) -> int | None:
        """Retrieve current nice priority of a process."""
        if not hasattr(os, "getpriority") or not hasattr(os, "PRIO_PROCESS"):
            return None

        try:
            return os.getpriority(os.PRIO_PROCESS, pid)
        except (PermissionError, OSError):
            return None

    @classmethod
    def apply_background_nice(cls, pid: int | None = None) -> bool:
        """Convenience method to degrade target or current process to BACKGROUND_LOW."""
        target_pid = pid if pid is not None else os.getpid()
        return cls.set_priority(target_pid, ProcessPriorityLevel.BACKGROUND_LOW)
