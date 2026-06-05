"""Gatekeeper for orchestrating goal verifications.

[INPUT]
- .base::BaseCriterion, VerificationResult (POS: Base classes)
- .shell::ShellCriterion (POS: Shell command verifier)
- .semantic::SemanticCriterion (POS: LLM-based verifier)

[OUTPUT]
- VerificationGatekeeper: Orchestrator that parses rules and evaluates them.

[POS]
Acts as the central router and orchestrator for the verification phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.agent.goals.verification.base import (
    BaseCriterion,
    VerificationResult,
)
from myrm_agent_harness.agent.goals.verification.semantic import SemanticCriterion
from myrm_agent_harness.agent.goals.verification.shell import ShellCriterion

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider

CRITERION_REGISTRY = {
    "shell": ShellCriterion,
    "semantic": SemanticCriterion,
}


class VerificationGatekeeper:
    """Orchestrates goal verification based on configured criteria."""

    def __init__(self, criteria_configs: list[dict[str, object]]) -> None:
        self.criteria: list[BaseCriterion] = []
        for config in criteria_configs:
            crit_type = config.get("type")
            if crit_type in CRITERION_REGISTRY:
                cls = CRITERION_REGISTRY[crit_type]
                self.criteria.append(cls.from_dict(config))

    async def verify_all(self, goal_provider: GoalProvider | None = None) -> VerificationResult:
        """Run all criteria sequentially and aggregate errors."""
        if not self.criteria:
            return VerificationResult(passed=True)

        failed_reasons = []
        failed_logs = []

        for criterion in self.criteria:
            result = await criterion.verify(goal_provider)
            if not result.passed:
                failed_reasons.append(result.reason)
                failed_logs.append(result.error_logs)

        if failed_reasons:
            return VerificationResult(
                passed=False,
                reason="\n".join(failed_reasons),
                error_logs="\n\n---\n\n".join(failed_logs),
            )

        return VerificationResult(passed=True)
