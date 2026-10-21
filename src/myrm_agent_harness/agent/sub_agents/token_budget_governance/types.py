"""Types and models for One-Model Multi-Agent Shared Context Token Budget Governance (Item 52).

[INPUT]
- RoleBudgetSpec, ConsumptionRecord, GovernancePrecheckResult.

[OUTPUT]
- Typed data models: DoctorNudgeAlert, SharedTokenBudgetSnapshot.
- Custom exceptions: TokenBudgetError, BudgetExceededError, RoleBudgetNotFoundError.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

PrimitiveValue = str | int | float | bool | None
MetadataDict = dict[str, PrimitiveValue]


class ConsumptionCategory(StrEnum):
    """Categorization of token expenditure in multi-agent runs."""

    ROUTING_OVERHEAD = "routing_overhead"  # Intent classification, agent selection, orchestrator handoff
    EXECUTION_PAYLOAD = "execution_payload"  # Actual tool calls, artifact synthesis, code generation


class NudgeSeverity(StrEnum):
    """Severity of doctor budget and routing warnings."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RoleBudgetSpec:
    """Declared budget ceiling and stop condition for a specific agent role."""

    role_name: str
    token_ceiling: int
    stop_condition: str = "halt_and_report"  # halt_and_report, degrade_to_lightweight, prompt_user
    allow_overflow: bool = False


@dataclass(frozen=True)
class ConsumptionRecord:
    """An individual token consumption ledger entry."""

    record_id: str
    agent_role: str
    category: ConsumptionCategory
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    timestamp: float = field(default_factory=time.time)
    metadata: MetadataDict = field(default_factory=dict)


@dataclass(frozen=True)
class GovernancePrecheckResult:
    """Precheck outcome before fanning out tasks to subagents."""

    passed: bool
    requested_tokens: int
    remaining_budget: int
    reason: str


@dataclass(frozen=True)
class DoctorNudgeAlert:
    """Doctor alert raised when routing overhead or repetitive handoffs waste tokens."""

    alert_id: str
    severity: NudgeSeverity
    message: str
    handoff_count: int
    routing_ratio: float
    suggested_action: str
    created_at: float = field(default_factory=time.time)


@dataclass
class SharedTokenBudgetSnapshot:
    """Global governance snapshot across all subagents sharing the same primary model."""

    session_id: str
    primary_model: str
    shared_token_ceiling: int
    total_tokens_spent: int
    routing_tokens_spent: int
    execution_tokens_spent: int
    routing_ratio: float
    role_budgets: dict[str, RoleBudgetSpec]
    role_usage: dict[str, int]
    active_alerts: list[DoctorNudgeAlert]


class TokenBudgetError(Exception):
    """Base exception for token budget governance."""


class BudgetExceededError(TokenBudgetError):
    """Raised when an operation would exceed hard shared or role-scoped token ceilings."""


class RoleBudgetNotFoundError(TokenBudgetError):
    """Raised when query targets an unregistered agent role."""
