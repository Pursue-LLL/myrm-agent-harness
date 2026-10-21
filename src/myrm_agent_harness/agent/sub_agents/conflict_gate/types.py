"""Type definitions and contracts for Parallel Work Conflict Reconciliation Gate.

[INPUT]
- None (pure domain types)

[OUTPUT]
- WriteMutationType, WriteFingerprint, ConflictStatus, ResolutionStrategy
- WorkConflictItem, ConflictGateVerdict

[POS]
myrm_agent_harness/agent/sub_agents/conflict_gate/types.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

WriteMutationType = Literal[
    "file",
    "artifact",
    "config",
    "card",
]

ConflictStatus = Literal[
    "clean",
    "conflict_pending",
    "resolved",
]

ResolutionStrategy = Literal[
    "keep_worker_a",
    "keep_worker_b",
    "three_way_merge",
    "abort_both",
]


@dataclass(slots=True)
class WriteFingerprint:
    """Fingerprint representing a mutation performed by a subagent worker."""

    worker_id: str
    resource_id: str
    mutation_type: WriteMutationType
    content_hash: str
    summary: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(slots=True)
class WorkConflictItem:
    """Detected conflict between two parallel workers on the same resource."""

    conflict_id: str
    session_id: str
    resource_id: str
    mutation_type: WriteMutationType
    worker_a: WriteFingerprint
    worker_b: WriteFingerprint
    status: ConflictStatus = "conflict_pending"
    resolution_strategy: ResolutionStrategy | None = None
    resolved_content: str | None = None
    resolved_at: str | None = None


@dataclass(slots=True)
class ConflictGateVerdict:
    """Evaluation outcome returned by the Parallel Work Conflict Gate."""

    is_blocked: bool
    total_conflicts: int
    conflicts: list[WorkConflictItem] = field(default_factory=list)
    clean_writes: list[WriteFingerprint] = field(default_factory=list)
