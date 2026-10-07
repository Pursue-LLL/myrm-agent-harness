"""Tests for Deep Reasoning Stream Thinking Collapse and Prompt Cache Alignment Suite (Item 226)."""

import pytest

from myrm_agent_harness.agent.context_management.reasoning_collapse import (
    ReasoningCollapseConfig,
    ReasoningCollapseReport,
    ReasoningStreamCollapseEngine,
    ReasoningVendorType,
    ThinkingCollapseMode,
)


def test_ingest_turn_reasoning_and_vendor_normalization() -> None:
    """Verify reasoning stream ingestion across multiple LLM vendors produces normalized blocks with signatures."""
    engine = ReasoningStreamCollapseEngine()
    session_id = "sess-reason-multi-vendor"

    # DeepSeek R1 reasoning
    deepseek_block = engine.ingest_turn_reasoning(
        session_id=session_id,
        turn_index=1,
        vendor=ReasoningVendorType.DEEPSEEK,
        raw_thinking="First analyze the bug in compiler AST. We should inspect node visitor. Therefore, patch visitor.py.",
    )
    assert deepseek_block.turn_index == 1
    assert deepseek_block.vendor == ReasoningVendorType.DEEPSEEK
    assert len(deepseek_block.signature) == 16
    assert deepseek_block.token_estimate > 0

    # OpenAI o1 reasoning
    o1_block = engine.ingest_turn_reasoning(
        session_id=session_id,
        turn_index=2,
        vendor=ReasoningVendorType.OPENAI_O1,
        raw_thinking="Consider memory limits and concurrency locks. Conclusion: employ lightweight Mutex instead of Spinlock.",
    )
    assert o1_block.turn_index == 2
    assert o1_block.vendor == ReasoningVendorType.OPENAI_O1
    assert len(o1_block.signature) == 16

    # Digest extraction
    digest = engine.extract_thought_digest(deepseek_block.raw_content)
    assert "patch visitor.py" in digest or len(digest) > 0


def test_sliding_window_collapse_and_digest_extraction() -> None:
    """Verify sliding window collapses older turns into thought digests while keeping active turn intact."""
    engine = ReasoningStreamCollapseEngine(
        ReasoningCollapseConfig(
            mode=ThinkingCollapseMode.SLIDING_WINDOW,
            sliding_window_turns=1,
            min_tokens_to_collapse=10,
        )
    )
    session_id = "sess-sliding-collapse"

    # Long thinking texts (>100 chars to satisfy min_tokens_to_collapse)
    long_think_turn1 = (
        "Let us thoroughly inspect the database index layout. Checking B-tree branching factor. "
        "Reviewing cache thrashing telemetry. Therefore, optimize index columns and apply composite index."
    )
    long_think_turn2 = (
        "Now evaluating network serialization latency. Looking into Protobuf vs JSON benchmarks. "
        "Therefore, adopt binary serializer for fast IPC dispatch."
    )

    messages = [
        {"role": "system", "content": "You are a senior systems engineer. Maintain strict correctness."},
        {"role": "user", "content": "How do we fix the query latency?"},
        {
            "role": "assistant",
            "content": f"<think>{long_think_turn1}</think>We added composite index on (tenant_id, created_at).",
        },
        {"role": "user", "content": "What about inter-process communications?"},
        {
            "role": "assistant",
            "content": f"<think>{long_think_turn2}</think>We migrated to binary serializer for IPC.",
        },
    ]

    # Active turn is 4 (the latest assistant turn)
    processed, report = engine.collapse_historical_messages(
        session_id=session_id,
        messages=messages,
        active_turn_index=4,
    )

    assert report.session_id == session_id
    assert report.total_turns == 5
    assert report.tokens_saved > 0
    assert report.cache_prefix_aligned is True

    # Turn 2 (assistant turn 1) should be collapsed into <thought_digest
    assert "<thought_digest" in processed[2]["content"]
    assert "<think>" not in processed[2]["content"]

    # Turn 4 (active assistant turn) must retain full <think> tag
    assert "<think>" in processed[4]["content"]
    assert "<thought_digest" not in processed[4]["content"]


def test_prompt_cache_prefix_alignment_verification() -> None:
    """Verify prompt cache prefix integrity check detects prefix invariance."""
    engine = ReasoningStreamCollapseEngine()
    system_text = "SYSTEM PROMPT V1: Deterministic agent instructions. Never change."

    messages_aligned = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "<thought_digest turn=1>ok</thought_digest>Hi there."},
    ]
    assert engine.verify_prompt_cache_prefix_alignment(messages_aligned, system_text) is True

    # Corrupted system message
    messages_corrupted = [
        {"role": "system", "content": "Corrupted prefix text"},
        {"role": "user", "content": "Hello"},
    ]
    assert engine.verify_prompt_cache_prefix_alignment(messages_corrupted, system_text) is False


def test_collapse_mode_variants() -> None:
    """Verify FULL_RETAIN and DIGEST_ONLY mode variants operate as expected."""
    # 1. Full retain mode
    engine_retain = ReasoningStreamCollapseEngine(
        ReasoningCollapseConfig(mode=ThinkingCollapseMode.FULL_RETAIN)
    )
    long_think = (
        "Detailed reasoning about physics simulation. First analyze particle velocity and tensor field. "
        "Next verify kinematic stability under high friction. Therefore, set gravity to 9.8."
    )
    msgs = [
        {"role": "system", "content": "Sim system."},
        {"role": "assistant", "content": f"<think>{long_think}</think>Gravity calibrated."},
    ]
    processed_retain, report_retain = engine_retain.collapse_historical_messages(
        session_id="sess-retain",
        messages=msgs,
        active_turn_index=1,
    )
    assert report_retain.tokens_saved == 0
    assert "<think>" in processed_retain[1]["content"]

    # 2. Digest only mode (collapses even active turn)
    engine_digest = ReasoningStreamCollapseEngine(
        ReasoningCollapseConfig(mode=ThinkingCollapseMode.DIGEST_ONLY, min_tokens_to_collapse=5)
    )
    processed_digest, report_digest = engine_digest.collapse_historical_messages(
        session_id="sess-digest",
        messages=msgs,
        active_turn_index=1,
    )
    assert report_digest.tokens_saved > 0
    assert "<thought_digest" in processed_digest[1]["content"]
