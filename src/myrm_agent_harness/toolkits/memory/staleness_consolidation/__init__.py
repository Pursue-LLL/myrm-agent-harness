"""Auto Memory Staleness Decay and Consolidation Audit Suite (Item 158).

[INPUT]
- Memory profiles, decay factors, workspace directories, and consolidation requests.

[OUTPUT]
- AutoMemoryStalenessAndConsolidationAuditSuite, MemoryHalfLifeDecayProfiler,
  RepoFactInvalidationChecker, MemoryConsolidationEngine, and domain data models.

[POS]
- Module exports in myrm_agent_harness/toolkits/memory/staleness_consolidation/.
"""

from __future__ import annotations

from .audit_suite import AutoMemoryStalenessAndConsolidationAuditSuite
from .consolidation_engine import MemoryConsolidationEngine
from .decay_profiler import MemoryHalfLifeDecayProfiler
from .models import (
    ConsolidationProposal,
    MemoryAuditReport,
    MemoryItemProfile,
    MemoryStatus,
    RepoAssertionCheckResult,
)
from .repo_checker import RepoFactInvalidationChecker

__all__ = [
    "AutoMemoryStalenessAndConsolidationAuditSuite",
    "ConsolidationProposal",
    "MemoryAuditReport",
    "MemoryConsolidationEngine",
    "MemoryHalfLifeDecayProfiler",
    "MemoryItemProfile",
    "MemoryStatus",
    "RepoAssertionCheckResult",
    "RepoFactInvalidationChecker",
]
