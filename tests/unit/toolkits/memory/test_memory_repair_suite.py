"""[POS]: tests/unit/toolkits/memory/test_memory_repair_suite.py
[INPUT]: Unit test suite for memory integrity repair, stale entry pruning, and cache preservation.
[OUTPUT]: Fully verified test cases asserting self-healing, decay pruning, and barrier stability.
"""

import sqlite3
import time

from myrm_agent_harness.toolkits.memory.repair import (
    CachePreservingCompactionBarrier,
    DatabaseAutoHealer,
    DatabaseIntegrityDetector,
    HealthMetric,
    IntegrityCheckReport,
    IntegrityStatus,
    MemoryRecordItem,
    MemoryRepairService,
    PruneSummary,
    RepairActionStatus,
    RepairReport,
    StaleEntryPruner,
    StalePrunePolicy,
)


def _create_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE myrm_memories (
            id TEXT PRIMARY KEY,
            content TEXT,
            created_at_epoch REAL,
            last_recalled_at_epoch REAL,
            recall_count INTEGER DEFAULT 0,
            is_pinned INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active'
        )
        """
    )
    cursor.execute(
        """
        CREATE VIRTUAL TABLE myrm_memory_fts USING fts5(
            content,
            content='myrm_memories',
            content_rowid='rowid'
        )
        """
    )
    conn.commit()
    return conn


def test_integrity_check_on_healthy_database() -> None:
    conn = _create_test_db()
    detector = DatabaseIntegrityDetector(conn)
    report: IntegrityCheckReport = detector.inspect()

    assert report.db_status == IntegrityStatus.HEALTHY
    assert report.fts_healthy is True
    assert len(report.issues) == 0
    assert "myrm_memories" in report.table_counts
    conn.close()


def test_auto_healer_rebuild_and_checkpoint() -> None:
    conn = _create_test_db()
    healer = DatabaseAutoHealer(conn)
    report: RepairReport = healer.heal()

    assert report.status == RepairActionStatus.SUCCESS
    assert any("REINDEX" in item for item in report.repaired_items)
    assert any("FTS5 rebuild" in item for item in report.repaired_items)
    assert any("wal_checkpoint" in item for item in report.repaired_items)
    assert len(report.error_details) == 0
    conn.close()


def test_stale_pruner_utility_decay_and_pinned_guard() -> None:
    pruner = StaleEntryPruner()
    now_epoch = 1_000_000.0

    # 1. Pinned entry: 60 days old, 0 recalls -> must be protected
    pinned_entry = MemoryRecordItem(
        id="mem-pinned",
        content="User prefers Python over TypeScript",
        created_at_epoch=now_epoch - (60 * 86400.0),
        last_recalled_at_epoch=now_epoch - (60 * 86400.0),
        recall_count=0,
        is_pinned=True,
        status="active",
    )

    # 2. Fresh entry: 5 days old, 1 recall -> must be active
    fresh_entry = MemoryRecordItem(
        id="mem-fresh",
        content="Current task branch is feature-x",
        created_at_epoch=now_epoch - (5 * 86400.0),
        last_recalled_at_epoch=now_epoch - (5 * 86400.0),
        recall_count=1,
        is_pinned=False,
        status="active",
    )

    # 3. Stale entry: 45 days old, 0 recalls -> must be archived
    stale_entry = MemoryRecordItem(
        id="mem-stale",
        content="Temporary IP was 192.168.1.50",
        created_at_epoch=now_epoch - (45 * 86400.0),
        last_recalled_at_epoch=now_epoch - (45 * 86400.0),
        recall_count=0,
        is_pinned=False,
        status="active",
    )

    entries = [pinned_entry, fresh_entry, stale_entry]
    policy = StalePrunePolicy(stale_days_threshold=30, protect_pinned=True, dry_run=False)

    summary: PruneSummary = pruner.evaluate_entries(entries, policy, now_epoch=now_epoch)

    assert summary.evaluated_count == 3
    assert summary.archived_count == 1
    assert summary.protected_count == 2
    assert summary.archived_ids == ["mem-stale"]
    assert stale_entry.status == "archived"
    assert pinned_entry.status == "active"
    assert fresh_entry.status == "active"


def test_database_table_prune_and_health_metric() -> None:
    conn = _create_test_db()
    cursor = conn.cursor()
    now_epoch = time.time()
    old_epoch = now_epoch - (40 * 86400.0)

    # Insert 1 pinned, 1 fresh, 1 stale
    cursor.execute(
        "INSERT INTO myrm_memories VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("id-1", "Permanent rule", old_epoch, old_epoch, 0, 1, "active"),
    )
    cursor.execute(
        "INSERT INTO myrm_memories VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("id-2", "Recent note", now_epoch, now_epoch, 5, 0, "active"),
    )
    cursor.execute(
        "INSERT INTO myrm_memories VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("id-3", "Old temporary meeting", old_epoch, old_epoch, 0, 0, "active"),
    )
    conn.commit()

    service = MemoryRepairService(conn)

    # Health check before prune
    metric_before: HealthMetric = service.get_health_metric()
    assert metric_before.total_entries == 3
    assert metric_before.active_entries == 3
    assert metric_before.stale_entries == 1
    assert metric_before.integrity_status == IntegrityStatus.HEALTHY
    assert metric_before.overall_health_score < 100.0  # slight penalty for stale entry

    # Execute database prune
    policy = StalePrunePolicy(stale_days_threshold=30, protect_pinned=True)
    summary: PruneSummary = service.prune_stale_entries(table_name="myrm_memories", policy=policy)

    assert summary.archived_count == 1
    assert summary.archived_ids == ["id-3"]

    # Health check after prune
    metric_after: HealthMetric = service.get_health_metric()
    assert metric_after.total_entries == 3
    assert metric_after.active_entries == 2
    assert metric_after.stale_entries == 0
    assert metric_after.overall_health_score == 100.0
    conn.close()


def test_cache_preserving_compaction_barrier() -> None:
    barrier = CachePreservingCompactionBarrier()
    session_id = "session-test-42"
    prefix_prompt = "System: You are an expert AI software architect."

    hash_val = barrier.register_session_snapshot(session_id, prefix_prompt)
    assert len(hash_val) == 64
    assert barrier.is_session_active(session_id) is True
    assert barrier.can_compact_safely(session_id) is False

    # Pruning mutation should be deferred while session is active
    deferred = barrier.defer_compaction_if_active(session_id, ["id-10", "id-11"])
    assert deferred is True

    # Releasing session drains deferred compactions
    drained_ids = barrier.release_session(session_id)
    assert drained_ids == ["id-10", "id-11"]
    assert barrier.is_session_active(session_id) is False
    assert barrier.can_compact_safely(session_id) is True
