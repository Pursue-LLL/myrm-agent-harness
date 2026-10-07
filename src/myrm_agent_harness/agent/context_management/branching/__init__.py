"""Package facade for branching.

[INPUT]
- agent.context_management.branching.branch_carrier_types::AbandonedBranchLessonsSummary,
  BranchCarrierForkRequest, BranchCarrierForkResponse, TreeNodeView (POS: Types and models for branch
  carrier.)
- agent.context_management.branching.branch_summary_carrier_engine::BranchSummaryCarrierEngine (POS: Distills
  trial-and-error lessons from abandoned branches to roam into new forks.)
- agent.context_management.branching.session_dag_graph::SessionDagGraph (POS: Manages conversational messages
  structured as a Directed Acyclic Graph (DAG).)
- agent.context_management.branching.session_dag_types::BranchForkMode, BranchNavigatorMeta, SessionDagNode,
  StandaloneForkResult (POS: Types and models for session dag.)

[OUTPUT]
- Re-exports: AbandonedBranchLessonsSummary, BranchCarrierForkRequest, BranchCarrierForkResponse,
  BranchForkMode, BranchNavigatorMeta, BranchSummaryCarrierEngine, SessionDagGraph, SessionDagNode,
  StandaloneForkResult, TreeNodeView

[POS]
Package facade for branching.
"""

# ============================================================================
# # Conversation DAG Branching Engine (Item 144)
# ============================================================================

from .branch_carrier_types import (
    AbandonedBranchLessonsSummary,
    BranchCarrierForkRequest,
    BranchCarrierForkResponse,
    TreeNodeView,
)
from .branch_summary_carrier_engine import BranchSummaryCarrierEngine
from .session_dag_graph import SessionDagGraph
from .session_dag_types import (
    BranchForkMode,
    BranchNavigatorMeta,
    SessionDagNode,
    StandaloneForkResult,
)

__all__ = [
    "AbandonedBranchLessonsSummary",
    "BranchCarrierForkRequest",
    "BranchCarrierForkResponse",
    "BranchForkMode",
    "BranchNavigatorMeta",
    "BranchSummaryCarrierEngine",
    "SessionDagGraph",
    "SessionDagNode",
    "StandaloneForkResult",
    "TreeNodeView",
]
