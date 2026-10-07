"""Tests for Instant Cloud Session Snapshot Restore and Zero-Clone Warm Pool Suite (Item 231)."""

import pytest

from myrm_agent_harness.agent.context_management.cloud_snapshot import (
    CloudSnapshotConfig,
    IncrementalPatchBundle,
    InstantCloudSnapshotRestoreEngine,
    SandboxPoolState,
    SnapshotRestoreResult,
    SnapshotStorageDriver,
    VolumeSnapshotDescriptor,
    WarmSandboxDescriptor,
)


def test_baseline_snapshot_registration_and_retrieval() -> None:
    """Verify registration and lookup of heavy frozen workspace volume snapshots."""
    engine = InstantCloudSnapshotRestoreEngine(CloudSnapshotConfig())

    snapshot_id = "snap-heavy-repo-node20-500mb"
    desc = engine.create_baseline_snapshot(
        snapshot_id=snapshot_id,
        base_repo_ref="github.com/myrm-org/fullstack-app@main#commit-abc1234",
        workspace_root="/var/volumes/myrm_baselines/fullstack-app",
        dependencies_hash="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        estimated_size_bytes=524288000,  # Exactly 500 MB
        storage_driver=SnapshotStorageDriver.COW_OVERLAY,
        metadata={"pkg_manager": "pnpm", "node_version": "20.11.0"},
    )

    assert desc.snapshot_id == snapshot_id
    assert desc.estimated_size_bytes == 524288000
    assert desc.storage_driver == SnapshotStorageDriver.COW_OVERLAY
    assert desc.metadata.get("pkg_manager") == "pnpm"

    retrieved = engine.get_snapshot(snapshot_id)
    assert retrieved is not None
    assert retrieved.base_repo_ref == desc.base_repo_ref

    all_snapshots = engine.list_snapshots()
    assert len(all_snapshots) == 1


def test_prewarmed_sandbox_pool_claim_and_recycle() -> None:
    """Verify pre-warmed sandbox pool leases workers in milliseconds and handles exhaustion gracefully."""
    config = CloudSnapshotConfig(warm_pool_size=3, sandbox_lease_ttl_seconds=600.0)
    engine = InstantCloudSnapshotRestoreEngine(config)

    # Initial state: 3 idle workers
    status = engine.get_pool_status()
    assert status[SandboxPoolState.WARM_IDLE.value] == 3
    assert status[SandboxPoolState.CLAIMED_BUSY.value] == 0

    # Claim 1st sandbox
    sbx1 = engine.claim_sandbox(session_id="session-user-alpha")
    assert sbx1.state == SandboxPoolState.CLAIMED_BUSY
    assert sbx1.assigned_session_id == "session-user-alpha"
    assert sbx1.lease_expiry_timestamp is not None

    status_after_one = engine.get_pool_status()
    assert status_after_one[SandboxPoolState.WARM_IDLE.value] == 2
    assert status_after_one[SandboxPoolState.CLAIMED_BUSY.value] == 1

    # Claim remaining 2
    sbx2 = engine.claim_sandbox(session_id="session-user-beta")
    sbx3 = engine.claim_sandbox(session_id="session-user-gamma")
    assert engine.get_pool_status()[SandboxPoolState.WARM_IDLE.value] == 0

    # Pool exhausted: 4th claim triggers dynamic on-demand provisioning
    sbx4 = engine.claim_sandbox(session_id="session-user-delta")
    assert sbx4.state == SandboxPoolState.CLAIMED_BUSY
    assert sbx4.assigned_session_id == "session-user-delta"
    assert "sbx-ondemand-" in sbx4.sandbox_id

    # Release worker back to warm pool
    released = engine.release_sandbox(sbx1.sandbox_id)
    assert released
    status_recycled = engine.get_pool_status()
    assert status_recycled[SandboxPoolState.WARM_IDLE.value] == 1


def test_sub_800ms_zero_clone_restore_with_cow() -> None:
    """Verify sub-800ms instant session restore for 500MB workspace using zero-clone CoW overlay."""
    engine = InstantCloudSnapshotRestoreEngine(CloudSnapshotConfig(max_restore_latency_ms=800.0))

    snapshot_id = "snap-production-monorepo-500mb"
    engine.create_baseline_snapshot(
        snapshot_id=snapshot_id,
        base_repo_ref="github.com/myrm-org/heavy-monorepo@v2.4.0",
        workspace_root="/var/volumes/myrm_baselines/heavy-monorepo",
        dependencies_hash="sha256:d8e8fca2dc0f896fd7cb4cb0031ba249",
        estimated_size_bytes=500 * 1024 * 1024,  # 500MB
        storage_driver=SnapshotStorageDriver.COW_OVERLAY,
    )

    session_id = "sess-instant-restore-998"
    result: SnapshotRestoreResult = engine.restore_session_instantaneously(
        session_id=session_id,
        snapshot_id=snapshot_id,
        target_mount_base="/tmp/myrm_sandboxes",
    )

    assert result.session_id == session_id
    assert result.is_zero_clone
    assert result.driver_used == SnapshotStorageDriver.COW_OVERLAY
    # Enforce sub-800ms hard performance SLA
    assert result.duration_ms < 800.0
    assert "/cow_upper" in result.active_workspace_path
    assert not result.patch_applied
    assert result.patch_files_count == 0


def test_incremental_patch_streaming_application() -> None:
    """Verify lightweight incremental git patch streams without full repository network transfer."""
    engine = InstantCloudSnapshotRestoreEngine(CloudSnapshotConfig())

    snapshot_id = "snap-base-dev"
    engine.create_baseline_snapshot(
        snapshot_id=snapshot_id,
        base_repo_ref="github.com/myrm-org/app@main",
        workspace_root="/var/volumes/myrm_baselines/app",
        dependencies_hash="sha256:11223344",
        storage_driver=SnapshotStorageDriver.HARDLINK_REF,
    )

    patch = IncrementalPatchBundle(
        patch_id="patch-fix-typo-001",
        source_commit="commit-aaa",
        target_commit="commit-bbb",
        diff_content="diff --git a/src/index.ts b/src/index.ts\n--- a/src/index.ts\n+++ b/src/index.ts\n@@ -1 +1 @@\n-const x = 1;\n+const x = 2;",
        affected_paths=("src/index.ts", "package.json"),
    )

    result = engine.restore_session_instantaneously(
        session_id="sess-patched-flow",
        snapshot_id=snapshot_id,
        patch_bundle=patch,
    )

    assert result.patch_applied
    assert result.patch_files_count == 2
    assert result.duration_ms < 800.0
    assert result.is_zero_clone
