"""操作系统文件描述符（FD）水位监控与紧急反压哨兵模块.

本模块负责高性能、低开销地采样进程当前占用的文件描述符数量，
根据软限制阈值实时判决高水位预警与反压状态，防止系统级 EMFILE 崩溃。

[INPUT]
- __future__
- logging
- os
- time

[OUTPUT]
- logger
- FDWatermarkSentinel

[POS]
操作系统文件描述符（FD）水位监控与紧急反压哨兵模块.
"""

from __future__ import annotations

import logging
import os
import time

from myrm_agent_harness.runtime.socket_lease_governor.nofile_limit_lifter import (
    get_nofile_limits,
)
from myrm_agent_harness.runtime.socket_lease_governor.socket_governor_types import (
    FDMetricsSnapshot,
    FDWatermarkStatus,
    GovernorConfig,
)

logger = logging.getLogger(__name__)


class FDWatermarkSentinel:
    """文件描述符水位监测与反压决策哨兵."""

    def __init__(
        self,
        config: GovernorConfig | None = None,
        cache_ttl_ms: float = 100.0,
    ) -> None:
        self.config: GovernorConfig = config or GovernorConfig()
        self.cache_ttl_ms: float = cache_ttl_ms

        self._cached_snapshot: FDMetricsSnapshot | None = None
        self._last_sample_time_ms: float = 0.0

        # 检测系统支持的 FD 读取路径
        self._fd_dir_path: str | None = None
        for candidate in ("/dev/fd", "/proc/self/fd"):
            if os.path.exists(candidate) and os.path.isdir(candidate):
                self._fd_dir_path = candidate
                break

    def count_open_fds(self) -> int:
        """获取当前进程实际打开的文件描述符数量."""
        if self._fd_dir_path is not None:
            try:
                # /dev/fd 或 /proc/self/fd 下的条目数直接对应已打开的 fd
                return len(os.listdir(self._fd_dir_path))
            except (OSError, PermissionError) as exc:
                logger.debug("Failed to list %s: %s", self._fd_dir_path, exc)

        # 平台不支持或读取失败时的安全兜底估算
        return 32

    def sample_metrics(self, force_refresh: bool = False) -> FDMetricsSnapshot:
        """采样当前 FD 水位指标快照（带毫秒级短时缓存防高频系统调用颠簸）."""
        now_ms = time.time() * 1000
        if (
            not force_refresh
            and self._cached_snapshot is not None
            and (now_ms - self._last_sample_time_ms) < self.cache_ttl_ms
        ):
            return self._cached_snapshot

        allocated = self.count_open_fds()
        soft_limit, hard_limit = get_nofile_limits()

        # 若软限制无法取得或为负数，采用安全基准 1024
        effective_soft = soft_limit if soft_limit > 0 else 1024
        effective_hard = hard_limit if hard_limit > 0 else effective_soft

        usage_ratio = allocated / effective_soft

        # 判定水位状态
        if usage_ratio >= self.config.fd_critical_ratio:
            status = FDWatermarkStatus.CRITICAL_BACKPRESSURE
        elif usage_ratio >= self.config.fd_warning_ratio:
            status = FDWatermarkStatus.WARNING
        else:
            status = FDWatermarkStatus.NORMAL

        snapshot = FDMetricsSnapshot(
            allocated_fds=allocated,
            soft_limit=effective_soft,
            hard_limit=effective_hard,
            usage_ratio=round(usage_ratio, 4),
            status=status,
            recorded_at_ms=now_ms,
        )

        self._cached_snapshot = snapshot
        self._last_sample_time_ms = now_ms
        return snapshot

    def is_backpressure_active(self) -> bool:
        """当前是否处于反压状态（达到危急水位限制）."""
        snapshot = self.sample_metrics()
        return snapshot.status == FDWatermarkStatus.CRITICAL_BACKPRESSURE
