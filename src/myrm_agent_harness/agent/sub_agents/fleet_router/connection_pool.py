"""myrm_agent_harness/agent/sub_agents/fleet_router/connection_pool.py

[INPUT]
- time
- uuid

[OUTPUT]
- FleetRouterError
- GatewayNotFoundError
- GatewayOfflineError
- DuplicateGatewayError
- MultiGatewayConnectionPool

[POS]
myrm_agent_harness/agent/sub_agents/fleet_router/connection_pool.py
"""

import time
import uuid

from myrm_agent_harness.agent.sub_agents.fleet_router.types import (
    FleetProfile,
    FleetTopologySnapshot,
    GatewayNode,
    GatewayStatus,
    GatewayTelemetry,
    OfflineBufferedCommand,
)


class FleetRouterError(Exception):
    """Base exception for fleet router failures."""
    pass


class GatewayNotFoundError(FleetRouterError):
    """Raised when the requested gateway cannot be found."""
    pass


class GatewayOfflineError(FleetRouterError):
    """Raised when attempting an operation on an offline gateway without buffering."""
    pass


class DuplicateGatewayError(FleetRouterError):
    """Raised when registering a gateway ID that already exists."""
    pass


class MultiGatewayConnectionPool:
    """Connection pool and state manager for multi-machine distributed fleet gateways."""

    def __init__(self, heartbeat_timeout_seconds: float = 30.0) -> None:
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._gateways: dict[str, GatewayNode] = {}
        self._profiles: dict[str, FleetProfile] = {}
        self._offline_queues: dict[str, list[OfflineBufferedCommand]] = {}

    def register_gateway(self, node: GatewayNode) -> GatewayNode:
        if node.gateway_id in self._gateways:
            raise DuplicateGatewayError(f"Gateway '{node.gateway_id}' is already registered.")
        self._gateways[node.gateway_id] = node
        if node.gateway_id not in self._offline_queues:
            self._offline_queues[node.gateway_id] = []
        return node

    def unregister_gateway(self, gateway_id: str) -> None:
        if gateway_id not in self._gateways:
            raise GatewayNotFoundError(f"Gateway '{gateway_id}' not found.")
        del self._gateways[gateway_id]
        self._offline_queues.pop(gateway_id, None)
        # Deactivate associated profiles
        for p in self._profiles.values():
            if p.gateway_id == gateway_id:
                p.is_active = False

    def get_gateway(self, gateway_id: str) -> GatewayNode | None:
        return self._gateways.get(gateway_id)

    def list_gateways(self) -> list[GatewayNode]:
        return list(self._gateways.values())

    def register_profile(self, profile: FleetProfile) -> FleetProfile:
        if profile.gateway_id not in self._gateways:
            raise GatewayNotFoundError(
                f"Cannot register profile '{profile.profile_id}': gateway '{profile.gateway_id}' does not exist."
            )
        self._profiles[profile.profile_id] = profile
        return profile

    def get_profile(self, profile_id: str) -> FleetProfile | None:
        return self._profiles.get(profile_id)

    def list_profiles(self) -> list[FleetProfile]:
        return list(self._profiles.values())

    def update_heartbeat(
        self,
        gateway_id: str,
        telemetry: GatewayTelemetry,
        latency_ms: float,
        status: GatewayStatus | None = None,
        now: float | None = None,
    ) -> GatewayNode:
        gateway = self.get_gateway(gateway_id)
        if not gateway:
            raise GatewayNotFoundError(f"Gateway '{gateway_id}' not found.")

        current_time = now if now is not None else time.time()
        new_status = status if status is not None else GatewayStatus.ONLINE
        if latency_ms > 500.0 and new_status == GatewayStatus.ONLINE:
            new_status = GatewayStatus.DEGRADED

        updated_node = GatewayNode(
            gateway_id=gateway.gateway_id,
            label=gateway.label,
            host=gateway.host,
            port=gateway.port,
            protocol=gateway.protocol,
            platform=gateway.platform,
            status=new_status,
            latency_ms=latency_ms,
            telemetry=telemetry,
            last_heartbeat=current_time,
        )
        self._gateways[gateway_id] = updated_node
        return updated_node

    def sweep_stale_gateways(self, now: float | None = None) -> list[str]:
        current_time = now if now is not None else time.time()
        degraded_or_offline: list[str] = []

        for gid, g in list(self._gateways.items()):
            delta = current_time - g.last_heartbeat
            if delta > self.heartbeat_timeout_seconds and g.status != GatewayStatus.OFFLINE:
                updated = GatewayNode(
                    gateway_id=g.gateway_id,
                    label=g.label,
                    host=g.host,
                    port=g.port,
                    protocol=g.protocol,
                    platform=g.platform,
                    status=GatewayStatus.OFFLINE,
                    latency_ms=g.latency_ms,
                    telemetry=g.telemetry,
                    last_heartbeat=g.last_heartbeat,
                )
                self._gateways[gid] = updated
                degraded_or_offline.append(gid)
        return degraded_or_offline

    def buffer_offline_command(
        self,
        gateway_id: str,
        profile_id: str,
        command_type: str,
        payload: dict[str, str],
        now: float | None = None,
    ) -> OfflineBufferedCommand:
        if gateway_id not in self._gateways:
            raise GatewayNotFoundError(f"Gateway '{gateway_id}' not found.")

        current_time = now if now is not None else time.time()
        cmd = OfflineBufferedCommand(
            command_id=f"cmd-buf-{uuid.uuid4().hex[:8]}",
            gateway_id=gateway_id,
            profile_id=profile_id,
            command_type=command_type,
            payload=payload,
            queued_at=current_time,
            retry_count=0,
        )
        if gateway_id not in self._offline_queues:
            self._offline_queues[gateway_id] = []
        self._offline_queues[gateway_id].append(cmd)
        return cmd

    def get_buffered_commands(self, gateway_id: str) -> list[OfflineBufferedCommand]:
        return list(self._offline_queues.get(gateway_id, []))

    def flush_buffered_commands(self, gateway_id: str) -> list[OfflineBufferedCommand]:
        gateway = self.get_gateway(gateway_id)
        if not gateway:
            raise GatewayNotFoundError(f"Gateway '{gateway_id}' not found.")
        if gateway.status == GatewayStatus.OFFLINE:
            raise GatewayOfflineError(
                f"Cannot flush buffered commands: gateway '{gateway_id}' is offline."
            )

        queue = self._offline_queues.get(gateway_id, [])
        flushed = list(queue)
        self._offline_queues[gateway_id] = []
        return flushed

    def get_topology_snapshot(self) -> FleetTopologySnapshot:
        total_buffered = sum(len(q) for q in self._offline_queues.values())
        return FleetTopologySnapshot(
            gateways=dict(self._gateways),
            profiles=dict(self._profiles),
            offline_queue={k: list(v) for k, v in self._offline_queues.items()},
            total_buffered_commands=total_buffered,
        )
