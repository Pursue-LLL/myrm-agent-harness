"""Composed MemoryManager type.

[INPUT]
- memory._manager.* mixins (POS: partial MemoryManager behavior modules)
- memory._manager.shared (POS: shared imports and error types)

[OUTPUT]
- MemoryManager: unified memory operations façade

[POS]
Internal composition root; consumers import via ``memory.manager``.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._manager.convenience import MemoryManagerConvenienceMixin
from myrm_agent_harness.toolkits.memory._manager.core import MemoryManagerCore
from myrm_agent_harness.toolkits.memory._manager.deletion import MemoryManagerDeletionMixin
from myrm_agent_harness.toolkits.memory._manager.governance_session import (
    MemoryManagerGovernanceSessionMixin,
)
from myrm_agent_harness.toolkits.memory._manager.import_export import MemoryManagerImportExportMixin
from myrm_agent_harness.toolkits.memory._manager.listing_maintenance import (
    MemoryManagerListingMaintenanceMixin,
)
from myrm_agent_harness.toolkits.memory._manager.mutations import MemoryManagerMutationsMixin
from myrm_agent_harness.toolkits.memory._manager.reindex import MemoryManagerReindexMixin
from myrm_agent_harness.toolkits.memory._manager.retrieval_write import MemoryManagerRetrievalWriteMixin
from myrm_agent_harness.toolkits.memory._manager.shared import (
    MemoryError,
    MemoryNotFoundError,
    MemoryTaintedError,
)
from myrm_agent_harness.toolkits.memory._manager.storage import MemoryManagerStorageMixin


class MemoryManager(
    MemoryManagerCore,
    MemoryManagerGovernanceSessionMixin,
    MemoryManagerRetrievalWriteMixin,
    MemoryManagerConvenienceMixin,
    MemoryManagerDeletionMixin,
    MemoryManagerListingMaintenanceMixin,
    MemoryManagerMutationsMixin,
    MemoryManagerStorageMixin,
    MemoryManagerImportExportMixin,
    MemoryManagerReindexMixin,
):
    """Orchestrates all memory operations. Bound to a single user via ``user_id``."""


__all__ = ["MemoryError", "MemoryManager", "MemoryNotFoundError", "MemoryTaintedError"]
