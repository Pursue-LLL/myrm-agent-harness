"""Video task persistence with Protocol-based backend abstraction.

[OUTPUT]
- VideoTaskStore: Protocol for persisting video generation task state.
- InMemoryVideoTaskStore: Default zero-config in-memory implementation.
- FileVideoTaskStore: JSON file-based persistence for service restart recovery.

[POS]
Framework provides Protocol + two implementations (in-memory default, file-based).
Business layer can inject custom implementations (e.g. Redis, DB) via the Protocol.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import TaskState, TaskStatus

logger = logging.getLogger(__name__)


@runtime_checkable
class VideoTaskStore(Protocol):
    """Protocol for video task persistence.

    Framework defines the interface; business layer can provide custom backends.
    """

    def save(self, task: TaskStatus) -> None:
        """Persist or update a task."""
        ...

    def load(self, task_id: str) -> TaskStatus | None:
        """Load a task by ID. Returns None if not found."""
        ...

    def find_by_idempotency_key(self, key: str) -> TaskStatus | None:
        """Find a task by idempotency key. Returns None if not found."""
        ...

    def list_pending(self) -> list[TaskStatus]:
        """List all tasks in non-terminal states (QUEUED, GENERATING, DOWNLOADING)."""
        ...

    def delete(self, task_id: str) -> None:
        """Remove a task from the store."""
        ...


_PENDING_STATES = frozenset({TaskState.QUEUED, TaskState.GENERATING, TaskState.DOWNLOADING})


class InMemoryVideoTaskStore:
    """Default in-memory task store. Zero configuration, no persistence across restarts."""

    __slots__ = ("_tasks",)

    def __init__(self) -> None:
        self._tasks: dict[str, TaskStatus] = {}

    def save(self, task: TaskStatus) -> None:
        self._tasks[task.task_id] = task

    def load(self, task_id: str) -> TaskStatus | None:
        return self._tasks.get(task_id)

    def find_by_idempotency_key(self, key: str) -> TaskStatus | None:
        if not key:
            return None
        for task in self._tasks.values():
            if task.idempotency_key == key:
                return task
        return None

    def list_pending(self) -> list[TaskStatus]:
        return [t for t in self._tasks.values() if t.state in _PENDING_STATES]

    def delete(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)


class FileVideoTaskStore:
    """JSON file-based task store for persistence across service restarts.

    Each task is stored as a separate JSON file in the configured directory.
    Suitable for local deployments; SaaS can inject DB-backed stores.
    """

    __slots__ = ("_cache", "_dir")

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, TaskStatus] = {}
        self._load_existing()

    def save(self, task: TaskStatus) -> None:
        self._cache[task.task_id] = task
        self._write_file(task)

    def load(self, task_id: str) -> TaskStatus | None:
        return self._cache.get(task_id)

    def find_by_idempotency_key(self, key: str) -> TaskStatus | None:
        if not key:
            return None
        for task in self._cache.values():
            if task.idempotency_key == key:
                return task
        return None

    def list_pending(self) -> list[TaskStatus]:
        return [t for t in self._cache.values() if t.state in _PENDING_STATES]

    def delete(self, task_id: str) -> None:
        self._cache.pop(task_id, None)
        path = self._dir / f"{task_id}.json"
        path.unlink(missing_ok=True)

    def _write_file(self, task: TaskStatus) -> None:
        path = self._dir / f"{task.task_id}.json"
        try:
            path.write_text(
                json.dumps(task.to_persistence_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Failed to persist video task %s", task.task_id, exc_info=True)

    def _load_existing(self) -> None:
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                task = TaskStatus(
                    task_id=data["task_id"],
                    state=TaskState(data["state"]),
                    provider=data.get("provider", ""),
                    model=data.get("model", ""),
                    prompt=data.get("prompt", ""),
                    provider_task_id=data.get("provider_task_id", ""),
                    idempotency_key=data.get("idempotency_key", ""),
                    created_at=data.get("created_at", 0.0),
                    completed_at=data.get("completed_at"),
                    error=data.get("error"),
                )
                self._cache[task.task_id] = task
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("Skipping corrupt task file: %s", path, exc_info=True)
