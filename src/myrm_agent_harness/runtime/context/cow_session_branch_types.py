"""Type definitions for Instant Session Forking and Copy-on-Write (CoW) State Branching.

Defines data contracts for immutable ancestor sharing, delta message stores,
CoW artifact resolution, and hierarchical exploration lineages.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- BranchMessageEntry: Represents a single conversational turn message inside a session branch.
- CoWArtifactRecord: Represents an artifact state record either inherited or overridden in a branch.
- SessionBranchDescriptor: Metadata describing a session branch and its lineage connection.
- ProjectedSessionView: Virtual projected composite view combining inherited history with local deltas.

[POS]
Type definitions for Instant Session Forking and Copy-on-Write (CoW) State Branching.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BranchMessageEntry:
    """Represents a single conversational turn message inside a session branch."""

    turn_id: str
    role: str
    content: str
    timestamp: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CoWArtifactRecord:
    """Represents an artifact state record either inherited or overridden in a branch."""

    artifact_id: str
    version: int
    content: str
    updated_at: float
    origin_session_id: str


@dataclass(frozen=True)
class SessionBranchDescriptor:
    """Metadata describing a session branch and its lineage connection."""

    session_id: str
    parent_session_id: str | None
    fork_point_turn_id: str | None
    branch_label: str
    created_at: float
    depth: int


@dataclass(frozen=True)
class ProjectedSessionView:
    """Virtual projected composite view combining inherited history with local deltas."""

    session_id: str
    branch_label: str
    messages: tuple[BranchMessageEntry, ...]
    artifacts: dict[str, CoWArtifactRecord]
    inherited_turns_count: int
    local_turns_count: int
    total_turns_count: int
    lineage_path: tuple[str, ...]
