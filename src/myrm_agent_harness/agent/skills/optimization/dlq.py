"""Dead Letter Queue with Persistence

P0-1: 持久化DLQ，支持服务重启后恢复失败任务。

[INPUT]
- (none)

[OUTPUT]
- DeadLetterQueue: Dead letter queue for failed message recovery.

[POS]
Dead Letter Queue with Persistence
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """死信队列（支持持久化）

    特性：
    1. 内存deque（maxlen限制）
    2. 可选文件持久化
    3. 服务重启自动恢复
    """

    def __init__(self, maxlen: int = 1000, persist_path: str | Path | None = None):
        """初始化DLQ

        Args:
            maxlen: 队列最大长度
            persist_path: 持久化文件路径（None则不持久化）
        """
        self.maxlen = maxlen
        self.persist_path = Path(persist_path) if persist_path else None

        self._queue: deque[dict[str, Any]] = deque(maxlen=maxlen)

        # 如果有持久化路径，尝试加载历史数据
        if self.persist_path:
            self._load_from_disk()

    def append(self, task: dict[str, Any]) -> None:
        """添加任务到DLQ

        Args:
            task: 任务数据（必须包含task_id）
        """
        self._queue.append(task)

        # 持久化到磁盘
        if self.persist_path:
            self._save_to_disk()

        logger.warning(
            f"Task added to DLQ: {task.get('task_id')} "
            f"(attempts: {task.get('attempts')}, error: {task.get('last_error')})"
        )

    def remove(self, task: dict[str, Any]) -> None:
        """从DLQ移除任务

        Args:
            task: 要移除的任务
        """
        try:
            self._queue.remove(task)

            if self.persist_path:
                self._save_to_disk()

        except ValueError:
            logger.warning(f"Task not found in DLQ: {task.get('task_id')}")

    def get_all(self) -> list[dict[str, Any]]:
        """获取所有DLQ任务"""
        return list(self._queue)

    def find_by_id(self, task_id: str) -> dict[str, Any] | None:
        """根据task_id查找任务"""
        for task in self._queue:
            if task.get("task_id") == task_id:
                return task
        return None

    def clear(self) -> int:
        """清空DLQ

        Returns:
            清空的任务数量
        """
        count = len(self._queue)
        self._queue.clear()

        if self.persist_path:
            self._save_to_disk()

        logger.info(f"DLQ cleared, removed {count} tasks")
        return count

    def __len__(self) -> int:
        return len(self._queue)

    # ==================== 私有方法 ====================

    def _save_to_disk(self) -> None:
        """保存到磁盘"""
        if not self.persist_path:
            return

        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "version": "1.0",
                "saved_at": datetime.now().isoformat(),
                "tasks": list(self._queue),
            }

            with open(self.persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save DLQ to disk: {e}")

    def _load_from_disk(self) -> None:
        """从磁盘加载"""
        if not self.persist_path or not self.persist_path.exists():
            return

        try:
            with open(self.persist_path, encoding="utf-8") as f:
                data = json.load(f)

            tasks = data.get("tasks", [])
            for task in tasks:
                self._queue.append(task)

            logger.info(f"DLQ loaded from disk: {len(tasks)} tasks")

        except Exception as e:
            logger.error(f"Failed to load DLQ from disk: {e}")
