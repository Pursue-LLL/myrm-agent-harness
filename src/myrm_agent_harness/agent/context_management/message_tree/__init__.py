"""Package facade for message tree.

[INPUT]
- agent.context_management.message_tree.in_place_message_tree_engine::InPlaceMessageTreeEngine (POS: Manages
  in-place branching, sibling version switching, and path resolution.)
- agent.context_management.message_tree.message_tree_types::MessageTreeGraph, SiblingVersionItem,
  TreeMessageNode, TreeNodeRole, VersionSwitchResult (POS: Types and models for message tree.)

[OUTPUT]
- Re-exports: InPlaceMessageTreeEngine, MessageTreeGraph, SiblingVersionItem, TreeMessageNode, TreeNodeRole,
  VersionSwitchResult

[POS]
Package facade for message tree.
"""

# ============================================================================
# In-Place Message Tree Branching & Version Navigator Package (Item 164)
# ============================================================================

from .in_place_message_tree_engine import InPlaceMessageTreeEngine
from .message_tree_types import (
    MessageTreeGraph,
    SiblingVersionItem,
    TreeMessageNode,
    TreeNodeRole,
    VersionSwitchResult,
)

__all__ = [
    "InPlaceMessageTreeEngine",
    "MessageTreeGraph",
    "SiblingVersionItem",
    "TreeMessageNode",
    "TreeNodeRole",
    "VersionSwitchResult",
]
