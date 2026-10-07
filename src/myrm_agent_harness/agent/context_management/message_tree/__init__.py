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
