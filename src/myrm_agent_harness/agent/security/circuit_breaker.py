"""Session-scoped security circuit breaker for prompt injection quarantine and self-healing.

[INPUT]
- dataclasses::dataclass (POS: Python 数据类标准库)
- threading::Lock (POS: 线程同步锁)
- time::time (POS: Python 时间标准库)

[OUTPUT]
- CircuitBreakerTripInfo: Immutable record of the security incident triggering the breaker
- SessionCircuitBreaker: Thread-safe session circuit breaker registry
- get_global_session_circuit_breaker: Process-scoped singleton accessor

[POS]
Harness agent security layer. Manages session-level quarantine when indirect prompt
injection or honeytoken exfiltration is detected. Protects the agent from continuous
exploitation while allowing clean sessions to operate unhindered and enabling one-click user remediation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock

logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CircuitBreakerTripInfo:
    """Details of an outbound exfiltration or injection incident that tripped the breaker."""

    session_id: str
    token_name: str
    target_host: str
    reason: str
    tripped_at: float
    quarantine_active: bool = True

    def format_diagnostic(self) -> str:
        """User-friendly diagnostic text for UI cards and audit records."""
        return (
            f"Circuit breaker tripped for session '{self.session_id}'. "
            f"Blocked exfiltration of decoy '{self.token_name}' to '{self.target_host}'. "
            f"Reason: {self.reason}."
        )


class SessionCircuitBreaker:
    """Registry maintaining per-session circuit breaker trip states and quarantine policies."""

    def __init__(self) -> None:
        self._lock: Lock = Lock()
        self._tripped_sessions: dict[str, CircuitBreakerTripInfo] = {}

    def trip(
        self,
        session_id: str,
        token_name: str,
        target_host: str,
        reason: str = "Honeytoken exfiltration attempt",
    ) -> CircuitBreakerTripInfo:
        """Trip the circuit breaker for a given session into quarantine."""
        if not session_id:
            session_id = "default_session"

        info = CircuitBreakerTripInfo(
            session_id=session_id,
            token_name=token_name,
            target_host=target_host,
            reason=reason,
            tripped_at=time.time(),
            quarantine_active=True,
        )

        with self._lock:
            self._tripped_sessions[session_id] = info

        logger.critical(
            "[CIRCUIT_BREAKER] Tripped for session '%s' due to token '%s' exfiltration to %s",
            session_id,
            token_name,
            target_host,
        )
        return info

    def is_tripped(self, session_id: str) -> bool:
        """Check whether a session currently has an active quarantined circuit breaker."""
        if not session_id:
            return False
        with self._lock:
            info = self._tripped_sessions.get(session_id)
            return bool(info and info.quarantine_active)

    def get_trip_info(self, session_id: str) -> CircuitBreakerTripInfo | None:
        """Get the incident report if the session has tripped."""
        with self._lock:
            return self._tripped_sessions.get(session_id)

    def reset(self, session_id: str, operator: str = "user_remediation") -> bool:
        """Reset and restore normal operations for a session after context isolation."""
        with self._lock:
            if session_id in self._tripped_sessions:
                old_info = self._tripped_sessions[session_id]
                # Mark inactive while preserving history if needed
                self._tripped_sessions.pop(session_id, None)
                logger.info(
                    "[CIRCUIT_BREAKER] Reset session '%s' by operator '%s' (previous trip: %s)",
                    session_id,
                    operator,
                    old_info.token_name,
                )
                return True
        return False

    def clear_all(self) -> None:
        """Clear all session circuit breaker states."""
        with self._lock:
            self._tripped_sessions.clear()


_GLOBAL_CIRCUIT_BREAKER: SessionCircuitBreaker | None = None


def get_global_session_circuit_breaker() -> SessionCircuitBreaker:
    """Get or initialize the process singleton SessionCircuitBreaker."""
    global _GLOBAL_CIRCUIT_BREAKER
    if _GLOBAL_CIRCUIT_BREAKER is None:
        _GLOBAL_CIRCUIT_BREAKER = SessionCircuitBreaker()
    return _GLOBAL_CIRCUIT_BREAKER
