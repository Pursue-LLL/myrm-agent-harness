"""取消令牌机制

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- asyncio (POS: Python 标准库，提供异步编程支持)
- contextvars (POS: Python 标准库，ContextVar 跨层传递)
- collections.abc::Callable, Coroutine (POS: Python 标准库，类型注解)
- enum (POS: Python 标准库，枚举类型)
- threading (POS: Python 标准库，线程锁)
- time (POS: Python 标准库，时间测量)
- .cancellation_metrics::CancellationMetrics (POS: ./cancellation_metrics.py，监控数据结构)

[OUTPUT]
- CancelReason: 取消原因枚举（DISCONNECT/USER_CANCELLED/TIMEOUT/ERROR/ESTOP）
- CancellationToken: 取消令牌类，用于在异步操作中传递取消状态
- CancellationMonitor: 取消监控器，定期检查客户端连接状态 + 监控指标
- CancellationRegistry: 全局取消令牌注册表，支持单条 cancel、cancel_all（E-Stop）+ TTL清理
- CancellationMetrics: 监控数据结构（re-export）
- create_cancellation_context(): 创建取消上下文（令牌 + 监控器工厂）
- get_cancel_token() / set_cancel_token(): ContextVar 访问器，供工具层隐式获取/注入取消令牌
- OperationCancelledError / run_until_cancelled(): 令牌被取消时中止仍阻塞在驱动调用上的操作，让调用方在一个轮询周期内重新拿回控制权
- reraise_if_cancelled(): 在 ``except asyncio.CancelledError`` 内区分「本任务确被要求停止」与「SDK/子任务漏出的取消」，只在确被要求停止时重新抛出

[POS]
Cancellation token mechanism. Provides request-level cancellation state management with graceful async cancellation support.
The token is a pure flag; `run_until_cancelled` is the boundary for operations that cannot observe it by themselves, and
`reraise_if_cancelled` is the boundary for ``except`` blocks that would otherwise absorb a stop meant for their task.

"""

import asyncio
import contextlib
import inspect
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine
from contextvars import ContextVar
from enum import StrEnum
from typing import ClassVar

from .cancellation_metrics import CancellationMetrics

logger = logging.getLogger(__name__)


class CancelReason(StrEnum):
    """Cancellation reason categories for metrics and logging."""

    DISCONNECT = "client_disconnected"
    """Client connection closed (SSE/HTTP disconnect)"""

    USER_CANCELLED = "user_cancelled"
    """User actively cancelled the request via API"""

    TIMEOUT = "timeout"
    """Request exceeded timeout limit"""

    ERROR = "error"
    """Internal error triggered cancellation"""

    ESTOP = "estop"
    """Global E-Stop (/freeze) cancelled all active agent streams"""


class CancellationToken:
    """取消令牌，用于在异步操作中传递取消状态"""

    def __init__(self, request_id: str | None = None):
        self._cancelled = False
        self._request_id = request_id or "unknown"
        self._cancel_reason: CancelReason | str | None = None
        self._created_at = time.time()

    @property
    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._cancelled

    @property
    def request_id(self) -> str:
        """获取请求 ID (通常是 message_id)"""
        return self._request_id

    @property
    def cancel_reason(self) -> CancelReason | str | None:
        """获取取消原因"""
        return self._cancel_reason

    @property
    def created_at(self) -> float:
        """获取创建时间戳（用于TTL计算）"""
        return self._created_at

    def cancel(self, reason: CancelReason | str = CancelReason.DISCONNECT) -> None:
        """标记为已取消

        Args:
            reason: 取消原因（CancelReason枚举或自定义字符串）
        """
        if not self._cancelled:
            self._cancelled = True
            self._cancel_reason = reason
            reason_str = reason.value if isinstance(reason, CancelReason) else reason
            logger.warning(f" Request cancelled: request_id={self._request_id}, reason={reason_str}")

    def check_cancelled(self, operation: str = "operation") -> None:
        """检查是否已取消，如果已取消则抛出异常

        Args:
            operation: 当前操作名称，用于日志记录

        Raises:
            asyncio.CancelledError: 如果已取消
        """
        if self._cancelled:
            logger.warning(
                f" Operation aborted due to cancellation: "
                f"request_id={self._request_id}, operation={operation}, reason={self._cancel_reason}"
            )
            raise asyncio.CancelledError(f"Request cancelled: {self._cancel_reason}")


