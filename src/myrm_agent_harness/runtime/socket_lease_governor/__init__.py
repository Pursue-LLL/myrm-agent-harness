"""全链路连接池枯竭防御、文件描述符硬配额保护与 Socket 租约中枢套件.

对外导出核心类型、软限制抬升器、FD 水位哨兵与租约治理中枢.

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- (模块级副作用与注册)

[POS]
全链路连接池枯竭防御、文件描述符硬配额保护与 Socket 租约中枢套件.
"""

from myrm_agent_harness.runtime.socket_lease_governor.fd_watermark_sentinel import (
    FDWatermarkSentinel,
)
from myrm_agent_harness.runtime.socket_lease_governor.nofile_limit_lifter import (
    get_nofile_limits,
    raise_nofile_soft_limit,
)
from myrm_agent_harness.runtime.socket_lease_governor.socket_governor_types import (
    FDMetricsSnapshot,
    FDWatermarkStatus,
    GovernorConfig,
    LeaseAcquisitionTimeoutError,
    LeaseStatus,
    ResourceLeaseType,
    ResourceOverloadError,
    SocketLeaseTicket,
)
from myrm_agent_harness.runtime.socket_lease_governor.socket_lease_governor import (
    SocketLeaseGovernor,
)

__all__ = [
    "FDMetricsSnapshot",
    "FDWatermarkSentinel",
    "FDWatermarkStatus",
    "GovernorConfig",
    "LeaseAcquisitionTimeoutError",
    "LeaseStatus",
    "ResourceLeaseType",
    "ResourceOverloadError",
    "SocketLeaseTicket",
    "SocketLeaseGovernor",
    "get_nofile_limits",
    "raise_nofile_soft_limit",
]
