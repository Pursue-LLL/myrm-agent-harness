# [POS]: myrm_agent_harness.toolkits.memory.peer_gateway
# [INPUT]: .models, .escalation, .resolver, .gateway
# [OUTPUT]: Multi-Channel Peer Alias & Anti-Cross-Contamination Gateway Suite symbols

"""Multi-Channel Peer Alias and Anti-Cross-Contamination Gateway Suite.

P1 delivery for Item 113 in topic_01 memory roadmap.
"""

from myrm_agent_harness.toolkits.memory.peer_gateway.escalation import (
    HashEscalationEngine,
)
from myrm_agent_harness.toolkits.memory.peer_gateway.gateway import (
    AntiCrossContaminationGateway,
)
from myrm_agent_harness.toolkits.memory.peer_gateway.models import (
    ChannelType,
    GatewayPeerAliasConfig,
    PeerBoundaryCheckResult,
    ResolvedPeerIdentity,
)
from myrm_agent_harness.toolkits.memory.peer_gateway.resolver import (
    DeterministicPeerResolver,
)

__all__ = [
    "AntiCrossContaminationGateway",
    "ChannelType",
    "DeterministicPeerResolver",
    "GatewayPeerAliasConfig",
    "HashEscalationEngine",
    "PeerBoundaryCheckResult",
    "ResolvedPeerIdentity",
]
