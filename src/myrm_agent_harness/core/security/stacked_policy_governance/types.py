"""Type definitions for Three-Tier Stacked Policy Governance and Downgrade Gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PolicyTier = Literal["session", "agent", "server"]
PolicyDecision = Literal["allow", "deny", "ask"]
LifecyclePhase = Literal["request", "tool_call", "tool_result"]


@dataclass(slots=True, frozen=True)
class PolicyRule:
    """Individual declarative policy rule bound to a specific tier."""

    tier: PolicyTier
    name: str
    phase: LifecyclePhase
    action: PolicyDecision
    target_pattern: str  # Tool name or command wildcard pattern
    reason: str
    session_id: str | None = None
    agent_id: str | None = None


@dataclass(slots=True, frozen=True)
class AskCardPayload:
    """MCP-style interactive approval card data emitted upon ASK decision."""

    prompt_title: str
    target_operation: str
    risk_level: Literal["low", "medium", "high", "critical"]
    recommended_action: PolicyDecision
    context_summary: str


@dataclass(slots=True, frozen=True)
class PolicyEvaluationResult:
    """Outcome of evaluating request/tool_call against stacked policy tiers."""

    decision: PolicyDecision
    matched_tier: PolicyTier | None
    matched_rule: str | None
    reason: str
    requires_approval: bool = False
    ask_card: AskCardPayload | None = None


@dataclass(slots=True, frozen=True)
class DowngradeGateSpec:
    """Threshold configurations for Tokenomics Downgrade Gate."""

    soft_limit_tokens: int = 80000
    soft_limit_cost: float = 2.0
    hard_limit_cost: float = 10.0
    primary_model: str = "claude-3-7-sonnet"
    fallback_model: str = "gpt-4o-mini"


@dataclass(slots=True, frozen=True)
class DowngradeGateStatus:
    """Runtime status of Downgrade Gate evaluating current consumption."""

    is_downgraded: bool
    is_hard_blocked: bool
    active_model: str
    total_tokens: int
    total_cost: float
    message: str
    details: dict[str, str] = field(default_factory=dict)
