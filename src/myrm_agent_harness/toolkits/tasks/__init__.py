"""Async task management system.

Generic async job queue: task models, executor protocol, SQLite persistence.
Domain payloads (image/video/audio) live in ``toolkits/llms/media_task_types.py``.
The worker loop is implemented in ``myrm-agent-server/app/tasks/worker.py``.

[INPUT]
- tasks.protocols (POS: core task data models and status types)
- tasks.executor::AsyncTaskExecutor (POS: task executor protocol layer)
- tasks.store::SQLiteTaskStore, TaskFilters, TaskStoreProtocol (POS: persistence)

[OUTPUT]
- Task, TaskStatus, TaskError, RetryPolicy, ErrorRecoverability: core task models
- AsyncTaskExecutor: executor protocol for business-layer implementations
- SQLiteTaskStore, TaskFilters, TaskStore: persistence types

[POS]
Framework-agnostic async job queue. No LLM tools, zero Turn1 token footprint.
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

__all__ = [
    "AsyncTaskExecutor",
    "ErrorRecoverability",
    "RetryPolicy",
    "SQLiteTaskStore",
    "Task",
    "TaskError",
    "TaskFilters",
    "TaskStatus",
    "TaskStore",
]
