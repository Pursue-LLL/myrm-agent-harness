"""Async task management system.

Generic async job queue: task models and SQLite persistence.
Domain payloads (image/video/audio) live in ``toolkits/llms/media_task_types.py``.
The worker loop is implemented in ``myrm-agent-server/app/tasks/worker.py``.

[INPUT]
- tasks.protocols (POS: core task data models and status types)
- tasks.store::SQLiteTaskStore, TaskFilters, TaskStoreProtocol (POS: persistence)

[OUTPUT]
- Task, TaskStatus, TaskError, RetryPolicy, ErrorRecoverability: core task models
- SQLiteTaskStore, TaskFilters, TaskStore: persistence types

[POS]
Framework-agnostic async job queue. No LLM tools, zero Turn1 token footprint.
"""

from .protocols import (
    ErrorRecoverability,
    RetryPolicy,
    Task,
    TaskError,
    TaskStatus,
)
from .store import SQLiteTaskStore, TaskFilters, TaskStore

__all__ = [
    "ErrorRecoverability",
    "RetryPolicy",
    "SQLiteTaskStore",
    "Task",
    "TaskError",
    "TaskFilters",
    "TaskStatus",
    "TaskStore",
]
