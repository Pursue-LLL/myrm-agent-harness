"""A2A protocol boundary contracts.

Defines the Protocol interface that business layers implement to
provide AgentCard content.

[INPUT]
- types::AgentCard

[OUTPUT]
- AgentCardProvider: Protocol for generating AgentCard

[POS]
Framework-business boundary. Harness defines the interface,
server layer implements it with business data.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.a2a.types import AgentCard


@runtime_checkable
class AgentCardProvider(Protocol):
    """Generates AgentCard content from business data.

    Business layer implements this to fill AgentCard from
    agent configuration and installed skills.
    """

    async def get_card(self) -> AgentCard:
        """Return the public AgentCard for discovery."""
        ...

    async def get_extended_card(self) -> AgentCard | None:
        """Return authenticated-only extended card.

        Returns None if not supported (default for single-user scenarios).
        """
        ...
