"""Compaction A/B Evaluator — same-task forked continuation benchmark harness.

[INPUT]
- protocols::CompactionAssertion, CompactionFidelityScore (POS: compaction eval types)
- protocols::AgentResponse, EvalCase, EvalTurnResult (POS: agent execution models)
- compaction_assertions::evaluate_compaction_assertions (POS: 5D compaction assertion engine)

[OUTPUT]
- CompactionABResult: comparative A/B outcome (Baseline vs Compacted arms + Pareto savings)
- CompactionABEvaluator: orchestrates forked continuation comparison

[POS]
Provides the framework benchmark runner for comparing long-horizon agent execution
under Full-Context Baseline vs Active-Compaction Compacted arms on the same task.
Ensures zero amnesia and high decision fidelity across context window compaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .compaction_assertions import (
    canonicalize_tool_name,
    evaluate_compaction_assertions,
)
from .protocols import (
    AgentResponse,
    CompactionAssertion,
    CompactionFidelityScore,
)

if TYPE_CHECKING:
    from .protocols import JudgeConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CompactionABResult:
    """Outcome of a Same-Task Forked Compaction A/B Benchmark."""

    task_name: str
    baseline_response: AgentResponse
    compacted_response: AgentResponse
    fidelity_score: CompactionFidelityScore
    passed: bool
    details: str
    baseline_tokens: int = 0
    compacted_tokens: int = 0
    token_savings_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "passed": self.passed,
            "baseline_tokens": self.baseline_tokens,
            "compacted_tokens": self.compacted_tokens,
            "token_savings_pct": round(self.token_savings_pct, 2),
            "fidelity": self.fidelity_score.to_dict(),
            "details": self.details,
            "baseline_answer_snippet": (self.baseline_response.answer or "")[:150],
            "compacted_answer_snippet": (self.compacted_response.answer or "")[:150],
        }


class CompactionABEvaluator:
    """Evaluates compaction quality by comparing continuation outcomes on identical tasks."""

    def __init__(self, *, judge_config: JudgeConfig | None = None) -> None:
        self._judge_config = judge_config

    async def evaluate_continuation_ab(
        self,
        task_name: str,
        baseline_response: AgentResponse,
        compacted_response: AgentResponse,
        assertions: list[CompactionAssertion],
        *,
        baseline_context_tokens: int = 0,
        compacted_context_tokens: int = 0,
    ) -> CompactionABResult:
        """Compare the continuation response of the compacted arm against the baseline arm.

        Args:
            task_name: Identifier for the evaluation case.
            baseline_response: Response generated using the uncompacted full context.
            compacted_response: Response generated using the compacted context.
            assertions: Compaction assertions defining required constraints and artifacts.
            baseline_context_tokens: Total tokens in full context.
            compacted_context_tokens: Total tokens in compacted context.

        Returns:
            CompactionABResult containing the 5D fidelity breakdown and token savings.
        """
        # Calculate Token Savings Ratio
        if baseline_context_tokens > 0:
            saved = max(0, baseline_context_tokens - compacted_context_tokens)
            token_savings_pct = (saved / baseline_context_tokens) * 100.0
        else:
            token_savings_pct = 0.0

        scores_map: dict[str, float] = {}
        passed, details = await evaluate_compaction_assertions(
            assertions,
            compacted_response,
            scores_out=scores_map,
            judge_override=self._judge_config,
        )

        # Baseline comparative tool alignment check
        baseline_tools = {
            canonicalize_tool_name(
                str(
                    t.get("name") if isinstance(t, dict) else getattr(t, "name", str(t))
                )
            )
            for t in baseline_response.tools_called
        }
        compacted_tools = {
            canonicalize_tool_name(
                str(
                    t.get("name") if isinstance(t, dict) else getattr(t, "name", str(t))
                )
            )
            for t in compacted_response.tools_called
        }

        if baseline_tools:
            tool_overlap = len(baseline_tools & compacted_tools) / len(baseline_tools)
        else:
            tool_overlap = 1.0 if not compacted_tools else 0.8

        # Aggregate fidelity scores across multiple assertions if present
        def _avg_score(metric_key: str, default_val: float) -> float:
            vals = [v for k, v in scores_map.items() if k.endswith(metric_key)]
            return sum(vals) / len(vals) if vals else default_val

        avg_constraint = _avg_score("constraint_recall", 1.0)
        avg_decision = _avg_score("decision_fidelity", tool_overlap)
        avg_state = _avg_score("state_accuracy", 1.0)
        avg_artifact = _avg_score("artifact_coverage", 1.0)
        avg_overall = _avg_score("overall_fidelity", 1.0 if passed else 0.5)

        fidelity_score = CompactionFidelityScore(
            constraint_recall=round(avg_constraint, 4),
            decision_fidelity=round(avg_decision, 4),
            state_accuracy=round(avg_state, 4),
            artifact_coverage=round(avg_artifact, 4),
            continuation_success=1.0 if passed else 0.0,
            overall_fidelity=round(avg_overall, 4),
            token_savings_pct=token_savings_pct,
        )

        return CompactionABResult(
            task_name=task_name,
            baseline_response=baseline_response,
            compacted_response=compacted_response,
            fidelity_score=fidelity_score,
            passed=bool(passed),
            details=details or "",
            baseline_tokens=baseline_context_tokens,
            compacted_tokens=compacted_context_tokens,
            token_savings_pct=token_savings_pct,
        )
