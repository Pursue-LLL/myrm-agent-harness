"""Types and data models for Pi Harness v2 Deterministic Subagent Session Fork Primitive (Item 51).

[INPUT]
- Parent session identifier and tool call identifier.
- Fork scope selector: branch (single lineage path) or tree (full shared topology).

[OUTPUT]
- Typed data models: ForkedSessionNode, ChildSessionLink, ForkResult.
- Custom exceptions: SessionForkError, ParentSessionNotFoundError, ForkConflictError.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

PrimitiveValue = str | int | float | bool | None
MetadataDict = dict[str, PrimitiveValue]


class ForkScope(StrEnum):
    """Scope defining which subset of entries are duplicated during fork."""

    BRANCH = "branch"  # Copies active branch lineage from root to target leaf
    TREE = "tree"      # Copies full shared tree topology


@dataclass(frozen=True)
class ForkedSessionNode:
    """An immutable entry / node replicated into a forked child session."""

    node_id: str
    parent_id: str | None
    node_type: str
    content: str
    created_at: float = field(default_factory=time.time)
    metadata: MetadataDict = field(default_factory=dict)


@dataclass
class ChildSessionLink:
    """Deterministic relationship and metadata between parent tool invocation and child session."""

    child_session_id: str
    parent_session_id: str
    tool_call_id: str
    fork_scope: ForkScope
    created_at: float = field(default_factory=time.time)
    reattach_count: int = 0
    last_attached_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ForkResult:
    """Result of a session fork or safe replay reattach operation."""

    child_session_id: str
    parent_session_id: str
    tool_call_id: str
    is_reattached: bool
    fork_scope: ForkScope
    copied_nodes_count: int
    root_node_id: str
    leaf_node_id: str


class SessionForkError(Exception):
    """Base exception for deterministic session fork subsystem."""


class ParentSessionNotFoundError(SessionForkError):
    """Raised when parent session history is required but not provided or found."""


class ForkConflictError(SessionForkError):
    """Raised when a child session exists with mismatched invocation parameters."""
