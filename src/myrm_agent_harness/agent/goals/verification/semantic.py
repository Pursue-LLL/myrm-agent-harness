"""Semantic assertion acceptance criterion.

[INPUT]
- .base::BaseCriterion, VerificationResult (POS: Base classes)
- protocol::GoalProvider (POS: Goal lifecycle provider)

[OUTPUT]
- SemanticCriterion: Verifies success using LLM as a judge.

[POS]
Provides LLM-based logic verification for non-deterministic or formatting goals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from myrm_agent_harness.agent.goals.verification.base import (
    BaseCriterion,
    VerificationResult,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider


class SemanticCriterion(BaseCriterion):
    """Verifies completion by evaluating an artifact or outcome using an LLM judge."""

    def __init__(self, criteria: str, target_file: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.criteria = criteria
        self.target_file = target_file

    async def verify(self, goal_provider: GoalProvider | None = None) -> VerificationResult:
        if not goal_provider:
            return VerificationResult(
                passed=False,
                criterion_label=self.criteria,
                reason="System Error: GoalProvider not injected. Cannot run semantic evaluation.",
                error_logs="Missing GoalProvider reference.",
            )

        content_to_verify = ""
        if self.target_file:
            from myrm_agent_harness.toolkits.code_execution.executors.base import (
                get_executor,
            )

            executor = get_executor()
            if executor:
                exists = await executor.file_exists(self.target_file)
                if not exists:
                    return VerificationResult(
                        passed=False,
                        criterion_label=self.criteria,
                        reason=f"Semantic check failed: Target file {self.target_file} does not exist.",
                        error_logs=f"File {self.target_file} not found in workspace.",
                    )
                content_to_verify = await executor.read_file(self.target_file)
            else:
                return VerificationResult(
                    passed=False,
                    criterion_label=self.criteria,
                    reason="System Error: Sandbox executor not found. Cannot read target file.",
                    error_logs="Missing execution environment.",
                )

        if not content_to_verify:
            content_to_verify = "(No specific file content provided. Evaluate based on general goal outcome.)"

        try:
            result = await goal_provider.evaluate_semantic(self.criteria, content_to_verify)
            result.criterion_label = self.criteria
            return result
        except Exception as e:
            return VerificationResult(
                passed=False,
                criterion_label=self.criteria,
                reason="Failed to execute semantic evaluation in Server.",
                error_logs=str(e),
            )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SemanticCriterion:
        return cls(
            criteria=str(data["criteria"]),
            target_file=str(data["target_file"]) if "target_file" in data else None,
        )