class CancellationMonitor:
    """取消监控器，用于定期检查客户端连接状态 + 监控指标收集"""

    def __init__(
        self,
        token: CancellationToken,
        disconnect_checker: Callable[[], Coroutine[None, None, bool]],
        check_interval: float = 0.5,
        immediate_mode: bool = False,
    ):
        """
        Args:
            token: 取消令牌
            disconnect_checker: 异步函数，返回 True 表示客户端已断开
            check_interval: 检查间隔（秒），默认 0.5s
            immediate_mode: 快速响应模式（使用 0.1s 间隔），默认 False
        """
        self._token = token
        self._disconnect_checker = disconnect_checker
        self._check_interval = 0.1 if immediate_mode else check_interval
        self._task: asyncio.Task[None] | None = None
        self.metrics = CancellationMetrics()

    async def start(self) -> None:
        """启动监控任务"""
        self.metrics.active_monitors += 1
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """停止监控任务"""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self.metrics.active_monitors = max(0, self.metrics.active_monitors - 1)

    async def _monitor_loop(self) -> None:
        """监控循环，定期检查客户端连接状态 + 收集监控指标"""
        try:
            while not self._token.is_cancelled:
                try:
                    # Record check operation
                    start_time = time.perf_counter()
                    disconnected = await self._disconnect_checker()
                    check_duration_ms = (time.perf_counter() - start_time) * 1000

                    # Update metrics
                    self.metrics.check_count += 1
                    self.metrics.check_total_ms += check_duration_ms
                    self.metrics.max_check_ms = max(self.metrics.max_check_ms, check_duration_ms)

                    if disconnected:
                        self.metrics.disconnect_detected_count += 1
                        self.metrics.cancel_triggered_count += 1
                        self._token.cancel(CancelReason.DISCONNECT)
                        self.metrics.cancel_completed_count += 1
                        break
                except (Exception, BaseException) as e:
                    if not isinstance(e, asyncio.CancelledError):
                        logger.debug(f"Disconnect checker failed (ignoring): {e}")
                    break

                await asyncio.sleep(self._check_interval)
        except asyncio.CancelledError:
            pass
        except BaseException as e:
            logger.debug(f"Monitor loop exited with error: {e}")


class CancellationRegistry:
    """Global registry for active cancellation tokens.

    Enables manual cancellation of agent requests via API.
    Includes TTL-based cleanup to prevent memory leaks.

    Thread-safe for concurrent access from multiple endpoints.
    """

    _lock = threading.Lock()
    _tokens: ClassVar[dict[str, CancellationToken]] = {}

    @classmethod
    def register(cls, token: CancellationToken) -> None:
        """Register a token for potential future cancellation.

        Args:
            token: CancellationToken to register
        """
        with cls._lock:
            cls._tokens[token.request_id] = token
        logger.debug(f"Registered cancellation token: {token.request_id}")

    @classmethod
    def unregister(cls, request_id: str) -> None:
        """Remove a token from the registry (called when request completes).

        Args:
            request_id: Request ID to unregister
        """
        with cls._lock:
            if cls._tokens.pop(request_id, None):
                logger.debug(f"Unregistered cancellation token: {request_id}")

    @classmethod
    def cancel(cls, request_id: str, reason: CancelReason | str = CancelReason.USER_CANCELLED) -> bool:
        """Cancel a specific request by ID.

        Args:
            request_id: Request ID to cancel
            reason: Cancellation reason

        Returns:
            True if token was found and cancelled, False otherwise
        """
        with cls._lock:
            token = cls._tokens.get(request_id)
            if token and not token.is_cancelled:
                token.cancel(reason)
                logger.info(f"Manually cancelled request: {request_id}, reason={reason}")
                return True
            return False

    @classmethod
    def cancel_all(cls, reason: CancelReason | str = CancelReason.ESTOP) -> int:
        """Cancel every active registered stream.

        Returns:
            Number of streams that were cancelled.
        """
        cancelled = 0
        with cls._lock:
            for token in cls._tokens.values():
                if not token.is_cancelled:
                    token.cancel(reason)
                    cancelled += 1
        if cancelled:
            reason_str = reason.value if isinstance(reason, CancelReason) else reason
            logger.info("Cancelled %d active agent streams, reason=%s", cancelled, reason_str)
        return cancelled

    @classmethod
    def get_active_count(cls) -> int:
        """Get number of currently registered tokens.

        Returns:
            Number of active tokens
        """
        with cls._lock:
            return len(cls._tokens)

    @classmethod
    def cleanup_expired(cls, ttl_seconds: float = 3600) -> int:
        """Remove tokens older than TTL (prevents memory leaks).

        Args:
            ttl_seconds: Time-to-live in seconds (default 1 hour)

        Returns:
            Number of expired tokens removed
        """
        now = time.time()
        expired = []
        with cls._lock:
            for req_id, token in cls._tokens.items():
                if now - token.created_at > ttl_seconds:
                    expired.append(req_id)
            for req_id in expired:
                cls._tokens.pop(req_id, None)

        if expired:
            logger.warning(f"Cleaned up {len(expired)} expired cancellation tokens (TTL={ttl_seconds}s)")
        return len(expired)


