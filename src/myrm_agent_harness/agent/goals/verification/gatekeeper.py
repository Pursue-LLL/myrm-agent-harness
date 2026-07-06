"""Gatekeeper for orchestrating goal verifications.

[INPUT]
- .base::BaseCriterion, VerificationResult, AggregatedVerificationResult (POS: Base classes)
- .shell::ShellCriterion (POS: Shell command verifier)
- .semantic::SemanticCriterion (POS: LLM-based verifier)

[OUTPUT]
- VerificationGatekeeper: Orchestrator that parses rules and evaluates them.

[POS]
Acts as the central router and orchestrator for the verification phase.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.goals.verification.base import (
    AggregatedVerificationResult,
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

    async def verify_all(self, goal_provider: GoalProvider | None = None) -> AggregatedVerificationResult:
        """Run all criteria sequentially and return per-criterion results."""
        if not self.criteria:
            return AggregatedVerificationResult(passed=True)

        results: list[VerificationResult] = []
        all_passed = True

        for criterion in self.criteria:
            start = time.perf_counter()
            result = await criterion.verify(goal_provider)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            result.duration_ms = elapsed_ms
            results.append(result)
            if not result.passed:
                all_passed = False

        return AggregatedVerificationResult(passed=all_passed, per_criterion=results)
