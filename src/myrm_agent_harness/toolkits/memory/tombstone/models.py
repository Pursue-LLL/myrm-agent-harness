"""[POS]: src/myrm_agent_harness/toolkits/memory/tombstone/models.py
[INPUT]: Memory candidate records, state transitions, and contradiction definitions.
[OUTPUT]: Strongly-typed domain models for memory tombstoning, contradiction detection, and eviction.
"""

import time
from dataclasses import dataclass, field
from enum import StrEnum


class TombstoneState(StrEnum):
    """Lifecycle states for memory directives subjected to tombstone management."""

    ACTIVE = "active"
    SUPERSEDED_CANDIDATE = "superseded_candidate"
    TOMBSTONED = "tombstoned"
    EVICTED = "evicted"
    REVIVED = "revived"


@dataclass(frozen=True)
class ContradictionPair:
    """Pair of mutually opposing or antithetical memory directives."""

    new_memory_id: str
    outdated_memory_id: str
    topic_keyword: str
    confidence_score: float
    reason: str


@dataclass
class TombstoneCandidateItem:
    """Memory item undergoing contradiction screening or tombstone masking."""

    memory_id: str
    content: str
    category: str = "general"
    created_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)


@dataclass
class TombstoneAuditRecord:
    """Historical audit ledger entry tracking tombstone status and supersession lineage."""

    memory_id: str
    state: TombstoneState
    tombstoned_at: float | None = None
    superseded_by_id: str | None = None
    reason: str | None = None
    evicted_at: float | None = None


@dataclass
class TombstoneCurationReport:
    """Execution report detailing memory contradiction scan and tombstone curation results."""

    total_scanned: int
    total_contradictions_found: int
    total_tombstoned: int
    total_evicted: int
    contradictions: list[ContradictionPair] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
