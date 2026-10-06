"""Unit tests for Four-Tier Tokenomics context compression and dynamic budget routing.

Covers:
1. ProtectedPatternsMatcher immutable entity shielding and code_safe fidelity
2. Tier 1 lossless cleaning, URL scrubbing, and Headroom tabular JSON arrays
3. Tier 2 Session-Dedup content-hash addressing and CCR retrieval markers
4. Tier 3 Caveman semantic prose trimming without harming protected facts
5. Tier 4 Ultra extreme compaction for emergency saturation
6. CompressionBudgetRouter dynamic watermark routing and four-dimensional balance metrics
"""

from __future__ import annotations

import json

from myrm_agent_harness.runtime.context.compression_budget_router import (
    CompressionBudgetRouter,
)
from myrm_agent_harness.runtime.context.protected_patterns_matcher import (
    ProtectedPatternsMatcher,
)
from myrm_agent_harness.runtime.context.tiered_context_compression_pipeline import (
    TieredContextCompressionPipeline,
)
from myrm_agent_harness.runtime.context.tokenomics_compression_types import (
    CompressionTierKind,
    ContextTaxonomyKind,
    ProtectedPatternsConfig,
    TaskRiskLevel,
)


def test_protected_patterns_matcher_mask_and_restore() -> None:
    """Verify that file paths, line numbers, commands, error codes, and code blocks are shielded."""
    config = ProtectedPatternsConfig(code_safe=True)
    matcher = ProtectedPatternsMatcher(config=config)

    original_text = (
        "Encountered RuntimeError at src/runtime/executor.py line 42.\n"
        "Please run `pytest -v tests/test_runner.py` to reproduce.\n"
        "```python\ndef buggy_function():\n    raise RuntimeError('Critical failure')\n```\n"
        "Notice Exit code 1 returned."
    )

    masked, placeholders = matcher.mask_protected_entities(original_text)
    assert len(placeholders) >= 4
    # All protected entities must be masked
    assert "src/runtime/executor.py" not in masked
    assert "buggy_function" not in masked
    assert "pytest -v" not in masked

    # Mutate the unmasked text (simulating aggressive text compression/normalization)
    modified_masked = masked.replace("Encountered", "Saw").replace("Notice", "Observed")

    # Restoration must bring back verbatim original protected facts
    restored = matcher.restore_protected_entities(modified_masked, placeholders)
    assert "src/runtime/executor.py" in restored
    assert "line 42" in restored
    assert "pytest -v tests/test_runner.py" in restored
    assert "def buggy_function():" in restored
    assert "RuntimeError" in restored
    assert "Exit code 1" in restored


def test_tier_1_lossless_cleaning_and_headroom_json() -> None:
    """Verify whitespace normalization, tracking URL pruning, and Headroom JSON columnar compacting."""
    pipeline = TieredContextCompressionPipeline()

    raw_text = (
        "System ready.\n\n\n\n\n"
        "Reference docs: https://example.com/api?utm_source=chat&utm_medium=agent&id=123 \n\n"
        '[{"id": "1", "name": "alpha", "status": "ok"}, {"id": "2", "name": "beta", "status": "ok"}]'
    )

    cleaned = pipeline.apply_tier_1_lossless(raw_text)

    # 1. Whitespace normalized
    assert "\n\n\n" not in cleaned

    # 2. Tracking parameters pruned, core query preserved
    assert "utm_source" not in cleaned
    assert "utm_medium" not in cleaned
    assert "id=123" in cleaned

    # 3. Headroom columnar json representation applied
    assert "_headroom_columns" in cleaned
    assert "_rows" in cleaned
    headroom_payload = json.loads(cleaned.split("\n\n")[-1])
    assert headroom_payload["_headroom_columns"] == ["id", "name", "status"]
    assert len(headroom_payload["_rows"]) == 2


def test_tier_2_structural_dedup_content_hash() -> None:
    """Verify that multi-line identical content blocks across turns are replaced by hash references."""
    pipeline = TieredContextCompressionPipeline(min_dedup_length=50)

    heavy_log = (
        "Detailed execution traceback log:\n"
        "AssertionError: Expected status code 200 but received 500 Internal Server Error.\n"
        "Traceback (most recent call last):\n"
        "  File '/app/server/main.py', line 108, in handle_request"
    )

    # Turn 1: Fresh observation, stored in hash cache
    turn_1_output = pipeline.apply_tier_2_structural_dedup(heavy_log, current_turn=1)
    assert "Duplicate content hash:" not in turn_1_output
    assert "AssertionError" in turn_1_output

    # Turn 2: Repeated observation of identical block -> replaced with retrieval pointer
    turn_2_output = pipeline.apply_tier_2_structural_dedup(heavy_log, current_turn=2)
    assert "[Duplicate content hash:" in turn_2_output
    assert "presented in turn 1]" in turn_2_output


