"""Model and Harness orthogonal decoupling with Total Cost-to-Outcome routing.

Model responsibilities: Understanding, reasoning, generation, action selection.
Harness responsibilities: Context assembly, tool exposure, state preservation,
permission enforcement, telemetry audit, retry self-healing, session management.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar

from myrm_agent_harness.runtime.context.multi_gateway_trust_types import (
    CostRoutingDecision,
    ModelCostProfile,
    TaskComplexity,
)


class ModelHarnessCostRouter:
    """Evaluates the true Total Cost-to-Outcome (TCO) for a given task complexity.

    Selects the optimal model based on expected retry penalty and success probability
    rather than naive token price alone.
    """

    HARNESS_CORE_MANDATE: str = (
        "Harness governs: context assembly, tool contracts, retry guardrails, "
        "and sandboxing. Model is strictly limited to reasoning and action selection."
    )

    COMPLEXITY_FAILURE_PENALTY: ClassVar[Mapping[TaskComplexity, float]] = {
        TaskComplexity.SIMPLE_LOOKUP: 0.0,
        TaskComplexity.STANDARD_TASK: 0.01,
        TaskComplexity.COMPLEX_REFACTOR: 0.06,
        TaskComplexity.DEEP_EXPLORATION: 0.12,
    }

    def __init__(
        self,
        candidate_models: Sequence[ModelCostProfile],
        retry_penalty_multiplier: float = 1.5,
    ) -> None:
        if not candidate_models:
            msg = "Candidate models sequence cannot be empty."
            raise ValueError(msg)
        self._candidates: dict[str, ModelCostProfile] = {
            m.model_id: m for m in candidate_models
        }
        self._retry_penalty_multiplier: float = max(1.0, retry_penalty_multiplier)

    def compute_expected_cost_to_outcome(
        self,
        profile: ModelCostProfile,
        complexity: TaskComplexity,
        estimated_input_k_tokens: float,
        estimated_output_k_tokens: float,
    ) -> tuple[float, float]:
        """Compute the expected total cost and expected attempts to achieve a successful outcome.

        Returns (expected_total_cost, expected_attempts).
        """
        # Adjust base success rate by task complexity
        if complexity in profile.complexity_success_rates:
            effective_rate = profile.complexity_success_rates[complexity]
        else:
            complexity_discount_map: Mapping[TaskComplexity, float] = {
                TaskComplexity.SIMPLE_LOOKUP: 1.0,
                TaskComplexity.STANDARD_TASK: 0.9,
                TaskComplexity.COMPLEX_REFACTOR: 0.75,
                TaskComplexity.DEEP_EXPLORATION: 0.6,
            }
            effective_rate = (
                profile.historical_success_rate
                * complexity_discount_map.get(complexity, 0.8)
            )

        effective_rate = max(0.05, min(1.0, effective_rate))

        expected_attempts = 1.0 / effective_rate
        single_run_token_cost = (
            profile.input_token_rate_per_k * estimated_input_k_tokens
            + profile.output_token_rate_per_k * estimated_output_k_tokens
        )

        # Retry penalty accounts for extra prompt re-assembly, tool rollback, and latency cost
        failed_attempts = max(0.0, expected_attempts - 1.0)
        token_retry_penalty = (
            single_run_token_cost * self._retry_penalty_multiplier * failed_attempts
        )
        engineering_failure_cost = (
            self.COMPLEXITY_FAILURE_PENALTY.get(complexity, 0.01) * failed_attempts
        )
        expected_total_cost = (
            (single_run_token_cost * expected_attempts)
            + token_retry_penalty
            + engineering_failure_cost
        )

        return round(expected_total_cost, 6), round(expected_attempts, 2)

    def route_task(
        self,
        complexity: TaskComplexity,
        estimated_input_k_tokens: float = 4.0,
        estimated_output_k_tokens: float = 1.0,
    ) -> CostRoutingDecision:
        """Route the task to the model with the minimum expected Total Cost-to-Outcome."""
        best_model_id: str = ""
        lowest_cost: float = float("inf")
        best_attempts: float = 1.0

        for m_id, profile in self._candidates.items():
            tco, attempts = self.compute_expected_cost_to_outcome(
                profile=profile,
                complexity=complexity,
                estimated_input_k_tokens=estimated_input_k_tokens,
                estimated_output_k_tokens=estimated_output_k_tokens,
            )
            if tco < lowest_cost:
                lowest_cost = tco
                best_model_id = m_id
                best_attempts = attempts

        rationale = (
            f"Selected '{best_model_id}' with expected TCO of ${lowest_cost:.4f} "
            f"(expected attempts: {best_attempts}) for {complexity.value} task."
        )

        return CostRoutingDecision(
            selected_model=best_model_id,
            estimated_total_cost=lowest_cost,
            expected_attempts=best_attempts,
            harness_responsibility=self.HARNESS_CORE_MANDATE,
            rationale=rationale,
        )
