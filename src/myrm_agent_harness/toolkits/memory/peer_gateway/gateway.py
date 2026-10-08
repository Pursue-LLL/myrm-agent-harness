# [POS]: myrm_agent_harness.toolkits.memory.peer_gateway.gateway
# [INPUT]: ChannelType, GatewayPeerAliasConfig, PeerBoundaryCheckResult, ResolvedPeerIdentity, DeterministicPeerResolver
# [OUTPUT]: AntiCrossContaminationGateway

"""Anti-cross-contamination gateway boundary enforcer for multi-tenant and multi-peer memory safety.

Prevents cross-tenant leaks and accidental cross-session contamination across channels.

[INPUT]
- toolkits.memory.peer_gateway.models::ChannelType, GatewayPeerAliasConfig, PeerBoundaryCheckResult,
  ResolvedPeerIdentity (POS: Domain models for Multi-Channel Peer Alias and Anti-Cross-Contamination Gateway
  Suite.)
- toolkits.memory.peer_gateway.resolver::DeterministicPeerResolver (POS: Deterministic multi-channel peer
  identity resolution engine.)

[OUTPUT]
- AntiCrossContaminationGateway: Gateway defense middleware enforcing strict tenant/peer memory boundary
  isolation.

[POS]
Anti-cross-contamination gateway boundary enforcer for multi-tenant and multi-peer memory safety.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.peer_gateway.models import (
    ChannelType,
    GatewayPeerAliasConfig,
    PeerBoundaryCheckResult,
    ResolvedPeerIdentity,
)
from myrm_agent_harness.toolkits.memory.peer_gateway.resolver import DeterministicPeerResolver

logger = logging.getLogger(__name__)


class AntiCrossContaminationGateway:
    """Gateway defense middleware enforcing strict tenant/peer memory boundary isolation."""

    def __init__(
        self,
        resolver: DeterministicPeerResolver | None = None,
        config: GatewayPeerAliasConfig | None = None,
    ) -> None:
        self._resolver = resolver or DeterministicPeerResolver(config)

    @property
    def resolver(self) -> DeterministicPeerResolver:
        return self._resolver

    @property
    def config(self) -> GatewayPeerAliasConfig:
        return self._resolver.config

    def validate_session_peer_boundary(
        self,
        session_peer_id: str,
        target_peer_id: str,
    ) -> PeerBoundaryCheckResult:
        """Verify that memory access does not breach peer boundary fences.

        Access is permitted if:
        1. Target peer matches the session peer (self-access).
        2. Target peer is registered in allowed_collaborator_peers (shared/system agents).
        Otherwise access is strictly blocked to prevent cross-contamination.
        """
        s_peer = session_peer_id.strip()
        t_peer = target_peer_id.strip()

        # 1. Direct match: session owner accesses their own memory partition
        if s_peer == t_peer:
            return PeerBoundaryCheckResult(
                allowed=True,
                session_peer_id=s_peer,
                target_peer_id=t_peer,
                violation_reason=None,
            )

        # 2. Permitted shared collaborator or system peer
        if t_peer in self.config.allowed_collaborator_peers:
            return PeerBoundaryCheckResult(
                allowed=True,
                session_peer_id=s_peer,
                target_peer_id=t_peer,
                violation_reason=None,
            )

        # 3. Violation: Cross-peer memory contamination attempt
        logger.warning(
            "Blocked memory boundary breach: session peer '%s' attempted to access target '%s'",
            s_peer,
            t_peer,
        )
        return PeerBoundaryCheckResult(
            allowed=False,
            session_peer_id=s_peer,
            target_peer_id=t_peer,
            violation_reason=(
                f"Cross-peer contamination blocked: session peer '{s_peer}' is not authorized "
                f"to access private memory partition of peer '{t_peer}'"
            ),
        )

    def resolve_and_verify(
        self,
        channel_type: ChannelType | str,
        raw_channel_id: str,
        target_peer_id: str | None = None,
    ) -> tuple[ResolvedPeerIdentity, PeerBoundaryCheckResult]:
        """Resolve external identity and enforce memory isolation boundaries in a single atomic pass."""
        identity = self._resolver.resolve_peer(channel_type, raw_channel_id)
        effective_target = target_peer_id.strip() if target_peer_id else identity.canonical_peer_id
        check_result = self.validate_session_peer_boundary(
            session_peer_id=identity.canonical_peer_id,
            target_peer_id=effective_target,
        )
        return identity, check_result
