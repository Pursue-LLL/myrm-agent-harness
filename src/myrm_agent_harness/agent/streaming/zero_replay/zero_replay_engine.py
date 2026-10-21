"""[INPUT]
- SessionAtomicSnapshot, LiveStreamFilterConfig from .snapshot_models

[OUTPUT]
- ZeroReplayProtocolEngine: Core protocol gatekeeper compiling atomic snapshots and filtering live streams

[POS]
Harness framework layer implementation of Zero-Replay reconnect protocol.
Guarantees zero-event replay, eliminating UI flickering and message disorder upon client reconnects.
"""

from __future__ import annotations

import threading
import time
from typing import Literal

from .snapshot_models import (
    LiveStreamFilterConfig,
    SessionAtomicSnapshot,
    SessionLifecycleStatus,
)


class ZeroReplayProtocolEngine:
    """Thread-safe engine governing atomic state snapshots and live stream event gating."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._versions: dict[str, int] = {}
        self._epochs: dict[str, str] = {}

    def get_or_create_epoch(self, session_id: str) -> str:
        with self._lock:
            if session_id not in self._epochs:
                import uuid

                self._epochs[session_id] = uuid.uuid4().hex[:12]
            return self._epochs[session_id]

    def reset_epoch(self, session_id: str) -> str:
        with self._lock:
            import uuid

            new_epoch = uuid.uuid4().hex[:12]
            self._epochs[session_id] = new_epoch
            self._versions[session_id] = 1
            return new_epoch

    def increment_state_version(self, session_id: str) -> int:
        with self._lock:
            current = self._versions.get(session_id, 1)
            next_ver = current + 1
            self._versions[session_id] = next_ver
            return next_ver

    def get_current_version(self, session_id: str) -> int:
        with self._lock:
            return self._versions.get(session_id, 1)

    def compile_atomic_snapshot(
        self,
        session_id: str,
        status: SessionLifecycleStatus = "idle",
        leaf_entry_id: str | None = None,
        active_tool_calls: list[dict[str, str]] | None = None,
        message_count: int = 0,
        latest_turn_summary: str | None = None,
        artifacts_summary: list[dict[str, str]] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> SessionAtomicSnapshot:
        epoch_id = self.get_or_create_epoch(session_id)
        version = self.get_current_version(session_id)
        now_ms = time.time() * 1000.0

        return SessionAtomicSnapshot(
            session_id=session_id,
            epoch_id=epoch_id,
            state_version=version,
            snapshot_timestamp_ms=now_ms,
            status=status,
            leaf_entry_id=leaf_entry_id,
            active_tool_calls=active_tool_calls or [],
            message_count=message_count,
            latest_turn_summary=latest_turn_summary,
            artifacts_summary=artifacts_summary or [],
            metadata=metadata or {},
        )

    @classmethod
    def is_event_eligible_for_live_stream(
        cls,
        event_timestamp_ms: float,
        event_version: int,
        filter_config: LiveStreamFilterConfig,
    ) -> bool:
        """Determines if a stream event must be forwarded to the reconnecting live client.

        Zero-Replay Principle:
        Events with version <= client snapshot version are STRICTLY DROPPED.
        Historical events are never replayed over the live stream.
        """
        if event_version <= filter_config.client_state_version:
            return False

        if filter_config.allow_equal_timestamp:
            return event_timestamp_ms >= filter_config.client_snapshot_timestamp_ms
        return event_timestamp_ms > filter_config.client_snapshot_timestamp_ms

    @classmethod
    def evaluate_handshake(
        cls,
        client_epoch_id: str,
        client_version: int,
        server_snapshot: SessionAtomicSnapshot,
    ) -> Literal["continue_live", "require_full_snapshot_reload"]:
        """Evaluates reconnecting client handshake.

        If the client is on a stale epoch (e.g. server restarted or session cleared)
        or has negative version drift, force a full atomic snapshot reload.
        """
        if client_epoch_id != server_snapshot.epoch_id:
            return "require_full_snapshot_reload"

        if client_version > server_snapshot.state_version:
            # Client has phantom futuristic version (clock skew or corrupt local storage)
            return "require_full_snapshot_reload"

        return "continue_live"
