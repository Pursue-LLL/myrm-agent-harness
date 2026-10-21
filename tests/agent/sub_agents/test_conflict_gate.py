"""Tests for Parallel Work Conflict Reconciliation Gate.

[INPUT]
- myrm_agent_harness.agent.sub_agents.conflict_gate.*

[OUTPUT]
- Pytest test cases verifying conflict detection, idempotent writes, and reconciliation strategies

[POS]
myrm-agent-harness/tests/agent/sub_agents/test_conflict_gate.py
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.conflict_gate import (
    ConflictGateVerdict,
    ParallelWorkConflictDetector,
    WriteFingerprint,
)


def test_conflict_gate_clean_and_idempotent_writes() -> None:
    detector = ParallelWorkConflictDetector()
    session_id = "test-session-clean"

    # Single write to a file
    w1 = WriteFingerprint(
        worker_id="worker-1",
        resource_id="src/main.py",
        mutation_type="file",
        content_hash="hash-abc-123",
        summary="Add login function",
    )
    verdict1: ConflictGateVerdict = detector.evaluate_write_fingerprints(
        session_id, [w1]
    )
    assert not verdict1.is_blocked
    assert verdict1.total_conflicts == 0
    assert len(verdict1.clean_writes) == 1

    # Idempotent write: multiple workers writing identical hash
    w2 = WriteFingerprint(
        worker_id="worker-2",
        resource_id="src/main.py",
        mutation_type="file",
        content_hash="hash-abc-123",
        summary="Also add same login function",
    )
    verdict2: ConflictGateVerdict = detector.evaluate_write_fingerprints(
        session_id, [w1, w2]
    )
    assert not verdict2.is_blocked
    assert verdict2.total_conflicts == 0
    assert len(verdict2.clean_writes) == 2


def test_conflict_gate_detects_hash_collision_and_blocks() -> None:
    detector = ParallelWorkConflictDetector()
    session_id = "test-session-conflict"

    # Worker A and Worker B mutate same file with different content
    w_a = WriteFingerprint(
        worker_id="worker-coder",
        resource_id="src/database.py",
        mutation_type="file",
        content_hash="hash-postgres-conn",
        summary="Migrate to Postgres pool",
    )
    w_b = WriteFingerprint(
        worker_id="worker-architect",
        resource_id="src/database.py",
        mutation_type="file",
        content_hash="hash-sqlite-memory",
        summary="Refactor to SQLite local test harness",
    )

    verdict: ConflictGateVerdict = detector.evaluate_write_fingerprints(
        session_id, [w_a, w_b]
    )
    assert verdict.is_blocked
    assert verdict.total_conflicts == 1
    assert len(verdict.conflicts) == 1

    conflict = verdict.conflicts[0]
    assert conflict.status == "conflict_pending"
    assert conflict.resource_id == "src/database.py"
    assert conflict.worker_a.worker_id == "worker-coder"
    assert conflict.worker_b.worker_id == "worker-architect"

    pending = detector.get_pending_conflicts(session_id)
    assert len(pending) == 1
    assert pending[0].conflict_id == conflict.conflict_id


def test_conflict_gate_reconcile_and_resolve() -> None:
    detector = ParallelWorkConflictDetector()
    session_id = "test-session-resolve"

    w_a = WriteFingerprint(
        worker_id="worker-1",
        resource_id="config.json",
        mutation_type="config",
        content_hash="hash-a",
    )
    w_b = WriteFingerprint(
        worker_id="worker-2",
        resource_id="config.json",
        mutation_type="config",
        content_hash="hash-b",
    )

    verdict = detector.evaluate_write_fingerprints(session_id, [w_a, w_b])
    assert verdict.is_blocked
    conflict_id = verdict.conflicts[0].conflict_id

    # 1. Resolve with keep_worker_a
    resolved = detector.resolve_conflict(conflict_id, "keep_worker_a")
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolution_strategy == "keep_worker_a"
    assert resolved.resolved_at is not None

    # Check pending list is now empty
    pending_after = detector.get_pending_conflicts(session_id)
    assert len(pending_after) == 0

    # 2. Unknown conflict resolve returns None
    none_res = detector.resolve_conflict("conf-unknown", "abort_both")
    assert none_res is None
