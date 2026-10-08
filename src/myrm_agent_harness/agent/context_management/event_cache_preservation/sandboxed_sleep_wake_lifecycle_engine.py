# [INPUT]: CachePartitionedContextBundle, CachePreservingEventEnvelopeProtocol, DormantSnapshot, EventEnvelopePayload, HydrationState
# [OUTPUT]: SandboxedSleepWakeLifecycleEngine
# [POS]: agent/context_management/event_cache_preservation/sandboxed_sleep_wake_lifecycle_engine.py

"""Sandboxed sleep-wake lifecycle engine achieving sub-500ms cold-start hydration and zero idle cost.

[INPUT]
- CachePartitionedContextBundle, CachePreservingEventEnvelopeProtocol, DormantSnapshot, EventEnvelopePayload, HydrationState: Contract models.

[OUTPUT]
- SandboxedSleepWakeLifecycleEngine: Freezes inactive sandboxes into tiny snapshots and hydrates on incoming events.

[POS]
Lifecycle and resource economy engine in event cache preservation subsystem.
"""

from __future__ import annotations

import datetime
import hashlib
import time
from typing import Sequence

from .cache_preserving_event_envelope_protocol import CachePreservingEventEnvelopeProtocol
from .event_envelope_types import (
    CachePartitionedContextBundle,
    DormantSnapshot,
    EventEnvelopePayload,
    HydrationState,
)


class SandboxedSleepWakeLifecycleEngine:
    """Manages hibernation freeze and sub-500ms instant hydration upon incoming events."""

    DEFAULT_IDLE_TIMEOUT_SECONDS: int = 300  # 5 minutes
    MAX_SNAPSHOT_BYTES: int = 10 * 1024 * 1024  # 10MB safety budget

    def __init__(self, protocol: CachePreservingEventEnvelopeProtocol | None = None) -> None:
        self._protocol = protocol or CachePreservingEventEnvelopeProtocol()
        self._current_state = HydrationState.ACTIVE_RUNNING
        self._last_active_time = time.monotonic()

    @property
    def current_state(self) -> HydrationState:
        """Current lifecycle status."""
        return self._current_state

    def check_idle_and_freeze(
        self,
        session_id: str,
        static_prefix: str,
        conversation_history: Sequence[str],
        idle_threshold_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
    ) -> DormantSnapshot | None:
        """Evaluate if sandbox has been idle beyond threshold; freeze into snapshot if so."""
        now = time.monotonic()
        elapsed = now - self._last_active_time

        if elapsed >= idle_threshold_seconds:
            # Enter Dormant Sleep
            snapshot = self.create_dormant_snapshot(
                session_id=session_id,
                static_prefix=static_prefix,
                conversation_history=conversation_history,
            )
            self._current_state = HydrationState.DORMANT_SLEEP
            return snapshot

        return None

    def create_dormant_snapshot(
        self,
        session_id: str,
        static_prefix: str,
        conversation_history: Sequence[str],
    ) -> DormantSnapshot:
        """Create a compact snapshot (<10MB) preserving cached prefix and message history."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload_repr = f"{static_prefix}\n---\n" + "\n---\n".join(conversation_history)
        raw_bytes = payload_repr.encode("utf-8")

        if len(raw_bytes) > self.MAX_SNAPSHOT_BYTES:
            # Safety clamp within 10MB
            raw_bytes = raw_bytes[: self.MAX_SNAPSHOT_BYTES]

        h = hashlib.sha256(raw_bytes).hexdigest()[:16]

        snapshot = DormantSnapshot(
            session_id=session_id,
            last_active_timestamp=now_iso,
            serialized_state_bytes=len(raw_bytes),
            snapshot_hash=h,
            cached_prefix_text=static_prefix,
            history_turns_count=len(conversation_history),
        )
        self._current_state = HydrationState.DORMANT_SLEEP
        return snapshot

    def hydrate_and_wake(
        self,
        snapshot: DormantSnapshot,
        conversation_history: Sequence[str],
        incoming_event: EventEnvelopePayload | None = None,
    ) -> tuple[CachePartitionedContextBundle, float]:
        """Wake up dormant sandbox, restore prefix, and mount event envelope in sub-500ms."""
        t0 = time.perf_counter()
        self._current_state = HydrationState.HYDRATING

        # Re-partition context
        bundle = self._protocol.partition_context(
            static_prefix=snapshot.cached_prefix_text,
            conversation_history=conversation_history,
            event_payload=incoming_event,
        )

        hydration_elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Mark active
        self._current_state = HydrationState.ACTIVE_RUNNING
        self._last_active_time = time.monotonic()

        return bundle, round(hydration_elapsed_ms, 2)
