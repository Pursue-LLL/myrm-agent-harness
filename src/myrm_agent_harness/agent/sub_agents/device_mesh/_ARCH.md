# device_mesh/

## 架构概述

边缘设备网格与多节点分布式调度器领域子包（EdgeDeviceMeshNodeScheduler）。
提供跨局域网、Tailscale 与多端硬件设备的安全注册、Token 配对门禁、心跳遥测监测与多智能体跨节点命令派发。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 导出公共调度器、领域模型及元工具 | ✅ |
| `types.py` | 模型 | 定义 DeviceNodeKind、DeviceNodeStatus、DeviceTelemetry、MeshDeviceNode、DispatchCommandRequest 与 DispatchCommandResult | ✅ |
| `scheduler.py` | 核心 | EdgeDeviceMeshScheduler 线程安全调度引擎，管理节点生命周期、心跳保活、离线判定与任务分发 | ✅ |
| `tools.py` | 工具 | 提供 list_mesh_devices、dispatch_node_command、fetch_node_telemetry 三大 LangChain 跨节点工具 | ✅ |
