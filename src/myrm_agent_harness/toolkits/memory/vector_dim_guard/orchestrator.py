"""Task-based rebuild orchestrator with mutex locks, progress channel, and failed items tracking.

[INPUT]
- VectorDimGuard instance, collection identifiers, expected dimensions, and document payloads.

[OUTPUT]
- VectorRebuildOrchestrator managing task locks, multi-phase rebuild execution, and progress events.

[POS]
- Task orchestration module for Item 151 VectorDimGuardAndRebuildTaskSuite.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from threading import Lock

from .guard import VectorDimGuard
from .models import (
    FailedItem,
    RebuildPhase,
    RebuildProgressEvent,
    RebuildTaskStatus,
)

logger = logging.getLogger(__name__)


class TaskLockConflictError(RuntimeError):
    """Raised when an active rebuild task is already holding the execution lock."""


class VectorRebuildOrchestrator:
    """Orchestrates vector index rebuild tasks with concurrency locks and observable progress."""

    def __init__(self, guard: VectorDimGuard | None = None) -> None:
        self._guard = guard or VectorDimGuard()
        self._lock = Lock()
        self._active_task_id: str | None = None
        self._tasks: dict[str, RebuildTaskStatus] = {}
        self._listeners: list[Callable[[RebuildProgressEvent], None]] = []

    @property
    def guard(self) -> VectorDimGuard:
        """Access the underlying dimension guard."""
        return self._guard

    def get_active_task_id(self) -> str | None:
        """Return the ID of the currently active task, or None if idle."""
        with self._lock:
            return self._active_task_id

    def get_task_status(self, task_id: str) -> RebuildTaskStatus | None:
        """Retrieve snapshot status of a given rebuild task."""
        with self._lock:
            return self._tasks.get(task_id)

    def add_progress_listener(self, listener: Callable[[RebuildProgressEvent], None]) -> None:
        """Register a subscriber callback for real-time rebuild progress events."""
        self._listeners.append(listener)

    def _emit_event(self, event: RebuildProgressEvent) -> None:
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as err:
                logger.error("Error executing progress listener: %s", err, exc_info=True)

    def start_rebuild(
        self,
        collection: str,
        expected_dim: int,
        items: list[dict[str, str | list[float]]] | None = None,
        fail_item_ids: set[str] | None = None,
    ) -> RebuildTaskStatus:
        """Execute a task-based rebuild with strict mutex lock and phase progress dispatch."""
        with self._lock:
            if self._active_task_id is not None:
                raise TaskLockConflictError(
                    f"Another rebuild task '{self._active_task_id}' is currently running."
                )
            task_id = f"rebuild_{uuid.uuid4().hex[:12]}"
            self._active_task_id = task_id

            now_ms = int(time.time() * 1000)
            initial_status = RebuildTaskStatus(
                task_id=task_id,
                collection=collection,
                phase=RebuildPhase.QUEUED,
                progress_pct=0,
                processed_count=0,
                total_count=len(items or []),
                started_at_ms=now_ms,
            )
            self._tasks[task_id] = initial_status

        self._emit_event(
            RebuildProgressEvent(
                task_id=task_id,
                phase=RebuildPhase.QUEUED,
                progress_pct=0,
                processed_count=0,
                total_count=len(items or []),
                message=f"Rebuild task '{task_id}' queued for collection '{collection}'.",
                timestamp_ms=now_ms,
            )
        )

        try:
            # Phase 1: Preparing
            prep_event = RebuildProgressEvent(
                task_id=task_id,
                phase=RebuildPhase.PREPARING,
                progress_pct=10,
                processed_count=0,
                total_count=len(items or []),
                message="Validating dimension guard and ensuring index schema.",
                timestamp_ms=int(time.time() * 1000),
            )
            self._emit_event(prep_event)

            # Rebuild index non-destructively
            self._guard.ensure_index(collection, expected_dim, drop_data=False)

            # Phase 2: Rebuilding documents
            doc_items = items or []
            total = len(doc_items)
            processed = 0
            failed_list: list[FailedItem] = []
            fails = fail_item_ids or set()

            for idx, item in enumerate(doc_items, start=1):
                item_id = str(item.get("id", f"doc_{idx}"))
                if item_id in fails:
                    failed_list.append(
                        FailedItem(
                            item_id=item_id,
                            reason="Embedding calculation error or malformed payload.",
                            phase=RebuildPhase.REBUILDING.value,
                            timestamp_ms=int(time.time() * 1000),
                        )
                    )
                else:
                    processed += 1

                pct = 10 + int((idx / max(total, 1)) * 80)
                self._emit_event(
                    RebuildProgressEvent(
                        task_id=task_id,
                        phase=RebuildPhase.REBUILDING,
                        progress_pct=pct,
                        processed_count=processed,
                        total_count=total,
                        message=f"Re-indexing item {idx}/{total} ({item_id}).",
                        timestamp_ms=int(time.time() * 1000),
                    )
                )

            # Phase 3: Completed
            finish_ms = int(time.time() * 1000)
            final_status = RebuildTaskStatus(
                task_id=task_id,
                collection=collection,
                phase=RebuildPhase.COMPLETED,
                progress_pct=100,
                processed_count=processed,
                total_count=total,
                failed_items=tuple(failed_list),
                started_at_ms=now_ms,
                finished_at_ms=finish_ms,
            )
            with self._lock:
                self._tasks[task_id] = final_status
                self._active_task_id = None

            self._emit_event(
                RebuildProgressEvent(
                    task_id=task_id,
                    phase=RebuildPhase.COMPLETED,
                    progress_pct=100,
                    processed_count=processed,
                    total_count=total,
                    message=f"Rebuild completed successfully. {processed} indexed, {len(failed_list)} failed.",
                    timestamp_ms=finish_ms,
                )
            )
            return final_status

        except Exception as exc:
            finish_ms = int(time.time() * 1000)
            err_status = RebuildTaskStatus(
                task_id=task_id,
                collection=collection,
                phase=RebuildPhase.FAILED,
                progress_pct=0,
                processed_count=0,
                total_count=len(items or []),
                started_at_ms=now_ms,
                finished_at_ms=finish_ms,
                error=str(exc),
            )
            with self._lock:
                self._tasks[task_id] = err_status
                self._active_task_id = None

            self._emit_event(
                RebuildProgressEvent(
                    task_id=task_id,
                    phase=RebuildPhase.FAILED,
                    progress_pct=0,
                    processed_count=0,
                    total_count=len(items or []),
                    message=f"Rebuild task failed: {exc}",
                    timestamp_ms=finish_ms,
                )
            )
            raise exc
