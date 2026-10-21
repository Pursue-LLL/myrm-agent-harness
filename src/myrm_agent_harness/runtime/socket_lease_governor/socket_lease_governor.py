"""全系统连接池枯竭防御与统一 Socket 租约中枢模块.

本模块实现各异步工具与 MCP 服务调用的统一连接租借治理，
通过严格的硬配额隔离、高水位反压熔断与有界等待，防止底层连接池耗尽与进程级崩溃。

[INPUT]
- __future__
- asyncio
- logging
- uuid
- collections
- contextlib

[OUTPUT]
- logger
- SocketLeaseGovernor

[POS]
全系统连接池枯竭防御与统一 Socket 租约中枢模块.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from myrm_agent_harness.runtime.socket_lease_governor.fd_watermark_sentinel import (
    FDWatermarkSentinel,
)
from myrm_agent_harness.runtime.socket_lease_governor.socket_governor_types import (
    GovernorConfig,
    LeaseAcquisitionTimeoutError,
    ResourceLeaseType,
    ResourceOverloadError,
    SocketLeaseTicket,
)

logger = logging.getLogger(__name__)


class SocketLeaseGovernor:
    """统一连接租约中枢与资源防枯竭协调器."""

    def __init__(
        self,
        config: GovernorConfig | None = None,
        sentinel: FDWatermarkSentinel | None = None,
    ) -> None:
        self.config: GovernorConfig = config or GovernorConfig()
        self.sentinel: FDWatermarkSentinel = sentinel or FDWatermarkSentinel(config=self.config)

        # 为各资源通道初始化独立的 BoundedSemaphore 硬配额池
        self._pools: dict[ResourceLeaseType, asyncio.BoundedSemaphore] = {
            ResourceLeaseType.HTTP_SOCKET: asyncio.BoundedSemaphore(self.config.max_http_sockets),
            ResourceLeaseType.DATABASE_CONNECTION: asyncio.BoundedSemaphore(
                self.config.max_db_connections
            ),
            ResourceLeaseType.VECTOR_STORAGE: asyncio.BoundedSemaphore(
                self.config.max_vector_connections
            ),
            ResourceLeaseType.MCP_TRANSPORT: asyncio.BoundedSemaphore(
                self.config.max_mcp_transports
            ),
        }

        # 统计计数器
        self._active_leases: dict[ResourceLeaseType, int] = {
            res: 0 for res in ResourceLeaseType
        }
        self.total_acquired_count: int = 0
        self.total_timeout_count: int = 0
        self.total_rejected_count: int = 0

    def get_active_leases(self, resource_type: ResourceLeaseType) -> int:
        """获取指定资源当前持有的活跃租约数量."""
        return self._active_leases.get(resource_type, 0)

    @asynccontextmanager
    async def acquire_lease(
        self,
        resource_type: ResourceLeaseType,
        timeout: float | None = None,
        priority: bool = False,
    ) -> AsyncIterator[SocketLeaseTicket]:
        """异步租借受管连接配额上下文管理器.

        若当前系统处于危急 FD 反压状态且非特权请求，直接熔断拒绝；
        否则在有限超时内排队申请信号量，离开作用域自动安全归还。
        """
        acquire_timeout = (
            timeout if timeout is not None else self.config.default_acquire_timeout
        )

        # 1. 检查文件描述符水位反压
        if not priority and self.sentinel.is_backpressure_active():
            snapshot = self.sentinel.sample_metrics()
            self.total_rejected_count += 1
            msg = (
                f"Connection lease rejected due to CRITICAL_BACKPRESSURE. "
                f"FD usage: {snapshot.usage_ratio * 100:.1f}% "
                f"({snapshot.allocated_fds}/{snapshot.soft_limit})"
            )
            logger.warning(msg)
            raise ResourceOverloadError(message=msg, current_fd_ratio=snapshot.usage_ratio)

        # 2. 获取目标资源信号量
        sem = self._pools[resource_type]
        try:
            await asyncio.wait_for(sem.acquire(), timeout=acquire_timeout)
        except TimeoutError as exc:
            self.total_timeout_count += 1
            logger.warning(
                "Timeout acquiring socket lease for '%s' after %ss",
                resource_type,
                acquire_timeout,
            )
            raise LeaseAcquisitionTimeoutError(
                resource_type=resource_type,
                timeout=acquire_timeout,
            ) from exc

        # 3. 构造租约凭证
        ticket = SocketLeaseTicket(
            ticket_id=f"lease_{uuid.uuid4().hex[:8]}",
            resource_type=resource_type,
        )
        self._active_leases[resource_type] += 1
        self.total_acquired_count += 1

        try:
            yield ticket
        finally:
            # 4. 离开上下文强制归还配额，杜绝泄漏
            self._active_leases[resource_type] -= 1
            sem.release()
