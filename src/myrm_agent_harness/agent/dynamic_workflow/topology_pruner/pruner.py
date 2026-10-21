"""Model-tier adaptive topology pruning engine.

[INPUT]
- re::compile
- typing::Sequence
- types::(
    ModelIntelligenceTier,
    PruningDecisionKind,
    PruningStrategy,
    TaskComplexityLevel,
    TopologyPruningEvaluation,
  )

[OUTPUT]
- ModelTierAdaptiveTopologyPruner: Core pruning evaluation engine.
- get_topology_pruner: Singleton provider for global pruner instance.

[POS]
Harness-level dynamic workflow pruner that simplifies multi-agent fanout topologies into
single-agent direct reasoning based on model capability tiers (DSH architecture paradigm).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.agent.dynamic_workflow.topology_pruner.types import (
    ModelIntelligenceTier,
    PruningDecisionKind,
    PruningStrategy,
    TaskComplexityLevel,
    TopologyPruningEvaluation,
)

_TIER_1_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"claude-3[.-]7.*", re.IGNORECASE),
    re.compile(r"claude-3[.-]5-sonnet.*", re.IGNORECASE),
    re.compile(r"deepseek[-_]r1.*", re.IGNORECASE),
    re.compile(r"deepseek[-_]v3.*", re.IGNORECASE),
    re.compile(r"deepseek[-_]v4[-_]pro.*", re.IGNORECASE),
    re.compile(r"gpt[-_]5.*", re.IGNORECASE),
    re.compile(r"gpt[-_]4o(?!-mini).*", re.IGNORECASE),
    re.compile(r"^o1.*", re.IGNORECASE),
    re.compile(r"^o3.*", re.IGNORECASE),
)

_TIER_2_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"claude-3[.-]5-haiku.*", re.IGNORECASE),
    re.compile(r"gpt[-_]4o[-_]mini.*", re.IGNORECASE),
    re.compile(r"deepseek[-_]v4(?![-_]flash).*", re.IGNORECASE),
    re.compile(r"qwen[-_]2\.5[-_](32|72)b.*", re.IGNORECASE),
    re.compile(r"llama[-_]3\.[123][-_]70b.*", re.IGNORECASE),
    re.compile(r"mistral[-_]large.*", re.IGNORECASE),
)

_COMPLEXITY_HIGH_KEYWORDS: Sequence[str] = (
    "architecture", "migration", "redesign", "distributed", "security audit",
    "compiler", "microservice", "concurrency", "multi-repo", "system design"
)

_COMPLEXITY_EXTREME_KEYWORDS: Sequence[str] = (
    "complete rewrite", "multi-region disaster recovery", "zero-downtime database overhaul",
    "cryptographic protocol transition", "kernel driver refactor"
)


class ModelTierAdaptiveTopologyPruner:
    """Evaluates task and model tier to prune unnecessary subagent delegation hierarchies."""

    def resolve_model_tier(
        self,
        model_name: str,
        explicit_tier: ModelIntelligenceTier | None = None,
    ) -> ModelIntelligenceTier:
        """Map model identifier to its capability hierarchy tier."""
        if explicit_tier:
            return explicit_tier

        name = model_name.strip()
        for pat in _TIER_1_PATTERNS:
            if pat.search(name):
                return "tier_1_sota_reasoning"

        for pat in _TIER_2_PATTERNS:
            if pat.search(name):
                return "tier_2_strong_base"

        return "tier_3_fast_light"

    def assess_complexity(
        self,
        task_description: str,
        planned_subtasks_count: int = 1,
    ) -> TaskComplexityLevel:
        """Estimate cognitive and structural complexity of the task."""
        text = task_description.lower()

        for kw in _COMPLEXITY_EXTREME_KEYWORDS:
            if kw in text:
                return "extreme"

        high_score = sum(1 for kw in _COMPLEXITY_HIGH_KEYWORDS if kw in text)
        if high_score >= 2 or planned_subtasks_count >= 5:
            return "high"
        if high_score == 1 or planned_subtasks_count >= 3 or len(task_description) > 300:
            return "medium"
        return "low"

    def evaluate_pruning(
        self,
        task_description: str,
        model_name: str,
        *,
        explicit_tier: ModelIntelligenceTier | None = None,
        strategy: PruningStrategy = "auto",
        planned_subtasks_count: int = 3,
    ) -> TopologyPruningEvaluation:
        """Determine whether to fold multi-agent delegation into direct deep reasoning."""
        tier = self.resolve_model_tier(model_name, explicit_tier)
        complexity = self.assess_complexity(task_description, planned_subtasks_count)

        # 1. Manual Strategy Overrides
        if strategy == "direct_only":
            return self._build_evaluation(
                decision="direct_execution",
                model_name=model_name,
                tier=tier,
                strategy=strategy,
                complexity=complexity,
                is_folded=True,
                rationale="User policy forced direct single-agent execution without subagent spawn.",
                planned_count=planned_subtasks_count,
                executed_count=1,
            )

        if strategy == "always_multi_agent":
            return self._build_evaluation(
                decision="fanout_multi_agent",
                model_name=model_name,
                tier=tier,
                strategy=strategy,
                complexity=complexity,
                is_folded=False,
                rationale="User policy forced multi-agent fanout decomposition.",
                planned_count=planned_subtasks_count,
                executed_count=planned_subtasks_count,
            )

        # 2. Automated Adaptive Pruning Logic
        if complexity == "low":
            return self._build_evaluation(
                decision="direct_execution",
                model_name=model_name,
                tier=tier,
                strategy=strategy,
                complexity=complexity,
                is_folded=True,
                rationale=(
                    f"Task complexity is low. Folded {planned_subtasks_count} subtasks into direct execution "
                    f"to eliminate multi-agent communication overhead."
                ),
                planned_count=planned_subtasks_count,
                executed_count=1,
            )

        if complexity == "medium":
            if tier == "tier_1_sota_reasoning":
                return self._build_evaluation(
                    decision="direct_execution",
                    model_name=model_name,
                    tier=tier,
                    strategy=strategy,
                    complexity=complexity,
                    is_folded=True,
                    rationale=(
                        f"Tier 1 SOTA model ({model_name}) possesses sufficient reasoning depth to resolve "
                        f"medium complexity task directly, saving delegation latency."
                    ),
                    planned_count=planned_subtasks_count,
                    executed_count=1,
                )
            return self._build_evaluation(
                decision="fanout_multi_agent",
                model_name=model_name,
                tier=tier,
                strategy=strategy,
                complexity=complexity,
                is_folded=False,
                rationale=(
                    f"Model tier ({tier}) benefits from explicit multi-agent decomposition for medium complexity."
                ),
                planned_count=planned_subtasks_count,
                executed_count=planned_subtasks_count,
            )

        if complexity == "high":
            if tier == "tier_1_sota_reasoning":
                return self._build_evaluation(
                    decision="hybrid_folded",
                    model_name=model_name,
                    tier=tier,
                    strategy=strategy,
                    complexity=complexity,
                    is_folded=True,
                    rationale=(
                        "High complexity task adapted for Tier 1 model: folded worker steps into primary reasoning, "
                        "retaining only independent verification agent."
                    ),
                    planned_count=planned_subtasks_count,
                    executed_count=2,
                )
            return self._build_evaluation(
                decision="fanout_multi_agent",
                model_name=model_name,
                tier=tier,
                strategy=strategy,
                complexity=complexity,
                is_folded=False,
                rationale="High complexity task requires full multi-agent specialization under base model.",
                planned_count=planned_subtasks_count,
                executed_count=planned_subtasks_count,
            )

        # Extreme complexity
        return self._build_evaluation(
            decision="fanout_multi_agent",
            model_name=model_name,
            tier=tier,
            strategy=strategy,
            complexity=complexity,
            is_folded=False,
            rationale="Extreme architectural scope strictly mandates full multi-agent safety boundaries.",
            planned_count=planned_subtasks_count,
            executed_count=planned_subtasks_count,
        )

    def _build_evaluation(
        self,
        decision: PruningDecisionKind,
        model_name: str,
        tier: ModelIntelligenceTier,
        strategy: PruningStrategy,
        complexity: TaskComplexityLevel,
        is_folded: bool,
        rationale: str,
        planned_count: int,
        executed_count: int,
    ) -> TopologyPruningEvaluation:
        saved_subagents = max(0, planned_count - executed_count)
        saved_turns = saved_subagents * 3
        saved_tokens = saved_subagents * 2400

        return TopologyPruningEvaluation(
            decision=decision,
            model_name=model_name,
            model_tier=tier,
            strategy=strategy,
            task_complexity=complexity,
            is_folded=is_folded,
            rationale=rationale,
            planned_subtasks_count=planned_count,
            executed_subtasks_count=executed_count,
            estimated_saved_turns=saved_turns,
            estimated_saved_tokens=saved_tokens,
        )


_global_pruner: ModelTierAdaptiveTopologyPruner | None = None


def get_topology_pruner() -> ModelTierAdaptiveTopologyPruner:
    """Retrieve singleton ModelTierAdaptiveTopologyPruner instance."""
    global _global_pruner
    if _global_pruner is None:
        _global_pruner = ModelTierAdaptiveTopologyPruner()
    return _global_pruner
