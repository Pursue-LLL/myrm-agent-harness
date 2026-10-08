"""Unit tests for Context Compression Silent Fallback Guard and Anti-Amnesia Resilience Suite.

Validates physical window assertions, hierarchical map-reduce compression with 15% overlap,
semantic fidelity and HUD badges, anti-hanging timeout guards, and adaptive 500-turn watchdog.
"""

from __future__ import annotations

import asyncio
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.anti_amnesia import (
    AdaptiveTurnBudgetWatchdog,
    AntiAmnesiaExecutionReport,
    AntiAmnesiaSuite,
    CapacityAssertionResult,
    ChunkedMapReduceCompactor,
    CompressionFallbackTier,
    CompressionLockTimeoutError,
    CompressionTransparencyAndLockGuard,
    InsufficientWindowCapacityError,
    ModelWindowSpec,
    WindowCapacityAsserter,
)


def test_physical_window_capacity_assertion() -> None:
    """Verify physical context window assertion prevents silent fallback truncation."""
    small_model = ModelWindowSpec(
        model_name="local-qwen-7b",
        context_window=8192,
        max_output_tokens=2048,
        safety_headroom_ratio=1.25,
        is_local=True,
    )
    # Safe input capacity = (8192 - 2048) / 1.25 = 4915 tokens

    # Safe fit (3000 tokens) passes
    res_safe = WindowCapacityAsserter.evaluate_capacity(3000, small_model)
    assert res_safe.passed is True
    assert res_safe.deficit_tokens == 0

    # Oversized history (12000 tokens) strictly fails assertion
    res_fail = WindowCapacityAsserter.evaluate_capacity(12000, small_model)
    assert res_fail.passed is False
    assert res_fail.deficit_tokens > 7000
    assert "Physical capacity check failed" in str(res_fail.error_message)

    with pytest.raises(InsufficientWindowCapacityError) as exc_info:
        WindowCapacityAsserter.assert_capacity_or_raise(12000, small_model)
    assert exc_info.value.model_name == "local-qwen-7b"
    assert exc_info.value.required_tokens == 12000

    # Safe tier selection: falls back to Map-Reduce rather than violent monolithic truncation
    tier, spec = WindowCapacityAsserter.select_safe_compression_tier(
        total_tokens=15000,
        primary_spec=None,
        fallback_spec=small_model,
    )
    assert tier == CompressionFallbackTier.MAP_REDUCE_FALLBACK
    assert spec is not None
    assert spec.model_name == "local-qwen-7b"


def test_chunked_map_reduce_hierarchical_compaction() -> None:
    """Verify lossless hierarchical map-reduce slicing with 15% continuity overlap."""
    messages = [
        HumanMessage(content="Initialize database migration for UserAuthService in auth_v2.py."),
        AIMessage(content="Starting migration script verification."),
        ToolMessage(
            content="Error: DatabaseMigrationFailed in auth_v2.py at line 42: ForeignKeyViolation. " * 30,
            name="run_migration",
            tool_call_id="call_db_01",
        ),
        AIMessage(content="Fixing schema relationship in models/user.py and re-running tests."),
        ToolMessage(
            content="SUCCESS: 12 tests in test_user_service.py passed with zero errors. " * 25,
            name="run_pytest",
            tool_call_id="call_db_02",
        ),
    ]

    small_spec = ModelWindowSpec(
        model_name="small-worker-model",
        context_window=4096,
        max_output_tokens=1024,
    )

    unified_msg, nodes = ChunkedMapReduceCompactor.execute_map_reduce_compaction(
        messages=messages,
        model_spec=small_spec,
    )

    assert len(nodes) >= 1
    content_str = str(unified_msg.content)
    assert "<hierarchical_workflow_memory" in content_str
    assert "lossless_map_reduce" in content_str
    # Verify technical entities were cleanly preserved across chunks
    assert "auth_v2.py" in content_str or "DatabaseMigrationFailed" in content_str or "test_user_service.py" in content_str


