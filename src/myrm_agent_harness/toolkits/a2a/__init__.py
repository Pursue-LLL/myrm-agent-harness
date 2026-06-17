"""A2A (Agent-to-Agent) protocol support.

Provides data models, client resolver, and protocol contracts for
Google's A2A standard — enabling agent discovery and capability
declaration in the Agent ecosystem.

Public API::

    from myrm_agent_harness.toolkits.a2a import (
        AgentCard,
        AgentSkill,
        AgentCapabilities,
        AgentInterface,
        AgentProvider,
        AgentCardProvider,
        A2ACardResolver,
        WELL_KNOWN_AGENT_CARD_PATH,
    )
"""

from myrm_agent_harness.toolkits.a2a.protocols import AgentCardProvider
from myrm_agent_harness.toolkits.a2a.resolver import (
    A2ACardResolver,
    A2AResolveError,
    SSRFBlockedError,
)
from myrm_agent_harness.toolkits.a2a.types import (
    A2A_PROTOCOL_VERSION,
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    TransportProtocol,
    WELL_KNOWN_AGENT_CARD_PATH,
)

__all__ = [
    "A2A_PROTOCOL_VERSION",
    "A2ACardResolver",
    "A2AResolveError",
    "AgentCapabilities",
    "AgentCard",
    "AgentCardProvider",
    "AgentExtension",
    "AgentInterface",
    "AgentProvider",
    "AgentSkill",
    "SSRFBlockedError",
    "TransportProtocol",
    "WELL_KNOWN_AGENT_CARD_PATH",
]
