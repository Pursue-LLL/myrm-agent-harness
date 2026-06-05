"""Per-User Rate Limiter for Skill Optimization

P1-9: 实现per-user速率限制，防止单个用户占用过多优化资源。

[INPUT]
- (none)

[OUTPUT]
- UserRateLimiter: class — User Rate Limiter
- get_rate_limiter: function — get_rate_limiter

[POS]
Per-User Rate Limiter for Skill Optimization
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta


class RateLimitExceeded(Exception):  # noqa: N818  intentional descriptive name (public API, cross-repo)
    """Raised when a user exceeds their rate limit quota."""

    def __init__(self, detail: str, *, retry_after: str | None = None):
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after


class UserRateLimiter:
    """Per-User速率限制器

    维护每个用户的并发优化配额，防止资源滥用。

    特性：
    1. 并发控制：每用户最大并发优化数
    2. 日配额：每用户每日优化次数限制
    3. 自动重置：每日0点重置配额
    """

    def __init__(self, max_concurrent_per_user: int = 3, daily_quota_per_user: int = 50):
        """初始化速率限制器

        Args:
            max_concurrent_per_user: 每用户最大并发数（默认3）
            daily_quota_per_user: 每用户每日配额（默认50次）
        """
        self.max_concurrent_per_user = max_concurrent_per_user
        self.daily_quota_per_user = daily_quota_per_user

        # 并发控制 {user_id: Semaphore}
        self._user_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self.max_concurrent_per_user)
        )

        # 日配额追踪 {user_id: {"count": int, "reset_at": datetime}}
        self._daily_quotas: dict[str, dict[str, int | datetime]] = defaultdict(
            lambda: {
                "count": 0,
                "reset_at": self._get_next_reset_time(),
            }
        )

    def _get_next_reset_time(self) -> datetime:
        """获取下次重置时间（明天0点）"""
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)

    async def acquire(self, user_id: str = "default") -> None:
        """获取优化配额

        检查并发和日配额限制。

        Args:
            user_id: 用户ID

        Raises:
            HTTPException: 429 Too Many Requests (超额)
        """
        # 检查日配额
        quota = self._daily_quotas[user_id]

        # 自动重置配额（如果已过0点）
        if datetime.now() >= quota["reset_at"]:
            quota["count"] = 0
            quota["reset_at"] = self._get_next_reset_time()

        if quota["count"] >= self.daily_quota_per_user:
            reset_at_str = quota["reset_at"].strftime("%Y-%m-%d %H:%M:%S")
            raise RateLimitExceeded(
                f"Daily quota exceeded. Limit: {self.daily_quota_per_user}/day. Resets at {reset_at_str}",
                retry_after=reset_at_str,
            )

        # 检查并发限制
        semaphore = self._user_semaphores[user_id]
        if semaphore.locked():
            current_concurrent = self.max_concurrent_per_user - semaphore._value
            if current_concurrent >= self.max_concurrent_per_user:
                raise RateLimitExceeded(
                    f"Concurrent optimization limit exceeded. Limit: {self.max_concurrent_per_user} concurrent",
                )

        # 获取并发锁
        await semaphore.acquire()

        # 增加日配额计数
        quota["count"] += 1

    def release(self, user_id: str = "default") -> None:
        """释放并发配额

        Args:
            user_id: 用户ID
        """
        if user_id in self._user_semaphores:
            self._user_semaphores[user_id].release()

    def get_user_quota_status(self, user_id: str = "default") -> dict[str, object]:
        """获取用户配额状态

        Args:
            user_id: 用户ID

        Returns:
            配额状态信息
        """
        quota = self._daily_quotas[user_id]
        semaphore = self._user_semaphores.get(user_id)

        current_concurrent = 0
        if semaphore:
            current_concurrent = self.max_concurrent_per_user - semaphore._value

        return {
            "user_id": user_id,
            "daily_quota": {
                "limit": self.daily_quota_per_user,
                "used": quota["count"],
                "remaining": max(0, self.daily_quota_per_user - quota["count"]),
                "reset_at": quota["reset_at"].isoformat(),
            },
            "concurrent": {
                "limit": self.max_concurrent_per_user,
                "current": current_concurrent,
                "available": max(0, self.max_concurrent_per_user - current_concurrent),
            },
        }


# 全局实例（单例）
_rate_limiter_instance: UserRateLimiter | None = None


def get_rate_limiter() -> UserRateLimiter:
    """获取速率限制器实例（单例）"""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        _rate_limiter_instance = UserRateLimiter()
    return _rate_limiter_instance
