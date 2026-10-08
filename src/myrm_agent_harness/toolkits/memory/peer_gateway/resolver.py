# [POS]: myrm_agent_harness.toolkits.memory.peer_gateway.resolver
# [INPUT]: ChannelType, GatewayPeerAliasConfig, ResolvedPeerIdentity, HashEscalationEngine
# [OUTPUT]: DeterministicPeerResolver

"""Deterministic multi-channel peer identity resolution engine.

Resolves external channel IDs to canonical system peer IDs using pinned defaults,
explicit multi-device aliases, and adaptive collision escalation.

[INPUT]
- toolkits.memory.peer_gateway.escalation::HashEscalationEngine (POS: Adaptive hash collision escalation
  algorithm for deterministic peer normalization.)
- toolkits.memory.peer_gateway.models::ChannelType, GatewayPeerAliasConfig, ResolvedPeerIdentity (POS: Domain
  models for Multi-Channel Peer Alias and Anti-Cross-Contamination Gateway Suite.)

[OUTPUT]
- DeterministicPeerResolver: Resolves external client identities to deterministic canonical peers.

[POS]
Deterministic multi-channel peer identity resolution engine.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.peer_gateway.escalation import HashEscalationEngine
from myrm_agent_harness.toolkits.memory.peer_gateway.models import (
    ChannelType,
    GatewayPeerAliasConfig,
    ResolvedPeerIdentity,
)

logger = logging.getLogger(__name__)


class DeterministicPeerResolver:
    """Resolves external client identities to deterministic canonical peers."""

    def __init__(self, config: GatewayPeerAliasConfig | None = None) -> None:
        self._config = config or GatewayPeerAliasConfig()
        self._known_peers: set[str] = set()
        if self._config.pin_user_peer:
            self._known_peers.add(self._config.pin_user_peer)
        for target_id in self._config.user_peer_aliases.values():
            self._known_peers.add(target_id)

    @property
    def config(self) -> GatewayPeerAliasConfig:
        return self._config

    def register_alias(self, channel_key: str, canonical_peer_id: str) -> None:
        """Register or override a multi-channel alias mapping dynamically."""
        self._config.user_peer_aliases[channel_key.strip()] = canonical_peer_id.strip()
        self._known_peers.add(canonical_peer_id.strip())

    def get_aliases(self) -> dict[str, str]:
        """Retrieve copy of all registered channel-to-peer aliases."""
        return dict(self._config.user_peer_aliases)

    def resolve_peer(
        self,
        channel_type: ChannelType | str,
        raw_channel_id: str,
    ) -> ResolvedPeerIdentity:
        """Deterministically map a channel identifier to a canonical system peer.

        Resolution Priority:
        1. Pinned Primary Peer (e.g. local desktop single-user mode)
        2. Explicit Alias Lookup (e.g. desktop:alice -> peer_alice_master)
        3. Adaptive Hash Escalation (collision-free alphanumeric normalization)
        """
        c_type = ChannelType(channel_type) if isinstance(channel_type, str) else channel_type
        raw_clean = raw_channel_id.strip()

        # 1. Pinned primary peer takes absolute priority in single-user setups
        if self._config.pin_user_peer:
            return ResolvedPeerIdentity(
                canonical_peer_id=self._config.pin_user_peer,
                channel_type=c_type,
                raw_channel_id=raw_clean,
                alias_matched=False,
                is_pinned=True,
                hash_escalated=False,
            )

        # 2. Check explicit channel-specific and raw aliases
        candidates_to_probe = (
            f"{c_type.value}:{raw_clean}",
            raw_clean,
            f"{c_type.value}:{raw_clean.lower()}",
        )
        for probe_key in candidates_to_probe:
            if probe_key in self._config.user_peer_aliases:
                canonical = self._config.user_peer_aliases[probe_key]
                return ResolvedPeerIdentity(
                    canonical_peer_id=canonical,
                    channel_type=c_type,
                    raw_channel_id=raw_clean,
                    alias_matched=True,
                    is_pinned=False,
                    hash_escalated=False,
                )

        # 3. Adaptive hash escalation fallback
        unique_id, was_escalated = HashEscalationEngine.escalate_hash_suffix(
            raw_id=f"{c_type.value}_{raw_clean}",
            collision_registry=self._known_peers,
            prefix=self._config.runtime_peer_prefix,
        )
        self._known_peers.add(unique_id)

        return ResolvedPeerIdentity(
            canonical_peer_id=unique_id,
            channel_type=c_type,
            raw_channel_id=raw_clean,
            alias_matched=False,
            is_pinned=False,
            hash_escalated=was_escalated,
        )
