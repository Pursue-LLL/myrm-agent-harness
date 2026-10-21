"""myrm_agent_harness/agent/sub_agents/fleet_router/types.py

[INPUT]
- enum
- pydantic

[OUTPUT]
- GatewayStatus
- GatewayPlatform
- GatewayTelemetry
- GatewayNode
- FleetProfile
- OfflineBufferedCommand
- CrossGatewayArtifactEnvelope
- FleetTopologySnapshot

[POS]
myrm_agent_harness/agent/sub_agents/fleet_router/types.py
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class GatewayStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


class GatewayPlatform(StrEnum):
    DARWIN = "darwin"
    LINUX = "linux"
    VPS = "vps"
    CLOUD = "cloud"


class GatewayTelemetry(BaseModel):
    cpu_pct: float = Field(ge=0.0, le=100.0, description="CPU utilization percentage")
    mem_pct: float = Field(ge=0.0, le=100.0, description="Memory utilization percentage")
    active_agents: int = Field(ge=0, description="Count of currently active agents")
    queue_depth: int = Field(ge=0, description="Pending commands in execution queue")


class GatewayNode(BaseModel):
    gateway_id: str
    label: str
    host: str
    port: int = Field(ge=1, le=65535)
    protocol: str = Field(default="ws")
    platform: GatewayPlatform
    status: GatewayStatus = Field(default=GatewayStatus.ONLINE)
    latency_ms: float = Field(default=0.0, ge=0.0)
    telemetry: GatewayTelemetry
    last_heartbeat: float


class FleetProfile(BaseModel):
    profile_id: str
    gateway_id: str
    name: str
    avatar: str
    role: str
    system_context: str
    is_active: bool = True


class OfflineBufferedCommand(BaseModel):
    command_id: str
    gateway_id: str
    profile_id: str
    command_type: str
    payload: dict[str, str] = Field(default_factory=dict)
    queued_at: float
    retry_count: int = 0


class CrossGatewayArtifactEnvelope(BaseModel):
    artifact_id: str
    source_gateway: str
    target_gateway: str
    name: str
    file_path: str
    sha256: str
    chunk_data: str
    created_at: float


class FleetTopologySnapshot(BaseModel):
    gateways: dict[str, GatewayNode] = Field(default_factory=dict)
    profiles: dict[str, FleetProfile] = Field(default_factory=dict)
    offline_queue: dict[str, list[OfflineBufferedCommand]] = Field(default_factory=dict)
    total_buffered_commands: int = 0
