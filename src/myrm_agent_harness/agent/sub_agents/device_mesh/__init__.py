"""
[INPUT]
- .types::(DeviceNodeKind, DeviceNodeStatus, DeviceTelemetry, MeshDeviceNode, DispatchCommandRequest, DispatchCommandResult)
- .scheduler::EdgeDeviceMeshScheduler
- .tools::(get_default_mesh_scheduler, create_list_mesh_devices_tool, create_dispatch_node_command_tool, create_fetch_node_telemetry_tool)

[OUTPUT]
- EdgeDeviceMeshScheduler: 边缘设备网格调度器核心类
- DeviceNodeKind: 设备类型
- DeviceNodeStatus: 设备状态
- DeviceTelemetry: 设备指标遥测
- MeshDeviceNode: 设备网络节点
- DispatchCommandRequest: 命令派发请求
- DispatchCommandResult: 命令派发执行结果
- get_default_mesh_scheduler: 全局默认调度器单例
- create_list_mesh_devices_tool: 设备列表发现工具
- create_dispatch_node_command_tool: 远程命令执行工具
- create_fetch_node_telemetry_tool: 设备遥测查询工具

[POS]
边缘设备网格与多节点分布式调度器公共门面（device_mesh package facade）。
"""

from __future__ import annotations

from .scheduler import EdgeDeviceMeshScheduler
from .tools import (
    create_dispatch_node_command_tool,
    create_fetch_node_telemetry_tool,
    create_list_mesh_devices_tool,
    get_default_mesh_scheduler,
)
from .types import (
    DeviceNodeKind,
    DeviceNodeStatus,
    DeviceTelemetry,
    DispatchCommandRequest,
    DispatchCommandResult,
    MeshDeviceNode,
)

__all__ = [
    "DeviceNodeKind",
    "DeviceNodeStatus",
    "DeviceTelemetry",
    "DispatchCommandRequest",
    "DispatchCommandResult",
    "EdgeDeviceMeshScheduler",
    "MeshDeviceNode",
    "create_dispatch_node_command_tool",
    "create_fetch_node_telemetry_tool",
    "create_list_mesh_devices_tool",
    "get_default_mesh_scheduler",
]
