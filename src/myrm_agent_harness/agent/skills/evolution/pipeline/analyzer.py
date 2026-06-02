"""Lightweight execution analysis for skill evolution decisions.

[INPUT]
- agent.skills.evolution.core.types::ExecutionAnalysis, (POS: Data types for skill evolution system.)

[OUTPUT]
- EvolutionRecommendation: Evolution recommendation result.
- SkillExecutionAnalyzer: Analyzes execution history to recommend evolution actions.
- analyze_skill_for_evolution: Convenience function for quick skill analysis.

[POS]
Lightweight execution analysis for skill evolution decisions.
"""

import logging
from dataclasses import dataclass

from myrm_agent_harness.agent.skills.evolution.core.types import ExecutionAnalysis, SkillRecord

logger = logging.getLogger(__name__)


@dataclass
class EvolutionRecommendation:
    """Evolution recommendation result."""

    should_fix: bool
    should_derive: bool
    should_capture: bool
    confidence: float  # 0.0-1.0
    reasons: list[str]


class SkillExecutionAnalyzer:
    """Lightweight analyzer for skill execution patterns (收益6/10).

    Analyzes execution history to recommend evolution actions.
    Simplified from OpenSpace's complex pattern recognition.
    """

    def __init__(self, fix_threshold: float = 0.5, usage_min: int = 3):
        """Initialize analyzer.

        Args:
            fix_threshold: Success rate below this triggers FIX recommendation
            usage_min: Minimum usage count before analyzing
        """
        self.fix_threshold = fix_threshold
        self.usage_min = usage_min

    def analyze_skill(self, skill: SkillRecord) -> EvolutionRecommendation:
        """Analyze single skill for evolution opportunities.

        Args:
            skill: Skill to analyze

        Returns:
            Evolution recommendation with confidence and reasons
        """
        reasons: list[str] = []
        should_fix = False
        should_derive = False
        should_capture = False
        confidence = 0.0

        metrics = skill.metrics

        # Check if we have enough data
        if metrics.usage_count < self.usage_min:
            return EvolutionRecommendation(
                should_fix=False,
                should_derive=False,
                should_capture=False,
                confidence=0.0,
                reasons=["Insufficient usage data for analysis"],
            )

        # FIX recommendation
        if metrics.should_trigger_fix(self.fix_threshold):
            should_fix = True
            confidence = 0.9
            if metrics.consecutive_failures >= 3:
                reasons.append(f"Critical: {metrics.consecutive_failures} consecutive failures")
            else:
                reasons.append(f"Low success rate: {metrics.success_rate:.1%} ({metrics.usage_count} executions)")

        # DERIVED recommendation (simplified logic)
        elif metrics.success_rate > 0.7 and metrics.usage_count > 10:
            should_derive = True
            confidence = 0.6
            reasons.append("Skill is stable and popular, consider optimizations")

        # CAPTURED recommendation (extremely rare, manual trigger only)
        # Left as stub for completeness
        should_capture = False

        return EvolutionRecommendation(
            should_fix=should_fix,
            should_derive=should_derive,
            should_capture=should_capture,
            confidence=confidence,
            reasons=reasons,
        )

    def analyze_execution_history(
        self, skill: SkillRecord, execution_analysis: ExecutionAnalysis
    ) -> dict[str, str | float]:
        """Analyze detailed execution data (按需调用).

        This is lightweight vs OpenSpace's complex pattern recognition.
        Only called when evolution needs detailed context.

        Args:
            skill: Skill being analyzed
            execution_analysis: Detailed execution context

        Returns:
            Analysis summary dict
        """
        summary: dict[str, str | float] = {}

        # Extract error patterns from error_message
        if execution_analysis.error_message:
            summary["error_type"] = self._classify_error(execution_analysis.error_message)

        # Include root cause if available
        if execution_analysis.root_cause:
            summary["has_root_cause"] = True

        # Include suggested fix if available
        if execution_analysis.suggested_fix:
            summary["has_suggested_fix"] = True

        return summary

    def _classify_error(self, error_msg: str) -> str:
        """Classify error type for targeted fixes."""
        error_msg_lower = error_msg.lower()

        if "timeout" in error_msg_lower:
            return "timeout"
        elif "permission" in error_msg_lower or "403" in error_msg_lower:
            return "permission"
        elif "not found" in error_msg_lower or "404" in error_msg_lower:
            return "not_found"
        elif "syntax" in error_msg_lower:
            return "syntax"
        elif "type" in error_msg_lower:
            return "type_error"
        else:
            return "unknown"

    def _estimate_relevance(self, context_used: list[str]) -> float:
        """Estimate context relevance score (simplified).

        Real implementation would use embedding similarity.
        This is lightweight placeholder.
        """
        if not context_used:
            return 0.0

        # Simple heuristic: more context = potentially more relevant
        # Real system would compute semantic similarity
        return min(1.0, len(context_used) / 5.0)

    def should_evolve_now(self, skill: SkillRecord) -> tuple[bool, str]:
        """Quick check if skill should evolve immediately.

        Used for fast filtering before detailed analysis.

        Args:
            skill: Skill to check

        Returns:
            (should_evolve, reason) tuple
        """
        if skill.metrics.consecutive_failures >= 3:
            return (True, "Critical failure threshold reached")

        if skill.metrics.should_trigger_fix(self.fix_threshold):
            return (True, "Success rate below threshold")

        return (False, "Skill performing adequately")


def analyze_skill_for_evolution(skill: SkillRecord, *, detailed: bool = False) -> EvolutionRecommendation:
    """Convenience function for quick skill analysis.

    Args:
        skill: Skill to analyze
        detailed: If True, performs detailed analysis (slower)

    Returns:
        Evolution recommendation
    """
    analyzer = SkillExecutionAnalyzer()
    return analyzer.analyze_skill(skill)
