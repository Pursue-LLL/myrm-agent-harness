"""Domain types and models for SwarmForge Dynamic Swarm Topology Orchestrator & MultiGent Mesh Network (Item 55).

Defines declarative topologies (star, hierarchical tree, peer-to-peer mesh, pipeline, ring),
node roles, statuses, mesh message routing protocols (unicast, multicast, broadcast),
shared blackboard entry models, and live state migration contracts.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- TopologyType
- SwarmNodeRole
- SwarmNodeStatus
- MessageRoutingMode
- MeshDeliveryStatus
- MeshEdge
- SwarmNode
- MeshMessage
- BlackboardEntry
- SwarmTopologyConfig

[POS]
Domain types and models for SwarmForge Dynamic Swarm Topology Orchestrator & MultiGent Mesh Network (Item 55).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class TopologyType(StrEnum):
    """Topology structure configurations for dynamic agent swarms."""

    STAR = "star"
    HIERARCHICAL_TREE = "hierarchical_tree"
    PEER_MESH = "peer_mesh"
    PIPELINE = "pipeline"
    RING = "ring"


class SwarmNodeRole(StrEnum):
    """Functional role of an agent node in the swarm mesh."""

    COORDINATOR = "coordinator"
    WORKER = "worker"
    REVIEWER = "reviewer"
    SPECIALIST = "specialist"
    GATEWAY = "gateway"


class SwarmNodeStatus(StrEnum):
    """Operational lifecycle status of a swarm node."""

    IDLE = "idle"
    ACTIVE = "active"
    BUSY = "busy"
    MIGRATING = "migrating"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class MessageRoutingMode(StrEnum):
    """Routing scope of a message across the mesh network."""

    UNICAST = "unicast"
    MULTICAST = "multicast"
    BROADCAST = "broadcast"


class MeshDeliveryStatus(StrEnum):
    """Transmission delivery status of a mesh message."""

    SENT = "sent"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"


@dataclass(frozen=True)
class MeshEdge:
    """Network connection edge between two nodes in the topology."""

    source: str
    target: str
    bidirectional: bool = True
    weight: float = 1.0


@dataclass
class SwarmNode:
    """An active agent instance participating in the swarm mesh."""

    node_id: str
    name: str
    role: SwarmNodeRole
    status: SwarmNodeStatus = SwarmNodeStatus.IDLE
    capabilities: list[str] = field(default_factory=list)
    connected_peers: list[str] = field(default_factory=list)
    workload_score: float = 0.0
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MeshMessage:
    """P2P or group message transmitted through the mesh event bus."""

    message_id: str
    sender_id: str
    recipient_id: str  # specific node_id, group/channel tag, or "*" for broadcast
    routing_mode: MessageRoutingMode
    channel: str
    payload: dict[str, str | int | float | bool]
    timestamp: float = field(default_factory=time.time)
    delivery_status: MeshDeliveryStatus = MeshDeliveryStatus.DELIVERED


@dataclass(frozen=True)
class BlackboardEntry:
    """Key-value factual assertion stored in the swarm shared blackboard."""

    key: str
    value: str
    author_id: str
    version: int = 1
    updated_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)


@dataclass
class SwarmTopologyConfig:
    """Declarative specification for configuring a dynamic swarm topology."""

    topology_id: str
    topology_type: TopologyType
    max_nodes: int = 16
    is_adaptive: bool = True
    heartbeat_interval_sec: float = 5.0


@dataclass
class SwarmTopologyState:
    """Runtime snapshot of the swarm mesh state and communication topology."""

    topology_id: str
    topology_type: TopologyType
    nodes: dict[str, SwarmNode] = field(default_factory=dict)
    edges: list[MeshEdge] = field(default_factory=list)
    blackboard: dict[str, BlackboardEntry] = field(default_factory=dict)
    recent_messages: list[MeshMessage] = field(default_factory=list)
    is_adaptive: bool = True


@dataclass(frozen=True)
class MigrationRequest:
    """Request to live-migrate an agent node to a different role or topology position."""

    node_id: str
    target_role: SwarmNodeRole
    state_diff: dict[str, str] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of a node live-migration operation."""

    migration_id: str
    node_id: str
    success: bool
    previous_role: SwarmNodeRole
    current_role: SwarmNodeRole
    reconnected_peers: list[str] = field(default_factory=list)
    details: str = ""
