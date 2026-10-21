"""In-process counters for web fetch remote escalation (thread-safe).

[POS]
Thread-safe escalation counters for logging or export during remote fetch escalation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class WebFetchEscalationMetrics:
    """Thread-safe escalation counters for logging or export."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    triggered_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    session_cap_blocked_count: int = 0

    def record_triggered(self) -> None:
        with self._lock:
            self.triggered_count += 1

    def record_success(self) -> None:
        with self._lock:
            self.success_count += 1

    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1

    def record_session_cap_blocked(self) -> None:
        with self._lock:
            self.session_cap_blocked_count += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "triggered_count": self.triggered_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "session_cap_blocked_count": self.session_cap_blocked_count,
            }


web_fetch_escalation_metrics = WebFetchEscalationMetrics()
