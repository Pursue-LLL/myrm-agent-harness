# [POS]: myrm_agent_harness.toolkits.memory.peer_gateway.models
# [INPUT]: None (Standard library & Pydantic)
# [OUTPUT]: ChannelType, GatewayPeerAliasConfig, ResolvedPeerIdentity, PeerBoundaryCheckResult

"""Domain models for Multi-Channel Peer Alias and Anti-Cross-Contamination Gateway Suite.

P1 delivery for Item 113 in topic_01 memory roadmap.
Provides deterministic peer mapping across desktop, web, and external IM channels,
preventing cognitive fragmentation and unauthorized memory cross-contamination.

[INPUT]
- Third-party: pydantic

[OUTPUT]
- ChannelType: Supported external or client access channel platforms.
- GatewayPeerAliasConfig: Configuration governing deterministic resolution and anti-contamination boundaries.
- ResolvedPeerIdentity: Resolved canonical peer identity output by deterministic resolver.
- PeerBoundaryCheckResult: Verification outcome evaluating whether memory access crosses illegal tenant
  boundaries.

[POS]
Domain models for Multi-Channel Peer Alias and Anti-Cross-Contamination Gateway Suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ChannelType(StrEnum):
    """Supported external or client access channel platforms."""

    WEB = "web"
    DESKTOP = "desktop"
    FEISHU = "feishu"
    DINGTALK = "dingtalk"
    TELEGRAM = "telegram"
    SLACK = "slack"
    API = "api"


class GatewayPeerAliasConfig(BaseModel):
    """Configuration governing deterministic resolution and anti-contamination boundaries."""

    pin_user_peer: str | None = Field(
        default=None,
        description="Optional forced primary user peer id for local desktop or single-user sandbox",
    )
    user_peer_aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Explicit mapping from channel identifier (or raw ID) to canonical peer ID",
    )
    runtime_peer_prefix: str = Field(
        default="peer_",
        description="Standardized prefix for synthetic or escalated peer identifiers",
    )
    allowed_collaborator_peers: list[str] = Field(
        default_factory=list,
        description="Peers permitted for cross-session reading (e.g. system agent, reviewer)",
    )


class ResolvedPeerIdentity(BaseModel):
    """Resolved canonical peer identity output by deterministic resolver."""

    canonical_peer_id: str = Field(description="Normalized system peer identifier")
    channel_type: ChannelType = Field(description="Originating client access channel")
    raw_channel_id: str = Field(description="Raw external identifier supplied by channel")
    alias_matched: bool = Field(default=False, description="True if identity resolved via alias table")
    is_pinned: bool = Field(default=False, description="True if identity resolved via pin_user_peer mandate")
    hash_escalated: bool = Field(default=False, description="True if hash suffix was escalated to avoid collision")
    resolved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PeerBoundaryCheckResult(BaseModel):
    """Verification outcome evaluating whether memory access crosses illegal tenant boundaries."""

    allowed: bool = Field(description="True if requested memory access conforms to identity boundaries")
    session_peer_id: str = Field(description="Active session peer identifier")
    target_peer_id: str = Field(description="Requested target memory peer identifier")
    violation_reason: str | None = Field(default=None, description="Detailed explanation if blocked")
