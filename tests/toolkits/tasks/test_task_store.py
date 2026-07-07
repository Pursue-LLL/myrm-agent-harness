"""Tests for TaskStore SQLite implementation."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.tasks import (
    ErrorRecoverability,
    RetryPolicy,
    SQLiteTaskStore,
    Task,
    TaskError,
    TaskFilters,
    TaskStatus,
)


@pytest.fixture
async def temp_store():
    """Create temporary SQLite store for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = SQLiteTaskStore(db_path=db_path)

    yield store

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_create_and_get_task(temp_store):
    """Test creating and retrieving a task."""
    task = Task(
        task_id="test-001",
        task_type="image_generate",
        user_id="user-123",
        status=TaskStatus.PENDING,
        payload={"prompt": "a cat"},
    )

    await temp_store.create_task(task)

    retrieved = await temp_store.get_task("test-001")
    assert retrieved is not None
    assert retrieved.task_id == "test-001"
    assert retrieved.task_type == "image_generate"
    assert retrieved.user_id == "user-123"
    assert retrieved.payload == {"prompt": "a cat"}


@pytest.mark.asyncio
async def test_update_task(temp_store):
    """Test updating task status."""
    task = Task(
        task_id="test-002",
        task_type="image_generate",
        user_id="user-123",
        status=TaskStatus.PENDING,
        payload={},
    )

    await temp_store.create_task(task)

    await temp_store.update_task(
        "test-002",
        status=TaskStatus.RUNNING,
    )

    updated = await temp_store.get_task("test-002")
    assert updated.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_list_tasks_with_filters(temp_store):
    """Test listing tasks with filters."""
    tasks = [
        Task("t1", "image_generate", "user-1", TaskStatus.PENDING, {}),
        Task("t2", "image_generate", "user-1", TaskStatus.RUNNING, {}),
        Task("t3", "audio_transcribe", "user-2", TaskStatus.PENDING, {}),
    ]

    for task in tasks:
        await temp_store.create_task(task)

    # Filter by status
    pending = await temp_store.list_tasks(TaskFilters(status=TaskStatus.PENDING))
    assert len(pending) == 2

    # Filter by user_id
    user1_tasks = await temp_store.list_tasks(TaskFilters(user_id="user-1"))
    assert len(user1_tasks) == 2

    # Filter by task_type
    image_tasks = await temp_store.list_tasks(TaskFilters(task_type="image_generate"))
    assert len(image_tasks) == 2


@pytest.mark.asyncio
async def test_idempotency_key(temp_store):
    """Test idempotency key prevents duplicate task creation."""
    task1 = Task(
        task_id="t1",
        task_type="image_generate",
        user_id="user-1",
        status=TaskStatus.PENDING,
        payload={},
        idempotency_key="unique-key-1",
    )

    await temp_store.create_task(task1)

    existing = await temp_store.find_by_idempotency_key("unique-key-1")
    assert existing is not None
    assert existing.task_id == "t1"


@pytest.mark.asyncio
async def test_cache_key(temp_store):
    """Test cache key enables result reuse."""
    task1 = Task(
        task_id="t1",
        task_type="image_generate",
        user_id="user-1",
        status=TaskStatus.SUCCEEDED,
        payload={},
        result={"url": "image.png"},
        cache_key="prompt-hash-123",
    )

    await temp_store.create_task(task1)

    cached = await temp_store.find_by_cache_key("prompt-hash-123")
    assert cached is not None
    assert cached.result == {"url": "image.png"}


@pytest.mark.asyncio
async def test_get_task_missing_returns_none(temp_store):
    """Missing task_id returns None."""
    assert await temp_store.get_task("does-not-exist") is None


