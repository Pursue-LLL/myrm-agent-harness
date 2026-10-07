# ============================================================================
# # DualBranchingSessionDagAndEditFromHereEngine Types (Item 144)
# # Strict typed contracts for DAG branching, in-session branch switching,
# # and standalone session fork workflows.
# ============================================================================

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class BranchForkMode(StrEnum):
    """Operation modes for conversation DAG branching."""

    IN_SESSION_BRANCH = "in_session_branch"  # Edit from here: creates sub-branch node in existing DAG
    STANDALONE_SESSION = "standalone_session"  # New session: forks an independent isolated session clone


@dataclass(slots=True)
class SessionDagNode:
    """Represents an immutable message node inside the Conversation DAG."""

    node_id: str
    parent_id: str | None
    children_ids: list[str] = field(default_factory=list)
    branch_id: str = "main"
    role: str = "user"
    content: str = ""
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float | bool | list[str] | dict[str, str | int | float | bool] | None]:
        """Serializes DAG node to dictionary representation."""
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "children_ids": list(self.children_ids),
            "branch_id": self.branch_id,
            "role": self.role,
            "content": self.content,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, str | int | float | bool | list[str] | dict[str, str | int | float | bool] | None],
    ) -> SessionDagNode:
        """Constructs a DAG node from dictionary representation."""
        raw_children = data.get("children_ids")
        children_ids: list[str] = [str(c) for c in raw_children] if isinstance(raw_children, list) else []

        raw_meta = data.get("metadata")
        metadata: dict[str, str | int | float | bool] = {}
        if isinstance(raw_meta, dict):
            for k, v in raw_meta.items():
                if isinstance(v, (str, int, float, bool)):
                    metadata[str(k)] = v

        return cls(
            node_id=str(data.get("node_id", "")),
            parent_id=str(data["parent_id"]) if data.get("parent_id") is not None else None,
            children_ids=children_ids,
            branch_id=str(data.get("branch_id", "main")),
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            metadata=metadata,
            created_at=float(data.get("created_at", 0.0)),
        )


@dataclass(slots=True)
class BranchNavigatorMeta:
    """Metadata payload powering the UI branch selector (< current/total >)."""

    node_id: str
    branch_id: str
    branch_index: int  # 1-indexed (e.g. 2 in < 2/3 >)
    total_branches: int  # Total siblings under same parent
    sibling_node_ids: list[str]
    has_children: bool


@dataclass(slots=True)
class StandaloneForkResult:
    """Summary of a New-Session-From-Here independent fork operation."""

    new_session_id: str
    origin_session_id: str
    forked_from_node_id: str
    copied_nodes_count: int
    active_leaf_node_id: str
    linear_history_preview: list[str]
