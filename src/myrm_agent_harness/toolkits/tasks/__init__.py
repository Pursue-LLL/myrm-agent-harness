"""Async task management system.

This module provides a generic async task system with support for:
- Multiple task types (image generation, audio transcription, etc.)
- Priority queuing
- Timeout and cancellation
- Retry with exponential backoff
- Result caching
- Multi-tenant isolation
- Progress tracking
- Worker health monitoring


[INPUT]
- tasks.protocol (POS: core task data models and status types)
- tasks.executor::AsyncTaskExecutor (POS: task executor protocol layer)
- tasks.store::SQLiteTaskStore, TaskFilters, TaskStoreProtocol (POS: task persistence layer)
- tasks.worker (POS: task worker with concurrency control)

[OUTPUT]
- Task, TaskStatus, TaskError, RetryPolicy, ErrorRecoverability: core task models
- AsyncTaskExecutor: executor protocol for business-layer implementations
- SQLiteTaskStore, TaskFilters, TaskStoreProtocol: persistence types
- TaskWorker, WorkerHealth: worker and health monitoring types

[POS]
Tasks toolkit entry point. Aggregates task models, executor protocol, persistence layer,
and worker infrastructure for the generic async task management system.

Example usage:

    # Framework layer (setup)
    from myrm_agent_harness.toolkits.tasks import (
        Task, TaskStatus, SQLiteTaskStore, TaskFilters
    )

    store = SQLiteTaskStore("tasks.db")

    # Create task
    task = Task(
        task_id="img-123",
        task_type="image_generate",
        user_id="user-456",
        status=TaskStatus.PENDING,
        payload={"prompt": "A futuristic lab", "size": "1024x1024"},
        priority=8,  # High priority
    )
    await store.create_task(task)

    # Query tasks
    tasks = await store.list_tasks(
        TaskFilters(status=TaskStatus.PENDING, order_by="priority DESC")
    )

    # Business layer (executor implementation)
    from myrm_agent_harness.toolkits.tasks import AsyncTaskExecutor

    class ImageTaskExecutor:
        async def execute(self, task: Task) -> dict:
            # Execute task logic
            return {"images": [...]}

        async def cancel(self, task: Task) -> bool:
            # Handle cancellation
            return True

        def can_execute(self, task_type: str) -> bool:
            return task_type == "image_generate"
"""

from .executor import AsyncTaskExecutor
from .protocols import (
    ErrorRecoverability,
    RetryPolicy,
    Task,
    TaskError,
    TaskStatus,
)
from .store import SQLiteTaskStore, TaskFilters, TaskStore
from .types import (
    # Audio transcription
    AudioTranscriptionPayload,
    AudioTranscriptionResult,
    # Batch processing
    BatchProcessingPayload,
    BatchProcessingResult,
    ImageData,
    # Image generation
    ImageGenerationPayload,
    ImageGenerationResult,
    # Video generation
    VideoGenerationPayload,
    VideoGenerationResult,
    # Utilities
    get_payload_class,
    get_result_class,
)

__all__ = [
    # Executor
    "AsyncTaskExecutor",
    "AudioTranscriptionPayload",
    "AudioTranscriptionResult",
    "BatchProcessingPayload",
    "BatchProcessingResult",
    "ErrorRecoverability",
    "ImageData",
    # Task types
    "ImageGenerationPayload",
    "ImageGenerationResult",
    "RetryPolicy",
    "SQLiteTaskStore",
    # Core protocol
    "Task",
    "TaskError",
    # Store
    "TaskFilters",
    "TaskStatus",
    "TaskStore",
    "VideoGenerationPayload",
    "VideoGenerationResult",
    "get_payload_class",
    "get_result_class",
]
