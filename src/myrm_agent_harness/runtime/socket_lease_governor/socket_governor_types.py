"""连接池枯竭防御与 Socket 租约中枢类型定义模块.

本模块定义连接租赁、FD 水位监测、配额配置与异常类型的核心数据模型。
严禁使用 Any 类型，确保完全强类型化。

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ResourceLeaseType
- LeaseStatus
- FDWatermarkStatus
- LeaseAcquisitionTimeoutError
- ResourceOverloadError
- SocketLeaseTicket
- FDMetricsSnapshot
- GovernorConfig

[POS]
连接池枯竭防御与 Socket 租约中枢类型定义模块.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ResourceLeaseType(StrEnum):
    """受控连接与系统资源租赁类型."""

    HTTP_SOCKET = "http_socket"  # 外网 HTTP/WebSocket 长连接
    DATABASE_CONNECTION = "database_connection"  # 关系型数据库连接池
    VECTOR_STORAGE = "vector_storage"  # 向量数据库与本地索引连接
    MCP_TRANSPORT = "mcp_transport"  # MCP 外部工具通信通道


class LeaseStatus(StrEnum):
    """租约状态枚举."""

    GRANTED = "granted"  # 租约已成功授予
    QUEUED = "queued"  # 处于排队等待中
    REJECTED_OVERLOAD = "rejected_overload"  # 触发反压熔断拒绝授予
    RELEASED = "released"  # 租约已归还释放
    TIMED_OUT = "timed_out"  # 排队超时未能获得租约


class FDWatermarkStatus(StrEnum):
    """操作系统文件描述符（FD）占用水位状态枚举."""

    NORMAL = "normal"  # 正常状态（占用率 < 75%）
    WARNING = "warning"  # 高水位预警状态（75% <= 占用率 < 85%）
    CRITICAL_BACKPRESSURE = "critical_backpressure"  # 紧急反压状态（占用率 >= 85%）


class LeaseAcquisitionTimeoutError(Exception):
    """当租约获取等待超时时抛出的强类型异常."""

    def __init__(self, resource_type: ResourceLeaseType, timeout: float) -> None:
        super().__init__(
            f"Failed to acquire lease for '{resource_type}' within {timeout}s timeout"
        )
        self.resource_type: ResourceLeaseType = resource_type
        self.timeout: float = timeout


class ResourceOverloadError(Exception):
    """当系统处于高水位反压熔断状态，拒绝非必要资源租用时抛出的强类型异常."""

    def __init__(self, message: str, current_fd_ratio: float) -> None:
        super().__init__(message)
        self.current_fd_ratio: float = current_fd_ratio


@dataclass(frozen=True)
class SocketLeaseTicket:
    """连接租约凭证对象."""

    ticket_id: str
    resource_type: ResourceLeaseType
    leased_at_ms: float = field(default_factory=lambda: time.time() * 1000)


@dataclass(frozen=True)
class FDMetricsSnapshot:
    """当前进程文件描述符（FD）水位快照."""

    allocated_fds: int
    soft_limit: int
    hard_limit: int
    usage_ratio: float
    status: FDWatermarkStatus
    recorded_at_ms: float = field(default_factory=lambda: time.time() * 1000)


@dataclass(frozen=True)
class GovernorConfig:
    """连接租约中枢配额与反压配置."""

    max_http_sockets: int = 128
    max_db_connections: int = 16
    max_vector_connections: int = 16
    max_mcp_transports: int = 32
    fd_warning_ratio: float = 0.75
    fd_critical_ratio: float = 0.85
    default_acquire_timeout: float = 5.0
