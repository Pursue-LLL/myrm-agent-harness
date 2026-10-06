"""Data contracts and types for Git-like non-linear session tree and branching engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SessionTreeEntryKind(StrEnum):
    """The polymorphic kind of an entry residing within the session tree."""

    MESSAGE = "message"  # Standard dialog turn (user, assistant, tool)
    COMPACTION_CHECKPOINT = "compaction_checkpoint"  # Context summarization checkpoint marker
    MODEL_SWITCH = "model_switch"  # Recorded model or provider transition
    BRANCH_LABEL = "branch_label"  # Named tag or branch checkpoint label


@dataclass(frozen=True)
class GitSessionTreeNode:
    """An immutable node in the non-linear session exploration tree."""

    node_id: str
    parent_id: str | None
    entry_kind: SessionTreeEntryKind
    role: str
    content: str
    created_at: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GitSessionBranchDescriptor:
    """Descriptor defining a named exploration branch within the session tree."""

    branch_name: str
    fork_node_id: str
    head_node_id: str
    created_at: float


@dataclass(frozen=True)
class SessionTreeTopology:
    """Exported topological overview of the non-linear session tree."""

    root_node_id: str
    active_head_id: str
    total_nodes: int
    total_branches: int
    branch_heads: dict[str, str]
