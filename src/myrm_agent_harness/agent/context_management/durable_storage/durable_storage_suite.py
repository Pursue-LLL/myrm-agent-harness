# [INPUT]: BenchmarkMetrics, CommitWrite, DurableStorageProtocol, StorageBackendKind, StorageWriteKind
# [OUTPUT]: PortableDurableStorageSuite
# [POS]: agent/context_management/durable_storage/durable_storage_suite.py

"""Unified orchestration facade and deterministic benchmark runner for durable storage.

[INPUT]
- BenchmarkMetrics, CommitWrite, StorageBackendKind, StorageWriteKind: Domain types from durable_storage_types.
- DurableStorageProtocol: Base storage contract.

[OUTPUT]
- PortableDurableStorageSuite: Central facade for factory creation, conformance testing,
  and multi-backend deterministic benchmarking across Memory, JSONL, and SQLite engines.

[POS]
Top-level entrypoint for portable durable storage architecture in agent context management.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Mapping, Sequence

from .durable_storage_protocol import DurableStorageProtocol
from .durable_storage_types import (
    BenchmarkMetrics,
    CommitWrite,
    StorageBackendKind,
    StorageWriteKind,
)
from .jsonl_durable_storage import JsonlDurableStorage
from .memory_durable_storage import MemoryDurableStorage
from .sqlite_durable_storage import SqliteDurableStorage


class PortableDurableStorageSuite:
    """Orchestration facade providing factory creation, conformance validation, and benchmarks."""

    @staticmethod
    def create_storage(
        backend: StorageBackendKind,
        target_path: str | None = None,
    ) -> DurableStorageProtocol:
        """Create a durable storage instance for the requested backend kind."""
        if backend == StorageBackendKind.MEMORY:
            return MemoryDurableStorage()
        elif backend == StorageBackendKind.JSONL:
            if not target_path:
                raise ValueError("JSONL durable storage requires a valid file path")
            return JsonlDurableStorage(target_path)
        elif backend == StorageBackendKind.SQLITE:
            path = target_path or ":memory:"
            return SqliteDurableStorage(path)
        else:
            raise ValueError(f"Unsupported storage backend kind: {backend}")

    @classmethod
    def run_conformance_suite(cls, storage: DurableStorageProtocol) -> bool:
        """Run strict conformance verification asserting identical behavior across all backends.

        Verifies:
        1. Atomic multi-entity commit advance.
        2. Point lookup parity for conversations, entries, tasks, and documents.
        3. Monotonic ordering and sequence pagination in list_entries.
        4. Reopen crash-recovery stability without state loss.
        """
        conv_id = "test_conv_001"
        writes_1: list[CommitWrite] = [
            CommitWrite(
                kind=StorageWriteKind.CONVERSATION,
                id=conv_id,
                payload={"title": "Primary Session", "tag": "prod"},
            ),
            CommitWrite(
                kind=StorageWriteKind.DOCUMENT,
                id="doc_config",
                payload={"version": 1, "theme": "dark", "zoom": 1.2},
            ),
        ]
        seq1 = storage.commit(writes_1)
        if seq1 != 1:
            return False

        # Verify initial entities
        c1 = storage.get_conversation(conv_id)
        if c1 is None or c1.title != "Primary Session" or c1.metadata.get("tag") != "prod":
            return False

        d1 = storage.get_document("doc_config")
        if d1 is None or d1.version != 1 or d1.content.get("theme") != "dark":
            return False

        # Commit entry 1 and task
        writes_2: list[CommitWrite] = [
            CommitWrite(
                kind=StorageWriteKind.ENTRY,
                id="entry_01",
                payload={"conversation_id": conv_id, "kind": "user_input", "text": "Deploy agent"},
            ),
            CommitWrite(
                kind=StorageWriteKind.TASK,
                id="task_build",
                payload={"conversation_id": conv_id, "kind": "build", "status": "running", "step": 1},
            ),
        ]
        seq2 = storage.commit(writes_2)
        if seq2 != 2:
            return False

        # Commit entry 2 in a later sequence
        writes_3: list[CommitWrite] = [
            CommitWrite(
                kind=StorageWriteKind.ENTRY,
                id="entry_02",
                payload={"conversation_id": conv_id, "kind": "tool_call", "cmd": "pytest"},
            ),
        ]
        seq3 = storage.commit(writes_3)
        if seq3 != 3:
            return False

        # Verify entry listing and pagination
        all_entries = storage.list_entries(conv_id, limit=10, after_seq=0)
        if len(all_entries) != 2:
            return False
        if all_entries[0].id != "entry_01" or all_entries[1].id != "entry_02":
            return False

        paged_entries = storage.list_entries(conv_id, limit=1, after_seq=2)
        if len(paged_entries) != 1 or paged_entries[0].id != "entry_02":
            return False

        # Verify task state
        t1 = storage.get_task("task_build")
        if t1 is None or t1.status != "running" or t1.checkpoint.get("step") != 1:
            return False

        # Verify reopen resilience
        storage.reopen()
        if storage.get_current_seq() != 3:
            return False
        if storage.get_conversation(conv_id) is None:
            return False
        if len(storage.list_entries(conv_id)) != 2:
            return False

        return True

    @classmethod
    def run_benchmark_comparison(
        cls,
        base_dir: str,
        batches_count: int = 50,
    ) -> Mapping[StorageBackendKind, BenchmarkMetrics]:
        """Execute deterministic comparative benchmark across Memory, JSONL, and SQLite engines."""
        os.makedirs(base_dir, exist_ok=True)
        backends = [
            (StorageBackendKind.MEMORY, None),
            (StorageBackendKind.JSONL, os.path.join(base_dir, "benchmark.jsonl")),
            (StorageBackendKind.SQLITE, os.path.join(base_dir, "benchmark.db")),
        ]

        metrics_map: dict[StorageBackendKind, BenchmarkMetrics] = {}

        for backend_kind, file_path in backends:
            storage = cls.create_storage(backend_kind, file_path)
            total_records = 0

            # 1. Benchmark Commit Latency
            t0 = time.perf_counter()
            for b in range(batches_count):
                c_id = f"bench_conv_{b}"
                writes: list[CommitWrite] = [
                    CommitWrite(
                        kind=StorageWriteKind.CONVERSATION,
                        id=c_id,
                        payload={"title": f"Bench Conversation {b}"},
                    ),
                    CommitWrite(
                        kind=StorageWriteKind.ENTRY,
                        id=f"entry_{b}_1",
                        payload={"conversation_id": c_id, "kind": "msg", "idx": 1},
                    ),
                    CommitWrite(
                        kind=StorageWriteKind.ENTRY,
                        id=f"entry_{b}_2",
                        payload={"conversation_id": c_id, "kind": "msg", "idx": 2},
                    ),
                    CommitWrite(
                        kind=StorageWriteKind.TASK,
                        id=f"task_{b}",
                        payload={"conversation_id": c_id, "kind": "bench", "status": "done"},
                    ),
                ]
                storage.commit(writes)
                total_records += len(writes)
            commit_time_ms = (time.perf_counter() - t0) * 1000.0

            # 2. Benchmark Point Read Latency
            t_read = time.perf_counter()
            for b in range(batches_count):
                _ = storage.get_conversation(f"bench_conv_{b}")
                _ = storage.get_entry(f"entry_{b}_1")
                _ = storage.get_task(f"task_{b}")
            point_read_ms = (time.perf_counter() - t_read) * 1000.0

            # 3. Benchmark Range Scan Latency
            t_scan = time.perf_counter()
            for b in range(batches_count):
                _ = storage.list_entries(f"bench_conv_{b}", limit=10, after_seq=0)
            range_scan_ms = (time.perf_counter() - t_scan) * 1000.0

            # 4. Benchmark Reopen Latency
            t_reopen = time.perf_counter()
            storage.reopen()
            reopen_ms = (time.perf_counter() - t_reopen) * 1000.0

            # 5. Measure approximate disk or memory size
            footprint_kb = 0.0
            if file_path and os.path.exists(file_path):
                footprint_kb = os.path.getsize(file_path) / 1024.0
            else:
                footprint_kb = float(sys.getsizeof(storage) / 1024.0)

            storage.close()

            metrics_map[backend_kind] = BenchmarkMetrics(
                backend=backend_kind,
                commit_latency_ms=round(commit_time_ms, 2),
                point_read_latency_ms=round(point_read_ms, 2),
                range_scan_latency_ms=round(range_scan_ms, 2),
                reopen_latency_ms=round(reopen_ms, 2),
                records_count=total_records,
                memory_footprint_kb=round(footprint_kb, 2),
            )

        return metrics_map
