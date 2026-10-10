"""Data models for Auto Memory Staleness Decay and Consolidation Audit Suite (Item 158).

[INPUT]
- Timestamp strings, path references, assertion payloads, memory item profiles.

[OUTPUT]
- MemoryItemProfile, RepoAssertionCheckResult, ConsolidationProposal, and MemoryAuditReport.

[POS]
- Core models in myrm_agent_harness/toolkits/memory/staleness_consolidation/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MemoryStatus = Literal[
    "active",
    "stale",
    "invalidated",
    "consolidated",
    "archived",
]


@dataclass(slots=True)
class MemoryItemProfile:
    """Detailed profile of an autonomous memory record tracking access hotness and staleness."""

    memory_id: str
    content: str
    category: str = "general"
    created_at: str = ""
    last_recalled_at: str = ""
    recalled_count: int = 0
    staleness_score: float = 0.0
    status: MemoryStatus = "active"
    referenced_paths: list[str] = field(default_factory=list)
    referenced_assertions: list[str] = field(default_factory=list)
    invalidation_reason: str | None = None
    subsumed_by_id: str | None = None


@dataclass(slots=True)
class RepoAssertionCheckResult:
    """Result of verifying memory assertions against the current workspace file system."""

    memory_id: str
    is_valid: bool
    missing_paths: list[str] = field(default_factory=list)
    failed_assertions: list[str] = field(default_factory=list)
    diagnostic: str = ""


@dataclass(slots=True)
class ConsolidationProposal:
    """Proposed consolidation merging multiple fragmented rules into a unified entry."""

    proposal_id: str
    source_memory_ids: list[str]
    category: str
    proposed_content: str
    rationale: str


@dataclass(slots=True)
class MemoryAuditReport:
    """Comprehensive health check report across all active, stale, and invalidated memories."""

    total_items: int
    active_items: int
    stale_items: int
    invalidated_items: int
    consolidated_items: int
    archived_items: int
    average_staleness: float
    invalidated_results: list[RepoAssertionCheckResult] = field(default_factory=list)
    consolidation_proposals: list[ConsolidationProposal] = field(default_factory=list)
    generated_at: str = ""
