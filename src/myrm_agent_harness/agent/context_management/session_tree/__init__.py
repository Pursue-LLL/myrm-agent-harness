"""Package facade for session tree.

[INPUT]
- agent.context_management.session_tree.session_tree_rewind_engine::SessionTreeRewindEngine (POS: Manages
  session timeline branching, message cloning, and in-place rewind.)
- agent.context_management.session_tree.session_tree_types::ForkModeKind, ForkResult, RewindModeKind,
  RewindResult, SessionBranchNode, SessionMessageItem, SessionTreeTopology (POS: Types and models for session
  tree.)

[OUTPUT]
- Re-exports: ForkModeKind, ForkResult, RewindModeKind, RewindResult, SessionBranchNode, SessionMessageItem,
  SessionTreeRewindEngine, SessionTreeTopology

[POS]
Package facade for session tree.
"""

# ============================================================================
# Session Tree Fork & Message Rewind Package (Item 162)
# ============================================================================

from .session_tree_rewind_engine import SessionTreeRewindEngine
from .session_tree_types import (
    ForkModeKind,
    ForkResult,
    RewindModeKind,
    RewindResult,
    SessionBranchNode,
    SessionMessageItem,
    SessionTreeTopology,
)

__all__ = [
    "ForkModeKind",
    "ForkResult",
    "RewindModeKind",
    "RewindResult",
    "SessionBranchNode",
    "SessionMessageItem",
    "SessionTreeRewindEngine",
    "SessionTreeTopology",
]
