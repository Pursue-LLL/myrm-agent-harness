# [POS]: tests/unit/toolkits/memory/test_session_commit_two_phase_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory (SessionCommitTwoPhaseEngine, models)
# [OUTPUT]: Unit tests for SessionCommitTwoPhaseArchiveExtractAndMemoryDiffAuditSuite (Item 106)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory import (
    CommitBoundaryKind,
    CommitPhase,
    MemoryDiffChangeKind,
    MemoryDiffItem,
    SessionArchiveMessage,
    SessionCommitTwoPhaseEngine,
)


@pytest.fixture
def temp_engine(tmp_path: Path) -> SessionCommitTwoPhaseEngine:
    """Provides an isolated SessionCommitTwoPhaseEngine using pytest tmp_path."""
    return SessionCommitTwoPhaseEngine(base_storage_dir=tmp_path / "sessions")


def test_phase1_sync_commit_and_boundary_gating(temp_engine: SessionCommitTwoPhaseEngine) -> None:
    """Verify Phase 1 fast sync persistence and task boundary gating."""
    messages = [
        SessionArchiveMessage(
            role="user",
            content="Please refactor the database connection pool.",
        ),
        SessionArchiveMessage(
            role="assistant",
            content="Refactoring complete with atomic connection pooling.",
            tool_calls=({"tool": "write_file", "path": "db.py"},),
            tool_results=({"status": "ok"},),
            referenced_uris=("file:///workspace/db.py",),
        ),
    ]

    # 1. Commit with reliable boundary TARGET_COMPLETED
    res = temp_engine.commit(
        session_id="sess_alpha_01",
        messages=messages,
        boundary_kind=CommitBoundaryKind.TARGET_COMPLETED,
    )

    assert res.phase1_persisted is True
    assert res.archive_id == "archive_001"
    assert res.phase2_scheduled is True
    assert Path(res.messages_path).exists()

    # Verify messages.jsonl content
    lines = Path(res.messages_path).read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    row2 = json.loads(lines[1])
    assert row2["role"] == "assistant"
    assert row2["referenced_uris"] == ["file:///workspace/db.py"]

    # Verify task status is PHASE1_SYNC_ARCHIVED
    task = temp_engine.get_task(res.task_id)
    assert task is not None
    assert task.phase == CommitPhase.PHASE1_SYNC_ARCHIVED
    assert task.message_count == 2


def test_phase2_extraction_and_memory_diff_audit(temp_engine: SessionCommitTwoPhaseEngine) -> None:
    """Verify Phase 2 generates abstract/overview, writes memory_diff.json, and writes .done marker."""
    messages = [
        SessionArchiveMessage(
            role="user",
            content="Encountered bug in retry logic, fix applied and verified.",
        ),
    ]

    commit_res = temp_engine.commit(
        session_id="sess_beta_02",
        messages=messages,
        boundary_kind=CommitBoundaryKind.FAILURE_REPAIRED,
    )

    # Simulated memory delta items produced by memory extraction
    diff_items = [
        MemoryDiffItem(
            change_kind=MemoryDiffChangeKind.ADDED,
            memory_type="procedure_experience",
            item_id="proc_retry_safe_01",
            before_summary=None,
            after_summary="Exponential backoff retry with jitter",
        ),
        MemoryDiffItem(
            change_kind=MemoryDiffChangeKind.SUPERSEDED,
            memory_type="fact",
            item_id="fact_max_retries_01",
            before_summary="max_retries=3",
            after_summary="max_retries=5 with circuit breaker",
        ),
    ]

    completed_task = temp_engine.execute_phase2_sync(
        task_id=commit_res.task_id,
        memory_diff_items=diff_items,
    )

    assert completed_task.phase == CommitPhase.PHASE2_COMPLETED
    assert completed_task.completed_at is not None
    assert completed_task.diff_stats is not None
    assert completed_task.diff_stats.total_added == 1
    assert completed_task.diff_stats.total_superseded == 1

    archive_dir = temp_engine.base_dir / "sess_beta_02" / commit_res.archive_id
    assert (archive_dir / ".abstract.md").exists()
    assert (archive_dir / ".overview.md").exists()
    assert (archive_dir / ".done").exists()
    assert temp_engine.is_archive_done("sess_beta_02", commit_res.archive_id) is True

    # Read back memory_diff.json audit
    diff_audit = temp_engine.get_memory_diff("sess_beta_02", commit_res.archive_id)
    assert diff_audit is not None
    assert diff_audit.boundary_kind == CommitBoundaryKind.FAILURE_REPAIRED
    assert len(diff_audit.changes) == 2
    assert diff_audit.changes[0].change_kind == MemoryDiffChangeKind.ADDED
    assert diff_audit.changes[1].change_kind == MemoryDiffChangeKind.SUPERSEDED


def test_zero_change_memory_diff_output_contract(temp_engine: SessionCommitTwoPhaseEngine) -> None:
    """Verify zero memory changes still produce compliant empty memory_diff.json structure."""
    commit_res = temp_engine.commit(
        session_id="sess_gamma_03",
        messages=[SessionArchiveMessage(role="user", content="Just browsing logs")],
        boundary_kind=CommitBoundaryKind.MANUAL,
    )

    completed_task = temp_engine.execute_phase2_sync(
        task_id=commit_res.task_id,
        memory_diff_items=[],  # Zero memory diffs
    )

    assert completed_task.phase == CommitPhase.PHASE2_COMPLETED
    assert completed_task.diff_stats is not None
    assert completed_task.diff_stats.total_added == 0
    assert completed_task.diff_stats.total_updated == 0

    diff_audit = temp_engine.get_memory_diff("sess_gamma_03", commit_res.archive_id)
    assert diff_audit is not None
    assert len(diff_audit.changes) == 0
    assert diff_audit.stats.total_added == 0
    assert diff_audit.stats.total_deleted == 0


def test_sequential_archives_and_listing(temp_engine: SessionCommitTwoPhaseEngine) -> None:
    """Verify sequential archive IDs (archive_001, archive_002) and listing."""
    sess_id = "sess_multi_04"
    res1 = temp_engine.commit(
        session_id=sess_id,
        messages=[SessionArchiveMessage(role="user", content="Turn 1")],
        boundary_kind=CommitBoundaryKind.CONTEXT_COMPACTION,
    )
    res2 = temp_engine.commit(
        session_id=sess_id,
        messages=[SessionArchiveMessage(role="user", content="Turn 2")],
        boundary_kind=CommitBoundaryKind.USER_CORRECTION,
    )

    assert res1.archive_id == "archive_001"
    assert res2.archive_id == "archive_002"

    archives = temp_engine.list_session_archives(sess_id)
    assert archives == ["archive_001", "archive_002"]
