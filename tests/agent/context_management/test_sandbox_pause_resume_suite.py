"""Unit tests for Agentkit sandbox session pause, resume, and snapshot restoration suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.sandbox_pause_resume import (
    AgentkitPauseResumeSessionSandboxSuite,
    PauseResumeActionKind,
    PauseResumeReceipt,
    SandboxSessionRecord,
    SandboxSnapshotManifest,
    SessionLifecycleState,
)


def test_in_place_pause_and_resume_lifecycle() -> None:
    """Test standard session lifecycle: creation, pausing, in-place resume, and idempotency."""
    suite = AgentkitPauseResumeSessionSandboxSuite()
    session_id = "sandbox_sess_001"
    init_mem = {"workdir": "/workspace", "status": "active", "git_branch": "main"}

    rec: SandboxSessionRecord = suite.start_session(session_id=session_id, initial_memory=init_mem)
    assert rec.session_id == session_id
    assert rec.state == SessionLifecycleState.RUNNING

    # 1. Pause session
    receipt_pause: PauseResumeReceipt = suite.pause_session(
        session_id=session_id,
        dump_override={"workdir": "/workspace", "status": "suspended", "git_branch": "main"},
    )
    assert receipt_pause.success is True
    assert receipt_pause.action == PauseResumeActionKind.PAUSE
    assert receipt_pause.previous_state == SessionLifecycleState.RUNNING
    assert receipt_pause.current_state == SessionLifecycleState.PAUSED
    assert receipt_pause.state_checksum is not None

    # Idempotent pause
    receipt_pause_idem = suite.pause_session(session_id=session_id)
    assert receipt_pause_idem.success is True
    assert receipt_pause_idem.current_state == SessionLifecycleState.PAUSED
    assert "already paused" in receipt_pause_idem.message

    # 2. In-place resume
    receipt_resume: PauseResumeReceipt = suite.resume_session(session_id=session_id)
    assert receipt_resume.success is True
    assert receipt_resume.action == PauseResumeActionKind.RESUME_IN_PLACE
    assert receipt_resume.previous_state == SessionLifecycleState.PAUSED
    assert receipt_resume.current_state == SessionLifecycleState.RUNNING

    # Idempotent resume
    receipt_resume_idem = suite.resume_session(session_id=session_id)
    assert receipt_resume_idem.success is True
    assert receipt_resume_idem.current_state == SessionLifecycleState.RUNNING
    assert "already running" in receipt_resume_idem.message


def test_snapshot_creation_and_integrity_verification() -> None:
    """Test creating read-only snapshot manifests and verifying cryptographic checksum."""
    suite = AgentkitPauseResumeSessionSandboxSuite()
    session_id = "sandbox_sess_002"
    suite.start_session(
        session_id=session_id,
        initial_memory={"env": "prod", "checkpoint": "step_42"},
        metadata={"tenant": "team_alpha"},
    )

    manifest: SandboxSnapshotManifest = suite.take_snapshot(
        session_id=session_id,
        snapshot_id="snap_custom_42",
        metadata={"trigger": "manual_backup"},
    )

    assert manifest.snapshot_id == "snap_custom_42"
    assert manifest.source_session_id == session_id
    assert manifest.verify_integrity() is True
    assert suite.verify_snapshot_integrity("snap_custom_42") is True

    # Tampered snapshot fails integrity check
    tampered = SandboxSnapshotManifest(
        snapshot_id="tampered_snap",
        source_session_id=session_id,
        created_at_utc=manifest.created_at_utc,
        state_dump={"env": "corrupted"},
        checksum=manifest.checksum,
    )
    assert tampered.verify_integrity() is False


def test_branch_from_snapshot_independent_continuation() -> None:
    """Test restoring an independent branch from a snapshot with isolated memory state."""
    suite = AgentkitPauseResumeSessionSandboxSuite()
    orig_session_id = "sandbox_parent_001"
    suite.start_session(
        session_id=orig_session_id,
        initial_memory={"counter": "100", "node": "root"},
    )

    snap = suite.take_snapshot(session_id=orig_session_id, snapshot_id="snap_root_100")
    assert snap.verify_integrity() is True

    # Restore new branch session
    branch_session_id = "sandbox_branch_child_001"
    branch_receipt: PauseResumeReceipt = suite.branch_from_snapshot(
        snapshot_id="snap_root_100",
        new_session_id=branch_session_id,
        metadata={"fork_reason": "exploratory_task"},
    )

    assert branch_receipt.success is True
    assert branch_receipt.action == PauseResumeActionKind.RESUME_FROM_SNAPSHOT
    assert branch_receipt.source_session_id == orig_session_id
    assert branch_receipt.current_state == SessionLifecycleState.RUNNING

    # Verify state isolation
    parent_sess = suite.inspect_session(orig_session_id)
    child_sess = suite.inspect_session(branch_session_id)

    assert child_sess.parent_snapshot_id == "snap_root_100"
    assert child_sess.current_memory["counter"] == "100"

    # Modify child memory
    child_sess.current_memory["counter"] = "999"
    assert parent_sess.current_memory["counter"] == "100"
    assert child_sess.current_memory["counter"] == "999"

    # Audit summary
    summary = suite.get_session_audit_summary(branch_session_id)
    assert summary["session_id"] == branch_session_id
    assert summary["parent_snapshot_id"] == "snap_root_100"
    assert summary["state"] == "running"


def test_lifecycle_error_handling_and_termination_guard() -> None:
    """Test guardrails against invalid state transitions and operations on terminated sessions."""
    suite = AgentkitPauseResumeSessionSandboxSuite()
    session_id = "sandbox_sess_term"
    suite.start_session(session_id=session_id, initial_memory={"key": "val"})

    # Terminate session
    term_receipt = suite.terminate_session(session_id=session_id)
    assert term_receipt.action == PauseResumeActionKind.TERMINATE
    assert term_receipt.current_state == SessionLifecycleState.TERMINATED

    # Terminated session rejects pause, resume, snapshot
    with pytest.raises(RuntimeError, match="Cannot pause terminated session"):
        suite.pause_session(session_id=session_id)

    with pytest.raises(RuntimeError, match="Cannot resume terminated session"):
        suite.resume_session(session_id=session_id)

    with pytest.raises(RuntimeError, match="Cannot take snapshot of terminated session"):
        suite.take_snapshot(session_id=session_id)

    # Restoring non-existent snapshot raises KeyError
    with pytest.raises(KeyError, match="Snapshot 'missing_snap' not found"):
        suite.branch_from_snapshot(
            snapshot_id="missing_snap",
            new_session_id="sandbox_branch_fail",
        )

    # Re-registering existing session raises ValueError
    with pytest.raises(ValueError, match="already registered"):
        suite.start_session(session_id=session_id)
