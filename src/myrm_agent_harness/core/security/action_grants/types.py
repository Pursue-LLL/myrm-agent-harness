"""Type definitions for Scoped Time-Bounded Action Grant Registry and Trust Budget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GrantEvaluationStatus = Literal[
    "granted",
    "expired",
    "exhausted",
    "revoked",
    "mismatch_agent",
    "not_found",
]


@dataclass(slots=True, frozen=True)
class ActionGrantRecord:
    """Four-dimensional scoped action grant bound to a specific agent.

    Dimensions: service x action x transaction x time_window.
    Bound strictly to agent_id as mandatory security prerequisite.
    """

    grant_id: str
    agent_id: str
    service: str
    action: str
    transaction: str
    valid_from: float
    expires_at: float
    max_uses: int | None = None
    used_count: int = 0
    is_revoked: bool = False
    revocation_reason: str | None = None
    created_at: float = 0.0


@dataclass(slots=True, frozen=True)
class GrantEvaluationResult:
    """Evaluation outcome when testing if an agent invocation matches an active grant."""

    is_granted: bool
    status: GrantEvaluationStatus
    grant_id: str | None
    reason: str


@dataclass(slots=True, frozen=True)
class TrustBudgetRecord:
    """Cumulative trust budget per agent x service x action to counteract approval fatigue."""

    agent_id: str
    service: str
    action: str
    consecutive_approvals: int = 0
    is_locked_to_ask: bool = False
    last_demoted_at: float | None = None
    demotion_reason: str | None = None
