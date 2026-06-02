"""Steering 令牌机制

[INPUT]
- contextvars::ContextVar (POS: Python 标准库，请求级隔离)
- threading::Lock (POS: Python 标准库，线程安全)

[OUTPUT]
- SteeringToken: Steering 令牌类，允许外部在 Agent 运行时注入消息
- get_steering_token(): 获取当前请求的 SteeringToken
- set_steering_token(): 设置当前请求的 SteeringToken

[POS]
Steering token mechanism. Allows external message injection during Agent runtime to interrupt the current tool chain.

"""

import threading
from contextvars import ContextVar

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

STEERING_SKIP_MESSAGE = "Skipped: user sent a new message, remaining tool calls cancelled."


class SteeringToken:
    """运行时 Steering 令牌

    允许外部在 Agent 运行时注入消息，中断当前工具链。

    两层防御设计：
    1. 中间件层（快速路径）：多工具场景下，跳过剩余工具调用
    2. Agent 层（兜底路径）：turn 结束后检测 steering，注入 HumanMessage

    线程安全：steer() 可从任意线程调用（如 HTTP POST 端点）。
    """

    def __init__(self) -> None:
        self._queue: list[str] = []
        self._activated_messages: list[str] = []
        self._active: bool = False
        self._steering_applied: bool = False
        self._lock = threading.Lock()

    def steer(self, message: str) -> None:
        """注入 steering 消息（外部 API，线程安全）

        Args:
            message: 用户的新消息
        """
        with self._lock:
            self._queue.append(message)
        logger.warning(f"Steering message queued: {message[:80]}...")

    @property
    def has_pending(self) -> bool:
        """是否有待处理的 steering 消息"""
        with self._lock:
            return bool(self._queue)

    @property
    def is_active(self) -> bool:
        """steering 是否已激活（后续工具应跳过）"""
        return self._active

    @property
    def steering_applied(self) -> bool:
        """本轮是否已应用过 steering（Agent 层兜底检查用）"""
        return self._steering_applied

    def activate(self) -> list[str]:
        """激活 steering 并返回所有待处理消息

        原子操作：设置 _active=True 并清空队列。
        消息同时保存到 _activated_messages，供 Agent 层兜底取出。
        后续工具调用检查 is_active 后直接跳过。

        Returns:
            steering 消息列表（可能为空，如果已激活或无消息）
        """
        with self._lock:
            if self._active or not self._queue:
                return []
            self._active = True
            self._steering_applied = True
            msgs = self._queue[:]
            self._queue.clear()
            self._activated_messages.extend(msgs)
        logger.warning(f"Steering activated with {len(msgs)} message(s)")
        return msgs

    def collect_all_steering_messages(self) -> list[str]:
        """收集所有 steering 消息（Agent 层兜底用）

        合并 activate() 阶段的消息和后续入队的消息，一次性取出。
        调用后清空所有缓存。

        Returns:
            所有 steering 消息列表
        """
        with self._lock:
            msgs = self._activated_messages + self._queue
            self._activated_messages.clear()
            self._queue.clear()
        return msgs

    def reset_turn(self) -> None:
        """重置 turn 级状态（新 turn 开始时调用）

        重置 _active、_steering_applied 和 _activated_messages，
        但保留队列中的消息。
        """
        self._active = False
        self._steering_applied = False
        self._activated_messages.clear()


# ==================== ContextVar 隔离 ====================

_steering_token_var: ContextVar[SteeringToken | None] = ContextVar("steering_token", default=None)


def get_steering_token() -> SteeringToken | None:
    """获取当前请求的 SteeringToken"""
    return _steering_token_var.get()


def set_steering_token(token: SteeringToken | None) -> None:
    """设置当前请求的 SteeringToken"""
    _steering_token_var.set(token)
