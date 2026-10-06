"""Pluggable external memory provider lifecycle and supersedes lineage pack.

[INPUT]
- external_providers.models::{
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryLifecycleStage,
    MemoryScopeContext,
    MemoryScopeType,
    ProviderCatalogEntry,
    ProviderKind,
    SupersedesRecord,
  }
- external_providers.protocols::{
    ExternalMemoryProviderProtocol,
    PrefetchResult,
    ProviderExecutionMetrics,
  }
- external_providers.lineage_manager::{
    CascadeDeletionResult,
    SupersedesLineageManager,
  }
- external_providers.scheduler::{
    SingleActiveProviderScheduler,
    is_trivial_prompt,
  }
- external_providers.benchmark_suite::{
    BenchmarkDimensionScore,
    BenchmarkReport,
    ExternalMemoryBenchmarkSuite,
  }

[OUTPUT]
- Public module exports for external memory provider lifecycle and lineage management.

[POS]
Root package for external memory provider lifecycle contracts, supersedes versioning,
and three-dimensional evaluation benchmarking.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.external_providers.benchmark_suite import (
    BenchmarkDimensionScore,
    BenchmarkReport,
    ExternalMemoryBenchmarkSuite,
)
from myrm_agent_harness.toolkits.memory.external_providers.lineage_manager import (
    CascadeDeletionResult,
    SupersedesLineageManager,
)
from myrm_agent_harness.toolkits.memory.external_providers.models import (
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryLifecycleStage,
    MemoryScopeContext,
    MemoryScopeType,
    ProviderCatalogEntry,
    ProviderKind,
    SupersedesRecord,
)
from myrm_agent_harness.toolkits.memory.external_providers.protocols import (
    ExternalMemoryProviderProtocol,
    PrefetchResult,
    ProviderExecutionMetrics,
)
from myrm_agent_harness.toolkits.memory.external_providers.scheduler import (
    SingleActiveProviderScheduler,
    is_trivial_prompt,
)

__all__ = [
    "BenchmarkDimensionScore",
    "BenchmarkReport",
    "CascadeDeletionResult",
    "DerivedObservationRecord",
    "EvidenceRecord",
    "ExternalMemoryBenchmarkSuite",
    "ExternalMemoryProviderProtocol",
    "MemoryLifecycleStage",
    "MemoryScopeContext",
    "MemoryScopeType",
    "PrefetchResult",
    "ProviderCatalogEntry",
    "ProviderExecutionMetrics",
    "ProviderKind",
    "SingleActiveProviderScheduler",
    "SupersedesLineageManager",
    "SupersedesRecord",
    "is_trivial_prompt",
]
