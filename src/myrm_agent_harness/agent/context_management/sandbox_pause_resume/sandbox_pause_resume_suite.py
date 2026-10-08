# [INPUT]: sandbox_pause_resume_engine.py, session_pause_types.py
# [OUTPUT]: AgentkitPauseResumeSessionSandboxSuite
# [POS]: agent/context_management/sandbox_pause_resume/sandbox_pause_resume_suite.py

"""End-to-end orchestration suite for sandbox session pause, resume, and snapshot operations.

[INPUT]
- agent.context_management.sandbox_pause_resume.sandbox_pause_resume_engine::SandboxPauseResumeEngine
  (POS: State-machine engine executing lifecycle mutations.)
- agent.context_management.sandbox_pause_resume.session_pause_types::compute_state_checksum,
  PauseResumeReceipt, SandboxSessionRecord, SandboxSnapshotManifest, SessionLifecycleState
  (POS: Strongly typed domain models and audit receipts.)

[OUTPUT]
- AgentkitPauseResumeSessionSandboxSuite: High-level orchestration facade providing complete lifecycle management,
  integrity verification, and diagnostic auditing for sandbox sessions.

[POS]
Integration suite for sandbox session suspension, hot in-place continuation, and snapshot-based branching.
"""

from __future__ import annotations

from .sandbox_pause_resume_engine import SandboxPauseResumeEngine
from .session_pause_types import (
    compute_state_checksum,
    PauseResumeReceipt,
    SandboxSessionRecord,
    SandboxSnapshotManifest,
    SessionLifecycleState,
)


class AgentkitPauseResumeSessionSandboxSuite:
    """Unified facade managing sandbox session suspension, resumption, and snapshot branching."""

    def __init__(self, engine: SandboxPauseResumeEngine | None = None) -> None:
        self._engine = engine or SandboxPauseResumeEngine()

    @property
    def engine(self) -> SandboxPauseResumeEngine:
        """Access underlying state engine."""
        return self._engine

    def start_session(
        self,
        session_id: str,
        initial_memory: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> SandboxSessionRecord:
        """Start a new sandbox session in running state.

        Args:
            session_id: Unique session identifier.
            initial_memory: Optional initial key-value state.
            metadata: Optional metadata tags.

        Returns:
            Created SandboxSessionRecord.
        """
        return self._engine.register_session(
            session_id=session_id,
            initial_memory=initial_memory,
            metadata=metadata,
        )

    def pause_session(
        self,
        session_id: str,
        dump_override: dict[str, str] | None = None,
    ) -> PauseResumeReceipt:
        """Pause and suspend an active sandbox session.

        Args:
            session_id: Identifier of the target session.
            dump_override: Optional state dump payload override.

        Returns:
            PauseResumeReceipt recording the pause outcome.
        """
        return self._engine.pause_session(session_id=session_id, dump_override=dump_override)

    def resume_session(self, session_id: str) -> PauseResumeReceipt:
        """In-place hot resume of an existing paused sandbox session.

        Args:
            session_id: Identifier of the session to resume.

        Returns:
            PauseResumeReceipt recording in-place continuation.
        """
        return self._engine.resume_session(session_id=session_id)

    def take_snapshot(
        self,
        session_id: str,
        snapshot_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> SandboxSnapshotManifest:
        """Create an immutable read-only snapshot manifest of a session.

        Args:
            session_id: Target session identifier.
            snapshot_id: Optional explicit snapshot id.
            metadata: Optional snapshot metadata.

        Returns:
            Validated SandboxSnapshotManifest.
        """
        return self._engine.create_snapshot(
            session_id=session_id,
            snapshot_id=snapshot_id,
            metadata=metadata,
        )

    def branch_from_snapshot(
        self,
        snapshot_id: str,
        new_session_id: str,
        metadata: dict[str, str] | None = None,
    ) -> PauseResumeReceipt:
        """Restore and branch a new independent sandbox session from a snapshot.

        Args:
            snapshot_id: Snapshot identifier to branch from.
            new_session_id: New independent session identifier.
            metadata: Optional metadata for branched session.

        Returns:
            PauseResumeReceipt recording branch creation.
        """
        return self._engine.resume_session_from_snapshot(
            snapshot_id=snapshot_id,
            new_session_id=new_session_id,
            metadata=metadata,
        )

    def terminate_session(self, session_id: str) -> PauseResumeReceipt:
        """Terminate a sandbox session and release execution context.

        Args:
            session_id: Identifier of the session to terminate.

        Returns:
            PauseResumeReceipt recording termination.
        """
        return self._engine.terminate_session(session_id=session_id)

    def inspect_session(self, session_id: str) -> SandboxSessionRecord:
        """Inspect current state and attributes of a sandbox session.

        Args:
            session_id: Identifier of the session.

        Returns:
            SandboxSessionRecord instance.
        """
        return self._engine.get_session(session_id=session_id)

    def verify_snapshot_integrity(self, snapshot_id: str) -> bool:
        """Verify cryptographic integrity of a registered snapshot manifest.

        Args:
            snapshot_id: Identifier of the snapshot to verify.

        Returns:
            True if state dump matches checksum, False otherwise.
        """
        manifest = self._engine._snapshots.get(snapshot_id)
        if manifest is None:
            return False
        return manifest.verify_integrity()

    def get_session_audit_summary(self, session_id: str) -> dict[str, str]:
        """Generate high-level diagnostic summary for a session.

        Args:
            session_id: Identifier of the target session.

        Returns:
            Dictionary with audit metadata strings.
        """
        session = self._engine.get_session(session_id)
        checksum = compute_state_checksum(session.current_memory)
        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "turn_count": str(session.turn_count),
            "parent_snapshot_id": session.parent_snapshot_id or "none",
            "state_checksum": checksum,
            "memory_key_count": str(len(session.current_memory)),
        }
