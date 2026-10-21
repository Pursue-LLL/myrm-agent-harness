import pytest

from myrm_agent_harness.agent.sub_agents.fleet_router import (
    CrossGatewayArtifactRelayService,
    DuplicateGatewayError,
    FleetProfile,
    GatewayNode,
    GatewayNotFoundError,
    GatewayOfflineError,
    GatewayPlatform,
    GatewayStatus,
    GatewayTelemetry,
    HostGatewayContextInjector,
    MultiGatewayConnectionPool,
)


@pytest.fixture
def mock_gateways() -> tuple[GatewayNode, GatewayNode]:
    gw_local = GatewayNode(
        gateway_id="gw-mac-local",
        label="MacBook Pro Local",
        host="127.0.0.1",
        port=8080,
        protocol="ws",
        platform=GatewayPlatform.DARWIN,
        status=GatewayStatus.ONLINE,
        latency_ms=1.2,
        telemetry=GatewayTelemetry(
            cpu_pct=15.5,
            mem_pct=42.0,
            active_agents=2,
            queue_depth=0,
        ),
        last_heartbeat=1710000000.0,
    )
    gw_cloud = GatewayNode(
        gateway_id="gw-cloud-gpu",
        label="Ubuntu GPU Cloud Sandbox",
        host="10.0.4.15",
        port=9090,
        protocol="wss",
        platform=GatewayPlatform.LINUX,
        status=GatewayStatus.ONLINE,
        latency_ms=38.5,
        telemetry=GatewayTelemetry(
            cpu_pct=72.0,
            mem_pct=85.2,
            active_agents=6,
            queue_depth=3,
        ),
        last_heartbeat=1710000000.0,
    )
    return gw_local, gw_cloud


def test_gateway_registration_and_duplicate_rejection(
    mock_gateways: tuple[GatewayNode, GatewayNode]
) -> None:
    pool = MultiGatewayConnectionPool(heartbeat_timeout_seconds=30.0)
    gw1, gw2 = mock_gateways

    pool.register_gateway(gw1)
    pool.register_gateway(gw2)

    assert len(pool.list_gateways()) == 2
    assert pool.get_gateway("gw-mac-local") is not None
    assert pool.get_gateway("gw-cloud-gpu") is not None

    with pytest.raises(DuplicateGatewayError):
        pool.register_gateway(gw1)

    with pytest.raises(GatewayNotFoundError):
        pool.unregister_gateway("gw-non-existent")


def test_heartbeat_update_and_degraded_threshold(
    mock_gateways: tuple[GatewayNode, GatewayNode]
) -> None:
    pool = MultiGatewayConnectionPool(heartbeat_timeout_seconds=30.0)
    gw1, _ = mock_gateways
    pool.register_gateway(gw1)

    # Normal low latency update
    updated = pool.update_heartbeat(
        gateway_id="gw-mac-local",
        telemetry=GatewayTelemetry(cpu_pct=25.0, mem_pct=45.0, active_agents=3, queue_depth=1),
        latency_ms=12.0,
        now=1710000010.0,
    )
    assert updated.status == GatewayStatus.ONLINE
    assert updated.latency_ms == 12.0
    assert updated.last_heartbeat == 1710000010.0

    # High latency update auto marks as DEGRADED
    degraded = pool.update_heartbeat(
        gateway_id="gw-mac-local",
        telemetry=GatewayTelemetry(cpu_pct=95.0, mem_pct=90.0, active_agents=8, queue_depth=10),
        latency_ms=620.0,
        now=1710000020.0,
    )
    assert degraded.status == GatewayStatus.DEGRADED


def test_stale_gateway_sweep_to_offline(
    mock_gateways: tuple[GatewayNode, GatewayNode]
) -> None:
    pool = MultiGatewayConnectionPool(heartbeat_timeout_seconds=20.0)
    gw1, gw2 = mock_gateways
    pool.register_gateway(gw1)
    pool.register_gateway(gw2)

    # Advance time by 25s (beyond 20s timeout)
    offline_gids = pool.sweep_stale_gateways(now=1710000025.0)
    assert "gw-mac-local" in offline_gids
    assert "gw-cloud-gpu" in offline_gids

    node = pool.get_gateway("gw-mac-local")
    assert node is not None
    assert node.status == GatewayStatus.OFFLINE


