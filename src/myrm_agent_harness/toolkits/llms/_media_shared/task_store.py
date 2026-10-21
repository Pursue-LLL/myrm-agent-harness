"""Generic media task persistence with Protocol-based backend abstraction.

[OUTPUT]
- MediaTask: Protocol for task objects that stores can manage
- MediaTaskStore: Protocol for persisting media generation task state
- InMemoryMediaTaskStore: Default zero-config in-memory implementation
- FileMediaTaskStore: JSON file-based persistence for service restart recovery

[POS]
Generic store shared by video/ and image/ modules. Framework provides
Protocol + two implementations; business layer can inject custom backends.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import MediaTaskState

logger = logging.getLogger(__name__)

_PENDING_STATES = frozenset(
    {
        MediaTaskState.QUEUED,
        MediaTaskState.GENERATING,
        MediaTaskState.DOWNLOADING,
    }
)


@runtime_checkable
class MediaTask(Protocol):
    """Minimal interface a task object must expose for the store."""

    @property
    def task_id(self) -> str: ...
    @property
    def state(self) -> MediaTaskState: ...
    @property
    def idempotency_key(self) -> str: ...

    def to_persistence_dict(self) -> dict[str, object]: ...


@runtime_checkable
class MediaTaskStore(Protocol):
    """Protocol for media task persistence.

    Framework defines the interface; business layer can provide custom backends.
    """

    def save(self, task: MediaTask) -> None: ...
    def load(self, task_id: str) -> MediaTask | None: ...
    def find_by_idempotency_key(self, key: str) -> MediaTask | None: ...
    def list_pending(self) -> list[MediaTask]: ...
    def delete(self, task_id: str) -> None: ...


class InMemoryMediaTaskStore:
    """Default in-memory task store. Zero configuration, no persistence across restarts."""

    __slots__ = ("_tasks",)

    def __init__(self) -> None:
        self._tasks: dict[str, MediaTask] = {}

    def save(self, task: MediaTask) -> None:
        self._tasks[task.task_id] = task

    def load(self, task_id: str) -> MediaTask | None:
        return self._tasks.get(task_id)

    def find_by_idempotency_key(self, key: str) -> MediaTask | None:
        if not key:
            return None
        for task in self._tasks.values():
            if task.idempotency_key == key:
                return task
        return None

    def list_pending(self) -> list[MediaTask]:
        return [t for t in self._tasks.values() if t.state in _PENDING_STATES]

    def delete(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)


class FileMediaTaskStore:
    """JSON file-based task store for persistence across service restarts.

    Each task is stored as a separate JSON file in the configured directory.
    Suitable for local deployments; SaaS can inject DB-backed stores.
    """

    __slots__ = ("_cache", "_deserializer", "_dir")

    def __init__(
        self,
        directory: str | Path,
        *,
        deserializer: Callable[[dict[str, object]], MediaTask | None] | None = None,
    ) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, MediaTask] = {}
        self._deserializer = deserializer
        if deserializer:
            self._load_existing()

    def save(self, task: MediaTask) -> None:
        self._cache[task.task_id] = task
        self._write_file(task)

    def load(self, task_id: str) -> MediaTask | None:
        return self._cache.get(task_id)

    def find_by_idempotency_key(self, key: str) -> MediaTask | None:
        if not key:
            return None
        for task in self._cache.values():
            if task.idempotency_key == key:
                return task
        return None

    def list_pending(self) -> list[MediaTask]:
        return [t for t in self._cache.values() if t.state in _PENDING_STATES]

    def delete(self, task_id: str) -> None:
        self._cache.pop(task_id, None)
        path = self._dir / f"{task_id}.json"
        path.unlink(missing_ok=True)

    def _write_file(self, task: MediaTask) -> None:
        path = self._dir / f"{task.task_id}.json"
        try:
            path.write_text(
                json.dumps(task.to_persistence_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Failed to persist media task %s", task.task_id, exc_info=True)

    def _load_existing(self) -> None:
        if not self._deserializer:
            return
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                task = self._deserializer(data)
                if task:
                    self._cache[task.task_id] = task
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("Skipping corrupt task file: %s", path, exc_info=True)
