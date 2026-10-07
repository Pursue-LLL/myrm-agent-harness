"""Type definitions for Dual-Branching Session Fork and In-Place Turn Rewind Suite.

Provides immutable data contracts for tree-structured message DAG nodes,
branch metadata, version navigation telemetry, and fork clone outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class BranchingPosture(StrEnum):
    """The two orthogonal branching postures inspired by Pi Web."""

    NEW_SESSION_CLONE = "new_session_clone"    # Clone an independent session file
    IN_PLACE_EDIT_BRANCH = "in_place_edit_branch"  # Non-destructive version branch inside session


@dataclass(frozen=True)
class TreeNodeMessage:
    """Represents a discrete message node within the session DAG tree."""

    message_id: str
    session_id: str
    role: str
    content: str
    parent_id: str | None
    branch_id: str
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class BranchDescriptor:
    """Descriptor capturing a version branch within the session."""

    branch_id: str
    forked_from_message_id: str | None
    name: str
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class VersionNavigationInfo:
    """Version pagination capsule for frontend rendering (e.g., Version 1/3 ◀ ▶)."""

    parent_id: str | None
    current_version_index: int
    total_versions: int
    available_branch_ids: tuple[str, ...]
    active_branch_id: str
    active_message_id: str | None


@dataclass(frozen=True)
class ForkCloneResult:
    """Result emitted when forking a new independent session from an earlier turn."""

    source_session_id: str
    new_session_id: str
    cutoff_message_id: str
    cloned_message_count: int
    cloned_messages: tuple[TreeNodeMessage, ...]
    created_at: float = field(default_factory=time.time)