def test_offline_command_buffering_and_fail_closed(
    mock_gateways: tuple[GatewayNode, GatewayNode]
) -> None:
    pool = MultiGatewayConnectionPool(heartbeat_timeout_seconds=30.0)
    gw1, _ = mock_gateways
    pool.register_gateway(gw1)

    # Force gateway to OFFLINE
    pool.update_heartbeat(
        gateway_id="gw-mac-local",
        telemetry=gw1.telemetry,
        latency_ms=0.0,
        status=GatewayStatus.OFFLINE,
        now=1710000005.0,
    )

    cmd = pool.buffer_offline_command(
        gateway_id="gw-mac-local",
        profile_id="prof-coder-1",
        command_type="execute_task",
        payload={"task": "Run e2e test suite"},
        now=1710000010.0,
    )
    assert cmd.command_id.startswith("cmd-buf-")
    assert len(pool.get_buffered_commands("gw-mac-local")) == 1

    # Attempting to flush while still offline raises GatewayOfflineError
    with pytest.raises(GatewayOfflineError):
        pool.flush_buffered_commands("gw-mac-local")


def test_auto_healing_flush_upon_gateway_reconnection(
    mock_gateways: tuple[GatewayNode, GatewayNode]
) -> None:
    pool = MultiGatewayConnectionPool(heartbeat_timeout_seconds=30.0)
    gw1, _ = mock_gateways
    pool.register_gateway(gw1)

    # Buffer 2 commands while offline
    pool.update_heartbeat(
        gateway_id="gw-mac-local",
        telemetry=gw1.telemetry,
        latency_ms=0.0,
        status=GatewayStatus.OFFLINE,
        now=1710000005.0,
    )
    pool.buffer_offline_command(
        gateway_id="gw-mac-local",
        profile_id="prof-coder-1",
        command_type="job_a",
        payload={"step": "1"},
        now=1710000010.0,
    )
    pool.buffer_offline_command(
        gateway_id="gw-mac-local",
        profile_id="prof-coder-1",
        command_type="job_b",
        payload={"step": "2"},
        now=1710000012.0,
    )

    snapshot = pool.get_topology_snapshot()
    assert snapshot.total_buffered_commands == 2

    # Reconnection: Heartbeat brings gateway back to ONLINE
    pool.update_heartbeat(
        gateway_id="gw-mac-local",
        telemetry=GatewayTelemetry(cpu_pct=10.0, mem_pct=30.0, active_agents=1, queue_depth=0),
        latency_ms=1.5,
        status=GatewayStatus.ONLINE,
        now=1710000015.0,
    )

    # Auto-healing flush succeeds and drains queue in FIFO order
    flushed = pool.flush_buffered_commands("gw-mac-local")
    assert len(flushed) == 2
    assert flushed[0].command_type == "job_a"
    assert flushed[1].command_type == "job_b"
    assert len(pool.get_buffered_commands("gw-mac-local")) == 0


def test_host_context_injection_and_artifact_relay(
    mock_gateways: tuple[GatewayNode, GatewayNode]
) -> None:
    pool = MultiGatewayConnectionPool(heartbeat_timeout_seconds=30.0)
    gw1, gw2 = mock_gateways
    pool.register_gateway(gw1)
    pool.register_gateway(gw2)

    profile = FleetProfile(
        profile_id="prof-researcher-1",
        gateway_id="gw-cloud-gpu",
        name="DeepSearch Agent",
        avatar="🔍",
        role="Distributed Researcher",
        system_context="You are a research specialist.",
        is_active=True,
    )
    pool.register_profile(profile)

    # 1. Context Injection
    injector = HostGatewayContextInjector(connection_pool=pool)
    injected_prompt = injector.inject_host_context(
        profile_id="prof-researcher-1",
        base_system_context="You are a research specialist.",
    )
    assert "[DISTRIBUTED FLEET HOST TOPOLOGY]" in injected_prompt
    assert "Gateway ID: gw-cloud-gpu (Ubuntu GPU Cloud Sandbox)" in injected_prompt
    assert "Platform: linux" in injected_prompt
    assert "Assigned Profile: DeepSearch Agent" in injected_prompt

    badge = injector.format_host_badge("prof-researcher-1")
    assert badge is not None
    assert badge["gateway_id"] == "gw-cloud-gpu"
    assert badge["platform"] == "linux"

    # 2. Artifact Relay and SHA-256 verification
    relay = CrossGatewayArtifactRelayService(connection_pool=pool)
    envelope = relay.relay_artifact(
        source_gateway="gw-cloud-gpu",
        target_gateway="gw-mac-local",
        name="gpu_eval_results.json",
        file_path="artifacts/eval.json",
        chunk_data='{"accuracy": 0.985, "samples": 5000}',
        now=1710000020.0,
    )
    assert envelope.artifact_id.startswith("art-relay-")
    assert len(envelope.sha256) == 64
    assert relay.verify_artifact_integrity(envelope) is True

    # Tampered data should fail verification
    envelope.chunk_data = '{"accuracy": 0.000}'
    assert relay.verify_artifact_integrity(envelope) is False
