"""Unit tests for deterministic hash-pinned prefix cache guard and append-only context pipeline.

Validates SHA-256 stability of frozen system prompts, append-only history invariants,
cryptographic breach detection on prefix mutation, deterministic summary idempotence,
and KV-cache hit ratio telemetry.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.append_only_context_pipeline import (
    AppendOnlyContextPipeline,
)
from myrm_agent_harness.runtime.context.deterministic_prefix_cache_guard import (
    DeterministicPrefixCacheGuard,
    PrefixCacheBreachError,
)


@pytest.mark.asyncio
async def test_prefix_cache_guard_stability_and_fingerprint() -> None:
    """Validate that append-only extensions preserve static system hash and anchor prefix."""
    guard = DeterministicPrefixCacheGuard()
    pipeline = AppendOnlyContextPipeline()
    session_id = "sess_cache_001"

    static_system = "You are a senior staff software engineer. Strict coding rules apply."
    pipeline.set_static_system(session_id, static_system)

    # Turn 1
    pipeline.append_history_turn(session_id, "user: Write a sorting function")
    pipeline.append_history_turn(session_id, "assistant: Here is timsort implementation")
    _, fp1 = pipeline.assemble_full_context_stream(session_id, guard=guard, turn_index=1)
    assert fp1 is not None
    assert fp1.session_id == session_id
    assert fp1.turn_index == 1

    # Turn 2: append-only new turns
    pipeline.append_history_turn(session_id, "user: Add benchmark script")
    pipeline.append_history_turn(session_id, "assistant: Benchmark created")
    _, fp2 = pipeline.assemble_full_context_stream(session_id, guard=guard, turn_index=2)
    assert fp2 is not None
    assert fp2.turn_index == 2

    # Static system hash MUST stay 100% identical
    assert fp1.static_system_sha256 == fp2.static_system_sha256
    # History length increased
    assert fp2.prefix_length_chars > fp1.prefix_length_chars


@pytest.mark.asyncio
async def test_prefix_cache_breach_detection_on_system_mutation() -> None:
    """Ensure mutating the frozen system prompt triggers PrefixCacheBreachError."""
    guard = DeterministicPrefixCacheGuard()
    session_id = "sess_cache_002"

    guard.verify_and_anchor_prefix(
        session_id=session_id,
        turn_index=1,
        static_system_prompt="Stable system prompt v1",
        immutable_history_turns=("turn 1", "turn 2"),
    )

    # Turn 2: System prompt mutated with dynamic timestamp (violates cache prefix)
    with pytest.raises(PrefixCacheBreachError) as exc_info:
        guard.verify_and_anchor_prefix(
            session_id=session_id,
            turn_index=2,
            static_system_prompt="Stable system prompt v1 with dynamic time 12:00:00",
            immutable_history_turns=("turn 1", "turn 2", "turn 3"),
        )
    assert "Frozen system prompt mutated" in str(exc_info.value)


@pytest.mark.asyncio
async def test_prefix_cache_breach_detection_on_history_tampering() -> None:
    """Ensure modifying existing historical turns in-place triggers PrefixCacheBreachError."""
    guard = DeterministicPrefixCacheGuard()
    session_id = "sess_cache_003"

    history = ["turn 1 original", "turn 2 original"]
    guard.verify_and_anchor_prefix(
        session_id=session_id,
        turn_index=1,
        static_system_prompt="Frozen system prompt",
        immutable_history_turns=tuple(history),
    )

    # Tamper with turn 1 in place
    tampered_history = ["turn 1 TAMPERED_IN_PLACE", "turn 2 original", "turn 3 new"]
    with pytest.raises(PrefixCacheBreachError) as exc_info:
        guard.verify_and_anchor_prefix(
            session_id=session_id,
            turn_index=2,
            static_system_prompt="Frozen system prompt",
            immutable_history_turns=tuple(tampered_history),
        )
    assert "Historical turn at index 0 mutated" in str(exc_info.value)


@pytest.mark.asyncio
async def test_deterministic_summary_block_absolute_reproducibility() -> None:
    """Ensure identical facts and seed yield byte-for-byte identical SHA-256 hashes."""
    pipeline = AppendOnlyContextPipeline()
    session_id = "sess_cache_004"

    facts = (
        "Database initialized with SQLite WAL mode",
        "JWT token auth configured with 24h expiration",
        "Frontend connected via WebSocket",
    )

    # Call 1
    sum1 = pipeline.create_deterministic_compaction(
        session_id, start_turn=1, end_turn=5, key_facts=facts, seed=42
    )

    # Call 2 with shuffled order of same facts
    shuffled_facts = (
        "Frontend connected via WebSocket",
        "Database initialized with SQLite WAL mode",
        "JWT token auth configured with 24h expiration",
    )
    sum2 = pipeline.create_deterministic_compaction(
        session_id, start_turn=1, end_turn=5, key_facts=shuffled_facts, seed=42
    )

    # Hashes and contents must be strictly identical regardless of input order
    assert sum1.sha256_hash == sum2.sha256_hash
    assert sum1.content == sum2.content
    assert sum1.summary_id == sum2.summary_id

    # Different seed yields different hash
    sum_diff_seed = pipeline.create_deterministic_compaction(
        session_id, start_turn=1, end_turn=5, key_facts=facts, seed=99
    )
    assert sum_diff_seed.sha256_hash != sum1.sha256_hash


@pytest.mark.asyncio
async def test_cache_hit_telemetry_and_watchdog_alerting() -> None:
    """Verify KV-cache hit ratio telemetry tracking and breach threshold alert triggers."""
    guard = DeterministicPrefixCacheGuard(min_acceptable_hit_ratio=0.95)
    session_id = "sess_cache_005"

    # Turn 1: High cache hit ratio (98%)
    report1 = guard.record_cache_hit_telemetry(
        session_id=session_id,
        turn_index=1,
        reported_cache_hit_tokens=9800,
        reported_total_prompt_tokens=10000,
    )
    assert report1.is_prefix_stable is True
    assert report1.breach_detected is False
    assert report1.cache_hit_ratio == 0.98

    # Turn 2: Cache collapse (70% below 95% target)
    report2 = guard.record_cache_hit_telemetry(
        session_id=session_id,
        turn_index=2,
        reported_cache_hit_tokens=7000,
        reported_total_prompt_tokens=10000,
    )
    assert report2.is_prefix_stable is False
    assert report2.breach_detected is True
    assert report2.cache_hit_ratio == 0.70
    assert "fell below minimum target 0.950" in (report2.breach_reason or "")

    history = guard.get_telemetry_history(session_id)
    assert len(history) == 2
