# [INPUT] decoupled_dreaming package modules
# [OUTPUT] Comprehensive unit test suite for decoupled memory consolidation and dreaming state sync
# [POS] Tests for direct drive I/O, biological dreaming consolidation, lock-free broadcasting, and suite facade

"""Comprehensive unit tests for DecoupledMemoryConsolidationSuite."""

from pathlib import Path
import time
import pytest

from myrm_agent_harness.agent import (
    DecoupledMemoryConsolidationDreamingEngineAndServerlessStateSyncSuite,
    DecoupledMemoryConsolidationSuite,
    DirectMemoryDriveChannel,
    LockFreeSnapshotBroadcaster,
    NightlyDreamingPipeline,
)
from myrm_agent_harness.agent.context_management import (
    ConsolidatedEntityConcept,
    DreamingConsolidationReport,
    GoldenMemorySnapshot,
    MemoryDriveSpec,
    MemoryLogEntry,
)


def test_top_level_exports() -> None:
    """Verify all public types, facades, and aliases are exported correctly."""
    assert (
        DecoupledMemoryConsolidationDreamingEngineAndServerlessStateSyncSuite
        is DecoupledMemoryConsolidationSuite
    )


def test_direct_memory_drive_channel_io_and_atomic_persistence(tmp_path: Path) -> None:
    """Verify direct detached drive volume directory layout, logging, and atomic snapshot write."""
    drive_spec = MemoryDriveSpec(
        drive_id="user_drive_01",
        mount_path=str(tmp_path / "memory_volume"),
    )

    # 1. Append log entries
    entries = [
        MemoryLogEntry(
            entry_id="e1",
            session_id="s1",
            timestamp_unix=1700000000.0,
            role="user",
            content="We use PostgreSQL as the primary database.",
            category="architecture",
            importance_score=0.9,
        ),
        MemoryLogEntry(
            entry_id="e2",
            session_id="s1",
            timestamp_unix=1700000010.0,
            role="assistant",
            content="Understood. PostgreSQL configured.",
            category="architecture",
            importance_score=0.5,
        ),
    ]

    appended = DirectMemoryDriveChannel.append_log_entries(drive_spec, entries)
    assert appended == 2

    # 2. Read back log entries
    loaded_entries = DirectMemoryDriveChannel.read_log_entries(drive_spec, since_timestamp=0.0)
    assert len(loaded_entries) == 2
    assert loaded_entries[0].entry_id == "e1"
    assert "PostgreSQL" in loaded_entries[0].content

    # 3. Save golden snapshot
    concept = ConsolidatedEntityConcept(
        concept_id="c1",
        canonical_name="PostgreSQL",
        aliases=["pg", "postgres"],
        attributes={"category": "database"},
        confidence=0.95,
        source_entry_ids=["e1"],
        last_reinforced_unix=1700000000.0,
    )
    snapshot = GoldenMemorySnapshot(
        snapshot_id="snap_v1_test",
        version=1,
        timestamp_unix=1700000020.0,
        drive_id=drive_spec.drive_id,
        concepts=[concept],
        checksum_sha256="test_checksum_hash",
        total_entries_compacted=2,
    )

    saved_path = DirectMemoryDriveChannel.save_golden_snapshot(drive_spec, snapshot)
    assert saved_path.exists()
    assert "golden_v1.json" in saved_path.name

    # 4. Load latest snapshot
    loaded_snapshot = DirectMemoryDriveChannel.load_latest_snapshot(drive_spec)
    assert loaded_snapshot is not None
    assert loaded_snapshot.version == 1
    assert loaded_snapshot.concepts[0].canonical_name == "PostgreSQL"
    assert loaded_snapshot.concepts[0].confidence == 0.95

    # 5. Read-only drive protection
    ro_spec = MemoryDriveSpec(
        drive_id="ro_drive",
        mount_path=str(tmp_path / "memory_volume"),
        read_only=True,
    )
    with pytest.raises(PermissionError):
        DirectMemoryDriveChannel.append_log_entries(ro_spec, entries)


