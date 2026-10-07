"""Immutable tree-structured session types and navigation models.

Defines schemas for parentId-linked append-only conversation trees,
non-destructive branch pointer navigation, divergence extraction,
and branch exploration summary records.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class TreeEntryKind(StrEnum):
    """Categorized kind of entry inside the immutable conversation tree."""

    MESSAGE = "message"
    TOOL_INVOCATION = "tool_invocation"
    COMPACTION_SUMMARY = "compaction_summary"
    BRANCH_SUMMARY = "branch_summary"
    CUSTOM_STATE = "custom_state"


@dataclass(frozen=True)
class TreeEntry:
    """An immutable entry in the append-only conversation tree linked via parent_id."""

    entry_id: str
    parent_id: str | None
    kind: TreeEntryKind
    role: str
    content: str
    branch_tag: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    created_at_ms: int = 0


@dataclass(frozen=True)
class BranchSummaryRecord:
    """Exploration insights and outcomes extracted from an abandoned branch."""

    summary_id: str
    fork_point_id: str
    abandoned_leaf_id: str
    summary_text: str
    key_insights: tuple[str, ...] = field(default_factory=tuple)
    abandoned_node_count: int = 0
    created_at_ms: int = 0


@dataclass(frozen=True)
class TreeProjection:
    """Linearized context projection along the ancestry chain from root to active leaf."""

    leaf_id: str
    path_entries: tuple[TreeEntry, ...]
    active_branch_tag: str | None = None
    total_entries_count: int = 0
