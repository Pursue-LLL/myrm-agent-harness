"""Types and models for message tree.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- TreeNodeRole: Message role within in-place message tree hierarchy.
- TreeMessageNode: Immutable tree node representing an individual message turn.
- SiblingVersionItem: Summary of a sibling version candidate for in-place UI navigator.
- VersionSwitchResult: Outcome of switching sibling version on an in-place message node.
- MessageTreeGraph: Complete in-memory DAG message tree for a session.

[POS]
Types and models for message tree.
"""

# ============================================================================
# In-Place Message Tree Branching & Version Navigator Data Contracts (Item 164)
# Strong typing contracts for message-node level tree hierarchy, sibling version
# navigation (< 1/3 >), and active timeline path resolution.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TreeNodeRole(str, Enum):
    """Message role within in-place message tree hierarchy."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class TreeMessageNode:
    """Immutable tree node representing an individual message turn."""

    node_id: str
    session_id: str
    parent_id: str | None
    role: TreeNodeRole
    content: str
    sibling_index: int  # 1-indexed version number among siblings (e.g. 1 in < 1/3 >)
    total_siblings: int  # Total candidate variants sharing the same parent
    child_ids: tuple[str, ...]
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SiblingVersionItem:
    """Summary of a sibling version candidate for in-place UI navigator."""

    node_id: str
    sibling_index: int
    content_preview: str
    created_at_iso: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class VersionSwitchResult:
    """Outcome of switching sibling version on an in-place message node."""

    session_id: str
    target_node_id: str
    previous_sibling_index: int
    new_sibling_index: int
    total_siblings: int
    active_path_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MessageTreeGraph:
    """Complete in-memory DAG message tree for a session."""

    session_id: str
    root_node_id: str | None
    nodes: tuple[TreeMessageNode, ...]
    active_leaf_id: str | None
    active_path_ids: tuple[str, ...]