def test_nightly_dreaming_pipeline_consolidation_and_decay_pruning() -> None:
    """Verify decay scoring, stale pruning, entity aliasing, and snapshot synthesis."""
    drive_spec = MemoryDriveSpec(
        drive_id="dream_drive",
        mount_path="/mock/mount",
    )

    now = time.time()
    old_time = now - (40 * 86400.0)  # 40 days ago

    raw_entries = [
        # Stale low-importance log -> should be pruned
        MemoryLogEntry(
            entry_id="stale_1",
            session_id="old_sess",
            timestamp_unix=old_time,
            role="user",
            content="Thanks, goodbye!",
            importance_score=0.1,
        ),
        # Fresh important log with aliases -> should consolidate
        MemoryLogEntry(
            entry_id="fresh_1",
            session_id="active_sess",
            timestamp_unix=now,
            role="user",
            content="Make sure Docker and TypeScript are installed.",
            importance_score=0.8,
        ),
        MemoryLogEntry(
            entry_id="fresh_2",
            session_id="active_sess",
            timestamp_unix=now,
            role="user",
            content="Also verify k8s cluster connection.",
            importance_score=0.8,
        ),
    ]

    snapshot, report = NightlyDreamingPipeline.run_dreaming_consolidation(
        drive_spec=drive_spec,
        raw_entries=raw_entries,
        existing_snapshot=None,
        stale_threshold_days=30.0,
    )

    assert report.success is True
    assert report.scanned_entries == 3
    assert report.pruned_stale_entries == 1
    assert snapshot.version == 1
    assert len(snapshot.concepts) >= 2

    concept_names = [c.canonical_name for c in snapshot.concepts]
    assert "Docker" in concept_names
    assert "Kubernetes" in concept_names or "TypeScript" in concept_names

    # Run second dream iteration on top of existing snapshot
    new_entries = [
        MemoryLogEntry(
            entry_id="fresh_3",
            session_id="active_sess_2",
            timestamp_unix=now,
            role="user",
            content="Deploy new container with Docker.",
            importance_score=0.9,
        )
    ]
    snap_v2, report_v2 = NightlyDreamingPipeline.run_dreaming_consolidation(
        drive_spec=drive_spec,
        raw_entries=new_entries,
        existing_snapshot=snapshot,
    )
    assert snap_v2.version == 2
    # Verify confidence reinforcement
    docker_c = next(c for c in snap_v2.concepts if c.canonical_name == "Docker")
    assert docker_c.confidence >= 0.85


def test_lock_free_snapshot_broadcaster_pub_sub_and_ack() -> None:
    """Verify lock-free notification broadcasting and acknowledgement to concurrent sandboxes."""
    broadcaster = LockFreeSnapshotBroadcaster()
    broadcaster.register_sandbox("sandbox_worker_1")
    broadcaster.register_sandbox("sandbox_worker_2")

    active = broadcaster.get_active_sandboxes()
    assert "sandbox_worker_1" in active
    assert "sandbox_worker_2" in active

    snapshot = GoldenMemorySnapshot(
        snapshot_id="golden_snap_abc",
        version=1,
        timestamp_unix=time.time(),
        drive_id="shared_drive",
        concepts=[],
        checksum_sha256="hash_12345",
    )

    notification = broadcaster.broadcast_snapshot(snapshot)
    assert notification.snapshot_id == "golden_snap_abc"
    assert len(notification.target_sandbox_ids) == 2

    # Check pending notifications
    pending_1 = broadcaster.get_pending_notifications("sandbox_worker_1")
    assert len(pending_1) == 1
    assert pending_1[0].snapshot_id == "golden_snap_abc"

    # Acknowledge notification
    ack_res = broadcaster.acknowledge_notification("sandbox_worker_1", "golden_snap_abc")
    assert ack_res is True

    # Sandbox 1 should now have 0 pending notifications
    assert len(broadcaster.get_pending_notifications("sandbox_worker_1")) == 0
    # Sandbox 2 still has 1 pending
    assert len(broadcaster.get_pending_notifications("sandbox_worker_2")) == 1

    # Deregister sandbox
    broadcaster.unregister_sandbox("sandbox_worker_2")
    assert "sandbox_worker_2" not in broadcaster.get_active_sandboxes()


def test_decoupled_dreaming_suite_end_to_end(tmp_path: Path) -> None:
    """Verify complete end-to-end dreaming lifecycle via DecoupledMemoryConsolidationSuite."""
    drive_spec = MemoryDriveSpec(
        drive_id="user_master_drive",
        mount_path=str(tmp_path / "master_volume"),
    )

    # 1. Record interaction logs
    entries = [
        MemoryLogEntry(
            entry_id="log_1",
            session_id="sess_001",
            timestamp_unix=time.time(),
            role="user",
            content="We are building with Python and SQLite.",
            category="core",
            importance_score=0.9,
        ),
    ]
    count = DecoupledMemoryConsolidationSuite.record_interaction_logs(drive_spec, entries)
    assert count == 1

    # 2. Setup broadcaster
    broadcaster = DecoupledMemoryConsolidationSuite.create_broadcaster()
    broadcaster.register_sandbox("agent_sandbox_live")

    # 3. Execute nightly dreaming
    snapshot, report = DecoupledMemoryConsolidationSuite.execute_nightly_dreaming(
        drive_spec=drive_spec,
        broadcaster=broadcaster,
    )
    assert report.success is True
    assert snapshot.version == 1
    assert any(c.canonical_name in ("Python", "SQLite") for c in snapshot.concepts)

    # Verify broadcast received by live sandbox
    notifications = broadcaster.get_pending_notifications("agent_sandbox_live")
    assert len(notifications) == 1
    assert notifications[0].version == 1

    # 4. Load golden view directly
    golden_view = DecoupledMemoryConsolidationSuite.load_golden_memory_view(drive_spec)
    assert golden_view is not None
    assert golden_view.snapshot_id == snapshot.snapshot_id
