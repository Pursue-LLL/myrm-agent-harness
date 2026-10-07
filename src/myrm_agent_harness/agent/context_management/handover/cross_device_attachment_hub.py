"""Central bus orchestrating cross-device session handover and terminal attachment.

[INPUT]
- agent.context_management.handover.handover_types::AttachmentCatchupSnapshot, AttachmentMode, DeviceInfo,
  DeviceKind, HandoverSessionHandle, SessionExecutionState, TerminalOutputChunk (POS: Types and models for
  handover.)

[OUTPUT]
- TerminalOutputRingBuffer: Fixed-capacity ring buffer capturing latest terminal stdout/stderr chunks.
- ActiveSessionAttachmentHub: Central bus orchestrating cross-device session handover and terminal attachment.

[POS]
Central bus orchestrating cross-device session handover and terminal attachment.
"""

# ============================================================================
# Active Session Attachment Hub & Cross-Device Handover Engine (Item 159)
# Manages cross-device session registration, terminal PTY output ring buffer,
# instantaneous snapshot catch-up replay, and background detachment handover.
# ============================================================================

from __future__ import annotations

import collections
import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from .handover_types import (
    AttachmentCatchupSnapshot,
    AttachmentMode,
    DeviceInfo,
    DeviceKind,
    HandoverSessionHandle,
    SessionExecutionState,
    TerminalOutputChunk,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RING_BUFFER_CHUNKS = 1_000


class TerminalOutputRingBuffer:
    """Fixed-capacity ring buffer capturing latest terminal stdout/stderr chunks."""

    def __init__(self, max_chunks: int = _DEFAULT_MAX_RING_BUFFER_CHUNKS) -> None:
        self._max_chunks: int = max_chunks
        self._chunks: collections.deque[TerminalOutputChunk] = collections.deque(
            maxlen=max_chunks
        )
        self._chunk_counter: int = 0

    def append(self, stream: str, content: str) -> TerminalOutputChunk:
        """Append an output chunk to the ring buffer with auto-incrementing ID."""
        self._chunk_counter += 1
        chunk = TerminalOutputChunk(
            chunk_id=self._chunk_counter,
            stream=stream,
            content=content,
        )
        self._chunks.append(chunk)
        return chunk

    def get_snapshot(self) -> tuple[TerminalOutputChunk, ...]:
        """Get complete instantaneous snapshot of buffered terminal output."""
        return tuple(self._chunks)

    def get_chunks_since(self, last_chunk_id: int) -> tuple[TerminalOutputChunk, ...]:
        """Get newly arrived chunks strictly after given chunk ID for delta catch-up."""
        return tuple(c for c in self._chunks if c.chunk_id > last_chunk_id)

    @property
    def latest_chunk_id(self) -> int:
        """Return the highest emitted chunk ID."""
        return self._chunk_counter


class _SessionAttachmentEntry:
    """Internal mutable tracking entry for an attached session."""

    __slots__ = (
        "session_id",
        "title",
        "state",
        "controller_device_id",
        "observer_device_ids",
        "ring_buffer",
        "created_at_iso",
        "updated_at_iso",
        "reconnect_token",
    )

    def __init__(self, session_id: str, title: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        self.session_id: str = session_id
        self.title: str = title
        self.state: SessionExecutionState = SessionExecutionState.IDLE
        self.controller_device_id: str | None = None
        self.observer_device_ids: set[str] = set()
        self.ring_buffer: TerminalOutputRingBuffer = TerminalOutputRingBuffer()
        self.created_at_iso: str = now_iso
        self.updated_at_iso: str = now_iso
        self.reconnect_token: str = f"reconnect-{uuid.uuid4().hex[:16]}"


class ActiveSessionAttachmentHub:
    """Central bus orchestrating cross-device session handover and terminal attachment."""

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionAttachmentEntry] = {}
        self._devices: dict[str, DeviceInfo] = {}

    def register_session(
        self,
        session_id: str,
        title: str,
        initial_device: DeviceInfo | None = None,
    ) -> HandoverSessionHandle:
        """Register an active session handle for cross-device visibility."""
        entry = _SessionAttachmentEntry(session_id=session_id, title=title)
        if initial_device is not None:
            self._devices[initial_device.device_id] = initial_device
            entry.controller_device_id = initial_device.device_id
            entry.state = SessionExecutionState.RUNNING

        self._sessions[session_id] = entry
        logger.info(
            "Registered session '%s' with initial device '%s'",
            session_id,
            initial_device.device_id if initial_device else "None",
        )
        return self._to_handle(entry)

    def attach_device(
        self,
        session_id: str,
        device: DeviceInfo,
        mode: AttachmentMode = AttachmentMode.EXCLUSIVE_STEER,
    ) -> AttachmentCatchupSnapshot:
        """Attach a device to an active session with instantaneous snapshot catch-up."""
        entry = self._sessions.get(session_id)
        if entry is None:
            raise KeyError(f"Session '{session_id}' not found in active attachment hub.")

        self._devices[device.device_id] = device
        now_iso = datetime.now(timezone.utc).isoformat()
        entry.updated_at_iso = now_iso

        if mode == AttachmentMode.EXCLUSIVE_STEER:
            # Transfer execution steering ownership to new device
            old_controller = entry.controller_device_id
            if old_controller and old_controller != device.device_id:
                # Demote previous controller to observer
                entry.observer_device_ids.add(old_controller)
            entry.observer_device_ids.discard(device.device_id)
            entry.controller_device_id = device.device_id
            if entry.state == SessionExecutionState.DETACHED_BACKGROUND:
                entry.state = SessionExecutionState.RUNNING
        else:
            # Shared read-only mirroring observation
            if entry.controller_device_id != device.device_id:
                entry.observer_device_ids.add(device.device_id)

        # Build instantaneous catch-up snapshot
        history_chunks = entry.ring_buffer.get_snapshot()
        last_id = entry.ring_buffer.latest_chunk_id

        return AttachmentCatchupSnapshot(
            session_id=session_id,
            state=entry.state,
            history_output_chunks=history_chunks,
            last_chunk_id=last_id,
            active_controller_device_id=entry.controller_device_id,
            reconnect_token=entry.reconnect_token,
        )

    def detach_device(
        self,
        session_id: str,
        device_id: str,
        keep_background: bool = True,
    ) -> HandoverSessionHandle:
        """Detach a device when stepping away or closing app."""
        entry = self._sessions.get(session_id)
        if entry is None:
            raise KeyError(f"Session '{session_id}' not found in active attachment hub.")

        entry.observer_device_ids.discard(device_id)
        if entry.controller_device_id == device_id:
            entry.controller_device_id = None
            if keep_background:
                entry.state = SessionExecutionState.DETACHED_BACKGROUND
                logger.info(
                    "Controller device '%s' detached; session '%s' persists in background.",
                    device_id,
                    session_id,
                )
            else:
                entry.state = SessionExecutionState.IDLE

        entry.updated_at_iso = datetime.now(timezone.utc).isoformat()
        return self._to_handle(entry)

    def broadcast_terminal_output(
        self,
        session_id: str,
        stream: str,
        content: str,
    ) -> TerminalOutputChunk:
        """Record and broadcast incremental terminal output stream."""
        entry = self._sessions.get(session_id)
        if entry is None:
            raise KeyError(f"Session '{session_id}' not found in active attachment hub.")

        chunk = entry.ring_buffer.append(stream=stream, content=content)
        entry.updated_at_iso = datetime.now(timezone.utc).isoformat()
        return chunk

    def poll_incremental_output(
        self,
        session_id: str,
        last_chunk_id: int,
    ) -> tuple[TerminalOutputChunk, ...]:
        """Poll newly produced chunks since client's last observed chunk ID."""
        entry = self._sessions.get(session_id)
        if entry is None:
            raise KeyError(f"Session '{session_id}' not found in active attachment hub.")

        return entry.ring_buffer.get_chunks_since(last_chunk_id)

    def update_session_state(
        self,
        session_id: str,
        new_state: SessionExecutionState,
    ) -> HandoverSessionHandle:
        """Update session execution lifecycle state."""
        entry = self._sessions.get(session_id)
        if entry is None:
            raise KeyError(f"Session '{session_id}' not found in active attachment hub.")

        entry.state = new_state
        entry.updated_at_iso = datetime.now(timezone.utc).isoformat()
        return self._to_handle(entry)

    def list_active_sessions(self) -> tuple[HandoverSessionHandle, ...]:
        """List all active session handles currently registered in the hub."""
        return tuple(self._to_handle(entry) for entry in self._sessions.values())

    def get_session(self, session_id: str) -> HandoverSessionHandle | None:
        """Get session handle by ID or None if absent."""
        entry = self._sessions.get(session_id)
        return self._to_handle(entry) if entry is not None else None

    @staticmethod
    def _to_handle(entry: _SessionAttachmentEntry) -> HandoverSessionHandle:
        return HandoverSessionHandle(
            session_id=entry.session_id,
            title=entry.title,
            state=entry.state,
            active_controller_device_id=entry.controller_device_id,
            attached_observers=tuple(sorted(entry.observer_device_ids)),
            created_at_iso=entry.created_at_iso,
            updated_at_iso=entry.updated_at_iso,
        )
