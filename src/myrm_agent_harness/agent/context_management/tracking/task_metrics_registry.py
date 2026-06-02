"""TaskMetrics in-memory registry.

[INPUT]
- datetime::datetime (POS: Python 日期时间)
- threading::Lock (POS: Python 线程锁)
- tracking.task_metrics_model::TaskMetrics (POS: 任务指标领域模型)
- utils.logger_utils::get_agent_logger (POS: Agent 日志工具)

[OUTPUT]
- create_task_metrics: create or fetch metrics for a chat.
- get_task_metrics: fetch metrics for a chat.
- get_or_create_task_metrics: nullable chat helper.
- clear_task_metrics: remove metrics for a chat.
- get_all_active_metrics: snapshot active metrics.

[POS]
Task metrics registry. Owns process-local TaskMetrics storage, expiry cleanup, and thread-safe lookup.
"""

from datetime import datetime
from threading import Lock

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .task_metrics_model import TaskMetrics

logger = get_agent_logger(__name__)

_task_metrics_store: dict[str, TaskMetrics] = {}
_store_lock = Lock()

DEFAULT_METRICS_TTL_SECONDS = 24 * 60 * 60
MAX_METRICS_ENTRIES = 1000


def create_task_metrics(chat_id: str) -> TaskMetrics:
    """创建任务指标实例"""
    with _store_lock:
        if len(_task_metrics_store) >= MAX_METRICS_ENTRIES:
            _cleanup_expired_metrics_unsafe()

        if chat_id not in _task_metrics_store:
            _task_metrics_store[chat_id] = TaskMetrics(task_id=chat_id)
            logger.info(" [TaskMetrics] Created new task metrics for: %s...", chat_id[:8])
        return _task_metrics_store[chat_id]


def _cleanup_expired_metrics_unsafe() -> int:
    """清理过期的任务指标(不加锁版本,调用方需持有锁)"""
    now = datetime.now()
    expired_ids = []

    for chat_id, metrics in _task_metrics_store.items():
        age_seconds = (now - metrics.task_start_time).total_seconds()
        if age_seconds > DEFAULT_METRICS_TTL_SECONDS:
            expired_ids.append(chat_id)

    for chat_id in expired_ids:
        del _task_metrics_store[chat_id]

    if len(_task_metrics_store) >= MAX_METRICS_ENTRIES:
        sorted_items = sorted(_task_metrics_store.items(), key=lambda x: x[1].task_start_time)
        to_remove = max(1, len(sorted_items) // 10)
        for chat_id, _ in sorted_items[:to_remove]:
            del _task_metrics_store[chat_id]
            expired_ids.append(chat_id)

    if expired_ids:
        logger.warning(" [TaskMetrics] Cleaned up %d expired entries", len(expired_ids))

    return len(expired_ids)


def get_task_metrics(chat_id: str) -> TaskMetrics | None:
    """获取任务指标实例"""
    with _store_lock:
        return _task_metrics_store.get(chat_id)


def get_or_create_task_metrics(chat_id: str | None) -> TaskMetrics | None:
    """获取或创建任务指标实例"""
    if chat_id is None:
        return None
    return create_task_metrics(chat_id)


def clear_task_metrics(chat_id: str) -> None:
    """清除任务指标"""
    with _store_lock:
        if chat_id in _task_metrics_store:
            metrics = _task_metrics_store.pop(chat_id)
            logger.info(" [TaskMetrics] Cleared: %s", metrics.to_summary())


def get_all_active_metrics() -> dict[str, TaskMetrics]:
    """获取所有活跃的任务指标"""
    with _store_lock:
        return dict(_task_metrics_store)


__all__ = [
    "DEFAULT_METRICS_TTL_SECONDS",
    "MAX_METRICS_ENTRIES",
    "_store_lock",
    "_task_metrics_store",
    "clear_task_metrics",
    "create_task_metrics",
    "get_all_active_metrics",
    "get_or_create_task_metrics",
    "get_task_metrics",
]
