"""Zero-Token Visualization Contract Guard.

Enforces zero-token consumption for all fleet canvas, 3D office, and avatar UI layers
by mirroring deterministic runtime events and intercepting prohibited LLM calls.

[INPUT]
- __future__
- threading
- time
- collections
- types

[OUTPUT]
- ZeroTokenContractGuard

[POS]
Zero-Token Visualization Contract Guard.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from .types import (
    PROTECTED_VIZ_SURFACES,
    VizCallAuditRecord,
    ZeroTokenAuditSnapshot,
    ZeroTokenContractViolationError,
    ZeroTokenEvent,
)


class ZeroTokenContractGuard:
    """Enforces zero-token visualization contract for a specific session."""

    def __init__(self, chat_id: str, estimated_tokens_per_event: int = 150) -> None:
        self.chat_id: str = chat_id
        self._estimated_tokens_per_event: int = max(1, estimated_tokens_per_event)
        self._lock: threading.Lock = threading.Lock()

        self._mirrored_events: list[ZeroTokenEvent] = []
        self._violations: list[VizCallAuditRecord] = []
        self._total_events: int = 0
        self._violations_count: int = 0
        self._last_mirrored_at: float | None = None

    def mirror_runtime_event(self, event: ZeroTokenEvent) -> ZeroTokenAuditSnapshot:
        """Mirrors a deterministic runtime event without consuming any LLM tokens."""
        with self._lock:
            self._mirrored_events.append(event)
            self._total_events += 1
            self._last_mirrored_at = event.timestamp
            return self._build_snapshot_locked()

    def mirror_batch_events(
        self, events: Sequence[ZeroTokenEvent]
    ) -> ZeroTokenAuditSnapshot:
        """Mirrors a sequence of runtime events atomically."""
        with self._lock:
            for ev in events:
                self._mirrored_events.append(ev)
                self._total_events += 1
                self._last_mirrored_at = ev.timestamp
            return self._build_snapshot_locked()

    def intercept_llm_call(self, caller_surface: str, prompt: str) -> None:
        """Doctor guard that intercepts and blocks illegal LLM invocations from viz surfaces."""
        normalized_surface = caller_surface.strip().lower()

        # Check if caller matches any protected viz surface identifier
        is_protected = (
            normalized_surface in PROTECTED_VIZ_SURFACES
            or any(sub in normalized_surface for sub in ("viz", "canvas", "office_3d", "pet_animation"))
        )

        if is_protected:
            reason = (
                f"Violation detected: Surface '{caller_surface}' attempted an LLM call "
                f"({len(prompt)} chars). All visualization must subscribe to runtime events."
            )
            record = VizCallAuditRecord(
                caller_surface=caller_surface,
                prompt_chars=len(prompt),
                is_violation=True,
                intercepted_reason=reason,
                timestamp=time.time(),
            )
            with self._lock:
                self._violations.append(record)
                self._violations_count += 1

            raise ZeroTokenContractViolationError(
                surface=caller_surface,
                reason=reason,
            )

        # Allow non-visualization surfaces (e.g. core orchestrator, tool callers)
        return

    def get_audit_snapshot(self) -> ZeroTokenAuditSnapshot:
        """Returns the current Zero-Token compliance audit snapshot."""
        with self._lock:
            return self._build_snapshot_locked()

    def get_recent_events(self, limit: int = 50) -> list[ZeroTokenEvent]:
        """Returns the most recent mirrored runtime events up to limit."""
        with self._lock:
            return list(self._mirrored_events[-limit:])

    def reset(self) -> None:
        """Resets the audit ledger for the session."""
        with self._lock:
            self._mirrored_events.clear()
            self._violations.clear()
            self._total_events = 0
            self._violations_count = 0
            self._last_mirrored_at = None

    def _build_snapshot_locked(self) -> ZeroTokenAuditSnapshot:
        saved_tokens = self._total_events * self._estimated_tokens_per_event
        is_compliant = (self._violations_count == 0)
        recent_violations = list(self._violations[-10:])
        return ZeroTokenAuditSnapshot(
            chat_id=self.chat_id,
            total_events_mirrored=self._total_events,
            total_tokens_spent=0,  # Pure zero-token guarantee
            saved_tokens_estimated=saved_tokens,
            violations_intercepted=self._violations_count,
            is_compliant=is_compliant,
            recent_violations=recent_violations,
            last_mirrored_at=self._last_mirrored_at,
        )
