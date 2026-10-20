"""
[INPUT]
- pytest
- myrm_agent_harness.agent.sub_agents.device_mesh::(
    EdgeDeviceMeshScheduler,
    DeviceTelemetry,
    DispatchCommandRequest,
    create_list_mesh_devices_tool,
    create_dispatch_node_command_tool,
    create_fetch_node_telemetry_tool,
  )

[OUTPUT]
- test_register_and_pair_node: 测试边缘节点注册与 Token 配对门禁
- test_heartbeat_and_stale_detection: 测试心跳上报与离线超时自动判定
- test_dispatch_command_online_and_guards: 测试分布式命令派发与状态流转防线
- test_device_mesh_langchain_tools: 测试三大 LangChain 工具端到端调用

[POS]
Harness 框架层边缘设备网格与多节点分布式调度器单元测试套件。
"""

from __future__ import annotations

import json
import time

import pytest

from myrm_agent_harness.agent.sub_agents.device_mesh import (
    DeviceTelemetry,
    DispatchCommandRequest,
    EdgeDeviceMeshScheduler,
    create_dispatch_node_command_tool,
    create_fetch_node_telemetry_tool,
    create_list_mesh_devices_tool,
)


def test_register_and_pair_node() -> None:
    """Verify device registration, token verification, and pairing state transitions."""
    scheduler = EdgeDeviceMeshScheduler(stale_timeout_seconds=10.0)

    # 1. Register with pairing token -> directly online
    node1 = scheduler.register_node(
        node_id="rpi-edge-01",
        name="Raspberry Pi 5 Garage",
        kind="raspberry_pi",
        ip_or_hostname="192.168.1.120",
        capabilities=["bash", "gpio", "sensor"],
        pairing_token="token-secret-123",
    )
    assert node1.node_id == "rpi-edge-01"
    assert node1.status == "online"
    assert "gpio" in node1.capabilities

    # 2. Register with expected token but auto_pair=False -> unpaired
    node2 = scheduler.register_node(
        node_id="mac-mini-01",
        name="M4 Mac Mini Studio",
        kind="mac_mini",
        ip_or_hostname="192.168.1.150",
        capabilities=["bash", "metal_inference"],
        pairing_token="m4-secret-token",
        auto_pair=False,
    )
    assert node2.status == "unpaired"

    # Pair with invalid token -> fails
    assert not scheduler.pair_node("mac-mini-01", "wrong-token")
    # Pair with matching token -> succeeds and becomes online
    assert scheduler.pair_node("mac-mini-01", "m4-secret-token")
    updated_node2 = scheduler.get_node("mac-mini-01")
    assert updated_node2 is not None
    assert updated_node2.status == "online"


def test_heartbeat_and_stale_detection() -> None:
    """Verify heartbeat telemetry updating and stale offline detection."""
    scheduler = EdgeDeviceMeshScheduler(stale_timeout_seconds=0.2)

    scheduler.register_node(
        node_id="gpu-node-01",
        name="RTX 4090 Linux Server",
        kind="linux_server",
        ip_or_hostname="10.0.0.50",
        pairing_token="gpu-token",
    )

    # Update heartbeat with telemetry
    telemetry = DeviceTelemetry(
        cpu_usage_pct=45.5,
        memory_usage_pct=62.0,
        gpu_usage_pct=88.0,
        uptime_seconds=36000.0,
        active_tasks=2,
    )
    updated = scheduler.heartbeat("gpu-node-01", telemetry=telemetry)
    assert updated.telemetry.cpu_usage_pct == 45.5
    assert updated.telemetry.gpu_usage_pct == 88.0
    assert updated.status == "online"

    # Heartbeat on missing node raises KeyError
    with pytest.raises(KeyError):
        scheduler.heartbeat("non-existent-node")

    # Sleep beyond stale timeout -> status turns offline
    time.sleep(0.25)
    stale_node = scheduler.get_node("gpu-node-01")
    assert stale_node is not None
    assert stale_node.status == "offline"

    # Heartbeat revives offline node back to online
    revived = scheduler.heartbeat("gpu-node-01")
    assert revived.status == "online"


def test_dispatch_command_online_and_guards() -> None:
    """Verify command dispatch routing, offline rejection, and unpaired blocking."""
    scheduler = EdgeDeviceMeshScheduler(stale_timeout_seconds=5.0)

    # Register online node
    scheduler.register_node(
        node_id="online-box",
        name="Online Worker",
        kind="linux_server",
        ip_or_hostname="192.168.1.10",
        pairing_token="valid-token",
    )

    # 1. Dispatch to online node -> success
    req = DispatchCommandRequest(
        node_id="online-box",
        command="docker ps -a",
        timeout_seconds=15.0,
    )
    res = scheduler.dispatch_command(req)
    assert res.success is True
    assert res.exit_code == 0
    assert "docker ps -a" in res.stdout
    assert res.task_id.startswith("mesh_task_")

    # 2. Dispatch to non-existent node -> raises KeyError
    with pytest.raises(KeyError):
        scheduler.dispatch_command(
            DispatchCommandRequest(node_id="missing-box", command="uname -a")
        )

    # 3. Register unpaired node -> dispatch rejected
    scheduler.register_node(
        node_id="unpaired-box",
        name="Unpaired Worker",
        kind="raspberry_pi",
        ip_or_hostname="192.168.1.20",
        pairing_token="",
    )
    unpaired_res = scheduler.dispatch_command(
        DispatchCommandRequest(node_id="unpaired-box", command="uname -a")
    )
    assert unpaired_res.success is False
    assert "unpaired" in unpaired_res.stderr

    # 4. Check history recording
    history = scheduler.get_history()
    assert len(history) == 2


def test_device_mesh_langchain_tools() -> None:
    """Verify LangChain meta tools interact cleanly with the scheduler."""
    scheduler = EdgeDeviceMeshScheduler()

    scheduler.register_node(
        node_id="cam-pi-01",
        name="Camera Pi",
        kind="raspberry_pi",
        ip_or_hostname="192.168.1.88",
        capabilities=["camera", "rtsp"],
        pairing_token="cam-token",
    )
    scheduler.heartbeat(
        "cam-pi-01",
        telemetry=DeviceTelemetry(cpu_usage_pct=15.0, memory_usage_pct=30.0),
    )

    # 1. list_mesh_devices
    list_tool = create_list_mesh_devices_tool(scheduler)
    list_output = list_tool.invoke({})
    nodes_data = json.loads(list_output)
    assert len(nodes_data) == 1
    assert nodes_data[0]["node_id"] == "cam-pi-01"
    assert nodes_data[0]["cpu_usage_pct"] == 15.0

    # 2. dispatch_node_command
    dispatch_tool = create_dispatch_node_command_tool(scheduler)
    dispatch_output = dispatch_tool.invoke(
        {"node_id": "cam-pi-01", "command": "v4l2-ctl --list-devices"}
    )
    res_data = json.loads(dispatch_output)
    assert res_data["success"] is True
    assert "v4l2-ctl" in res_data["stdout"]

    # 3. fetch_node_telemetry
    telemetry_tool = create_fetch_node_telemetry_tool(scheduler)
    telemetry_output = telemetry_tool.invoke({"node_id": "cam-pi-01"})
    telem_data = json.loads(telemetry_output)
    assert telem_data["node_id"] == "cam-pi-01"
    assert telem_data["cpu_usage_pct"] == 15.0
