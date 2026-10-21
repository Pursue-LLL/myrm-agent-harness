"""
[INPUT]
- threading (POS: 线程安全锁与多并发会话保护)
- time (POS: 时间戳与心跳超时判定)
- uuid (POS: 唯一任务 ID 生成)
- .types::DeviceNodeKind, DeviceNodeStatus, DeviceTelemetry, MeshDeviceNode, DispatchCommandRequest, DispatchCommandResult

[OUTPUT]
- EdgeDeviceMeshScheduler: 边缘设备网格与多节点分布式调度器核心引擎

[POS]
调度引擎核心实现。统一治理局域网、Tailscale 与多端边缘设备注册、
安全 Token 配对门禁、心跳遥测健康检测、离线状态判定与多智能体跨节点命令派发。
"""

from __future__ import annotations

import threading
import time
import uuid

from .types import (
    DeviceNodeKind,
    DeviceNodeStatus,
    DeviceTelemetry,
    DispatchCommandRequest,
    DispatchCommandResult,
    MeshDeviceNode,
)


class EdgeDeviceMeshScheduler:
    """Thread-safe orchestrator and scheduler for edge device mesh networks."""

    def __init__(self, stale_timeout_seconds: float = 60.0) -> None:
        self._stale_timeout = stale_timeout_seconds
        self._lock = threading.Lock()
        self._nodes: dict[str, MeshDeviceNode] = {}
        self._history: list[DispatchCommandResult] = []

    def register_node(
        self,
        node_id: str,
        name: str,
        kind: DeviceNodeKind,
        ip_or_hostname: str,
        capabilities: list[str] | None = None,
        pairing_token: str = "",
        auto_pair: bool = True,
    ) -> MeshDeviceNode:
        """Register a new edge device node into the mesh network."""
        with self._lock:
            now = time.time()
            initial_status: DeviceNodeStatus = (
                "online" if (pairing_token and auto_pair) else "unpaired"
            )
            node = MeshDeviceNode(
                node_id=node_id,
                name=name,
                kind=kind,
                ip_or_hostname=ip_or_hostname,
                status=initial_status,
                pairing_token=pairing_token,
                capabilities=capabilities or [],
                telemetry=DeviceTelemetry(uptime_seconds=0.0),
                last_heartbeat=now,
                created_at=now,
            )
            self._nodes[node_id] = node
            return node

    def pair_node(self, node_id: str, token: str) -> bool:
        """Pair an unpaired node with a verification token."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None or not token:
                return False
            if node.pairing_token and node.pairing_token != token:
                return False
            node.pairing_token = token
            node.status = "online"
            node.last_heartbeat = time.time()
            return True

    def heartbeat(
        self,
        node_id: str,
        telemetry: DeviceTelemetry | None = None,
    ) -> MeshDeviceNode:
        """Record a heartbeat pulse and updated telemetry snapshot from an edge node."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                raise KeyError(f"Mesh device node '{node_id}' not found.")
            node.last_heartbeat = time.time()
            if telemetry is not None:
                node.telemetry = telemetry
            if node.status in ("offline", "unpaired") and node.pairing_token:
                node.status = "online"
            return node

    def get_node(self, node_id: str) -> MeshDeviceNode | None:
        """Retrieve node state by node_id, refreshing stale offline status."""
        with self._lock:
            self._check_stale_locked()
            return self._nodes.get(node_id)

    def list_nodes(
        self,
        kind: DeviceNodeKind | None = None,
        status: DeviceNodeStatus | None = None,
    ) -> list[MeshDeviceNode]:
        """List all mesh nodes, optionally filtered by kind and status."""
        with self._lock:
            self._check_stale_locked()
            result: list[MeshDeviceNode] = []
            for node in self._nodes.values():
                if kind is not None and node.kind != kind:
                    continue
                if status is not None and node.status != status:
                    continue
                result.append(node)
            return sorted(result, key=lambda n: n.name)

    def remove_node(self, node_id: str) -> bool:
        """Remove a node from the mesh registry."""
        with self._lock:
            return self._nodes.pop(node_id, None) is not None

    def dispatch_command(
        self,
        req: DispatchCommandRequest,
    ) -> DispatchCommandResult:
        """Dispatch a workload or diagnostic command to a target edge node."""
        start_time = time.time()
        task_id = f"mesh_task_{uuid.uuid4().hex[:10]}"

        with self._lock:
            self._check_stale_locked()
            node = self._nodes.get(req.node_id)
            if node is None:
                raise KeyError(f"Mesh device node '{req.node_id}' not found.")

            if node.status == "offline":
                res = DispatchCommandResult(
                    task_id=task_id,
                    node_id=req.node_id,
                    exit_code=1,
                    stdout="",
                    stderr=f"Node '{req.node_id}' is offline and unreachable.",
                    duration_seconds=round(time.time() - start_time, 4),
                    success=False,
                    dispatched_at=start_time,
                )
                self._history.append(res)
                return res

            if node.status == "unpaired":
                res = DispatchCommandResult(
                    task_id=task_id,
                    node_id=req.node_id,
                    exit_code=1,
                    stdout="",
                    stderr=f"Node '{req.node_id}' is unpaired. Pairing token required before dispatch.",
                    duration_seconds=round(time.time() - start_time, 4),
                    success=False,
                    dispatched_at=start_time,
                )
                self._history.append(res)
                return res

            # Mark busy during simulated dispatch
            previous_status = node.status
            node.status = "busy"
            active_tasks = node.telemetry.active_tasks + 1
            node.telemetry = DeviceTelemetry(
                cpu_usage_pct=min(100.0, node.telemetry.cpu_usage_pct + 10.0),
                memory_usage_pct=node.telemetry.memory_usage_pct,
                gpu_usage_pct=node.telemetry.gpu_usage_pct,
                uptime_seconds=node.telemetry.uptime_seconds,
                active_tasks=active_tasks,
            )

        # Execute/Simulate command execution output
        duration = round(time.time() - start_time, 4)
        stdout_msg = f"[EdgeNode: {req.node_id}] Executed '{req.command}' successfully."
        res = DispatchCommandResult(
            task_id=task_id,
            node_id=req.node_id,
            exit_code=0,
            stdout=stdout_msg,
            stderr="",
            duration_seconds=duration,
            success=True,
            dispatched_at=start_time,
        )

        with self._lock:
            # Restore status and decrements active tasks
            if node_id := self._nodes.get(req.node_id):
                node_id.status = previous_status if previous_status != "busy" else "online"
                node_id.telemetry = DeviceTelemetry(
                    cpu_usage_pct=max(0.0, node_id.telemetry.cpu_usage_pct - 10.0),
                    memory_usage_pct=node_id.telemetry.memory_usage_pct,
                    gpu_usage_pct=node_id.telemetry.gpu_usage_pct,
                    uptime_seconds=node_id.telemetry.uptime_seconds,
                    active_tasks=max(0, node_id.telemetry.active_tasks - 1),
                )
            self._history.append(res)

        return res

    def get_history(self, node_id: str | None = None) -> list[DispatchCommandResult]:
        """Fetch command execution receipts, optionally filtered by node_id."""
        with self._lock:
            if node_id is None:
                return list(self._history)
            return [h for h in self._history if h.node_id == node_id]

    def _check_stale_locked(self) -> None:
        """Mark nodes with elapsed heartbeat beyond threshold as offline (internal lock)."""
        now = time.time()
        for node in self._nodes.values():
            if node.status in ("online", "busy") and (now - node.last_heartbeat > self._stale_timeout):
                node.status = "offline"
