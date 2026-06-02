"""StorageProvider错误处理和降级策略

职责：
- 统一的异常捕获和重试机制
- 降级策略（云存储失败时的优雅处理）
- 错误日志和监控钩子
- 可观测性指标

[INPUT]
- myrm_agent_harness.toolkits.storage.base::StorageProvider (POS: Provides FileOperationObserver.)

[OUTPUT]
- resilient_storage_operation: 弹性存储操作装饰器
- StorageError: 存储错误基类
- TemporaryStorageError: 临时错误（可重试）
- PermanentStorageError: 永久错误（不可重试）

[POS]
StorageProvider resilience layer. Ensures production availability with typed errors and retry logic.

"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T")


class StorageErrorType(Enum):
    """存储错误类型"""

    NETWORK = "network"  # 网络错误
    PERMISSION = "permission"  # 权限错误
    NOT_FOUND = "not_found"  # 文件未找到
    QUOTA_EXCEEDED = "quota_exceeded"  # 配额超限
    TIMEOUT = "timeout"  # 超时
    UNKNOWN = "unknown"  # 未知错误


class StorageError(Exception):
    """存储错误基类"""

    def __init__(self, message: str, error_type: StorageErrorType, original_error: Exception | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.original_error = original_error


class TemporaryStorageError(StorageError):
    """临时存储错误（可重试）"""

    pass


class PermanentStorageError(StorageError):
    """永久存储错误（不可重试）"""

    pass


@dataclass
class StorageMetrics:
    """存储操作指标"""

    operation: str  # read/write/delete/list
    success: bool
    duration_ms: float
    error_type: StorageErrorType | None = None
    retry_count: int = 0


class StorageOperationCallback:
    """存储操作回调（用于监控和日志）"""

    def on_success(self, metrics: StorageMetrics) -> None:
        """操作成功回调"""
        pass

    def on_error(self, metrics: StorageMetrics, error: Exception) -> None:
        """操作失败回调"""
        pass

    def on_retry(self, metrics: StorageMetrics, attempt: int, max_attempts: int) -> None:
        """重试回调"""
        pass


class DefaultStorageCallback(StorageOperationCallback):
    """默认存储回调（记录日志）"""

    def on_success(self, metrics: StorageMetrics) -> None:
        if metrics.duration_ms > 1000:
            logger.warning(
                f"Slow storage operation: {metrics.operation} took {metrics.duration_ms:.0f}ms "
                f"(retries={metrics.retry_count})"
            )

    def on_error(self, metrics: StorageMetrics, error: Exception) -> None:
        logger.error(
            f"Storage operation failed: {metrics.operation}, "
            f"error_type={metrics.error_type}, duration={metrics.duration_ms:.0f}ms, "
            f"retries={metrics.retry_count}, error={error}"
        )

    def on_retry(self, metrics: StorageMetrics, attempt: int, max_attempts: int) -> None:
        logger.warning(
            f"Retrying storage operation: {metrics.operation} "
            f"(attempt {attempt}/{max_attempts}, error_type={metrics.error_type})"
        )


def _classify_error(error: Exception) -> StorageErrorType:
    """分类存储错误"""
    error_str = str(error).lower()
    error_type_name = type(error).__name__.lower()

    # 网络错误
    if any(
        keyword in error_str or keyword in error_type_name
        for keyword in ["connection", "network", "timeout", "timed out", "unreachable"]
    ):
        return StorageErrorType.NETWORK

    # 权限错误
    if any(
        keyword in error_str or keyword in error_type_name for keyword in ["permission", "forbidden", "unauthorized"]
    ):
        return StorageErrorType.PERMISSION

    # 文件未找到
    if "filenotfound" in error_type_name or "not found" in error_str:
        return StorageErrorType.NOT_FOUND

    # 配额超限
    if any(keyword in error_str for keyword in ["quota", "limit", "too many", "rate limit"]):
        return StorageErrorType.QUOTA_EXCEEDED

    # 超时
    if "timeout" in error_type_name or "timeout" in error_str:
        return StorageErrorType.TIMEOUT

    return StorageErrorType.UNKNOWN


def _is_retryable(error_type: StorageErrorType) -> bool:
    """判断错误是否可重试"""
    return error_type in {
        StorageErrorType.NETWORK,
        StorageErrorType.TIMEOUT,
        StorageErrorType.QUOTA_EXCEEDED,
        StorageErrorType.UNKNOWN,
    }


async def resilient_storage_operation[T](
    operation: str,
    func: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    initial_backoff_ms: int = 100,
    max_backoff_ms: int = 5000,
    callback: StorageOperationCallback | None = None,
) -> T:
    """执行弹性存储操作（带重试和错误处理）

    Args:
        operation: 操作名称（read/write/delete/list）
        func: 异步操作函数
        max_retries: 最大重试次数（默认3次）
        initial_backoff_ms: 初始退避时间（默认100ms）
        max_backoff_ms: 最大退避时间（默认5000ms）
        callback: 操作回调（用于监控）

    Returns:
        操作结果

    Raises:
        TemporaryStorageError: 临时错误，重试后仍失败
        PermanentStorageError: 永久错误，无法重试
    """
    if callback is None:
        callback = DefaultStorageCallback()

    last_error: Exception | None = None
    retry_count = 0

    for attempt in range(max_retries + 1):
        start_time = time.time()

        try:
            result = await func()

            # 成功
            duration_ms = (time.time() - start_time) * 1000
            metrics = StorageMetrics(
                operation=operation,
                success=True,
                duration_ms=duration_ms,
                retry_count=retry_count,
            )
            callback.on_success(metrics)
            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            error_type = _classify_error(e)
            last_error = e

            metrics = StorageMetrics(
                operation=operation,
                success=False,
                duration_ms=duration_ms,
                error_type=error_type,
                retry_count=retry_count,
            )

            # 判断是否可重试
            if not _is_retryable(error_type):
                callback.on_error(metrics, e)
                raise PermanentStorageError(
                    f"Permanent storage error: {operation}", error_type=error_type, original_error=e
                ) from e

            # 最后一次尝试也失败了
            if attempt == max_retries:
                callback.on_error(metrics, e)
                raise TemporaryStorageError(
                    f"Storage operation failed after {max_retries} retries: {operation}",
                    error_type=error_type,
                    original_error=e,
                ) from e

            # 重试
            retry_count += 1
            callback.on_retry(metrics, attempt + 1, max_retries)

            # 指数退避
            backoff_ms = min(initial_backoff_ms * (2**attempt), max_backoff_ms)
            await asyncio.sleep(backoff_ms / 1000)

    # 不应该到达这里
    assert last_error is not None
    raise TemporaryStorageError(
        f"Storage operation failed: {operation}", error_type=StorageErrorType.UNKNOWN, original_error=last_error
    )
