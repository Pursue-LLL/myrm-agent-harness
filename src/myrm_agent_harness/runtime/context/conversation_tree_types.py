"""Type definitions for tree-structured conversation graph and branch replay engine.

Inspired by Pi Agent Tree History architecture. Provides data models for
in-session DAG nodes, branching paths, bookmarks, and export formats.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- TreeNodeKind: Semantic kind of a conversation node in the tree.
- TreeExportFormat: Format options for exporting the conversation graph.
- TreeBookmark: Bookmark metadata pinning an important architectural or decision node.
- ConversationTreeNode: An immutable node in the in-session DAG conversation tree.
- BranchPathInfo: Summary of a specific branch path in the conversation graph.
- TreeFilterCriteria: Criteria for filtering conversation tree nodes.

[POS]
Type definitions for tree-structured conversation graph and branch replay engine.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class TreeNodeKind(StrEnum):
    """Semantic kind of a conversation node in the tree."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REASONING = "reasoning"
    SYSTEM = "system"


class TreeExportFormat(StrEnum):
    """Format options for exporting the conversation graph."""

    INTERACTIVE_HTML = "interactive_html"
    JSON_DAG = "json_dag"
    MARKDOWN_OUTLINE = "markdown_outline"


@dataclass(frozen=True)
class TreeBookmark:
    """Bookmark metadata pinning an important architectural or decision node."""

    node_id: str
    title: str
    note: str
    created_at: float


@dataclass(frozen=True)
class ConversationTreeNode:
    """An immutable node in the in-session DAG conversation tree."""

    node_id: str
    parent_id: str | None
    children_ids: list[str] = field(default_factory=list)
    kind: TreeNodeKind = TreeNodeKind.USER
    role: str = "user"
    content: str = ""
    timestamp: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)
    is_bookmarked: bool = False
    bookmark_note: str = ""


@dataclass(frozen=True)
class BranchPathInfo:
    """Summary of a specific branch path in the conversation graph."""

    leaf_id: str
    path_length: int
    root_to_leaf_ids: list[str]
    branch_name: str
    leaf_preview: str


@dataclass(frozen=True)
class TreeFilterCriteria:
    """Criteria for filtering conversation tree nodes."""

    include_kinds: set[TreeNodeKind] | None = None
    min_timestamp: float | None = None
    only_bookmarked: bool = False
