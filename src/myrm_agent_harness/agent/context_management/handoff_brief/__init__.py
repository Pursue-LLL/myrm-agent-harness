"""Package facade for handoff brief.

[INPUT]
- agent.context_management.handoff_brief.handoff_brief_bridge::StandardizedAgentHandoffBridge (POS: Gateway
  orchestrating structured handoff briefs and cross-session state continuity.)
- agent.context_management.handoff_brief.handoff_brief_types::DecisionItem, DelegationRoleKind, HandoffBrief,
  HandoffIngressResult (POS: Types and models for handoff brief.)

[OUTPUT]
- Re-exports: DecisionItem, DelegationRoleKind, HandoffBrief, HandoffIngressResult,
  StandardizedAgentHandoffBridge

[POS]
Package facade for handoff brief.
"""

# ============================================================================
# Standardized Agent Handoff Brief & Continuity Bridge Package (Item 170)
# ============================================================================

from .handoff_brief_bridge import StandardizedAgentHandoffBridge
from .handoff_brief_types import (
    DecisionItem,
    DelegationRoleKind,
    HandoffBrief,
    HandoffIngressResult,
)

__all__ = [
    "DecisionItem",
    "DelegationRoleKind",
    "HandoffBrief",
    "HandoffIngressResult",
    "StandardizedAgentHandoffBridge",
]
