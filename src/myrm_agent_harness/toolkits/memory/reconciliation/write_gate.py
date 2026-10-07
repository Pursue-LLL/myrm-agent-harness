"""[POS]: src/myrm_agent_harness/toolkits/memory/reconciliation/write_gate.py
[INPUT]: WriteGatePolicy enums, session IDs, and runtime execution contexts.
[OUTPUT]: MemoryWriteGate decoupling read/write paths and enforcing explicit typed write permissions.
"""

from __future__ import annotations

from threading import Lock

from .models import WriteGateCheckResult, WriteGatePolicy


class MemoryWriteBlockedError(RuntimeError):
    """Raised when a memory write operation is rejected by the active write gate policy."""


class MemoryWriteGate:
    """Explicit gate decoupler enforcing read-always-open vs write-permission-checked policies."""

    def __init__(self, default_policy: WriteGatePolicy = WriteGatePolicy.ENABLED) -> None:
        self._lock = Lock()
        self._global_policy = default_policy
        self._session_overrides: dict[str, WriteGatePolicy] = {}

    @property
    def global_policy(self) -> WriteGatePolicy:
        """Returns the current global write policy."""
        with self._lock:
            return self._global_policy

    def set_global_policy(self, policy: WriteGatePolicy) -> None:
        """Updates the global memory write gate policy."""
        with self._lock:
            self._global_policy = policy

    def set_session_policy(self, session_id: str, policy: WriteGatePolicy) -> None:
        """Sets a session-specific write gate policy override."""
        with self._lock:
            self._session_overrides[session_id] = policy

    def clear_session_policy(self, session_id: str) -> None:
        """Removes a session-specific policy override."""
        with self._lock:
            self._session_overrides.pop(session_id, None)

    def check_write_allowed(self, session_id: str | None = None) -> WriteGateCheckResult:
        """Evaluates whether memory writes are currently authorized for the given session.

        Note: Reading is NEVER governed or blocked by this gate.
        """
        with self._lock:
            policy = self._session_overrides.get(session_id, self._global_policy) if session_id else self._global_policy

        if policy == WriteGatePolicy.ENABLED:
            return WriteGateCheckResult(
                is_allowed=True,
                policy=policy,
                reason="Memory writes are explicitly enabled.",
            )

        if policy == WriteGatePolicy.READ_ONLY_SESSION:
            return WriteGateCheckResult(
                is_allowed=False,
                policy=policy,
                reason="Session is configured in strict read-only mode to prevent side-effects.",
            )

        if policy == WriteGatePolicy.DISABLED_TEMPORARY:
            return WriteGateCheckResult(
                is_allowed=False,
                policy=policy,
                reason="Memory writing is temporarily suspended during inspection or maintenance.",
            )

        return WriteGateCheckResult(
            is_allowed=False,
            policy=policy,
            reason="Memory writes are blocked due to an unverified or corrupted system configuration.",
        )

    def ensure_write_allowed(self, session_id: str | None = None) -> None:
        """Raises MemoryWriteBlockedError if writes are not authorized."""
        check = self.check_write_allowed(session_id=session_id)
        if not check.is_allowed:
            raise MemoryWriteBlockedError(f"Memory write denied [{check.policy.value}]: {check.reason}")
