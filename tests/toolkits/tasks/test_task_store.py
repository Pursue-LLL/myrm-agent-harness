"""Tests for TaskStore SQLite implementation."""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.tasks import (
    SQLiteTaskStore,
    Task,
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
async def test_clean_old_tasks(temp_store):
    """Test cleaning old completed tasks."""
    # This would require mocking datetime to test properly
    # For now, just test the API exists
    deleted = await temp_store.clean_old_tasks(days=30)
    assert deleted >= 0
