"""Types and models for session tree.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ForkModeKind: Cloning strategy when forking a session from a timeline node.
- RewindModeKind: Archival behavior when rewinding to a previous message node.
- SessionMessageItem: Immutable session message entry in timeline history.
- SessionBranchNode: Descriptor of a session tree branch in the multi-version graph.
- ForkResult: Result of forking a session at a specific timeline message anchor.
- RewindResult: Result of rewinding timeline in-place to edit & re-generate.
- SessionTreeTopology: Complete branch graph topology for a session lineage.

[POS]
Types and models for session tree.
"""

# ============================================================================
# Session Tree Fork & Message Rewind Data Contracts (Item 162)
# Strong typing contracts for timeline forking, tree topology branching,
# in-place message rewind & re-generate, and non-destructive context cloning.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ForkModeKind(str, Enum):
    """Cloning strategy when forking a session from a timeline node."""

    DEEP_CLONE = "deep_clone"  # Deeply clone antecedent messages with new identifiers
    SHALLOW_REFERENCE = "shallow_reference"  # Reference antecedent messages immutably


class RewindModeKind(str, Enum):
    """Archival behavior when rewinding to a previous message node."""

    TRUNCATE_AND_ARCHIVE = "truncate_and_archive"  # Move subsequent messages to archival ledger
    HARD_DELETE = "hard_delete"  # Purge subsequent messages permanently


@dataclass(frozen=True, slots=True)
class SessionMessageItem:
    """Immutable session message entry in timeline history."""

    message_id: str
    session_id: str
    role: str
    content: str
    sequence_index: int
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionBranchNode:
    """Descriptor of a session tree branch in the multi-version graph."""

    branch_id: str
    session_id: str
    branch_name: str
    parent_session_id: str | None
    forked_from_message_id: str | None
    created_at_iso: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class ForkResult:
    """Result of forking a session at a specific timeline message anchor."""

    new_session_id: str
    parent_session_id: str
    fork_message_id: str
    cloned_messages_count: int
    branch_node: SessionBranchNode


@dataclass(frozen=True, slots=True)
class RewindResult:
    """Result of rewinding timeline in-place to edit & re-generate."""

    rewound_session_id: str
    target_message_id: str
    removed_messages_count: int
    archived_message_ids: tuple[str, ...]
    restored_prompt_text: str


@dataclass(frozen=True, slots=True)
class SessionTreeTopology:
    """Complete branch graph topology for a session lineage."""

    root_session_id: str
    branches: tuple[SessionBranchNode, ...]
    active_session_id: str
