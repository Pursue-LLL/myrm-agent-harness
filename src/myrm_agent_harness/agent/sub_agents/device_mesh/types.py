"""
[INPUT]
- dataclasses (POS: 标准不可变/可变数据结构模型)
- typing (POS: 静态类型系统与字面量枚举)

[OUTPUT]
- DeviceNodeKind: 边缘设备类型枚举字面量
- DeviceNodeStatus: 边缘节点健康运行状态字面量
- DeviceTelemetry: 边缘设备 CPU/内存/GPU 与任务遥测快照
- MeshDeviceNode: 边缘设备网络节点核心描述模型
- DispatchCommandRequest: 分布式命令与任务派发请求
- DispatchCommandResult: 命令派发执行结果与输出证据

[POS]
边缘设备网格与多节点分布式调度器领域类型定义（EdgeDeviceMeshNodeScheduler）。
提供严谨具体的强类型约束，0 Any 类型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

DeviceNodeKind = Literal[
    "linux_server",
    "mac_mini",
    "raspberry_pi",
    "mobile_device",
    "edge_accelerator",
    "custom",
]

DeviceNodeStatus = Literal[
    "online",
    "offline",
    "busy",
    "unpaired",
]


@dataclass(frozen=True)
class DeviceTelemetry:
    """Live resource and task telemetry snapshot reported by an edge node."""

    cpu_usage_pct: float = 0.0
    memory_usage_pct: float = 0.0
    gpu_usage_pct: float | None = None
    uptime_seconds: float = 0.0
    active_tasks: int = 0


@dataclass
class MeshDeviceNode:
    """Registered edge device node within the multi-agent mesh topology."""

    node_id: str
    name: str
    kind: DeviceNodeKind
    ip_or_hostname: str
    status: DeviceNodeStatus = "unpaired"
    pairing_token: str = ""
    capabilities: list[str] = field(default_factory=list)
    telemetry: DeviceTelemetry = field(default_factory=DeviceTelemetry)
    last_heartbeat: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class DispatchCommandRequest:
    """Request payload to dispatch a workload command to a specific edge node."""

    node_id: str
    command: str
    timeout_seconds: float = 30.0
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DispatchCommandResult:
    """Execution receipt and outputs from a dispatched command on an edge node."""

    task_id: str
    node_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    success: bool
    dispatched_at: float = field(default_factory=time.time)
