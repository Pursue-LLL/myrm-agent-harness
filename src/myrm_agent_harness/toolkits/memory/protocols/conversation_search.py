"""Conversation search protocol for framework-level recall tools.

[INPUT]
myrm_agent_harness.toolkits.memory.conversation_search.types (POS: conversation recall DTOs)

[OUTPUT]
ConversationSearchProtocol: storage-agnostic conversation recall provider contract.

[POS]
Conversation search protocol boundary. Defines the framework contract consumed by agent tools while keeping
database, product, GUI, tenant, and deployment semantics outside the Harness layer.
"""

from __future__ import annotations

from typing import Protocol

from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    ConversationSearchRequest,
    ConversationSearchResponse,
)


class ConversationSearchProtocol(Protocol):
    """Provider contract for searching or browsing persisted conversations."""

    async def search(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
        """Search conversations according to a typed request."""
