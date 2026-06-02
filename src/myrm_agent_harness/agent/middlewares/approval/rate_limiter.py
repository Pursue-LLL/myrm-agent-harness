"""Approval request rate limiter

防止审批请求滥用（恶意用户、Bug 导致的循环请求）。

[INPUT]

[OUTPUT]
- ApprovalRateLimiter: 滑动窗口速率限制器

[POS]
Approval rate limiter. Independent from core approval logic for easy testing and configuration.

"""

from __future__ import annotations

import time
from collections import defaultdict


class ApprovalRateLimiter:
    """审批请求速率限制器（滑动窗口算法）

    使用滑动窗口记录每个用户的请求时间戳，超过限制时拒绝新请求。

    Args:
        max_requests: 窗口内最大请求数
        window_seconds: 时间窗口（秒）
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check_limit(self, user_id: str) -> bool:
        """检查用户是否超过速率限制

        Args:
            user_id: 用户 ID

        Returns:
            True: 允许请求
            False: 超过限制，拒绝请求
        """
        now = time.time()
        cutoff = now - self._window_seconds

        # 清理过期记录
        user_requests = self._requests[user_id]
        self._requests[user_id] = [ts for ts in user_requests if ts > cutoff]

        # 检查限制
        if len(self._requests[user_id]) >= self._max_requests:
            return False

        # 记录本次请求
        self._requests[user_id].append(now)
        return True

    def get_remaining(self, user_id: str) -> int:
        """获取用户剩余可用请求数

        Args:
            user_id: 用户 ID

        Returns:
            剩余请求数
        """
        now = time.time()
        cutoff = now - self._window_seconds
        user_requests = self._requests.get(user_id, [])
        active_requests = [ts for ts in user_requests if ts > cutoff]
        return max(0, self._max_requests - len(active_requests))

    def reset(self, user_id: str | None = None) -> None:
        """重置速率限制记录

        Args:
            user_id: 用户 ID，None 则重置所有用户
        """
        if user_id is None:
            self._requests.clear()
        else:
            self._requests.pop(user_id, None)


# 全局单例（默认配置：10 次/分钟）
_global_limiter = ApprovalRateLimiter(max_requests=10, window_seconds=60)


def get_approval_rate_limiter() -> ApprovalRateLimiter:
    """获取全局速率限制器实例"""
    return _global_limiter
