"""Cost-performance arbitrage router with complexity heuristic analyzer.

[INPUT]
- arbitrage_types: ComplexityScore, RoutingDecision, ModelArbitrageTier,
  CostSavingsRecord, WorkspaceArbitrageConfig.

[OUTPUT]
- ComplexityHeuristicAnalyzer: Evaluates prompt complexity across dimensions.
- CostPerformanceArbitrageRouter: Routes to L1 or L2 tiers with dynamic promotion.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.workspace_arbitrage
- Module: cost_performance_arbitrage_router.py
"""

from typing import Dict, List, Optional, Sequence
from myrm_agent_harness.agent.context_management.workspace_arbitrage.arbitrage_types import (
    ComplexityScore,
    CostSavingsRecord,
    ModelArbitrageTier,
    RoutingDecision,
    WorkspaceArbitrageConfig,
)


class ComplexityHeuristicAnalyzer:
    """Multi-dimensional heuristic analyzer evaluating prompt execution complexity."""

    _DEEP_REASONING_KEYWORDS = (
        "architect",
        "architecture",
        "refactor",
        "reconciliation",
        "distributed",
        "benchmark",
        "concurrency",
        "deadlock",
        "cryptographic",
        "optimize complexity",
        "formal verification",
    )

    _CODE_HEAVY_MARKERS = (
        "def ",
        "class ",
        "async def ",
        "import ",
        "function ",
        "interface ",
        "```python",
        "```typescript",
        "```go",
        "```rust",
    )

    def analyze(self, prompt: str) -> ComplexityScore:
        """Analyzes the given user prompt and computes a deterministic complexity score.

        Args:
            prompt: The raw user prompt string.

        Returns:
            A ComplexityScore instance between 0.0 (trivial) and 1.0 (extreme).
        """
        prompt_lower = prompt.lower()
        score = 0.15  # baseline score for conversational interaction
        reasons: List[str] = []

        is_code = any(marker in prompt for marker in self._CODE_HEAVY_MARKERS)
        if is_code:
            score += 0.35
            reasons.append("Contains structured code markers or syntax snippets.")

        matched_reasoning = [
            kw for kw in self._DEEP_REASONING_KEYWORDS if kw in prompt_lower
        ]
        if matched_reasoning:
            boost = min(0.40, 0.15 * len(matched_reasoning))
            score += boost
            reasons.append(f"Contains deep reasoning keywords: {', '.join(matched_reasoning[:3])}.")

        is_multi_step = any(
            phrase in prompt_lower
            for phrase in ("step by step", "first, then", "multi-phase", "workflow plan")
        )
        if is_multi_step:
            score += 0.20
            reasons.append("Requests multi-step phased workflow planning.")

        # Length factor: long, complex instructions demand higher reasoning
        length = len(prompt)
        if length > 2000:
            score += 0.15
            reasons.append("Prompt payload length exceeds 2000 characters.")
        elif length < 60:
            score -= 0.10
            reasons.append("Very short prompt likely for simple query or conversational turn.")

        composite = max(0.0, min(1.0, round(score, 3)))
        return ComplexityScore(
            composite_score=composite,
            reasons=tuple(reasons),
            is_code_heavy=is_code,
            is_multi_step_planning=is_multi_step,
        )


