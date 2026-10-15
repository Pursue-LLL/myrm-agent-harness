# -*- coding: utf-8 -*-
"""Persistent Delegation Ledger.

Provides crash-resilient storage, status lifecycle tracking, and orphan task
recovery for background delegated subagents, guaranteeing task durability.
"""

import json
import os
import tempfile
import time
from threading import Lock
from typing import Dict, List, Optional

from .types import (
    DelegationTaskRecord,
    ReasoningEffortLevel,
    TaskDelegationStatus,
)


class PersistentDelegationLedger:
    """Thread-safe persistent ledger for background subagent tasks."""

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self._lock = Lock()
        self._storage_path = storage_path
        self._tasks: Dict[str, DelegationTaskRecord] = {}

        if self._storage_path and os.path.exists(self._storage_path):
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load tasks from disk storage."""
        if not self._storage_path or not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for task_dict in data.values():
                    task = DelegationTaskRecord(**task_dict)
                    self._tasks[task.task_id] = task
        except Exception:
            # Fallback to empty if corrupted or unreadable
            pass

    def _flush_to_disk_unlocked(self) -> None:
        """Persist in-memory records to disk atomically."""
        if not self._storage_path:
            return
        dirname = os.path.dirname(self._storage_path)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)

        serialized = {k: v.model_dump() for k, v in self._tasks.items()}
        temp_dir = dirname if dirname else None
        with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as tf:
            json.dump(serialized, tf, indent=2)
            temp_name = tf.name

        os.replace(temp_name, self._storage_path)

    def register_task(
        self,
        task_id: str,
        session_id: str,
        subagent_id: str,
        role: str,
        prompt: str,
        reasoning_effort: ReasoningEffortLevel = ReasoningEffortLevel.MEDIUM,
    ) -> DelegationTaskRecord:
        """Register a new background delegation task in PENDING status."""
        now = time.time()
        with self._lock:
            record = DelegationTaskRecord(
                task_id=task_id,
                session_id=session_id,
                subagent_id=subagent_id,
                role=role,
                prompt=prompt,
                reasoning_effort=reasoning_effort,
                status=TaskDelegationStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = record
            self._flush_to_disk_unlocked()
            return record

    def update_status(
        self,
        task_id: str,
        status: TaskDelegationStatus,
        summary: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[DelegationTaskRecord]:
        """Update task status with optional summary or error."""
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return None
            now = time.time()
            record.status = status
            record.updated_at = now
            if summary is not None:
                record.summary = summary
            if error_message is not None:
                record.error_message = error_message
            if status in (
                TaskDelegationStatus.COMPLETED,
                TaskDelegationStatus.FAILED,
                TaskDelegationStatus.CANCELLED,
            ):
                record.finished_at = now
            self._flush_to_disk_unlocked()
            return record

    def save_checkpoint(
        self,
        task_id: str,
        checkpoint_step: int,
        artifacts: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[DelegationTaskRecord]:
        """Save task checkpoint step and optional artifacts."""
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return None
            record.checkpoint_step = checkpoint_step
            record.updated_at = time.time()
            if artifacts:
                record.artifacts.extend(artifacts)
            self._flush_to_disk_unlocked()
            return record

    def get_task(self, task_id: str) -> Optional[DelegationTaskRecord]:
        """Retrieve task by id."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(
        self,
        session_id: Optional[str] = None,
        status: Optional[TaskDelegationStatus] = None,
    ) -> List[DelegationTaskRecord]:
        """List tasks optionally filtered by session or status."""
        with self._lock:
            tasks = list(self._tasks.values())
            if session_id:
                tasks = [t for t in tasks if t.session_id == session_id]
            if status:
                tasks = [t for t in tasks if t.status == status]
            return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def recover_orphaned_tasks(self) -> List[DelegationTaskRecord]:
        """Scan for orphaned tasks (PENDING/RUNNING during restart) and pause them for recovery."""
        recovered: List[DelegationTaskRecord] = []
        now = time.time()
        with self._lock:
            for record in self._tasks.values():
                if record.status in (
                    TaskDelegationStatus.RUNNING,
                    TaskDelegationStatus.PENDING,
                ):
                    record.status = TaskDelegationStatus.PAUSED
                    record.updated_at = now
                    record.error_message = (
                        "Process restarted: Task auto-recovered and paused for resume."
                    )
                    recovered.append(record)
            if recovered:
                self._flush_to_disk_unlocked()
        return recovered
