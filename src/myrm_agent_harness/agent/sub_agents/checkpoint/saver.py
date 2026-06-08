"""Subagent checkpoint save/restore.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- dataclasses::dataclass, asdict (POS: Python标准库，数据类)
- json (POS: Python标准库，JSON序列化)
- pathlib::Path (POS: Python标准库，路径操作)
- time (POS: Python标准库，时间戳)
- typing::Dict, List (POS: Python类型提示)

[OUTPUT]
- SubagentCheckpoint: 子Agent执行检查点数据类
- SubagentCheckpointStorage: 子Agent检查点存储（JSON文件后端）

[POS]
Subagent checkpoint persistence module. Saves and restores subagent execution state to persistent storage (local JSON files).

"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.utils import os_compat as fcntl
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    pass

logger = get_agent_logger(__name__)


def _default_checkpoint_storage_path() -> Path:
    """Resolve checkpoint directory from MYRM_DATA_DIR or cwd-relative default."""
    data_dir = os.environ.get("MYRM_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "checkpoints"
    return Path(".myrm/checkpoints")


def _validate_checkpoint_task_id(task_id: object) -> str:
    if not isinstance(task_id, str):
        raise TypeError(f"checkpoint.task_id must be str, got {type(task_id).__name__}")
    normalized = task_id.strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError(f"invalid checkpoint task_id: {task_id!r}")
    return normalized


try:
    from .checkpoint.metrics import CheckpointMetrics
except (ImportError, TypeError):
    # Fallback if circular import (shouldn't happen)
    CheckpointMetrics = None  # type: ignore


@dataclass
class SubagentCheckpoint:
    """Subagent execution checkpoint.

    Records complete execution state for resumption after force-stop.
    """

    task_id: str
    """Unique task identifier"""

    agent_type: str
    """Agent type (e.g., 'planner', 'researcher')"""

    session_id: str
    """Session identifier (for multi-tenant isolation)"""

    timestamp: float
    """Checkpoint creation timestamp (Unix epoch)"""

    # Execution state
    messages: list[dict[str, object]] = field(default_factory=list)
    """LangChain messages (serialized)"""

    tool_outputs: list[dict[str, object]] = field(default_factory=list)
    """Tool execution history (for recovery)"""

    variables: dict[str, object] = field(default_factory=dict)
    """Agent runtime variables"""

    # Metadata
    progress: float = 0.0
    """Execution progress (0.0 ~ 1.0)"""

    last_tool: str | None = None
    """Last executed tool name"""

    resumable: bool = True
    """Whether this checkpoint is resumable"""

    # Interruption metadata (populated during graceful shutdown)
    interruption_reason: str | None = None
    """Reason for interruption (e.g., 'gateway-shutdown', 'sigterm')"""

    recovery_attempts: int = 0
    """Number of recovery attempts made for this checkpoint"""

    task_description: str = ""
    """Original task description for context display during recovery"""

    accumulated_runtime_seconds: float = 0.0
    """Total runtime across interruptions (previous + current duration)"""

    def to_dict(self) -> dict[str, object]:
        """Convert checkpoint to dictionary.

        Returns:
            Dictionary representation
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SubagentCheckpoint:
        """Create checkpoint from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            SubagentCheckpoint instance
        """
        return cls(**data)


