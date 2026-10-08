# [INPUT]: session_pause_types.py
# [OUTPUT]: SandboxPauseResumeEngine
# [POS]: agent/context_management/sandbox_pause_resume/sandbox_pause_resume_engine.py

"""Core execution engine for sandbox session pause, in-place resume, and snapshot branching.

[INPUT]
- agent.context_management.sandbox_pause_resume.session_pause_types::compute_state_checksum,
  PauseResumeActionKind, PauseResumeReceipt, SandboxSessionRecord, SandboxSnapshotManifest,
  SessionLifecycleState (POS: Strongly typed domain models for session lifecycle and snapshot manifests.)

[OUTPUT]
- SandboxPauseResumeEngine: State-machine engine executing atomic pause, in-place resume,
  snapshot creation, and independent branching restoration.

[POS]
Lifecycle coordination engine for sandbox session suspend and resume workflows.
"""

from __future__ import annotations

import time

from .session_pause_types import (
    compute_state_checksum,
    PauseResumeActionKind,
    PauseResumeReceipt,
    SandboxSessionRecord,
    SandboxSnapshotManifest,
    SessionLifecycleState,
)


class SandboxPauseResumeEngine:
    """Coordinates lifecycle transitions and snapshot branching for sandbox sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SandboxSessionRecord] = {}
        self._snapshots: dict[str, SandboxSnapshotManifest] = {}

    def register_session(
        self,
        session_id: str,
        initial_memory: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> SandboxSessionRecord:
        """Register a new active sandbox session.

        Args:
            session_id: Unique session identifier.
            initial_memory: Optional initial key-value state variables.
            metadata: Optional administrative metadata tags.

        Returns:
            The created SandboxSessionRecord in RUNNING state.

        Raises:
            ValueError: If session_id already exists.
        """
        if session_id in self._sessions:
            msg = f"Session '{session_id}' already registered."
            raise ValueError(msg)

        record = SandboxSessionRecord(
            session_id=session_id,
            state=SessionLifecycleState.RUNNING,
            current_memory=dict(initial_memory or {}),
            created_at_utc=time.time(),
            metadata=dict(metadata or {}),
        )
        self._sessions[session_id] = record
        return record

    def get_session(self, session_id: str) -> SandboxSessionRecord:
        """Retrieve a session by its identifier.

        Args:
            session_id: The identifier of the session.

        Returns:
            SandboxSessionRecord instance.

        Raises:
            KeyError: If session_id is not found.
        """
        if session_id not in self._sessions:
            msg = f"Session '{session_id}' not found."
            raise KeyError(msg)
        return self._sessions[session_id]

    def has_session(self, session_id: str) -> bool:
        """Check whether a session exists."""
        return session_id in self._sessions

    def pause_session(
        self,
        session_id: str,
        dump_override: dict[str, str] | None = None,
    ) -> PauseResumeReceipt:
        """Suspend and pause an active running sandbox session.

        Args:
            session_id: Identifier of the session to pause.
            dump_override: Optional state dump to supersede memory on pause.

        Returns:
            PauseResumeReceipt recording state transition.

        Raises:
            KeyError: If session_id is not found.
            RuntimeError: If session is already terminated.
        """
        session = self.get_session(session_id)
        prev_state = session.state

        if prev_state == SessionLifecycleState.TERMINATED:
            msg = f"Cannot pause terminated session '{session_id}'."
            raise RuntimeError(msg)

        if prev_state == SessionLifecycleState.PAUSED:
            chk = compute_state_checksum(session.current_memory)
            return PauseResumeReceipt(
                action=PauseResumeActionKind.PAUSE,
                session_id=session_id,
                source_session_id=None,
                previous_state=SessionLifecycleState.PAUSED,
                current_state=SessionLifecycleState.PAUSED,
                timestamp_utc=time.time(),
                snapshot_id=None,
                success=True,
                message="Session was already paused (idempotent).",
                state_checksum=chk,
            )

        if dump_override is not None:
            session.current_memory = dict(dump_override)

        now = time.time()
        session.state = SessionLifecycleState.PAUSED
        session.last_paused_at_utc = now
        chk = compute_state_checksum(session.current_memory)

        return PauseResumeReceipt(
            action=PauseResumeActionKind.PAUSE,
            session_id=session_id,
            source_session_id=None,
            previous_state=prev_state,
            current_state=SessionLifecycleState.PAUSED,
            timestamp_utc=now,
            snapshot_id=None,
            success=True,
            message="Session successfully paused.",
            state_checksum=chk,
        )

    def resume_session(self, session_id: str) -> PauseResumeReceipt:
        """In-place warm resume of a paused sandbox session.

        Args:
            session_id: Identifier of the session to resume.

        Returns:
            PauseResumeReceipt recording resume transition.

        Raises:
            KeyError: If session_id is not found.
            RuntimeError: If session is terminated.
        """
        session = self.get_session(session_id)
        prev_state = session.state

        if prev_state == SessionLifecycleState.TERMINATED:
            msg = f"Cannot resume terminated session '{session_id}'."
            raise RuntimeError(msg)

        if prev_state == SessionLifecycleState.RUNNING:
            chk = compute_state_checksum(session.current_memory)
            return PauseResumeReceipt(
                action=PauseResumeActionKind.RESUME_IN_PLACE,
                session_id=session_id,
                source_session_id=None,
                previous_state=SessionLifecycleState.RUNNING,
                current_state=SessionLifecycleState.RUNNING,
                timestamp_utc=time.time(),
                snapshot_id=None,
                success=True,
                message="Session was already running (idempotent).",
                state_checksum=chk,
            )

        now = time.time()
        session.state = SessionLifecycleState.RUNNING
        session.last_resumed_at_utc = now
        chk = compute_state_checksum(session.current_memory)

        return PauseResumeReceipt(
            action=PauseResumeActionKind.RESUME_IN_PLACE,
            session_id=session_id,
            source_session_id=None,
            previous_state=prev_state,
            current_state=SessionLifecycleState.RUNNING,
            timestamp_utc=now,
            snapshot_id=None,
            success=True,
            message="Session successfully resumed in-place.",
            state_checksum=chk,
        )

    def create_snapshot(
        self,
        session_id: str,
        snapshot_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> SandboxSnapshotManifest:
        """Create an immutable read-only snapshot manifest of a session.

        Args:
            session_id: Identifier of the target session.
            snapshot_id: Optional explicit snapshot identifier.
            metadata: Optional metadata tags to attach.

        Returns:
            SandboxSnapshotManifest with verified checksum.

        Raises:
            KeyError: If session_id is not found.
            RuntimeError: If session is terminated.
        """
        session = self.get_session(session_id)
        if session.state == SessionLifecycleState.TERMINATED:
            msg = f"Cannot take snapshot of terminated session '{session_id}'."
            raise RuntimeError(msg)

        now = time.time()
        sid = snapshot_id or f"snap_{session_id}_{int(now * 1000)}"
        memory_copy = dict(session.current_memory)
        chk = compute_state_checksum(memory_copy)

        manifest = SandboxSnapshotManifest(
            snapshot_id=sid,
            source_session_id=session_id,
            created_at_utc=now,
            state_dump=memory_copy,
            checksum=chk,
            metadata=dict(metadata or {}),
        )
        self._snapshots[sid] = manifest
        return manifest

    def resume_session_from_snapshot(
        self,
        snapshot_id: str,
        new_session_id: str,
        metadata: dict[str, str] | None = None,
    ) -> PauseResumeReceipt:
        """Restore and branch a new independent sandbox session from a snapshot.

        Args:
            snapshot_id: The snapshot identifier to restore from.
            new_session_id: The new independent session identifier.
            metadata: Optional metadata for the new session.

        Returns:
            PauseResumeReceipt recording branch creation from snapshot.

        Raises:
            KeyError: If snapshot_id is not found.
            ValueError: If snapshot checksum fails integrity check or new_session_id exists.
        """
        if snapshot_id not in self._snapshots:
            msg = f"Snapshot '{snapshot_id}' not found."
            raise KeyError(msg)

        manifest = self._snapshots[snapshot_id]
        if not manifest.verify_integrity():
            msg = f"Snapshot '{snapshot_id}' integrity validation failed."
            raise ValueError(msg)

        if new_session_id in self._sessions:
            msg = f"Session '{new_session_id}' already exists."
            raise ValueError(msg)

        now = time.time()
        merged_meta = dict(manifest.metadata)
        if metadata:
            merged_meta.update(metadata)

        branched_record = SandboxSessionRecord(
            session_id=new_session_id,
            state=SessionLifecycleState.RUNNING,
            current_memory=dict(manifest.state_dump),
            created_at_utc=now,
            parent_snapshot_id=snapshot_id,
            metadata=merged_meta,
        )
        self._sessions[new_session_id] = branched_record
        chk = compute_state_checksum(branched_record.current_memory)

        return PauseResumeReceipt(
            action=PauseResumeActionKind.RESUME_FROM_SNAPSHOT,
            session_id=new_session_id,
            source_session_id=manifest.source_session_id,
            previous_state=SessionLifecycleState.PAUSED,
            current_state=SessionLifecycleState.RUNNING,
            timestamp_utc=now,
            snapshot_id=snapshot_id,
            success=True,
            message=f"Branch session '{new_session_id}' restored from snapshot '{snapshot_id}'.",
            state_checksum=chk,
        )

    def terminate_session(self, session_id: str) -> PauseResumeReceipt:
        """Terminate a sandbox session and mark its lifecycle finished.

        Args:
            session_id: Identifier of the session to terminate.

        Returns:
            PauseResumeReceipt recording termination.

        Raises:
            KeyError: If session_id is not found.
        """
        session = self.get_session(session_id)
        prev = session.state
        now = time.time()
        session.state = SessionLifecycleState.TERMINATED
        chk = compute_state_checksum(session.current_memory)

        return PauseResumeReceipt(
            action=PauseResumeActionKind.TERMINATE,
            session_id=session_id,
            source_session_id=None,
            previous_state=prev,
            current_state=SessionLifecycleState.TERMINATED,
            timestamp_utc=now,
            snapshot_id=None,
            success=True,
            message="Session terminated.",
            state_checksum=chk,
        )
