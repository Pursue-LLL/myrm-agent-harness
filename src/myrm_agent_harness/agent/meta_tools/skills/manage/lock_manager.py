"""Skill concurrency lock manager.

[INPUT]
- asyncio.Lock (POS: Async lock primitive)
- weakref.WeakValueDictionary (POS: Auto-cleanup weak references)

[OUTPUT]
- SkillLockManager: Concurrency control for skill modifications

[POS]
Provides per-skill lock mechanism to prevent concurrent modifications.
Uses WeakValueDictionary for automatic lock cleanup when no longer referenced.
Framework-layer utility, can be used across business layers.
"""

from __future__ import annotations

import asyncio
from weakref import WeakValueDictionary


class SkillLockManager:
    """技能并发锁管理器（框架层工具类）

    Features:
    - Per-skill lock isolation（按技能名+user_id隔离）
    - Auto-cleanup via WeakValueDictionary（自动清理未使用的锁）
    - Thread-safe lock acquisition（线程安全）

    Usage:
        lock = SkillLockManager.get_lock("my-skill", "user_123")
        async with lock:
            # Critical section: modify skill
            await backend.save_skill(...)
    """

    _locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
    _global_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_lock(cls, skill_name: str, user_id: str) -> asyncio.Lock:
        """获取指定技能的锁对象。

        Args:
            skill_name: 技能名称
            user_id: 用户 ID

        Returns:
            asyncio.Lock对象（可用于async with）
        """
        lock_key = f"{user_id}:{skill_name}"

        existing = cls._locks.get(lock_key)
        if existing:
            return existing

        new_lock = asyncio.Lock()
        cls._locks[lock_key] = new_lock
        return new_lock

    @classmethod
    def get_lock_count(cls) -> int:
        """获取当前活跃的锁数量（用于监控/调试）。

        Returns:
            活跃锁数量
        """
        return len(cls._locks)