def test_tier_3_semantic_caveman_trimming_with_shield() -> None:
    """Verify that polite filler is stripped while core engineering commands and facts survive."""
    pipeline = TieredContextCompressionPipeline()

    verbose_message = (
        "Certainly! I would be happy to help with that.\n"
        "I will proceed to edit /usr/local/bin/deploy.sh at line 15.\n"
        "Run `cargo test --workspace` to ensure all crates pass.\n"
        "Please let me know if you need anything else! Hope this helps."
    )

    trimmed = pipeline.apply_tier_3_semantic_pruning(verbose_message)

    # Polite prose eliminated
    assert "Certainly" not in trimmed
    assert "happy to help" not in trimmed
    assert "Hope this helps" not in trimmed

    # Core engineering facts shielded and preserved
    assert "/usr/local/bin/deploy.sh" in trimmed
    assert "line 15" in trimmed
    assert "cargo test --workspace" in trimmed


def test_tier_4_extreme_compaction_and_pipeline_execution() -> None:
    """Test full four-tier progressive pipeline execution and extreme compaction."""
    pipeline = TieredContextCompressionPipeline()

    narrative = (
        "Sure thing! Here is the breakdown:\n"
        "- Task A: Refactor database schema.\n"
        "We spent a lot of time analyzing alternative approaches that were discarded.\n"
        "- Task B: Fix memory leak in src/cache/lru.py line 88.\n"
        "Notice Exit code 0 on test completion."
    )

    active_tiers = [
        CompressionTierKind.TIER_1_LOSSLESS_CLEAN,
        CompressionTierKind.TIER_3_SEMANTIC_PRUNING,
        CompressionTierKind.TIER_4_EXTREME_COMPACTION,
    ]

    result = pipeline.execute_pipeline(
        text=narrative,
        active_tiers=active_tiers,
        current_turn=1,
    )

    assert result.reduction_ratio > 0.10
    assert result.protected_spans_preserved >= 1
    assert "src/cache/lru.py" in result.processed_text
    assert "- Task A:" in result.processed_text
    assert "Sure thing" not in result.processed_text


def test_compression_budget_router_and_four_dimensional_metrics() -> None:
    """Verify dynamic budget watermark routing across risk tiers and balance scorecard."""
    router = CompressionBudgetRouter()

    # 1. Message Taxonomy classification
    tax_directive = router.classify_message_taxonomy(
        role="user", content="Deploy v2.0", is_first_user_turn=True
    )
    assert tax_directive == ContextTaxonomyKind.USER_CORE_DIRECTIVE

    tax_tool = router.classify_message_taxonomy(
        role="tool", content="Exit code 0. Passed 12 tests."
    )
    assert tax_tool == ContextTaxonomyKind.TOOL_EVIDENCE

    tax_noise = router.classify_message_taxonomy(
        role="user", content="ok thanks", is_first_user_turn=False
    )
    assert tax_noise == ContextTaxonomyKind.BACKGROUND_NOISE

    # 2. Dynamic Budget Routing across watermarks
    # Low usage (<50%): Tier 1 only
    dec_low = router.choose_compression(
        task_risk=TaskRiskLevel.LOW,
        token_budget=100000,
        current_tokens=30000,  # 30% watermark
    )
    assert dec_low.selected_tiers == (CompressionTierKind.TIER_1_LOSSLESS_CLEAN,)

    # Moderate usage (50%-70%): Tier 1 + Tier 2
    dec_mid = router.choose_compression(
        task_risk=TaskRiskLevel.HIGH,
        token_budget=100000,
        current_tokens=60000,  # 60% watermark
    )
    assert dec_mid.selected_tiers == (
        CompressionTierKind.TIER_1_LOSSLESS_CLEAN,
        CompressionTierKind.TIER_2_STRUCTURAL_DEDUP,
    )

    # High usage (>70%): Tier 1 + Tier 2 + Tier 3
    dec_high = router.choose_compression(
        task_risk=TaskRiskLevel.HIGH,
        token_budget=100000,
        current_tokens=80000,  # 80% watermark
    )
    assert CompressionTierKind.TIER_3_SEMANTIC_PRUNING in dec_high.selected_tiers

    # Critical saturation (>90%): All four tiers unlocked
    dec_crit = router.choose_compression(
        task_risk=TaskRiskLevel.HIGH,
        token_budget=100000,
        current_tokens=95000,  # 95% watermark
    )
    assert len(dec_crit.selected_tiers) == 4
    assert CompressionTierKind.TIER_4_EXTREME_COMPACTION in dec_crit.selected_tiers

    # 3. Four-Dimensional Balance Scorecard
    metrics = router.evaluate_four_dimensional_balance(
        original_tokens=10000,
        compressed_tokens=4500,
        historical_successes=[True, True, True, False],  # 75%
        error_recoveries=[True, True],  # 100%
        user_reworks=[False, False, False],  # 0%
    )
    assert metrics.token_reduction_rate == 0.55
    assert metrics.task_success_rate == 0.75
    assert metrics.error_recovery_rate == 1.0
    assert metrics.user_rework_rate == 0.0
