"""External memory provider protocol export.

[INPUT]
- external_providers.protocols::{ExternalMemoryProviderProtocol, PrefetchResult, ProviderExecutionMetrics}
- external_providers.models::{DerivedObservationRecord, EvidenceRecord, MemoryScopeContext, ProviderKind}

[OUTPUT]
- ExternalMemoryProviderProtocol: unified 5-stage external provider lifecycle interface.
- PrefetchResult: prefetch container DTO.
- ProviderExecutionMetrics: telemetry container DTO.

[POS]
Re-exports the storage-agnostic external memory provider protocol at the protocols boundary.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.external_providers.models import (
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryScopeContext,
    ProviderKind,
)
from myrm_agent_harness.toolkits.memory.external_providers.protocols import (
    ExternalMemoryProviderProtocol,
    PrefetchResult,
    ProviderExecutionMetrics,
)

__all__ = [
    "DerivedObservationRecord",
    "EvidenceRecord",
    "ExternalMemoryProviderProtocol",
    "MemoryScopeContext",
    "PrefetchResult",
    "ProviderExecutionMetrics",
    "ProviderKind",
]