class CostPerformanceArbitrageRouter:
    """Intelligently routes requests across model tiers to maximize cost efficiency."""

    def __init__(self, config: Optional[WorkspaceArbitrageConfig] = None) -> None:
        self._config = config or WorkspaceArbitrageConfig()
        self._analyzer = ComplexityHeuristicAnalyzer()
        self._savings_records: Dict[str, List[CostSavingsRecord]] = {}

    def route_prompt(
        self,
        prompt: str,
        session_id: str,
        forced_tier: Optional[ModelArbitrageTier] = None,
    ) -> RoutingDecision:
        """Determines the optimal model tier for the given prompt.

        Args:
            prompt: User prompt content.
            session_id: Active session identifier.
            forced_tier: Optional user explicit override.

        Returns:
            A RoutingDecision specifying the selected tier and model.
        """
        complexity = self._analyzer.analyze(prompt)
        estimated_tokens = max(50, len(prompt) // 4)

        if forced_tier is not None:
            tier = forced_tier
            target_model = (
                self._config.l1_default_model
                if tier == ModelArbitrageTier.L1_FAST_LOCAL
                else self._config.l2_default_model
            )
            return RoutingDecision(
                selected_tier=tier,
                target_model_name=target_model,
                estimated_input_tokens=estimated_tokens,
                complexity=complexity,
                promoted_from_l1=False,
                decision_reason=f"User forced tier override to {tier.value}.",
            )

        if complexity.composite_score >= self._config.complexity_threshold_for_l2:
            tier = ModelArbitrageTier.L2_FLAGSHIP_REASONING
            target_model = self._config.l2_default_model
            reason = (
                f"Complexity score ({complexity.composite_score:.2f}) meets or exceeds L2 threshold "
                f"({self._config.complexity_threshold_for_l2:.2f})."
            )
        else:
            tier = ModelArbitrageTier.L1_FAST_LOCAL
            target_model = self._config.l1_default_model
            reason = (
                f"Complexity score ({complexity.composite_score:.2f}) is below L2 threshold; "
                f"routed to fast economic tier."
            )

        return RoutingDecision(
            selected_tier=tier,
            target_model_name=target_model,
            estimated_input_tokens=estimated_tokens,
            complexity=complexity,
            promoted_from_l1=False,
            decision_reason=reason,
        )

    def evaluate_promotion(
        self,
        current_decision: RoutingDecision,
        consecutive_tool_failures: int = 0,
        unmet_expectations: bool = False,
    ) -> RoutingDecision:
        """Evaluates whether an active L1 turn requires zero-loss dynamic promotion to L2.

        Args:
            current_decision: Existing routing decision.
            consecutive_tool_failures: Count of failures encountered in tool execution.
            unmet_expectations: Flag indicating response fell short of structural requirements.

        Returns:
            An upgraded RoutingDecision if promotion conditions are met, or unchanged.
        """
        if current_decision.selected_tier == ModelArbitrageTier.L2_FLAGSHIP_REASONING:
            return current_decision  # Already at top tier

        should_promote = consecutive_tool_failures >= 2 or unmet_expectations
        if not should_promote:
            return current_decision

        return RoutingDecision(
            selected_tier=ModelArbitrageTier.L2_FLAGSHIP_REASONING,
            target_model_name=self._config.l2_default_model,
            estimated_input_tokens=current_decision.estimated_input_tokens,
            complexity=current_decision.complexity,
            promoted_from_l1=True,
            decision_reason=(
                f"Dynamically promoted from L1 to L2: tool_failures={consecutive_tool_failures}, "
                f"unmet_expectations={unmet_expectations}."
            ),
        )

    def record_arbitrage_savings(
        self,
        session_id: str,
        total_tokens: int,
        actual_tier: ModelArbitrageTier,
    ) -> CostSavingsRecord:
        """Calculates and logs financial savings compared to unconditional flagship tier usage.

        Args:
            session_id: The session identifier.
            total_tokens: Tokens processed in this turn.
            actual_tier: The tier actually utilized.

        Returns:
            The immutable CostSavingsRecord for telemetry and dashboard rendering.
        """
        baseline_cost = round(
            (total_tokens / 1000.0) * self._config.baseline_l2_price_per_1k_tokens, 6
        )
        if actual_tier == ModelArbitrageTier.L1_FAST_LOCAL:
            actual_cost = round(
                (total_tokens / 1000.0) * self._config.l1_price_per_1k_tokens, 6
            )
        else:
            actual_cost = baseline_cost

        saved = max(0.0, round(baseline_cost - actual_cost, 6))
        saving_ratio = round(saved / baseline_cost, 4) if baseline_cost > 0.0 else 0.0

        record = CostSavingsRecord(
            session_id=session_id,
            l1_actual_cost_usd=actual_cost,
            baseline_l2_cost_usd=baseline_cost,
            saved_usd=saved,
            saving_ratio=saving_ratio,
        )

        if session_id not in self._savings_records:
            self._savings_records[session_id] = []
        self._savings_records[session_id].append(record)
        return record

    def get_session_savings_summary(self, session_id: str) -> Dict[str, float]:
        """Returns aggregated savings metrics for a session."""
        records = self._savings_records.get(session_id, [])
        total_saved = sum(r.saved_usd for r in records)
        total_actual = sum(r.l1_actual_cost_usd for r in records)
        total_baseline = sum(r.baseline_l2_cost_usd for r in records)
        overall_ratio = (
            round(total_saved / total_baseline, 4) if total_baseline > 0.0 else 0.0
        )
        return {
            "total_saved_usd": round(total_saved, 4),
            "total_actual_cost_usd": round(total_actual, 4),
            "total_baseline_cost_usd": round(total_baseline, 4),
            "overall_saving_ratio": overall_ratio,
        }