def test_transparency_hud_and_semantic_fidelity_assertion() -> None:
    """Verify semantic fidelity scoring and client-facing HUD badge generation."""
    original_messages = [
        HumanMessage(content="Refactor payment_gateway.py to support StripeWebhookHandler."),
        ToolMessage(content="CRITICAL: TransactionRollback in stripe_client.py", name="stripe_test", tool_call_id="c1"),
    ]

    compressed_high_fidelity = (
        "Consolidated Summary: Refactored payment_gateway.py with StripeWebhookHandler. "
        "Encountered TransactionRollback in stripe_client.py, resolved cleanly."
    )
    score, passed = CompressionTransparencyAndLockGuard.evaluate_semantic_fidelity(
        original_messages,
        compressed_high_fidelity,
        threshold=0.5,
    )
    assert score >= 0.5
    assert passed is True

    # Build HUD badge for map-reduce fallback
    hud = CompressionTransparencyAndLockGuard.create_transparency_hud(
        tier=CompressionFallbackTier.MAP_REDUCE_FALLBACK,
        model_name="local-qwen-7b",
        fidelity_score=score,
        fidelity_passed=passed,
    )
    assert hud.is_degraded is True
    assert hud.tier == CompressionFallbackTier.MAP_REDUCE_FALLBACK
    assert hud.badge_color == "yellow"
    assert "分块金字塔容灾模式" in hud.user_alert_message


@pytest.mark.asyncio
async def test_anti_hanging_transaction_timeout_guard() -> None:
    """Verify transaction timeout guard releases locks and raises timeout exception."""
    with pytest.raises(CompressionLockTimeoutError) as exc_info:
        async with CompressionTransparencyAndLockGuard.transaction_timeout_watchdog(timeout_seconds=0.05):
            await asyncio.sleep(0.2)
    assert "watchdog limit" in str(exc_info.value)
    assert "released" in str(exc_info.value)


def test_adaptive_500_turn_budget_watchdog() -> None:
    """Verify adaptive iteration watchdog extends fuel up to 500 rounds and detects stalls."""
    watchdog = AdaptiveTurnBudgetWatchdog(
        initial_budget=30,
        max_ceiling=500,
        fuel_step_turns=20,
        max_consecutive_stalls=3,
    )
    assert watchdog.allocated_budget == 30

    # Step turns with progress signals
    for i in range(25):
        state = watchdog.record_turn(has_progress_signal=True, signal_reason="code updated")
        assert state.can_continue is True

    # Nearing budget boundary (turn 25 with budget 30): fuel is injected
    assert watchdog.allocated_budget > 30

    # Trigger consecutive stalls (3 idle turns)
    watchdog.record_turn(has_progress_signal=False, signal_reason="idle")
    watchdog.record_turn(has_progress_signal=False, signal_reason="idle")
    stall_state = watchdog.record_turn(has_progress_signal=False, signal_reason="idle")

    assert stall_state.consecutive_idle_turns == 3
    assert stall_state.can_continue is False
    assert "Task stalled" in stall_state.status_reason


@pytest.mark.asyncio
async def test_end_to_end_anti_amnesia_suite_execution() -> None:
    """Verify complete anti-amnesia facade execution and audit reporting."""
    messages = [
        HumanMessage(content="Investigate core microservice latency issues in order_pipeline.py."),
        AIMessage(content="Checking recent deployment logs."),
        ToolMessage(content="Metrics report: ServiceTimeout in order_pipeline.py. " * 300, name="read_metrics", tool_call_id="call_m1"),
        AIMessage(content="Identified bottleneck in cache_layer.py."),
        ToolMessage(content="Cache miss rate: 98.2% in redis_cache.py. " * 250, name="read_cache", tool_call_id="call_m2"),
    ]

    fallback_small_model = ModelWindowSpec(
        model_name="fallback-local-llama",
        context_window=2048,
        max_output_tokens=512,
        is_local=True,
    )

    watchdog = AntiAmnesiaSuite.create_turn_watchdog(initial_budget=40)

    compressed_msgs, report = await AntiAmnesiaSuite.compress_with_anti_amnesia_protection(
        messages=messages,
        fallback_spec=fallback_small_model,
        watchdog=watchdog,
    )

    assert len(compressed_msgs) == 1
    assert isinstance(report, AntiAmnesiaExecutionReport)
    assert report.fallback_tier == CompressionFallbackTier.MAP_REDUCE_FALLBACK
    assert report.tokens_reclaimed >= 0
    assert report.hud_state.is_degraded is True
    assert report.watchdog_state is not None
    assert report.watchdog_state.allocated_budget == 40
