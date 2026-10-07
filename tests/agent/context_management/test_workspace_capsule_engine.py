# ============================================================================
# Unit Tests for Session Workspace Mobility & Cloud Offload Gateway (Item 163)
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.mobility import (
    BidirectionalMergeGuard,
    CloudWorkerOffloadGateway,
    FileChangeKind,
    MergeConflictItem,
    OffloadTargetKind,
    OffloadTransferReceipt,
    SyncMergeReport,
    WorkspaceCapsule,
    WorkspaceCapsulePacker,
    WorkspaceFileEntry,
)


def test_capsule_packing_and_verification() -> None:
    """Validate capsule packing, deterministic hashing, and integrity tampering defense."""
    files = [
        ("src/main.py", FileChangeKind.CREATED, "print('hello world')"),
        ("README.md", FileChangeKind.MODIFIED, "# Project Myrm\nUpdated doc"),
    ]

    capsule = WorkspaceCapsulePacker.create_capsule(
        session_id="sess-mob-1",
        files=files,
        base_checkpoint_hash="git-commit-abc1234",
        execution_progress_note="Step 3/5: Tests generated",
    )

    assert capsule.session_id == "sess-mob-1"
    assert len(capsule.files) == 2
    assert capsule.files[0].path == "README.md"  # Deterministic path sorting
    assert capsule.files[1].path == "src/main.py"

    # Integrity verification
    assert WorkspaceCapsulePacker.verify_capsule(capsule) is True

    # Tampered file content fails
    tampered_entry = WorkspaceFileEntry(
        path=capsule.files[0].path,
        kind=capsule.files[0].kind,
        content="Tampered content",
        content_hash=capsule.files[0].content_hash,  # Mismatch!
        byte_size=len("Tampered content"),
    )
    tampered_capsule = WorkspaceCapsule(
        capsule_id=capsule.capsule_id,
        session_id=capsule.session_id,
        created_at_iso=capsule.created_at_iso,
        base_checkpoint_hash=capsule.base_checkpoint_hash,
        files=(tampered_entry, capsule.files[1]),
        execution_progress_note=capsule.execution_progress_note,
        capsule_digest=capsule.capsule_digest,
    )
    assert WorkspaceCapsulePacker.verify_capsule(tampered_capsule) is False


def test_capsule_export_and_import_roundtrip() -> None:
    """Validate standard JSON export and import roundtrip with automatic verification."""
    files = [
        ("config.json", FileChangeKind.CREATED, '{"key": "value"}'),
    ]
    capsule = WorkspaceCapsulePacker.create_capsule(
        session_id="sess-export-01",
        files=files,
        base_checkpoint_hash="hash-001",
    )

    json_str = WorkspaceCapsulePacker.export_capsule_json(capsule)
    assert "sess-export-01" in json_str
    assert "config.json" in json_str

    imported = WorkspaceCapsulePacker.import_capsule_json(json_str)
    assert imported.capsule_id == capsule.capsule_id
    assert imported.capsule_digest == capsule.capsule_digest
    assert len(imported.files) == 1
    assert imported.files[0].content == '{"key": "value"}'


def test_cloud_worker_offload_dispatch() -> None:
    """Validate dispatching capsule to remote cloud worker returns verified receipt."""
    capsule = WorkspaceCapsulePacker.create_capsule(
        session_id="sess-offload-99",
        files=[("run.sh", FileChangeKind.CREATED, "pytest tests/")],
        base_checkpoint_hash="git-base",
    )

    receipt = CloudWorkerOffloadGateway.dispatch_offload(
        capsule=capsule,
        target_kind=OffloadTargetKind.CLOUD_SANDBOX_WORKER,
        target_endpoint="https://sandbox.myrm.cloud/v1/sessions/offload",
    )

    assert receipt.capsule_id == capsule.capsule_id
    assert receipt.session_id == "sess-offload-99"
    assert receipt.target_kind == OffloadTargetKind.CLOUD_SANDBOX_WORKER
    assert receipt.status == "transferred_and_acknowledged"


def test_bidirectional_merge_guard_clean_and_conflict() -> None:
    """Validate clean delta application and concurrent conflict interception."""
    base_files = {
        "existing.py": "def foo(): pass",
    }
    # 1. Clean merge scenario: local matches base, remote brings updates
    local_files = {
        "existing.py": "def foo(): pass",
    }
    remote_capsule_clean = WorkspaceCapsulePacker.create_capsule(
        session_id="sess-clean",
        files=[
            ("new_file.py", FileChangeKind.CREATED, "def new(): pass"),
            ("existing.py", FileChangeKind.MODIFIED, "def foo(): return 42"),
        ],
        base_checkpoint_hash="git-base-same",
    )

    updated_local, report_clean = BidirectionalMergeGuard.apply_remote_delta(
        local_files=local_files,
        remote_capsule=remote_capsule_clean,
        base_files=base_files,
    )
    assert report_clean.is_clean_merge is True
    assert report_clean.applied_files_count == 2
    assert updated_local["existing.py"] == "def foo(): return 42"
    assert updated_local["new_file.py"] == "def new(): pass"

    # 2. Conflict scenario: local file was concurrently modified away from base
    local_modified = {
        "existing.py": "def foo(): print('local concurrent modification')",
    }
    # Remote incoming also changed existing.py
    _, report_conflict = BidirectionalMergeGuard.apply_remote_delta(
        local_files=local_modified,
        remote_capsule=remote_capsule_clean,
        base_files=base_files,
    )
    assert report_conflict.is_clean_merge is False
    assert len(report_conflict.conflicts) == 1
    assert report_conflict.conflicts[0].file_path == "existing.py"
    assert "Concurrent modification detected" in report_conflict.conflicts[0].conflict_reason