class SubagentCheckpointStorage:
    """Subagent checkpoint storage (JSON file backend).

    Provides persistent storage for subagent checkpoints using local JSON files.
    Each checkpoint is stored in a separate file named by task_id.

    Storage structure:
        {MYRM_DATA_DIR or .myrm}/checkpoints/{task_id}.json

    Thread-safety: Uses fcntl.lockf() for file-level locking to prevent
    concurrent write corruption when multiple subagents save simultaneously.
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        """Initialize checkpoint storage.

        Args:
            storage_path: Storage directory path (default: MYRM_DATA_DIR/checkpoints or .myrm/checkpoints)
        """
        self._storage_path = storage_path or _default_checkpoint_storage_path()
        self._storage_path.mkdir(parents=True, exist_ok=True)
        logger.debug("Checkpoint storage initialized: %s", self._storage_path)

        # Metrics tracking (framework provides, business layer consumes)
        if CheckpointMetrics is not None:
            self.metrics = CheckpointMetrics()
        else:
            self.metrics = None  # type: ignore

    async def save(self, checkpoint: SubagentCheckpoint) -> None:
        """Save checkpoint to disk (async wrapper around sync save).

        Args:
            checkpoint: Checkpoint to save
        """
        self.save_sync(checkpoint)

    def save_sync(self, checkpoint: SubagentCheckpoint) -> None:
        """Save checkpoint to disk with file locking.

        Uses fcntl.lockf() to prevent concurrent writes from corrupting
        the JSON file when multiple subagents save simultaneously.

        Args:
            checkpoint: Checkpoint to save
        """
        task_id = _validate_checkpoint_task_id(checkpoint.task_id)
        file_path = self._storage_path / f"{task_id}.json"
        checkpoint_dict = checkpoint.to_dict()

        start_time = time.perf_counter()
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                fcntl.lockf(f, fcntl.LOCK_EX)
                try:
                    json.dump(checkpoint_dict, f, indent=2, ensure_ascii=False)
                finally:
                    fcntl.lockf(f, fcntl.LOCK_UN)
            logger.info(
                " Checkpoint saved: %s (progress=%.1f%%, size=%dB)",
                checkpoint.task_id,
                checkpoint.progress * 100,
                file_path.stat().st_size,
            )

            # Track metrics
            if self.metrics:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self.metrics.save_count += 1
                self.metrics.save_success_count += 1
                self.metrics.save_total_ms += elapsed_ms
                if checkpoint.messages:
                    self.metrics.messages_extracted_count += 1
        except Exception as e:
            # Track failure
            if self.metrics:
                self.metrics.save_count += 1
                self.metrics.save_failure_count += 1
            logger.error("Failed to save checkpoint %s: %s", checkpoint.task_id, e)
            raise

    async def load(self, task_id: str) -> SubagentCheckpoint | None:
        """Load checkpoint from disk with shared file lock.

        Args:
            task_id: Task ID to load

        Returns:
            Checkpoint if exists, None otherwise
        """
        task_id = _validate_checkpoint_task_id(task_id)
        start_time = time.perf_counter()
        file_path = self._storage_path / f"{task_id}.json"
        if not file_path.exists():
            logger.debug("Checkpoint not found: %s", task_id)
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                fcntl.lockf(f, fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    fcntl.lockf(f, fcntl.LOCK_UN)
            checkpoint = SubagentCheckpoint.from_dict(data)
            logger.info(
                "Checkpoint loaded: %s (progress=%.1f%%)",
                task_id,
                checkpoint.progress * 100,
            )

            # Track metrics
            if self.metrics:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self.metrics.resume_count += 1
                self.metrics.resume_success_count += 1
                self.metrics.resume_total_ms += elapsed_ms

            return checkpoint
        except Exception as e:
            # Track failure
            if self.metrics:
                self.metrics.resume_count += 1
                self.metrics.resume_failure_count += 1
            logger.error("Failed to load checkpoint %s: %s", task_id, e)
            raise

    async def delete(self, task_id: str) -> None:
        """Delete checkpoint.

        Args:
            task_id: Task ID to delete
        """
        task_id = _validate_checkpoint_task_id(task_id)
        file_path = self._storage_path / f"{task_id}.json"
        try:
            file_path.unlink(missing_ok=True)
            logger.debug("Checkpoint deleted: %s", task_id)
        except Exception as e:
            logger.error("Failed to delete checkpoint %s: %s", task_id, e)
            raise

    async def list_checkpoints(self, session_id: str | None = None) -> list[SubagentCheckpoint]:
        """List all saved checkpoints.

        Args:
            session_id: Optional session ID filter

        Returns:
            List of checkpoints (sorted by timestamp descending)
        """
        checkpoints: list[SubagentCheckpoint] = []

        try:
            for file_path in self._storage_path.glob("*.json"):
                try:
                    with open(file_path, encoding="utf-8") as f:
                        data = json.load(f)
                    checkpoint = SubagentCheckpoint.from_dict(data)

                    # Apply session_id filter if provided
                    if session_id and checkpoint.session_id != session_id:
                        continue

                    checkpoints.append(checkpoint)
                except Exception as e:
                    logger.warning("Failed to load checkpoint from %s: %s", file_path, e)
                    continue

            # Sort by timestamp descending (newest first)
            checkpoints.sort(key=lambda c: c.timestamp, reverse=True)
            logger.debug("Listed %d checkpoints", len(checkpoints))
            return checkpoints
        except Exception as e:
            logger.error("Failed to list checkpoints: %s", e)
            raise

    async def cleanup_old_checkpoints(self, ttl_seconds: int = 86400 * 7) -> int:
        """Cleanup old checkpoints (default: 7 days TTL).

        Args:
            ttl_seconds: Time-to-live in seconds (default: 7 days)

        Returns:
            Number of checkpoints deleted
        """
        now = time.time()
        deleted = 0

        try:
            for file_path in self._storage_path.glob("*.json"):
                try:
                    with open(file_path, encoding="utf-8") as f:
                        data = json.load(f)
                    checkpoint = SubagentCheckpoint.from_dict(data)

                    # Check if checkpoint is older than TTL
                    age = now - checkpoint.timestamp
                    if age > ttl_seconds:
                        file_path.unlink()
                        deleted += 1
                        logger.debug(
                            "Deleted old checkpoint: %s (age=%.1f days)",
                            checkpoint.task_id,
                            age / 86400,
                        )
                except Exception as e:
                    logger.warning("Failed to process checkpoint %s: %s", file_path, e)
                    continue

            if deleted > 0:
                logger.info(
                    " Cleaned up %d old checkpoints (TTL=%.1f days)",
                    deleted,
                    ttl_seconds / 86400,
                )
            return deleted
        except Exception as e:
            logger.error("Failed to cleanup old checkpoints: %s", e)
            raise
