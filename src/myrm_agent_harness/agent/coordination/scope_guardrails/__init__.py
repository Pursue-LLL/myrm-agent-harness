"""Orchestrator Scope Guardrails and Safe Team Design Mode module (Item 37).

[INPUT]
- Candidate team roles with requested tools and SafeTeamDesignConfig settings.

[OUTPUT]
- ScopeGuardrailsEngine, SafeTeamDesignConfig, MemberScopeCandidate, and TeamGuardrailsEvaluationResult.

[POS]
- Harness coordination layer public API for least-privilege role boundaries and fan-out defense.
"""

from __future__ import annotations

from myrm_agent_harness.agent.coordination.scope_guardrails.guardrails_engine import (
    ScopeGuardrailsEngine,
)
from myrm_agent_harness.agent.coordination.scope_guardrails.types import (
    MemberScopeCandidate,
    SafeTeamDesignConfig,
    ScopeViolationFinding,
    TeamGuardrailsEvaluationResult,
    ViolationSeverity,
    ViolationType,
)

__all__ = [
    "MemberScopeCandidate",
    "SafeTeamDesignConfig",
    "ScopeGuardrailsEngine",
    "ScopeViolationFinding",
    "TeamGuardrailsEvaluationResult",
    "ViolationSeverity",
    "ViolationType",
]