@pytest.mark.asyncio
async def test_update_task_rich_fields(temp_store):
    """Update error, result, payload, metadata, tags, and datetime fields."""
    task = Task(
        task_id="test-rich",
        task_type="image_generate",
        user_id="user-123",
        status=TaskStatus.RUNNING,
        payload={"prompt": "old"},
        tags=["a"],
    )
    await temp_store.create_task(task)

    started_at = datetime.now(UTC)
    error = TaskError(
        error_type="api_error",
        message="rate limited",
        recoverable=ErrorRecoverability.TRANSIENT,
        traceback="tb",
    )
    await temp_store.update_task(
        "test-rich",
        status=TaskStatus.FAILED,
        error=error,
        result={"url": "x.png"},
        payload={"prompt": "new"},
        metadata={"chat_id": "c1"},
        tags=["a", "b"],
        started_at=started_at,
        next_retry_at=started_at + timedelta(minutes=5),
        worker_heartbeat_at=started_at,
        progress=0.5,
    )

    updated = await temp_store.get_task("test-rich")
    assert updated is not None
    assert updated.status == TaskStatus.FAILED
    assert updated.error is not None
    assert updated.error.message == "rate limited"
    assert updated.result == {"url": "x.png"}
    assert updated.payload == {"prompt": "new"}
    assert updated.metadata == {"chat_id": "c1"}
    assert updated.tags == ["a", "b"]
    assert updated.started_at is not None
    assert updated.next_retry_at is not None
    assert updated.worker_heartbeat_at is not None


@pytest.mark.asyncio
async def test_create_task_persists_retry_policy(temp_store):
    """create_task round-trips retry_policy JSON."""
    policy = RetryPolicy(max_retries=5, base_delay=2.0)
    task = Task(
        task_id="retry-policy",
        task_type="image_generate",
        user_id="u1",
        status=TaskStatus.PENDING,
        payload={},
        retry_policy=policy,
    )
    await temp_store.create_task(task)
    loaded = await temp_store.get_task("retry-policy")
    assert loaded is not None
    assert loaded.retry_policy is not None
    assert loaded.retry_policy.max_retries == 5
    assert loaded.retry_policy.base_delay == 2.0


@pytest.mark.asyncio
async def test_list_tasks_date_and_multi_filters(temp_store):
    """List supports created_after/before and list-valued filters."""
    old = datetime.now(UTC) - timedelta(days=2)
    recent = datetime.now(UTC) - timedelta(hours=1)

    t_old = Task("old", "image_generate", "u1", TaskStatus.SUCCEEDED, {}, created_at=old, updated_at=old)
    t_new = Task("new", "audio_transcribe", "u1", TaskStatus.PENDING, {}, created_at=recent, updated_at=recent)
    await temp_store.create_task(t_old)
    await temp_store.create_task(t_new)

    after = await temp_store.list_tasks(
        TaskFilters(created_after=datetime.now(UTC) - timedelta(days=1), task_type=["audio_transcribe", "image_generate"])
    )
    assert len(after) == 1
    assert after[0].task_id == "new"

    before = await temp_store.list_tasks(
        TaskFilters(created_before=datetime.now(UTC) - timedelta(days=1))
    )
    assert len(before) == 1
    assert before[0].task_id == "old"

    statuses = await temp_store.list_tasks(TaskFilters(status=[TaskStatus.SUCCEEDED, TaskStatus.PENDING]))
    assert len(statuses) == 2


@pytest.mark.asyncio
async def test_clean_old_tasks_deletes_completed(temp_store):
    """Completed tasks older than cutoff are removed."""
    old_completed = datetime.now(UTC) - timedelta(days=40)
    task = Task(
        task_id="stale",
        task_type="image_generate",
        user_id="u1",
        status=TaskStatus.SUCCEEDED,
        payload={},
        completed_at=old_completed,
        created_at=old_completed,
        updated_at=old_completed,
    )
    await temp_store.create_task(task)

    deleted = await temp_store.clean_old_tasks(days=30)
    assert deleted == 1
    assert await temp_store.get_task("stale") is None


@pytest.mark.asyncio
async def test_clean_old_tasks(temp_store):
    """Test cleaning old completed tasks."""
    # This would require mocking datetime to test properly
    # For now, just test the API exists
    deleted = await temp_store.clean_old_tasks(days=30)
    assert deleted >= 0
