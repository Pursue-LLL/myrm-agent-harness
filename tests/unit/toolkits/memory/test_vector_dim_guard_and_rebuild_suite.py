"""Unit tests for Item 151 VectorDimGuardAndRebuildTaskSuite.

Tests:
1. Dimension inspection and match bypass.
2. Dimension mismatch triggering non-destructive index rebuild (preserving data without DD).
3. Task lock mutex preventing concurrent rebuild execution.
4. Multi-phase progress event channel dispatching real-time updates.
5. Failed items checklist tracking with observable error contexts.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.vector_dim_guard import (
    RebuildPhase,
    RebuildProgressEvent,
    TaskLockConflictError,
    VectorDimGuard,
    VectorRebuildOrchestrator,
)


def test_dim_guard_inspect_and_match() -> None:
    """Verifies that matching dimension bypasses index reconstruction."""
    guard = VectorDimGuard()
    guard.register_collection("collection_test", dimension=1536)

    res = guard.inspect_dim("collection_test", expected_dim=1536)
    assert res.exists is True
    assert res.dim_match is True
    assert res.needs_rebuild is False
    assert res.current_dim == 1536
    assert res.expected_dim == 1536


def test_dim_mismatch_triggers_non_destructive_rebuild() -> None:
    """Verifies dimension mismatch triggers rebuild while preserving underlying data (drop_data=False)."""
    guard = VectorDimGuard()
    # Seed collection with 3 documents and old dimension 384
    docs = {
        "doc1": {"content": "First doc", "embedding": [0.1] * 384},
        "doc2": {"content": "Second doc", "embedding": [0.2] * 384},
        "doc3": {"content": "Third doc", "embedding": [0.3] * 384},
    }
    guard.register_collection("collection_data", dimension=384, documents=docs)

    # 1. Inspect mismatch
    res_inspect = guard.inspect_dim("collection_data", expected_dim=1536)
    assert res_inspect.exists is True
    assert res_inspect.dim_match is False
    assert res_inspect.needs_rebuild is True
    assert res_inspect.current_dim == 384

    # 2. Ensure index with new dimension 1536 without dropping data
    res_rebuild = guard.ensure_index("collection_data", expected_dim=1536, drop_data=False)
    assert res_rebuild.dim_match is True
    assert res_rebuild.needs_rebuild is False
    assert res_rebuild.current_dim == 1536
    assert res_rebuild.data_intact is True

    # 3. Assert documents are completely intact
    assert guard.get_document_count("collection_data") == 3


def test_rebuild_task_lock_mutex() -> None:
    """Verifies that only one rebuild task can run at a time; concurrent runs trigger lock conflict."""
    guard = VectorDimGuard()
    guard.register_collection("col_mutex", dimension=384)
    orchestrator = VectorRebuildOrchestrator(guard)

    # Mock an ongoing active task
    orchestrator._active_task_id = "rebuild_locked_123"

    with pytest.raises(TaskLockConflictError, match="Another rebuild task"):
        orchestrator.start_rebuild("col_mutex", expected_dim=1536)

    # Release lock
    orchestrator._active_task_id = None
    res = orchestrator.start_rebuild("col_mutex", expected_dim=1536)
    assert res.phase == RebuildPhase.COMPLETED
    assert orchestrator.get_active_task_id() is None


def test_rebuild_progress_events_and_failed_items() -> None:
    """Verifies real-time event emission across phases and observable failed item tracking."""
    guard = VectorDimGuard()
    guard.register_collection("col_events", dimension=384)
    orchestrator = VectorRebuildOrchestrator(guard)

    received_events: list[RebuildProgressEvent] = []
    orchestrator.add_progress_listener(lambda ev: received_events.append(ev))

    items = [
        {"id": "doc_ok_1", "text": "normal text"},
        {"id": "doc_bad_2", "text": "corrupt text"},
        {"id": "doc_ok_3", "text": "normal text 3"},
    ]

    status = orchestrator.start_rebuild(
        collection="col_events",
        expected_dim=1536,
        items=items,
        fail_item_ids={"doc_bad_2"},
    )

    # Validate final status
    assert status.phase == RebuildPhase.COMPLETED
    assert status.progress_pct == 100
    assert status.processed_count == 2
    assert status.total_count == 3
    assert len(status.failed_items) == 1
    assert status.failed_items[0].item_id == "doc_bad_2"
    assert "Embedding calculation error" in status.failed_items[0].reason

    # Validate progress event stream
    phases = [ev.phase for ev in received_events]
    assert RebuildPhase.QUEUED in phases
    assert RebuildPhase.PREPARING in phases
    assert RebuildPhase.REBUILDING in phases
    assert RebuildPhase.COMPLETED in phases
    assert received_events[-1].progress_pct == 100
