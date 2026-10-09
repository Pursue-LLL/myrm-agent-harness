# [INPUT]: SubSessionFailureReport from orchestration_types
# [OUTPUT]: SubSessionFaultIsolator
# [POS]: myrm_agent_harness.agent.context_management.meta_session_orchestration.sub_session_fault_isolator
"""Sub-Session Crash Isolation and Parent Recovery Engine (Item 332).

Ensures unexpected failures, infinite loops, or unhandled tool exceptions in worker
sub-sessions are securely isolated and translated into actionable recovery reports.
"""

from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone
from typing import Final

from myrm_agent_harness.agent.context_management.meta_session_orchestration.orchestration_types import (
    SubSessionFailureReport,
)


class SubSessionFaultIsolator:
    """Thread-safe engine containing worker failures and suggesting deterministic recovery actions."""

    def __init__(self, max_allowed_retries: int = 2) -> None:
        self._lock = threading.RLock()
        self._max_retries: Final[int] = max_allowed_retries
        # (meta_session_id, task_id) -> retry_count
        self._retry_counts: dict[tuple[str, str], int] = {}
        # meta_session_id -> list of SubSessionFailureReport
        self._failure_history: dict[str, list[SubSessionFailureReport]] = {}

    def isolate_failure(
        self,
        task_id: str,
        meta_session_id: str,
        exc: Exception,
    ) -> SubSessionFailureReport:
        """Contain an exception thrown in a worker sub-session and generate a diagnostic report.

        Args:
            task_id: Failing worker sub-session identifier.
            meta_session_id: Parent meta-session identifier.
            exc: Caught python exception.

        Returns:
            Structured SubSessionFailureReport with recommended recovery strategy.
        """
        error_type = exc.__class__.__name__
        error_msg = str(exc) or "Unknown worker sub-session exception occurred"

        with self._lock:
            key = (meta_session_id, task_id)
            current_retries = self._retry_counts.get(key, 0)

            # Determine recovery recommendation based on retry history and error nature
            is_transient = any(
                keyword in error_type.lower() or keyword in error_msg.lower()
                for keyword in ("timeout", "rate", "connection", "temporary", "network")
            )

            if is_transient and current_retries < self._max_retries:
                suggested_recovery = "retry"
                self._retry_counts[key] = current_retries + 1
            elif "permission" in error_msg.lower() or "forbidden" in error_msg.lower():
                suggested_recovery = "parent_takeover"
            elif current_retries >= self._max_retries:
                suggested_recovery = "degrade"
            else:
                suggested_recovery = "parent_takeover"

            report = SubSessionFailureReport(
                task_id=task_id,
                meta_session_id=meta_session_id,
                error_type=error_type,
                error_message=error_msg,
                is_isolated=True,
                suggested_recovery=suggested_recovery,
                failure_timestamp_iso=datetime.now(timezone.utc).isoformat(),
            )

            history = self._failure_history.setdefault(meta_session_id, [])
            history.append(report)
            return report

    def get_failure_reports(self, meta_session_id: str) -> list[SubSessionFailureReport]:
        """Retrieve failure reports for a specific parent meta-session."""
        with self._lock:
            return list(self._failure_history.get(meta_session_id, []))

    def get_retry_count(self, meta_session_id: str, task_id: str) -> int:
        """Get number of times a sub-task has been retried."""
        with self._lock:
            return self._retry_counts.get((meta_session_id, task_id), 0)

    def reset_task(self, meta_session_id: str, task_id: str) -> None:
        """Clear retry history for a specific task."""
        with self._lock:
            self._retry_counts.pop((meta_session_id, task_id), None)

    def clear_session(self, meta_session_id: str) -> None:
        """Clear all failure reports and retry counts for a meta-session."""
        with self._lock:
            self._failure_history.pop(meta_session_id, None)
            keys_to_delete = [
                k for k in self._retry_counts if k[0] == meta_session_id
            ]
            for k in keys_to_delete:
                self._retry_counts.pop(k, None)
