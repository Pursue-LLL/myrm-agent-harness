"""Async task executor protocol.

This module defines the protocol for task execution. Business layer implements
this protocol to execute specific task types (image generation, audio transcription, etc.)


[INPUT]
- tasks.protocols::Task (POS: core task data model)

[OUTPUT]
- AsyncTaskExecutor: protocol defining execute/cancel/can_execute for business-layer task executors

[POS]
Task executor protocol layer. Defines the interface that business-layer implementations
must satisfy for executing, cancelling, and routing async tasks by type.
"""

from typing import Protocol

from .protocols import Task


class AsyncTaskExecutor(Protocol):
    """Protocol for async task execution.

    Business layer implementations should:
    1. Implement execute() to perform the actual work
    2. Implement cancel() to handle cancellation requests
    3. Implement can_execute() to declare supported task types

    Example implementation:

        class ImageTaskExecutor:
            def __init__(self, generator: ImageGenerator):
                self._generator = generator

            async def execute(self, task: Task) -> dict:
                result = await self._generator.generate(
                    prompt=task.payload["prompt"],
                    size=task.payload.get("size"),
                    cancellation_event=task.cancellation_event,
                )
                return {
                    "images": [...],
                    "model": result.model,
                }

            async def cancel(self, task: Task) -> bool:
                if task.cancellation_event:
                    task.cancellation_event.set()
                    return True
                return False

            def can_execute(self, task_type: str) -> bool:
                return task_type == "image_generate"
    """

    async def execute(self, task: Task) -> dict[str, object]:
        """Execute task and return result dictionary.

        Args:
            task: Task to execute (contains payload, cancellation_event, etc.)

        Returns:
            Result dictionary (will be stored in task.result)

        Raises:
            Exception: Any execution error (will be caught by worker and stored in task.error)

        Notes:
            - Check task.cancellation_event periodically for cancellation requests
            - Use task.update_progress() to report progress
            - Raise exceptions for errors (worker handles retry logic)
        """
        ...

    async def cancel(self, task: Task) -> bool:
        """Cancel task execution.

        Args:
            task: Task to cancel

        Returns:
            True if cancellation initiated successfully, False otherwise

        Notes:
            - Should set task.cancellation_event if available
            - Should try to stop underlying operations (API calls, file I/O, etc.)
            - Return False if cancellation not supported or already completed
        """
        ...

    def can_execute(self, task_type: str) -> bool:
        """Check if this executor can handle the given task type.

        Args:
            task_type: Task type string ("image_generate", "audio_transcribe", etc.)

        Returns:
            True if this executor can execute tasks of this type

        Notes:
            - Used by worker to route tasks to appropriate executor
            - Should return True only for task types this executor implements
        """
        ...


__all__ = ["AsyncTaskExecutor"]