__all__ = [
    "CancelReason",
    "CancellationMetrics",
    "CancellationMonitor",
    "CancellationRegistry",
    "CancellationToken",
    "OperationCancelledError",
    "create_cancellation_context",
    "get_cancel_token",
    "reraise_if_cancelled",
    "run_until_cancelled",
    "set_cancel_token",
]

_cancel_token: ContextVar[CancellationToken | None] = ContextVar("_cancel_token", default=None)


def get_cancel_token() -> CancellationToken | None:
    """Retrieve the current CancellationToken (None when outside BaseAgent.run)."""
    return _cancel_token.get()


def set_cancel_token(token: CancellationToken | None) -> None:
    """Set or clear the CancellationToken for the current async context."""
    _cancel_token.set(token)


_POLL_INTERVAL_S = 0.25
_ABORT_GRACE_S = 3.0


class OperationCancelledError(Exception):
    """The request was cancelled while an operation was still running, and the operation was aborted."""


def reraise_if_cancelled(exc: asyncio.CancelledError) -> None:
    """Raise *exc* again when *this* task was really asked to stop, otherwise return.

    Call inside an ``except asyncio.CancelledError`` block that wants to treat the error as something other than a
    stop. A ``CancelledError`` can also arrive when nobody asked this task to stop: an SDK cancel scope leaks one on
    timeout, and ``asyncio.gather(..., return_exceptions=True)`` hands a cancelled child back as a *value*, whose
    cancellation never travels through the parent. Swallowing it is only wrong when the stop was aimed here, which
    ``Task.cancelling()`` tells apart; absorbing a real ``wait_for`` timeout or ``task.cancel()`` would instead leave
    the caller waiting on a task that never ends.
    """
    task = asyncio.current_task()
    if task is not None and task.cancelling() > 0:
        raise exc


def _discard_outcome[T](task: asyncio.Future[T]) -> None:
    """Mark an abandoned task's outcome as retrieved so its unwind errors are not reported at GC."""
    if not task.cancelled():
        task.exception()


async def run_until_cancelled[T](work: Awaitable[T]) -> T:
    """Await `work`, aborting it as soon as the current request's token is cancelled.

    Cancelling a request only flips a flag. An operation blocked inside a driver call (a browser
    navigation to a server that never answers) never looks at it, so this races the operation
    against the flag and hands control back within one poll interval. Outside an agent run (no
    token) the work is simply awaited.

    Raises:
        OperationCancelledError: the token fired first; the work was cancelled and given a bounded
            grace period to unwind.
        asyncio.CancelledError: the caller itself was cancelled; the work is cancelled with it.
    """
    token = get_cancel_token()
    if token is None:
        return await work
    if token.is_cancelled:
        if inspect.iscoroutine(work):
            work.close()  # never started: avoid the 'never awaited' warning
        raise OperationCancelledError(f"Request cancelled before the operation started: {token.cancel_reason}")

    task = asyncio.ensure_future(work)
    task.add_done_callback(_discard_outcome)
    try:
        while True:
            await asyncio.wait({task}, timeout=_POLL_INTERVAL_S)
            if task.done():
                return task.result()
            if token.is_cancelled:
                break
    except asyncio.CancelledError:
        task.cancel()
        raise

    logger.warning("Aborting in-flight operation: request_id=%s, reason=%s", token.request_id, token.cancel_reason)
    task.cancel()
    await asyncio.wait({task}, timeout=_ABORT_GRACE_S)
    raise OperationCancelledError(f"Request cancelled during the operation: {token.cancel_reason}")


def create_cancellation_context(
    request_id: str | None = None,
) -> tuple[CancellationToken, Callable[[Callable[[], Coroutine[None, None, bool]]], CancellationMonitor]]:
    """创建取消上下文

    Args:
        request_id: 请求 ID (通常是 message_id)

    Returns:
        (token, monitor_factory): 取消令牌和监控器工厂函数
    """
    token = CancellationToken(request_id)

    def create_monitor(disconnect_checker: Callable[[], Coroutine[None, None, bool]]) -> CancellationMonitor:
        return CancellationMonitor(token, disconnect_checker)

    return token, create_monitor
