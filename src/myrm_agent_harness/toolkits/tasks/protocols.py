"""Task system protocol definitions.

This module defines the core protocol for asynchronous task management.
Supports generic task types (image generation, audio transcription, etc.)
with priority queuing, timeout, cancellation, retry, caching, and multi-tenant isolation.

[INPUT]
- (none)

[OUTPUT]
- TaskStatus: Task execution status.
- ErrorRecoverability: Error recoverability classification for retry logic.
- TaskError: Task execution error details.
- RetryPolicy: Retry policy for failed tasks.
- Task: Generic asynchronous task.

[POS]
Task system protocol definitions.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class TaskStatus(StrEnum):
    """Task execution status.

    State machine: PENDING → QUEUED → RUNNING → (SUCCEEDED | FAILED | CANCELLED)
    """

    PENDING = "pending"  # Created, waiting to be queued
    QUEUED = "queued"  # In queue, waiting for worker
    RUNNING = "running"  # Being executed by worker
    SUCCEEDED = "succeeded"  # Completed successfully
    FAILED = "failed"  # Failed (may retry)
    CANCELLED = "cancelled"  # Cancelled by user


class ErrorRecoverability(StrEnum):
    """Error recoverability classification for retry logic."""

    TRANSIENT = "transient"  # Temporary error, can retry (network, timeout, overload)
    PERMANENT = "permanent"  # Permanent error, no retry (invalid params, auth, not found)


@dataclass(frozen=True)
class TaskError:
    """Task execution error details."""

    error_type: str  # "timeout", "network_error", "api_error", "validation_error", etc.
    message: str  # Human-readable error message
    recoverable: ErrorRecoverability  # Whether can retry
    traceback: str | None = None  # Full traceback for debugging
    metadata: dict[str, object] | None = None  # Additional error context


@dataclass(frozen=True)
class RetryPolicy:
    """Retry policy for failed tasks.

    Implements exponential backoff: delay = base_delay * (exponential_base ^ retry_count)
    Clamped to [base_delay, max_delay].
    """

    max_retries: int = 3  # Maximum retry attempts
    base_delay: float = 1.0  # Initial delay in seconds
    max_delay: float = 60.0  # Maximum delay in seconds
    exponential_base: float = 2.0  # Exponential backoff base

    def get_delay(self, retry_count: int) -> float:
        """Calculate retry delay for given attempt number."""
        delay = self.base_delay * (self.exponential_base**retry_count)
        return min(delay, self.max_delay)


@dataclass
class Task:
    """Generic asynchronous task.

    Supports:
    - Priority queuing (0-10, higher = more urgent)
    - Timeout (prevents hung tasks)
    - Cancellation (user-initiated or system-initiated)
    - Retry (with exponential backoff)
    - Result caching (avoid duplicate work)
    - Progress tracking (0.0-1.0)
    - Multi-tenant isolation (user_id filtering)
    - Tagging/labeling (for organization)
    """

    # Core identity (no defaults)
    task_id: str  # Unique task identifier
    task_type: str  # Task type ("image_generate", "audio_transcribe", etc.)
    user_id: str  # User who owns this task (multi-tenant isolation)
    status: TaskStatus
    payload: dict[str, object]  # Task input parameters

    # Status & lifecycle (with defaults)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None  # When RUNNING started
    completed_at: datetime | None = None  # When terminal status reached

    # Payload & result
    result: dict[str, object] | None = None  # Task output (when succeeded)
    error: TaskError | None = None  # Task error (when failed)

    # Priority & scheduling
    priority: int = 5  # 0-10 (0=lowest, 10=highest, 5=default)
    timeout: int = 300  # Execution timeout in seconds (default 5 min)

    # Idempotency & caching
    idempotency_key: str | None = None  # Prevent duplicate task creation
    cache_key: str | None = None  # Enable result caching (skip execution)

    # Retry policy
    retry_count: int = 0  # Number of retries attempted
    retry_policy: RetryPolicy | None = None  # Retry configuration
    next_retry_at: datetime | None = None  # When next retry should occur

    # Progress tracking
    progress: float = 0.0  # Execution progress (0.0-1.0)
    progress_message: str | None = None  # Human-readable progress status

    # Cancellation
    cancellation_event: asyncio.Event | None = field(default=None, compare=False, repr=False)
    cancellation_reason: str | None = None  # Why task was cancelled

    # Organization & metadata
    tags: list[str] = field(default_factory=list)  # User-defined tags for filtering
    metadata: dict[str, object] = field(default_factory=dict)  # Additional context

    # Worker tracking
    worker_id: str | None = None  # Which worker is executing this task
    worker_heartbeat_at: datetime | None = None  # Last worker heartbeat

    def is_terminal(self) -> bool:
        """Check if task is in terminal status (no further transitions)."""
        return self.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    def is_active(self) -> bool:
        """Check if task is actively being processed."""
        return self.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)

    def can_retry(self) -> bool:
        """Check if task can be retried."""
        if not self.retry_policy:
            return False
        if self.status != TaskStatus.FAILED:
            return False
        if self.retry_count >= self.retry_policy.max_retries:
            return False
        return not (self.error and self.error.recoverable == ErrorRecoverability.PERMANENT)

    def mark_started(self, worker_id: str) -> None:
        """Mark task as started by worker."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self.updated_at = self.started_at
        self.worker_id = worker_id
        self.worker_heartbeat_at = self.started_at

    def mark_succeeded(self, result: dict[str, object]) -> None:
        """Mark task as succeeded."""
        self.status = TaskStatus.SUCCEEDED
        self.result = result
        self.progress = 1.0
        self.next_retry_at = None
        self.completed_at = datetime.now(UTC)
        self.updated_at = self.completed_at

    def mark_failed(self, error: TaskError) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.error = error
        self.next_retry_at = None
        self.completed_at = datetime.now(UTC)
        self.updated_at = self.completed_at

    def mark_cancelled(self, reason: str | None = None) -> None:
        """Mark task as cancelled."""
        self.status = TaskStatus.CANCELLED
        self.cancellation_reason = reason
        self.next_retry_at = None
        self.completed_at = datetime.now(UTC)
        self.updated_at = self.completed_at

    def update_progress(self, progress: float, message: str | None = None) -> None:
        """Update task execution progress."""
        self.progress = max(0.0, min(1.0, progress))
        self.progress_message = message
        self.updated_at = datetime.now(UTC)

    def heartbeat(self) -> None:
        """Update worker heartbeat timestamp."""
        self.worker_heartbeat_at = datetime.now(UTC)
        self.updated_at = self.worker_heartbeat_at


__all__ = [
    "ErrorRecoverability",
    "RetryPolicy",
    "Task",
    "TaskError",
    "TaskStatus",
]
