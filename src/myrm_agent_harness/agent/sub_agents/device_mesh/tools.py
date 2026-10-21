"""
[INPUT]
- typing::TYPE_CHECKING
- langchain.tools::tool
- pydantic::BaseModel, Field
- .scheduler::EdgeDeviceMeshScheduler
- .types::DispatchCommandRequest

[OUTPUT]
- get_default_mesh_scheduler: 获取默认设备网格调度器单例
- create_list_mesh_devices_tool: LangChain 工具，列出所有边缘网格设备
- create_dispatch_node_command_tool: LangChain 工具，向指定节点分发命令
- create_fetch_node_telemetry_tool: LangChain 工具，查询节点实时遥测

[POS]
Harness 框架层设备网格工具集（device_mesh tools）。
支持 Agent 自主发现边缘硬件、远程任务派发与分布式健康监测。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from .scheduler import EdgeDeviceMeshScheduler
from .types import DispatchCommandRequest

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

_GLOBAL_MESH_SCHEDULER: EdgeDeviceMeshScheduler | None = None


def get_default_mesh_scheduler() -> EdgeDeviceMeshScheduler:
    """Return the global default instance of EdgeDeviceMeshScheduler."""
    global _GLOBAL_MESH_SCHEDULER
    if _GLOBAL_MESH_SCHEDULER is None:
        _GLOBAL_MESH_SCHEDULER = EdgeDeviceMeshScheduler()
    return _GLOBAL_MESH_SCHEDULER


class ListMeshDevicesInput(BaseModel):
    """Input payload for list_mesh_devices."""

    kind: str | None = Field(
        default=None,
        description="Optional filter by node kind (linux_server, mac_mini, raspberry_pi, mobile_device, edge_accelerator)",
    )
    status: str | None = Field(
        default=None,
        description="Optional filter by node status (online, offline, busy, unpaired)",
    )


class DispatchNodeCommandInput(BaseModel):
    """Input payload for dispatch_node_command."""

    node_id: str = Field(
        ...,
        description="Target edge device node_id to execute the command on",
    )
    command: str = Field(
        ...,
        description="The shell command or diagnostic script to dispatch",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Execution timeout in seconds",
    )


class FetchNodeTelemetryInput(BaseModel):
    """Input payload for fetch_node_telemetry."""

    node_id: str = Field(
        ...,
        description="The edge device node_id to query telemetry for",
    )


def create_list_mesh_devices_tool(
    scheduler: EdgeDeviceMeshScheduler | None = None,
) -> BaseTool:
    """Create list_mesh_devices LangChain tool."""
    active_scheduler = scheduler or get_default_mesh_scheduler()

    @tool(args_schema=ListMeshDevicesInput)
    def list_mesh_devices(kind: str | None = None, status: str | None = None) -> str:
        """List registered edge devices in the network mesh topology with live status and telemetry."""
        # Validate filter types if provided
        k_val = kind if kind in ("linux_server", "mac_mini", "raspberry_pi", "mobile_device", "edge_accelerator", "custom") else None
        s_val = status if status in ("online", "offline", "busy", "unpaired") else None

        nodes = active_scheduler.list_nodes(kind=k_val, status=s_val)  # type: ignore[arg-type]
        if not nodes:
            return "No edge device nodes found matching the criteria."

        data = [
            {
                "node_id": n.node_id,
                "name": n.name,
                "kind": n.kind,
                "status": n.status,
                "ip_or_hostname": n.ip_or_hostname,
                "capabilities": n.capabilities,
                "cpu_usage_pct": n.telemetry.cpu_usage_pct,
                "memory_usage_pct": n.telemetry.memory_usage_pct,
                "active_tasks": n.telemetry.active_tasks,
            }
            for n in nodes
        ]
        return json.dumps(data, indent=2, ensure_ascii=False)

    return list_mesh_devices


def create_dispatch_node_command_tool(
    scheduler: EdgeDeviceMeshScheduler | None = None,
) -> BaseTool:
    """Create dispatch_node_command LangChain tool."""
    active_scheduler = scheduler or get_default_mesh_scheduler()

    @tool(args_schema=DispatchNodeCommandInput)
    def dispatch_node_command(
        node_id: str,
        command: str,
        timeout_seconds: float = 30.0,
    ) -> str:
        """Dispatch a shell command or workload task to a registered edge node and return outputs."""
        req = DispatchCommandRequest(
            node_id=node_id,
            command=command,
            timeout_seconds=timeout_seconds,
        )
        try:
            result = active_scheduler.dispatch_command(req)
        except KeyError as exc:
            return f"Dispatch failed: {exc}"

        return json.dumps(
            {
                "task_id": result.task_id,
                "node_id": result.node_id,
                "success": result.success,
                "exit_code": result.exit_code,
                "duration_seconds": result.duration_seconds,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
            ensure_ascii=False,
        )

    return dispatch_node_command


def create_fetch_node_telemetry_tool(
    scheduler: EdgeDeviceMeshScheduler | None = None,
) -> BaseTool:
    """Create fetch_node_telemetry LangChain tool."""
    active_scheduler = scheduler or get_default_mesh_scheduler()

    @tool(args_schema=FetchNodeTelemetryInput)
    def fetch_node_telemetry(node_id: str) -> str:
        """Fetch real-time CPU, memory, GPU, uptime, and active task telemetry of an edge device."""
        node = active_scheduler.get_node(node_id)
        if node is None:
            return f"Node '{node_id}' was not found in mesh."

        return json.dumps(
            {
                "node_id": node.node_id,
                "name": node.name,
                "status": node.status,
                "cpu_usage_pct": node.telemetry.cpu_usage_pct,
                "memory_usage_pct": node.telemetry.memory_usage_pct,
                "gpu_usage_pct": node.telemetry.gpu_usage_pct,
                "uptime_seconds": node.telemetry.uptime_seconds,
                "active_tasks": node.telemetry.active_tasks,
                "last_heartbeat": node.last_heartbeat,
            },
            indent=2,
            ensure_ascii=False,
        )

    return fetch_node_telemetry
