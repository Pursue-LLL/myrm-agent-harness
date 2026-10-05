"""Attribution Health Matrix Evaluator computing production governance metrics."""

from collections.abc import Sequence

from .models import (
    FilterDiscardReason,
    FourDimensionHealthReport,
    MemoryAttributionTrace,
)


class AttributionHealthMatrixEvaluator:
    """Evaluates batches of memory attribution traces across four production dimensions."""

    def evaluate_traces(
        self,
        traces: Sequence[MemoryAttributionTrace],
    ) -> FourDimensionHealthReport:
        """Compute four-dimensional production metrics across traces.

        Dimensions:
            1. Recall Quality (retained ratio and candidate health)
            2. Task Outcome (adoption rate of injected memories in final answer)
            3. Cost & Latency (token overhead per cited memory)
            4. Safety & Governance (compliance and policy violations avoided)

        Args:
            traces: Sequence of completed MemoryAttributionTrace objects.

        Returns:
            Comprehensive FourDimensionHealthReport.
        """
        if not traces:
            return FourDimensionHealthReport(
                total_traces_analyzed=0,
                recall_quality_score=1.0,
                task_outcome_adoption_rate=1.0,
                cost_overhead_token_ratio=0.0,
                safety_governance_score=1.0,
                recommendations=["No traces recorded yet; monitoring pipeline active."],
            )

        total_candidates = 0
        total_injected = 0
        total_tokens = 0
        total_cited = 0
        policy_blocked_count = 0

        for t in traces:
            total_candidates += len(t.candidate_recalls)
            total_injected += len(t.prompt_injections)
            total_tokens += sum(inj.token_count for inj in t.prompt_injections)
            total_cited += len(t.model_citations)

            for disc in t.discarded_items:
                if disc.discard_reason in (
                    FilterDiscardReason.POLICY_BLOCKED,
                    FilterDiscardReason.SCOPE_MISMATCH,
                ):
                    policy_blocked_count += 1

        # 1. Recall Quality Score
        if total_candidates > 0:
            recall_quality = min(1.0, max(0.0, total_injected / total_candidates))
        else:
            recall_quality = 1.0

        # 2. Task Outcome Adoption Rate
        if total_injected > 0:
            adoption_rate = min(1.0, max(0.0, total_cited / total_injected))
        else:
            adoption_rate = 1.0 if total_cited > 0 else 0.0

        # 3. Cost Overhead Token Ratio
        token_ratio = float(total_tokens) / max(1, total_cited)

        # 4. Safety Governance Score
        if total_candidates > 0:
            safety_score = max(0.0, 1.0 - (policy_blocked_count / total_candidates))
        else:
            safety_score = 1.0

        # 5. Diagnostic Recommendations
        recommendations: list[str] = []
        if adoption_rate < 0.3 and total_injected > 0:
            recommendations.append(
                f"Low citation adoption ({adoption_rate:.1%}): Model utilizes few injected "
                f"memories. Consider tightening similarity threshold to prune irrelevant context."
            )
        if token_ratio > 500.0:
            recommendations.append(
                f"High token overhead ({token_ratio:.0f} tokens/citation): Memory injection "
                f"consumes excessive prompt budget relative to cited facts."
            )
        if policy_blocked_count > 0:
            recommendations.append(
                f"Security alerts ({policy_blocked_count} boundary/policy rejections): "
                f"Inspect upstream retrieval filters for cross-tenant scope leakage attempts."
            )
        if not recommendations:
            recommendations.append(
                "Memory retrieval and attribution metrics are operating within healthy production bounds."
            )

        return FourDimensionHealthReport(
            total_traces_analyzed=len(traces),
            recall_quality_score=round(recall_quality, 4),
            task_outcome_adoption_rate=round(adoption_rate, 4),
            cost_overhead_token_ratio=round(token_ratio, 2),
            safety_governance_score=round(safety_score, 4),
            recommendations=recommendations,
        )
