"""Integration Retained Context Purge & Provenance Revocation mixin for MemoryManager.

[INPUT]
- typing::{TYPE_CHECKING, Any}
- myrm_agent_harness.toolkits.memory.integration_purge::{
    IntegrationRetainedContextManager,
    IntegrationRetainedContextSummary,
    PurgeExecutionMode,
    PurgeExecutionResult,
    ProvenanceRevocationRecord,
  }

[OUTPUT]
- MemoryManagerIntegrationPurgeMixin: Mixin providing connector-scoped purge and provenance revocation

[POS]
Mix-in for MemoryManager (Topic 01 Item 179). Enables privacy-first context retention
auditing, selective purging, and revocation tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.integration_purge.manager import (
    IntegrationRetainedContextManager,
)
from myrm_agent_harness.toolkits.memory.integration_purge.types import (
    IntegrationRetainedContextSummary,
    ProvenanceRevocationRecord,
    PurgeExecutionMode,
    PurgeExecutionResult,
)

if TYPE_CHECKING:
    pass


class MemoryManagerIntegrationPurgeMixin:
    """Mixin for MemoryManager offering integration retained context governance."""

    _integration_purge_manager: IntegrationRetainedContextManager | None = None

    def get_integration_retained_context_manager(self) -> IntegrationRetainedContextManager:
        """Get or lazily initialise the IntegrationRetainedContextManager."""
        if self._integration_purge_manager is None:
            # Bind the memory manager's delete_memories_by_metadata method as callback
            delete_cb = getattr(self, "delete_memories_by_metadata", None)
            self._integration_purge_manager = IntegrationRetainedContextManager(
                delete_memories_callback=delete_cb,
            )
        return self._integration_purge_manager

    async def inspect_integration_retained_context(
        self,
        integration_id: str,
        *,
        provider_type: str = "external_integration",
    ) -> IntegrationRetainedContextSummary:
        """Inspect and audit retained context items associated with an integration/connector."""
        mgr = self.get_integration_retained_context_manager()
        return await mgr.inspect_retained_context(integration_id, provider_type=provider_type)

    async def purge_integration_retained_context(
        self,
        integration_id: str,
        mode: PurgeExecutionMode,
        *,
        actor: str = "user",
        reason: str = "",
    ) -> PurgeExecutionResult:
        """Execute a connector-scoped context purge and provenance revocation."""
        mgr = self.get_integration_retained_context_manager()
        return await mgr.execute_purge(integration_id, mode, actor=actor, reason=reason)

    def is_integration_provenance_revoked(self, integration_id: str) -> bool:
        """Check whether an integration provenance has been revoked."""
        mgr = self.get_integration_retained_context_manager()
        return mgr.is_provenance_revoked(integration_id)

    def list_integration_revocation_records(self) -> list[ProvenanceRevocationRecord]:
        """List historical provenance revocation ledger records."""
        mgr = self.get_integration_retained_context_manager()
        return mgr.list_revocation_records()
