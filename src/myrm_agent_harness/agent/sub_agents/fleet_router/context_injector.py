
from myrm_agent_harness.agent.sub_agents.fleet_router.connection_pool import (
    MultiGatewayConnectionPool,
)


class HostGatewayContextInjector:
    """Injects distributed gateway topology and host awareness into Agent system context."""

    def __init__(self, connection_pool: MultiGatewayConnectionPool) -> None:
        self.connection_pool = connection_pool

    def inject_host_context(self, profile_id: str, base_system_context: str) -> str:
        profile = self.connection_pool.get_profile(profile_id)
        if not profile:
            return base_system_context

        gateway = self.connection_pool.get_gateway(profile.gateway_id)
        if not gateway:
            return base_system_context

        topology_block = (
            "\n\n[DISTRIBUTED FLEET HOST TOPOLOGY]\n"
            f"- Gateway ID: {gateway.gateway_id} ({gateway.label})\n"
            f"- Platform: {gateway.platform.value} ({gateway.host}:{gateway.port} via {gateway.protocol})\n"
            f"- Gateway Status: {gateway.status.value} (Round-trip Latency: {gateway.latency_ms:.1f}ms)\n"
            f"- Hardware Compute Envelope: CPU {gateway.telemetry.cpu_pct:.1f}%, "
            f"Memory {gateway.telemetry.mem_pct:.1f}%, Active Agents: {gateway.telemetry.active_agents}, "
            f"Queue Depth: {gateway.telemetry.queue_depth}\n"
            f"- Assigned Profile: {profile.name} (Role: {profile.role})\n"
            "You have direct awareness of this compute host. Answer accurately about your deployment environment.\n"
            "[END DISTRIBUTED FLEET HOST TOPOLOGY]"
        )

        stripped_base = base_system_context.strip()
        if not stripped_base:
            return topology_block.strip()
        return f"{stripped_base}{topology_block}"

    def format_host_badge(self, profile_id: str) -> dict[str, str] | None:
        profile = self.connection_pool.get_profile(profile_id)
        if not profile:
            return None
        gateway = self.connection_pool.get_gateway(profile.gateway_id)
        if not gateway:
            return None

        return {
            "gateway_id": gateway.gateway_id,
            "label": gateway.label,
            "platform": gateway.platform.value,
            "status": gateway.status.value,
            "latency_ms": f"{gateway.latency_ms:.1f}ms",
            "profile_name": profile.name,
            "profile_role": profile.role,
        }
