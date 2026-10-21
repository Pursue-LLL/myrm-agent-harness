"""Core types for Hybrid Cloud-Edge Sandbox Relay & Artifact Sync (Item 58).

[INPUT]
- Raw artifact deltas, sync requests, and local egress relay directives.

[OUTPUT]
- Strongly-typed models for bidirectional chunk append, CAS versioning,
  and network partition relay fetching.

[POS]
- Framework-level types underpinning hybrid local/cloud sandbox collaboration.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


class ArtifactSyncModeEnum(enum.StrEnum):
    """Synchronization strategy for hybrid artifacts."""

    APPEND_ONLY = "append_only"
    PATCH_DIFF = "patch_diff"
    OVERWRITE_STRICT = "overwrite_strict"


class RelayNodeRoleEnum(enum.StrEnum):
    """Deployment role of the participating sandbox execution node."""

    LOCAL_SANDBOX = "local_sandbox"
    CLOUD_SANDBOX = "cloud_sandbox"
    EDGE_GATEWAY = "edge_gateway"


class NetworkEgressStatusEnum(enum.StrEnum):
    """Lifecycle status of network partition egress fetch relay."""

    DIRECT_OK = "direct_ok"
    RELAY_REQUESTED = "relay_requested"
    RELAY_COMPLETED = "relay_completed"
    RELAY_FAILED = "relay_failed"


@dataclass(frozen=True)
class ArtifactSyncChunk:
    """Atomic delta chunk appended to a shared hybrid artifact."""

    chunk_id: str
    artifact_id: str
    version: int
    author_role: RelayNodeRoleEnum
    content_delta: str
    row_count: int
    timestamp: float
    checksum: str


@dataclass(frozen=True)
class HybridArtifactState:
    """Current state snapshot of a hybrid synchronized artifact."""

    artifact_id: str
    name: str
    current_version: int
    total_rows: int
    chunks: Sequence[ArtifactSyncChunk] = field(default_factory=tuple)
    last_synced_at: float = 0.0
    is_divergent: bool = False


@dataclass(frozen=True)
class LocalEgressRelayRequest:
    """Request dispatched from cloud sandbox when facing network egress constraints."""

    relay_id: str
    target_url: str
    intent: str
    headers: Mapping[str, str] = field(default_factory=dict)
    payload: Mapping[str, str | int | float | bool] = field(default_factory=dict)
    timeout_seconds: float = 15.0
    source_node: RelayNodeRoleEnum = RelayNodeRoleEnum.CLOUD_SANDBOX


@dataclass(frozen=True)
class LocalEgressRelayResponse:
    """Outcome of relay fetch executed on the local desktop network."""

    relay_id: str
    status: NetworkEgressStatusEnum
    extracted_data: str
    status_code: int
    latency_ms: float
    error_message: str = ""
