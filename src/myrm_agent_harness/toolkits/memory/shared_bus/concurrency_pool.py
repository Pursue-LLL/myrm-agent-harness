"""多 Agent 共享并发连接池与内存背压守卫，保障高并发读写不锁死、内存不击穿。

[INPUT]
- toolkits.memory.shared_bus.types::BackpressureStatus, ConcurrencyPoolConfig (POS: 跨 Agent
  共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。)

[OUTPUT]
- MemoryBackpressureGuard: 轻量内存背压监控守卫，实时探针当前进程 RSS 水位。
- SharedMemoryConcurrencyPool: 多 Agent 共享并发读写连接池与背压协调器。

[POS]
多 Agent 共享并发连接池与内存背压守卫，保障高并发读写不锁死、内存不击穿。
"""

from __future__ import annotations

import asyncio
import os
import resource
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from myrm_agent_harness.toolkits.memory.shared_bus.types import (
    BackpressureStatus,
    ConcurrencyPoolConfig,
)


class MemoryBackpressureGuard:
    """轻量内存背压监控守卫，实时探针当前进程 RSS 水位。"""

    def __init__(self, threshold_mb: float = 2048.0) -> None:
        self.threshold_mb = threshold_mb

    def get_current_rss_mb(self) -> float:
        """获取当前进程的实际物理内存驻留集 (RSS) 大小 (MB)。"""
        try:
            # macOS ru_maxrss 单位是 bytes，Linux 单位是 kilobytes
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            max_rss = rusage.ru_maxrss
            if os.uname().sysname == "Darwin":
                return float(max_rss) / (1024.0 * 1024.0)
            return float(max_rss) / 1024.0
        except Exception:
            return 0.0

    def is_over_threshold(self) -> bool:
        """判断是否已超越内存背压警戒线。"""
        rss = self.get_current_rss_mb()
        return rss > self.threshold_mb if self.threshold_mb > 0 else False


class SharedMemoryConcurrencyPool:
    """多 Agent 共享并发读写连接池与背压协调器。"""

    def __init__(self, config: ConcurrencyPoolConfig | None = None) -> None:
        self._config = config or ConcurrencyPoolConfig()
        self._reader_sem = asyncio.Semaphore(self._config.max_concurrent_readers)
        self._writer_sem = asyncio.Semaphore(self._config.max_concurrent_writers)
        self._guard = MemoryBackpressureGuard(self._config.memory_rss_threshold_mb)

        self._active_readers: int = 0
        self._active_writers: int = 0
        self._queued_tasks: int = 0
        self._lock = asyncio.Lock()

    @property
    def config(self) -> ConcurrencyPoolConfig:
        return self._config

    def get_status(self) -> BackpressureStatus:
        """获取当前池化并发与内存背压健康状态。"""
        rss_mb = self._guard.get_current_rss_mb()
        is_over = self._config.enable_memory_guard and self._guard.is_over_threshold()

        status_msg = "HEALTHY"
        if is_over:
            status_msg = f"THROTTLED: RSS {rss_mb:.1f}MB exceeds limit {self._config.memory_rss_threshold_mb}MB"
        elif self._queued_tasks > self._config.max_queue_depth:
            status_msg = f"CONGESTED: Queued {self._queued_tasks} exceeds limit {self._config.max_queue_depth}"

        return BackpressureStatus(
            active_readers=self._active_readers,
            active_writers=self._active_writers,
            queued_tasks=self._queued_tasks,
            current_rss_mb=rss_mb,
            is_throttled=is_over,
            status_message=status_msg,
        )

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[None]:
        """获取共享读通道许可。"""
        async with self._lock:
            if (
                self._config.enable_memory_guard
                and self._guard.is_over_threshold()
            ):
                raise RuntimeError(
                    f"Memory backpressure triggered: current RSS {self._guard.get_current_rss_mb():.1f}MB "
                    f"exceeds safety threshold {self._config.memory_rss_threshold_mb}MB"
                )
            self._queued_tasks += 1

        try:
            await asyncio.wait_for(
                self._reader_sem.acquire(),
                timeout=self._config.acquire_timeout_seconds,
            )
            async with self._lock:
                self._queued_tasks -= 1
                self._active_readers += 1
            yield
        finally:
            async with self._lock:
                self._active_readers = max(0, self._active_readers - 1)
            self._reader_sem.release()

    @asynccontextmanager
    async def write_session(self) -> AsyncIterator[None]:
        """获取独占写通道许可。"""
        async with self._lock:
            if (
                self._config.enable_memory_guard
                and self._guard.is_over_threshold()
            ):
                raise RuntimeError(
                    f"Memory backpressure triggered: current RSS {self._guard.get_current_rss_mb():.1f}MB "
                    f"exceeds safety threshold {self._config.memory_rss_threshold_mb}MB"
                )
            self._queued_tasks += 1

        try:
            await asyncio.wait_for(
                self._writer_sem.acquire(),
                timeout=self._config.acquire_timeout_seconds,
            )
            async with self._lock:
                self._queued_tasks -= 1
                self._active_writers += 1
            yield
        finally:
            async with self._lock:
                self._active_writers = max(0, self._active_writers - 1)
            self._writer_sem.release()
