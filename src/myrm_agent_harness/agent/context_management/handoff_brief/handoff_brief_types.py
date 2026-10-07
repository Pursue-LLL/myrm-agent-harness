"""Types and models for handoff brief.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- DelegationRoleKind: Specialized target agent profile for role-scoped handoff delegation.
- DecisionItem: Explicit technical or business decision captured with rationale.
- HandoffBrief: Standardized cross-session handoff brief preserving state and decisions.
- HandoffIngressResult: Result of importing a handoff brief into a target session context.

[POS]
Types and models for handoff brief.
"""

# ============================================================================
# Standardized Agent Handoff Brief & Continuity Bridge Contracts (Item 170)
# Strong typing contracts for cross-session/cross-agent handoff briefs, structured
# architectural decisions (what & why), blockers, and state continuity injection.
# ============================================================================

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DelegationRoleKind(str, Enum):
    """Specialized target agent profile for role-scoped handoff delegation."""

    GENERAL_AGENT = "general_agent"
    CODE_AUDITOR = "code_auditor"
    FRONTEND_SPECIALIST = "frontend_specialist"
    INFRA_OPS = "infra_ops"


@dataclass(frozen=True, slots=True)
class DecisionItem:
    """Explicit technical or business decision captured with rationale."""

    what: str
    why: str
    category: str = "architecture"


@dataclass(frozen=True, slots=True)
class HandoffBrief:
    """Standardized cross-session handoff brief preserving state and decisions."""

    brief_id: str
    source_session_id: str
    task_goal: str
    completed_steps: tuple[str, ...]
    blocked_points: tuple[str, ...]
    decisions: tuple[DecisionItem, ...]
    relevant_files: tuple[str, ...]
    env_dependencies: Mapping[str, str]
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class HandoffIngressResult:
    """Result of importing a handoff brief into a target session context."""

    target_session_id: str
    brief_id: str
    source_session_id: str
    injected_xml_context: str
    injected_token_estimate: int
    applied_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
