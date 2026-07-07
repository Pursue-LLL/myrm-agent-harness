"""Tests for Task protocol and Task dataclass."""

import asyncio

from myrm_agent_harness.toolkits.tasks import (
    ErrorRecoverability,
    RetryPolicy,
    Task,
    TaskError,
    TaskStatus,
)


def test_task_creation():
    """Test Task dataclass creation."""
    task = Task(
        task_id="test-001",
        task_type="image_generate",
        user_id="user-123",
        status=TaskStatus.PENDING,
        payload={"prompt": "a cat"},
        priority=5,
        timeout=300,
    )

    assert task.task_id == "test-001"
    assert task.task_type == "image_generate"
    assert task.status == TaskStatus.PENDING
    assert task.payload == {"prompt": "a cat"}
    assert task.priority == 5
    assert task.timeout == 300


def test_task_is_terminal():
    """Test Task.is_terminal()."""
    pending_task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.PENDING,
        payload={},
    )
    assert not pending_task.is_terminal()

    succeeded_task = Task(
        task_id="t2",
        task_type="test",
        user_id="u1",
        status=TaskStatus.SUCCEEDED,
        payload={},
    )
    assert succeeded_task.is_terminal()

    failed_task = Task(
        task_id="t3",
        task_type="test",
        user_id="u1",
        status=TaskStatus.FAILED,
        payload={},
    )
    assert failed_task.is_terminal()

    cancelled_task = Task(
        task_id="t4",
        task_type="test",
        user_id="u1",
        status=TaskStatus.CANCELLED,
        payload={},
    )
    assert cancelled_task.is_terminal()


def test_task_mark_started():
    """Test Task.mark_started()."""
    task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.PENDING,
        payload={},
    )

    task.mark_started(worker_id="worker-1")

    assert task.status == TaskStatus.RUNNING
    assert task.worker_id == "worker-1"
    assert task.started_at is not None
    assert task.worker_heartbeat_at is not None


def test_task_mark_succeeded():
    """Test Task.mark_succeeded()."""
    task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.RUNNING,
        payload={},
    )

    result = {"output": "success"}
    task.mark_succeeded(result)

    assert task.status == TaskStatus.SUCCEEDED
    assert task.result == result
    assert task.progress == 1.0
    assert task.completed_at is not None


def test_task_mark_failed():
    """Test Task.mark_failed()."""
    task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.RUNNING,
        payload={},
    )

    error = TaskError(
        error_type="timeout",
        message="Task timed out",
        recoverable=ErrorRecoverability.PERMANENT,
    )
    task.mark_failed(error)

    assert task.status == TaskStatus.FAILED
    assert task.error == error
    assert task.completed_at is not None


def test_task_mark_cancelled():
    """Test Task.mark_cancelled()."""
    task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.RUNNING,
        payload={},
    )

    task.mark_cancelled(reason="User cancelled")

    assert task.status == TaskStatus.CANCELLED
    assert task.cancellation_reason == "User cancelled"
    assert task.completed_at is not None


def test_task_can_retry():
    """Test Task.can_retry()."""
    task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.FAILED,
        payload={},
        retry_policy=RetryPolicy(max_retries=3),
        retry_count=2,
    )
    assert task.can_retry()

    task.retry_count = 3
    assert not task.can_retry()

    task_no_policy = Task(
        task_id="t2",
        task_type="test",
        user_id="u1",
        status=TaskStatus.FAILED,
        payload={},
        retry_count=0,
    )
    assert not task_no_policy.can_retry()


def test_task_is_active():
    """Test Task.is_active()."""
    queued = Task("t1", "test", "u1", TaskStatus.QUEUED, {})
    running = Task("t2", "test", "u1", TaskStatus.RUNNING, {})
    pending = Task("t3", "test", "u1", TaskStatus.PENDING, {})
    assert queued.is_active()
    assert running.is_active()
    assert not pending.is_active()


def test_task_can_retry_requires_failed_status():
    """can_retry() is False unless status is FAILED."""
    task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.RUNNING,
        payload={},
        retry_policy=RetryPolicy(max_retries=3),
        retry_count=0,
    )
    assert not task.can_retry()


def test_task_can_retry_permanent_error():
    """Permanent errors are not retryable."""
    task = Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.FAILED,
        payload={},
        retry_policy=RetryPolicy(max_retries=3),
        retry_count=0,
        error=TaskError(
            error_type="validation_error",
            message="bad prompt",
            recoverable=ErrorRecoverability.PERMANENT,
        ),
    )
    assert not task.can_retry()


def test_task_update_progress_clamps():
    """update_progress() clamps to [0, 1] and stores message."""
    task = Task("t1", "test", "u1", TaskStatus.RUNNING, {})
    task.update_progress(1.5, message="almost")
    assert task.progress == 1.0
    assert task.progress_message == "almost"
    task.update_progress(-0.2)
    assert task.progress == 0.0


def test_task_heartbeat_updates_timestamp():
    """heartbeat() refreshes worker heartbeat fields."""
    task = Task("t1", "test", "u1", TaskStatus.RUNNING, {})
    assert task.worker_heartbeat_at is None
    task.heartbeat()
    assert task.worker_heartbeat_at is not None
    assert task.updated_at == task.worker_heartbeat_at


def test_task_cancellation_event():
    """Test Task cancellation event."""
    event = asyncio.Event()
    Task(
        task_id="t1",
        task_type="test",
        user_id="u1",
        status=TaskStatus.RUNNING,
        payload={},
        cancellation_event=event,
    )

    assert not event.is_set()
    event.set()
    assert event.is_set()


def test_retry_policy():
    """Test RetryPolicy."""
    policy = RetryPolicy(
        max_retries=3,
        base_delay=1.0,
        max_delay=60.0,
        exponential_base=2.0,
    )

    assert policy.get_delay(0) == 1.0
    assert policy.get_delay(1) == 2.0
    assert policy.get_delay(2) == 4.0
    assert policy.get_delay(10) == 60.0

    policy_linear = RetryPolicy(
        max_retries=3,
        base_delay=5.0,
        exponential_base=1.0,  # No exponential growth
    )
    assert policy_linear.get_delay(1) == 5.0
    assert policy_linear.get_delay(2) == 5.0
