"""[POS]: tests/unit/toolkits/memory/test_queuefs_suite.py
[INPUT]: Path patterns, lock modes, and simulated async DAG tasks.
[OUTPUT]: Pytest test cases verifying semantic path locks, conflict resolution, and DAG stage execution.
"""

import pytest

from myrm_agent_harness.toolkits.memory.queuefs import (
    LockAcquisitionConflictError,
    PathSemanticLockManager,
    QueueFSConfig,
    QueueFSDAGEngine,
    SemanticDAGStage,
    SemanticLockMode,
    SemanticTaskStatus,
)


@pytest.mark.anyio
async def test_path_semantic_lock_manager() -> None:
    """Verify exclusive lock conflict, shared lock concurrency, and prefix hierarchy overlap."""
    mgr = PathSemanticLockManager(default_ttl_seconds=10.0)

    # 1. Acquire exclusive lock on parent directory
    lease_a = await mgr.acquire_lock(
        path_pattern="context://resources/docs/",
        owner="worker_a",
        mode=SemanticLockMode.EXCLUSIVE,
    )
    assert lease_a.lock_id.startswith("sem_lock_")
    assert mgr.is_locked("context://resources/docs/")
    assert mgr.is_locked("context://resources/docs/guide.md")

    # 2. Conflicting exclusive acquisition on child path must fail
    with pytest.raises(LockAcquisitionConflictError):
        await mgr.acquire_lock(
            path_pattern="context://resources/docs/guide.md",
            owner="worker_b",
            mode=SemanticLockMode.EXCLUSIVE,
        )

    # 3. Conflicting shared acquisition on parent path must fail due to active exclusive
    with pytest.raises(LockAcquisitionConflictError):
        await mgr.acquire_lock(
            path_pattern="context://resources/docs/",
            owner="worker_c",
            mode=SemanticLockMode.SHARED,
        )

    # 4. Release lease A
    released = await mgr.release_lock(lease_a.lock_id, owner="worker_a")
    assert released is True
    assert not mgr.is_locked("context://resources/docs/")

    # 5. Shared locks can coexist
    lease_s1 = await mgr.acquire_lock(
        path_pattern="context://resources/docs/",
        owner="reader_1",
        mode=SemanticLockMode.SHARED,
    )
    lease_s2 = await mgr.acquire_lock(
        path_pattern="context://resources/docs/guide.md",
        owner="reader_2",
        mode=SemanticLockMode.SHARED,
    )
    assert mgr.is_locked("context://resources/docs/", mode=SemanticLockMode.SHARED)
    assert mgr.active_locks_count() == 2

    # Clean up
    await mgr.release_lock(lease_s1.lock_id, owner="reader_1")
    await mgr.release_lock(lease_s2.lock_id, owner="reader_2")
    assert mgr.active_locks_count() == 0


@pytest.mark.anyio
async def test_queuefs_dag_task_execution() -> None:
    """Verify asynchronous task submission, stage transitions, and pipeline completion."""
    lock_mgr = PathSemanticLockManager(default_ttl_seconds=30.0)
    engine = QueueFSDAGEngine(
        config=QueueFSConfig(max_concurrent_workers=2),
        lock_manager=lock_mgr,
    )

    # 1. Submit task without blocking caller (millisecond latency)
    task = engine.submit_task(
        resource_uri="context://resources/auth/oauth.py",
        payload="# OAuth implementation",
    )
    assert task.task_id.startswith("qfs_task_")
    assert task.status == SemanticTaskStatus.PENDING
    assert task.progress_pct == 0.0
    assert task.current_stage == SemanticDAGStage.INGESTION

    # 2. Advance stage step by step
    task_step1 = await engine.advance_stage(task.task_id)
    assert task_step1.status == SemanticTaskStatus.RUNNING
    assert task_step1.current_stage == SemanticDAGStage.CHUNKING
    assert task_step1.progress_pct == 20.0

    # 3. Execute entire remaining pipeline to completion under lock
    completed_task = await engine.execute_pipeline(task.task_id)
    assert completed_task.status == SemanticTaskStatus.COMPLETED
    assert completed_task.progress_pct == 100.0
    assert completed_task.current_stage == SemanticDAGStage.INDEXING

    # Lock must be released after pipeline terminates
    assert not lock_mgr.is_locked("context://resources/auth/oauth.py")

    # 4. Telemetry stats verification
    stats = engine.get_stats()
    assert stats.completed_tasks == 1
    assert stats.pending_tasks == 0
    assert stats.running_tasks == 0
    assert stats.failed_tasks == 0
    assert stats.active_locks == 0


@pytest.mark.anyio
async def test_queuefs_lock_scope_context_manager() -> None:
    """Verify async context manager auto-releases lease even when exception occurs."""
    lock_mgr = PathSemanticLockManager(default_ttl_seconds=10.0)

    try:
        async with lock_mgr.lock_scope(
            path_pattern="context://artifacts/bundle.zip",
            owner="exporter",
            mode=SemanticLockMode.EXCLUSIVE,
        ):
            assert lock_mgr.is_locked("context://artifacts/bundle.zip")
            # Simulate processing error
            raise RuntimeError("Synthetic IO failure")
    except RuntimeError:
        pass

    # Lock must be cleanly released despite exception
    assert not lock_mgr.is_locked("context://artifacts/bundle.zip")
    assert lock_mgr.active_locks_count() == 0
