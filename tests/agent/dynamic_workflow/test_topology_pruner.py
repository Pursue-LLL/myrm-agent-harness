"""Unit tests for Model-Tier Adaptive Topology Pruning and Folding engine.

[INPUT]
- myrm_agent_harness.agent.dynamic_workflow.topology_pruner::(
    ModelTierAdaptiveTopologyPruner,
    get_topology_pruner,
  )

[OUTPUT]
- Pytest test cases covering model tier resolution, task complexity estimation, adaptive folding, and strategy overrides.

[POS]
tests/agent/dynamic_workflow/test_topology_pruner.py: Comprehensive test suite for Item 8 ModelTierAdaptiveTopologyPruning.
"""

from __future__ import annotations

from myrm_agent_harness.agent.dynamic_workflow.topology_pruner import (
    ModelTierAdaptiveTopologyPruner,
    get_topology_pruner,
)


def test_resolve_model_tier() -> None:
    """Verify regex classifier categorizes models into proper intelligence tiers."""
    pruner = ModelTierAdaptiveTopologyPruner()

    # Tier 1 models
    assert pruner.resolve_model_tier("claude-3-7-sonnet-20250219") == "tier_1_sota_reasoning"
    assert pruner.resolve_model_tier("deepseek-r1") == "tier_1_sota_reasoning"
    assert pruner.resolve_model_tier("deepseek_v4_pro") == "tier_1_sota_reasoning"
    assert pruner.resolve_model_tier("gpt-4o") == "tier_1_sota_reasoning"
    assert pruner.resolve_model_tier("o1-preview") == "tier_1_sota_reasoning"
    assert pruner.resolve_model_tier("o3-mini") == "tier_1_sota_reasoning"

    # Tier 2 models
    assert pruner.resolve_model_tier("claude-3-5-haiku-20241022") == "tier_2_strong_base"
    assert pruner.resolve_model_tier("gpt-4o-mini") == "tier_2_strong_base"
    assert pruner.resolve_model_tier("qwen-2.5-32b-instruct") == "tier_2_strong_base"
    assert pruner.resolve_model_tier("llama-3.3-70b-versatile") == "tier_2_strong_base"

    # Tier 3 models
    assert pruner.resolve_model_tier("qwen-2.5-7b") == "tier_3_fast_light"
    assert pruner.resolve_model_tier("deepseek-v4-flash") == "tier_3_fast_light"
    assert pruner.resolve_model_tier("llama-3-8b-instruct") == "tier_3_fast_light"

    # Explicit override takes precedence
    assert (
        pruner.resolve_model_tier("qwen-2.5-7b", explicit_tier="tier_1_sota_reasoning")
        == "tier_1_sota_reasoning"
    )


def test_assess_complexity() -> None:
    """Verify task complexity scoring based on text signals and planned subtasks."""
    pruner = ModelTierAdaptiveTopologyPruner()

    # Low complexity
    assert pruner.assess_complexity("Fix typo in README.md", planned_subtasks_count=1) == "low"

    # Medium complexity
    med = "Refactor user authentication service to support JWT expiration and add tests"
    assert pruner.assess_complexity(med, planned_subtasks_count=3) == "medium"

    # High complexity
    high = "Design distributed microservice architecture with security audit and concurrency control"
    assert pruner.assess_complexity(high, planned_subtasks_count=4) == "high"

    # Extreme complexity
    extreme = "Execute a complete rewrite of core database storage engine with zero-downtime transition"
    assert pruner.assess_complexity(extreme, planned_subtasks_count=6) == "extreme"


def test_tier_1_medium_task_direct_folding() -> None:
    """Tier 1 SOTA model folds medium task into single-agent direct deep reasoning."""
    pruner = get_topology_pruner()
    task = "Refactor payment webhook handling to verify signature idempotently across 2 controllers"

    eval_result = pruner.evaluate_pruning(
        task_description=task,
        model_name="claude-3-7-sonnet",
        planned_subtasks_count=3,
        strategy="auto",
    )

    assert eval_result.decision == "direct_execution"
    assert eval_result.is_folded is True
    assert eval_result.model_tier == "tier_1_sota_reasoning"
    assert eval_result.executed_subtasks_count == 1
    # 2 subtasks folded -> 6 turns saved, 4800 tokens saved
    assert eval_result.estimated_saved_turns == 6
    assert eval_result.estimated_saved_tokens == 4800


def test_tier_3_medium_task_fanout_retention() -> None:
    """Tier 3 fast light model retains multi-agent fanout for medium task."""
    pruner = get_topology_pruner()
    task = "Refactor payment webhook handling to verify signature idempotently across 2 controllers"

    eval_result = pruner.evaluate_pruning(
        task_description=task,
        model_name="qwen-2.5-7b",
        planned_subtasks_count=3,
        strategy="auto",
    )

    assert eval_result.decision == "fanout_multi_agent"
    assert eval_result.is_folded is False
    assert eval_result.model_tier == "tier_3_fast_light"
    assert eval_result.executed_subtasks_count == 3
    assert eval_result.estimated_saved_turns == 0
    assert eval_result.estimated_saved_tokens == 0


def test_tier_1_high_complexity_hybrid_folding() -> None:
    """Tier 1 SOTA model adapts high complexity task into hybrid folded topology."""
    pruner = get_topology_pruner()
    task = "Design distributed microservice architecture with security audit and concurrency control"

    eval_result = pruner.evaluate_pruning(
        task_description=task,
        model_name="deepseek-r1",
        planned_subtasks_count=4,
        strategy="auto",
    )

    assert eval_result.decision == "hybrid_folded"
    assert eval_result.is_folded is True
    assert eval_result.executed_subtasks_count == 2
    assert eval_result.estimated_saved_turns == 6  # (4 - 2) * 3
    assert eval_result.estimated_saved_tokens == 4800


def test_extreme_complexity_strict_fanout() -> None:
    """Extreme complexity mandates full multi-agent fanout regardless of model tier."""
    pruner = get_topology_pruner()
    task = "Execute a complete rewrite of core database storage engine with zero-downtime transition"

    eval_result = pruner.evaluate_pruning(
        task_description=task,
        model_name="o1-preview",
        planned_subtasks_count=6,
        strategy="auto",
    )

    assert eval_result.decision == "fanout_multi_agent"
    assert eval_result.is_folded is False
    assert eval_result.executed_subtasks_count == 6


def test_user_strategy_overrides() -> None:
    """Verify direct_only and always_multi_agent user strategy overrides."""
    pruner = get_topology_pruner()
    task = "Standard bugfix in authorization header parser"

    # User overrides direct_only even on Tier 3 model
    direct_res = pruner.evaluate_pruning(
        task_description=task,
        model_name="qwen-2.5-7b",
        planned_subtasks_count=3,
        strategy="direct_only",
    )
    assert direct_res.decision == "direct_execution"
    assert direct_res.is_folded is True
    assert direct_res.executed_subtasks_count == 1

    # User overrides always_multi_agent on Tier 1 model
    fanout_res = pruner.evaluate_pruning(
        task_description=task,
        model_name="claude-3-7-sonnet",
        planned_subtasks_count=3,
        strategy="always_multi_agent",
    )
    assert fanout_res.decision == "fanout_multi_agent"
    assert fanout_res.is_folded is False
    assert fanout_res.executed_subtasks_count == 3
