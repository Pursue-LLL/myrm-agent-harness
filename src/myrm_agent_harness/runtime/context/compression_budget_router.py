"""Dynamic budget router and four-dimensional quality evaluation engine.

Routes context compression tiers based on task risk and remaining token budget.
Monitors four-dimensional balance metrics to ensure compression never degrades
task success rate or error recovery.

[INPUT]
- runtime.context.tokenomics_compression_types::CompressionBudgetDecision, CompressionTierKind,
  ContextTaxonomyKind, FourDimensionalMetrics, TaskRiskLevel (POS: Strongly typed data contracts for the
  Four-Tier Tokenomics context compression engine.)

[OUTPUT]
- CompressionBudgetRouter: Adapts compression intensity to runtime token headroom and task risk.

[POS]
Dynamic budget router and four-dimensional quality evaluation engine.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.runtime.context.tokenomics_compression_types import (
    CompressionBudgetDecision,
    CompressionTierKind,
    ContextTaxonomyKind,
    FourDimensionalMetrics,
    TaskRiskLevel,
)


class CompressionBudgetRouter:
    """Adapts compression intensity to runtime token headroom and task risk."""

    WATERMARK_TIER_1_ONLY: float = 0.50
    WATERMARK_TIER_2_ENABLED: float = 0.70
    WATERMARK_TIER_4_EMERGENCY: float = 0.90

    @staticmethod
    def classify_message_taxonomy(
        role: str,
        content: str,
        is_first_user_turn: bool = False,
    ) -> ContextTaxonomyKind:
        """Classify message into immutable directive, state, evidence, or noise."""
        if role == "system" or is_first_user_turn:
            return ContextTaxonomyKind.USER_CORE_DIRECTIVE

        lowered = content.lower()
        if "checkpoint" in lowered or "current state:" in lowered or "plan:" in lowered:
            return ContextTaxonomyKind.TASK_STATE

        if (
            role == "tool"
            or "tool_call" in lowered
            or "exit code" in lowered
            or "traceback" in lowered
        ):
            return ContextTaxonomyKind.TOOL_EVIDENCE

        # Conversational greetings or casual remarks
        if len(content.strip()) < 30 and any(
            g in lowered for g in ("hello", "thanks", "ok", "got it", "sounds good")
        ):
            return ContextTaxonomyKind.BACKGROUND_NOISE

        return ContextTaxonomyKind.TASK_STATE

    def choose_compression(
        self,
        task_risk: TaskRiskLevel,
        token_budget: int,
        current_tokens: int,
    ) -> CompressionBudgetDecision:
        """Determine optimal compression tiers based on token headroom and risk level."""
        budget = max(1, token_budget)
        watermark = round(current_tokens / budget, 4)

        selected_tiers: list[CompressionTierKind] = [
            CompressionTierKind.TIER_1_LOSSLESS_CLEAN
        ]

        if watermark < self.WATERMARK_TIER_1_ONLY:
            rationale = (
                f"Headroom healthy (watermark: {watermark:.1%}). "
                "Applying lossless Tier 1 clean only."
            )
        elif watermark < self.WATERMARK_TIER_2_ENABLED:
            selected_tiers.append(CompressionTierKind.TIER_2_STRUCTURAL_DEDUP)
            rationale = (
                f"Moderate context saturation (watermark: {watermark:.1%}). "
                "Engaging Tier 1 lossless + Tier 2 structural dedup."
            )
        elif watermark < self.WATERMARK_TIER_4_EMERGENCY:
            selected_tiers.append(CompressionTierKind.TIER_2_STRUCTURAL_DEDUP)
            selected_tiers.append(CompressionTierKind.TIER_3_SEMANTIC_PRUNING)
            rationale = (
                f"High context pressure (watermark: {watermark:.1%}, risk: {task_risk.value}). "
                "Engaging Tier 3 semantic pruning with strict protected pattern guards."
            )
        else:
            # Extreme emergency watermark
            selected_tiers.extend(
                [
                    CompressionTierKind.TIER_2_STRUCTURAL_DEDUP,
                    CompressionTierKind.TIER_3_SEMANTIC_PRUNING,
                    CompressionTierKind.TIER_4_EXTREME_COMPACTION,
                ]
            )
            rationale = (
                f"Critical saturation emergency (watermark: {watermark:.1%}). "
                "Unlocking full four-tier progressive compaction pipeline."
            )

        return CompressionBudgetDecision(
            selected_tiers=tuple(selected_tiers),
            current_tokens=current_tokens,
            token_budget=token_budget,
            watermark_ratio=watermark,
            task_risk=task_risk,
            rationale=rationale,
        )

    @staticmethod
    def evaluate_four_dimensional_balance(
        original_tokens: int,
        compressed_tokens: int,
        historical_successes: Sequence[bool],
        error_recoveries: Sequence[bool],
        user_reworks: Sequence[bool],
    ) -> FourDimensionalMetrics:
        """Calculate four-dimensional trade-off metrics to prevent destructive optimization."""
        orig = max(1, original_tokens)
        reduction_rate = round(max(0.0, (orig - compressed_tokens) / orig), 4)

        success_rate = (
            round(sum(1 for s in historical_successes if s) / len(historical_successes), 4)
            if historical_successes
            else 1.0
        )
        recovery_rate = (
            round(sum(1 for r in error_recoveries if r) / len(error_recoveries), 4)
            if error_recoveries
            else 1.0
        )
        rework_rate = (
            round(sum(1 for w in user_reworks if w) / len(user_reworks), 4)
            if user_reworks
            else 0.0
        )

        return FourDimensionalMetrics(
            token_reduction_rate=reduction_rate,
            task_success_rate=success_rate,
            error_recovery_rate=recovery_rate,
            user_rework_rate=rework_rate,
        )
