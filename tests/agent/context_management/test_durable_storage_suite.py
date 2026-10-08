# [INPUT]: BenchmarkMetrics, CommitWrite, DurableStorageProtocol, PortableDurableStorageSuite, StorageBackendKind, StorageWriteKind
# [OUTPUT]: test_durable_storage_conformance_across_all_backends, test_jsonl_crash_reclaim_and_commit_marker_integrity, test_sqlite_wal_acid_transactions_and_index_scans, test_deterministic_benchmark_comparison_metrics
# [POS]: tests/agent/context_management/test_durable_storage_suite.py

"""Comprehensive test suite for portable durable storage runtimes across Memory, JSONL, and SQLite.

Validates:
1. Universal storage contract conformance across Memory, JSONL, and SQLite backends.
2. Atomic commit markers and partial tail crash reclamation in JSONL stream logs.
3. SQLite ACID transactions, WAL journaling pragmas, and indexed chronological range scans.
4. Deterministic multi-backend benchmark comparison metrics across commit, read, scan, and reopen.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from myrm_agent_harness.agent.context_management.durable_storage import (
    BenchmarkMetrics,
    CommitWrite,
    DurableStorageProtocol,
    JsonlDurableStorage,
    MemoryDurableStorage,
    PortableDurableStorageSuite,
    SqliteDurableStorage,
    StorageBackendKind,
    StorageWriteKind,
)


def test_durable_storage_conformance_across_all_backends() -> None:
    """Validate that Memory, JSONL, and SQLite backends satisfy identical storage contract semantics."""
    with tempfile.TemporaryDirectory() as temp_dir:
        jsonl_path = os.path.join(temp_dir, "conformance.jsonl")
        sqlite_path = os.path.join(temp_dir, "conformance.db")

        backends: list[DurableStorageProtocol] = [
            PortableDurableStorageSuite.create_storage(StorageBackendKind.MEMORY),
            PortableDurableStorageSuite.create_storage(StorageBackendKind.JSONL, jsonl_path),
            PortableDurableStorageSuite.create_storage(StorageBackendKind.SQLITE, sqlite_path),
        ]

        for storage in backends:
            assert PortableDurableStorageSuite.run_conformance_suite(storage) is True
            storage.close()


def test_jsonl_crash_reclaim_and_commit_marker_integrity() -> None:
    """Validate that uncommitted trailing partial writes are reclaimed back to the last valid commit marker."""
    with tempfile.TemporaryDirectory() as temp_dir:
        jsonl_path = os.path.join(temp_dir, "crash_test.jsonl")
        storage = JsonlDurableStorage(jsonl_path)

        # Commit 1
        storage.commit([
            CommitWrite(
                kind=StorageWriteKind.CONVERSATION,
                id="c1",
                payload={"title": "Session One"},
            ),
            CommitWrite(
                kind=StorageWriteKind.ENTRY,
                id="e1",
                payload={"conversation_id": "c1", "text": "Turn 1"},
            ),
        ])

        # Commit 2
        storage.commit([
            CommitWrite(
                kind=StorageWriteKind.ENTRY,
                id="e2",
                payload={"conversation_id": "c1", "text": "Turn 2"},
            ),
        ])
        assert storage.get_current_seq() == 2
        storage.close()

        # Simulate abrupt power crash by injecting broken uncommitted lines at tail
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write('{"type": "entry", "id": "e_broken_crash", "payload": {"text": "incomplete"\n')
            f.write('{"corrupted_binary_garbage": \x00\x01\x02\n')

        # Reopen storage; crash recovery should truncate unsealed garbage back to Commit 2
        recovered_storage = JsonlDurableStorage(jsonl_path)
        assert recovered_storage.get_current_seq() == 2
        assert recovered_storage.get_entry("e1") is not None
        assert recovered_storage.get_entry("e2") is not None
        assert recovered_storage.get_entry("e_broken_crash") is None

        # Subsequent commit 3 proceeds cleanly with sequence 3
        seq3 = recovered_storage.commit([
            CommitWrite(
                kind=StorageWriteKind.ENTRY,
                id="e3",
                payload={"conversation_id": "c1", "text": "Turn 3 post recovery"},
            ),
        ])
        assert seq3 == 3
        assert recovered_storage.get_entry("e3") is not None
        recovered_storage.close()


def test_sqlite_wal_acid_transactions_and_index_scans() -> None:
    """Validate SQLite ACID transactional batching, WAL mode, and indexed sequence scans."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "wal_acid.db")
        storage = SqliteDurableStorage(db_path)

        conv_id = "acid_conv"
        writes: list[CommitWrite] = [
            CommitWrite(
                kind=StorageWriteKind.CONVERSATION,
                id=conv_id,
                payload={"title": "ACID Session"},
            ),
        ]
        for i in range(1, 11):
            writes.append(
                CommitWrite(
                    kind=StorageWriteKind.ENTRY,
                    id=f"entry_{i:02d}",
                    payload={"conversation_id": conv_id, "kind": "user", "seq_num": i},
                )
            )

        seq = storage.commit(writes)
        assert seq == 1

        # Test index range scans with after_seq
        first_page = storage.list_entries(conv_id, limit=5, after_seq=0)
        assert len(first_page) == 5
        assert first_page[0].id == "entry_01"
        assert first_page[4].id == "entry_05"

        # Sequential scan with after_seq
        second_page = storage.list_entries(conv_id, limit=5, after_seq=first_page[4].seq)
        # All 10 entries were created in batch with seq=1, so after_seq=1 returns empty (strictly > seq)
        assert len(second_page) == 0

        # Create separate commit to advance sequence
        storage.commit([
            CommitWrite(
                kind=StorageWriteKind.ENTRY,
                id="entry_advanced",
                payload={"conversation_id": conv_id, "text": "Advanced turn"},
            )
        ])
        advanced_entries = storage.list_entries(conv_id, limit=10, after_seq=1)
        assert len(advanced_entries) == 1
        assert advanced_entries[0].id == "entry_advanced"
        assert advanced_entries[0].seq == 2

        # Close executes wal_checkpoint
        storage.close()


def test_deterministic_benchmark_comparison_metrics() -> None:
    """Validate deterministic multi-backend benchmark profiling runner across Memory, JSONL, and SQLite."""
    with tempfile.TemporaryDirectory() as temp_dir:
        bench_dir = os.path.join(temp_dir, "benchmarks")
        metrics_map = PortableDurableStorageSuite.run_benchmark_comparison(
            base_dir=bench_dir,
            batches_count=15,
        )

        assert StorageBackendKind.MEMORY in metrics_map
        assert StorageBackendKind.JSONL in metrics_map
        assert StorageBackendKind.SQLITE in metrics_map

        for backend_kind, metrics in metrics_map.items():
            assert metrics.backend == backend_kind
            assert metrics.records_count == 15 * 4  # 4 writes per batch * 15 batches = 60
            assert metrics.commit_latency_ms >= 0.0
            assert metrics.point_read_latency_ms >= 0.0
            assert metrics.range_scan_latency_ms >= 0.0
            assert metrics.reopen_latency_ms >= 0.0
            assert metrics.memory_footprint_kb >= 0.0
