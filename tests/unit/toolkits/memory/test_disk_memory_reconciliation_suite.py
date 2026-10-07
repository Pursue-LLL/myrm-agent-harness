"""[POS]: tests/unit/toolkits/memory/test_disk_memory_reconciliation_suite.py
[INPUT]: Temporary directories, markdown files, DiskMemoryFtsReconciler, and MemoryWriteGate.
[OUTPUT]: Unit tests verifying write-gate policies, Direction A indexing, and Direction B dead-row pruning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.reconciliation import (
    DiskMemoryFtsReconciler,
    MemoryWriteBlockedError,
    MemoryWriteGate,
    WriteGatePolicy,
)


def test_memory_write_gate_decoupling_and_exceptions() -> None:
    """Verifies that reading is unaffected while writes are strictly governed by typed policies."""
    gate = MemoryWriteGate(default_policy=WriteGatePolicy.ENABLED)

    # 1. Default policy is enabled
    check_default = gate.check_write_allowed()
    assert check_default.is_allowed is True
    assert check_default.policy == WriteGatePolicy.ENABLED
    gate.ensure_write_allowed()

    # 2. Global policy disabled temporarily
    gate.set_global_policy(WriteGatePolicy.DISABLED_TEMPORARY)
    check_temp = gate.check_write_allowed()
    assert check_temp.is_allowed is False
    with pytest.raises(MemoryWriteBlockedError) as exc_info:
        gate.ensure_write_allowed()
    assert "disabled_temporary" in str(exc_info.value)

    # 3. Session override takes precedence
    gate.set_session_policy("sess_audit", WriteGatePolicy.READ_ONLY_SESSION)
    check_sess = gate.check_write_allowed(session_id="sess_audit")
    assert check_sess.is_allowed is False
    assert check_sess.policy == WriteGatePolicy.READ_ONLY_SESSION

    # 4. Clear session override reverts to global
    gate.clear_session_policy("sess_audit")
    assert gate.check_write_allowed(session_id="sess_audit").policy == WriteGatePolicy.DISABLED_TEMPORARY


def test_reconciliation_loop_direction_a_and_direction_b(tmp_path: Path) -> None:
    """Verifies Direction A incremental indexing and Direction B pruning of deleted disk files."""
    db_file = tmp_path / "test_reconcile.db"
    notes_dir = tmp_path / "memory_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    reconciler = DiskMemoryFtsReconciler(db_path=db_file)

    # 1. Create two physical markdown notes on disk
    note1 = notes_dir / "architecture.md"
    note1.write_text("# Core Architecture\nUse hexagonal clean architecture throughout.", encoding="utf-8")

    note2 = notes_dir / "database.md"
    note2.write_text("# Database Configuration\nPostgreSQL connection pooling configured with pool_size=20.", encoding="utf-8")

    # Initial reconciliation pass (Direction A)
    report1 = reconciler.reconcile(roots=[notes_dir])
    assert report1.status == "completed"
    assert report1.scanned_disk_files_count == 2
    assert report1.indexed_or_updated_count == 2
    assert report1.pruned_dead_rows_count == 0
    assert reconciler.get_indexed_count() == 2

    # Verify FTS search matches
    hits_db = reconciler.search("PostgreSQL")
    assert len(hits_db) == 1
    assert "Database Configuration" in hits_db[0].title

    # 2. Modify note2 content on disk
    note2.write_text("# Database Configuration\nPostgreSQL updated pool_size=50 for higher throughput.", encoding="utf-8")
    report2 = reconciler.reconcile(roots=[notes_dir])
    assert report2.status == "completed"
    assert report2.indexed_or_updated_count == 1
    assert report2.pruned_dead_rows_count == 0
    assert reconciler.get_indexed_count() == 2

    # 3. Delete note2 from physical disk (Direction B testing)
    note2.unlink()
    assert not note2.exists()

    report3 = reconciler.reconcile(roots=[notes_dir])
    assert report3.status == "completed"
    assert report3.scanned_disk_files_count == 1
    assert report3.indexed_or_updated_count == 0
    assert report3.pruned_dead_rows_count == 1
    assert reconciler.get_indexed_count() == 1

    # Verify ghost record is completely purged from search index
    hits_purged = reconciler.search("PostgreSQL")
    assert len(hits_purged) == 0

    # Note 1 is still preserved and searchable
    hits_arch = reconciler.search("hexagonal")
    assert len(hits_arch) == 1
    assert "Core Architecture" in hits_arch[0].title


def test_reconciliation_blocked_by_write_gate(tmp_path: Path) -> None:
    """Verifies that reconciliation respects write-gate policy and bypasses writes in read-only mode."""
    db_file = tmp_path / "test_reconcile_gate.db"
    notes_dir = tmp_path / "notes_gate"
    notes_dir.mkdir(parents=True, exist_ok=True)

    note = notes_dir / "sample.md"
    note.write_text("# Sample Note\nRead-only test.", encoding="utf-8")

    gate = MemoryWriteGate(default_policy=WriteGatePolicy.READ_ONLY_SESSION)
    reconciler = DiskMemoryFtsReconciler(db_path=db_file, write_gate=gate)

    report = reconciler.reconcile(roots=[notes_dir])
    assert "blocked_by_write_gate" in report.status
    assert report.indexed_or_updated_count == 0
    assert reconciler.get_indexed_count() == 0
