# [INPUT]: ContextBlockDescriptor, ContextTier, HiddenReasoningTokensPenetrationAuditor, MultiDimensionalSessionTokenLedger, PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite, PrefixCachingAlignedLayoutEngine, PrefixCachingLayoutConfig, TokenUsageBreakdown, TurnLedgerRecord
# [OUTPUT]: test_prefix_caching_ledger_suite.py
# [POS]: tests/agent/context_management/test_prefix_caching_ledger_suite.py

"""Comprehensive unit tests for PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite.

Verifies:
1. Strict three-tier prompt layout realignment and deterministic sorting within tiers.
2. Dynamic clock / timestamp leakage detection and demotion to prevent KV cache cache-busting.
3. Cryptographic prefix hash invariance across variable conversation turns.
4. Deep penetration of hidden reasoning tokens and cache read/write tokens across OpenAI, Claude, DeepSeek, and Gemini schemas.
5. Multi-dimensional session token ledger accumulation, cost savings computation, and health anomaly diagnosis.
6. Unified facade end-to-end orchestration and ledger lifecycle isolation.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.prefix_caching_ledger import (
    ContextBlockDescriptor,
    ContextTier,
    HiddenReasoningTokensPenetrationAuditor,
    MultiDimensionalSessionTokenLedger,
    PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite,
    PrefixCachingAlignedLayoutEngine,
    PrefixCachingLayoutConfig,
    TokenUsageBreakdown,
    TurnLedgerRecord,
)


def test_prefix_caching_layout_alignment_and_ordering() -> None:
    """Verifies that unsorted context blocks are realigned to Tier 1 -> Tier 2 -> Tier 3 strictly."""
    engine = PrefixCachingAlignedLayoutEngine()

    blocks = [
        ContextBlockDescriptor(
            block_id="b-user",
            tier=ContextTier.TIER3_DYNAMIC_TAIL,
            category="user_query",
            content="Can you summarize the project status?",
            sort_key="user_01",
            estimated_tokens=20,
        ),
        ContextBlockDescriptor(
            block_id="b-tool-b",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="tool_definition",
            content='{"name": "read_file"}',
            sort_key="read_file",
            estimated_tokens=50,
        ),
        ContextBlockDescriptor(
            block_id="b-sys",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="system_instruction",
            content="You are an expert AI software architect.",
            sort_key="00_system",
            estimated_tokens=30,
        ),
        ContextBlockDescriptor(
            block_id="b-tool-a",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="tool_definition",
            content='{"name": "bash"}',
            sort_key="bash",
            estimated_tokens=40,
        ),
        ContextBlockDescriptor(
            block_id="b-memory",
            tier=ContextTier.TIER2_SEMI_STATIC_PROJECT,
            category="project_memory",
            content="Architecture: Monorepo with Harness runtime.",
            sort_key="arch_memory",
            estimated_tokens=60,
        ),
        # Misplaced dynamic clock in Tier 1: should be automatically sanitized to Tier 3
        ContextBlockDescriptor(
            block_id="b-clock",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="dynamic_clock",
            content="Current time: 2026-10-08 16:30:00",
            sort_key="time_stamp",
            estimated_tokens=10,
        ),
    ]

    realigned = engine.realign_blocks(blocks)
    assert len(realigned) == 6

    # Tier 1 blocks must come first (system -> bash -> read_file)
    assert realigned[0].block_id == "b-sys"
    assert realigned[1].block_id == "b-tool-a"
    assert realigned[2].block_id == "b-tool-b"

    # Tier 2 block
    assert realigned[3].block_id == "b-memory"

    # Tier 3 blocks (dynamic clock must be demoted to Tier 3, followed by user query)
    assert realigned[4].tier == ContextTier.TIER3_DYNAMIC_TAIL
    assert realigned[5].tier == ContextTier.TIER3_DYNAMIC_TAIL
    assert any(b.block_id == "b-clock" for b in realigned[4:])

    # Token ratio verification
    ratio = engine.calculate_cacheable_ratio(blocks)
    assert ratio > 0.7  # Tier 1 + Tier 2 comprise >70% of tokens


def test_prefix_hash_stability_across_turns() -> None:
    """Verifies that Tier 1 prefix cryptographic hash remains 100% constant across multi-turn changes."""
    engine = PrefixCachingAlignedLayoutEngine()

    tier1_blocks = [
        ContextBlockDescriptor(
            block_id="sys",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="system",
            content="Core Prompt v1.0",
            sort_key="00",
        ),
        ContextBlockDescriptor(
            block_id="tools",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="tools",
            content="Tools Schema Manifest",
            sort_key="01",
        ),
    ]

    # Turn 1: user query A
    turn1_blocks = list(tier1_blocks) + [
        ContextBlockDescriptor(
            block_id="t1",
            tier=ContextTier.TIER3_DYNAMIC_TAIL,
            category="user",
            content="Hello Turn 1",
        )
    ]
    hash_turn1 = engine.compute_prefix_hash(turn1_blocks)

    # Turn 2: completely different user query B and semi-static memory update
    turn2_blocks = list(tier1_blocks) + [
        ContextBlockDescriptor(
            block_id="mem",
            tier=ContextTier.TIER2_SEMI_STATIC_PROJECT,
            category="memory",
            content="Added new project note",
        ),
        ContextBlockDescriptor(
            block_id="t2",
            tier=ContextTier.TIER3_DYNAMIC_TAIL,
            category="user",
            content="Hello Turn 2 with long payload",
        ),
    ]
    hash_turn2 = engine.compute_prefix_hash(turn2_blocks)

    # Hashes must be strictly identical (guarantees provider KV Cache hit!)
    assert hash_turn1 == hash_turn2

    # Modifying Tier 1 breaks the prefix hash
    turn3_mutated_tier1 = [
        ContextBlockDescriptor(
            block_id="sys",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="system",
            content="Core Prompt v1.1 (Modified)",
            sort_key="00",
        ),
        tier1_blocks[1],
    ]
    hash_turn3 = engine.compute_prefix_hash(turn3_mutated_tier1)
    assert hash_turn3 != hash_turn1


def test_hidden_reasoning_tokens_penetration_auditor() -> None:
    """Verifies deep extraction of hidden reasoning and KV cache tokens across heterogeneous providers."""
    auditor = HiddenReasoningTokensPenetrationAuditor()

    # 1. OpenAI format with completion_tokens_details.reasoning_tokens and prompt_tokens_details.cached_tokens
    openai_payload = {
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "prompt_tokens_details": {"cached_tokens": 800},
            "completion_tokens_details": {"reasoning_tokens": 350},
        }
    }
    b_openai = auditor.audit_raw_usage(openai_payload)
    assert b_openai.input_tokens == 1000
    assert b_openai.output_tokens == 500
    assert b_openai.reasoning_tokens == 350
    assert b_openai.cache_read_tokens == 800
    assert pytest.approx(b_openai.cache_hit_rate, 0.01) == 0.80
    assert pytest.approx(b_openai.reasoning_ratio, 0.01) == 0.70

    # 2. Anthropic format with thinking_tokens and cache_read_input_tokens
    anthropic_payload = {
        "usage": {
            "input_tokens": 2000,
            "output_tokens": 800,
            "cache_read_input_tokens": 1600,
            "cache_creation_input_tokens": 400,
            "output_tokens_details": {"thinking_tokens": 600},
        }
    }
    b_anthropic = auditor.audit_raw_usage(anthropic_payload)
    assert b_anthropic.input_tokens == 2000
    assert b_anthropic.output_tokens == 800
    assert b_anthropic.cache_read_tokens == 1600
    assert b_anthropic.cache_write_tokens == 400
    assert b_anthropic.reasoning_tokens == 600
    assert pytest.approx(b_anthropic.cache_hit_rate, 0.01) == 0.80

    # 3. DeepSeek format
    deepseek_payload = {
        "prompt_tokens": 3000,
        "completion_tokens": 1200,
        "prompt_cache_hit_tokens": 2700,
        "prompt_cache_miss_tokens": 300,
        "reasoning_tokens": 900,
    }
    b_deepseek = auditor.audit_raw_usage(deepseek_payload)
    assert b_deepseek.input_tokens == 3000
    assert b_deepseek.output_tokens == 1200
    assert b_deepseek.cache_read_tokens == 2700
    assert b_deepseek.cache_write_tokens == 300
    assert b_deepseek.reasoning_tokens == 900
    assert pytest.approx(b_deepseek.cache_hit_rate, 0.01) == 0.90

    # 4. Google Gemini format
    gemini_payload = {
        "prompt_token_count": 1500,
        "candidates_token_count": 400,
        "cached_content_token_count": 1200,
        "thoughts_token_count": 250,
    }
    b_gemini = auditor.audit_raw_usage(gemini_payload)
    assert b_gemini.input_tokens == 1500
    assert b_gemini.output_tokens == 400
    assert b_gemini.cache_read_tokens == 1200
    assert b_gemini.reasoning_tokens == 250


def test_multi_dimensional_session_token_ledger_accounting() -> None:
    """Verifies cumulative session accounting, cost savings calculation, and anomaly detection."""
    ledger = MultiDimensionalSessionTokenLedger(session_id="session-xyz")

    # Turn 1: Cold start (0 cache read)
    u1 = TokenUsageBreakdown(input_tokens=1000, output_tokens=300, reasoning_tokens=100, cache_read_tokens=0)
    ledger.record_turn("turn-1", "deepseek-r1", u1)

    # Turn 2: High cache hit rate (900 / 1000) with heavy reasoning
    u2 = TokenUsageBreakdown(input_tokens=1000, output_tokens=800, reasoning_tokens=600, cache_read_tokens=900)
    ledger.record_turn("turn-2", "deepseek-r1", u2)

    assert ledger.turn_count == 2
    agg = ledger.get_session_aggregate()
    assert agg.input_tokens == 2000
    assert agg.output_tokens == 1100
    assert agg.reasoning_tokens == 700
    assert agg.cache_read_tokens == 900

    # Test savings calculation: 900 tokens read from cache with 90% discount rate -> saves 810 tokens
    saved_tokens = ledger.estimate_effective_token_savings(discount_rate=0.9)
    assert saved_tokens == 810

    saved_pct = ledger.estimate_cost_savings_percentage(discount_rate=0.9)
    # (900 * 0.9) / 2000 = 810 / 2000 = 40.5%
    assert pytest.approx(saved_pct, 0.001) == 0.405

    # Health diagnostics
    health = ledger.diagnose_ledger_health()
    assert health["turn_count"] == 2
    assert health["total_tokens"] == 3100
    assert health["alert_high_reasoning_burn"] is True  # 700 / 1100 = 63.6% > 50%
    assert health["alert_cache_hit_drop"] is False  # cache_hit_rate is 45% > 40%


def test_facade_end_to_end_orchestration() -> None:
    """Verifies end-to-end facade coordinating prompt assembly and session ledger auditing."""
    suite = PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite()

    blocks = [
        ContextBlockDescriptor(
            block_id="b-inst",
            tier=ContextTier.TIER1_STATIC_PREFIX,
            category="system",
            content="System Instructions Block",
            sort_key="00",
        ),
        ContextBlockDescriptor(
            block_id="b-query",
            tier=ContextTier.TIER3_DYNAMIC_TAIL,
            category="user",
            content="User Question Block",
            sort_key="99",
        ),
    ]

    prompt_text, p_hash = suite.assemble_aligned_prompt(blocks)
    assert "System Instructions Block" in prompt_text
    assert "User Question Block" in prompt_text
    assert len(p_hash) == 64  # SHA-256 length

    # Record turn with raw OpenAI dict
    raw_response = {
        "usage": {
            "prompt_tokens": 1200,
            "completion_tokens": 400,
            "prompt_tokens_details": {"cached_tokens": 1000},
            "completion_tokens_details": {"reasoning_tokens": 250},
        }
    }

    record = suite.audit_and_record_turn(
        session_id="sess-alpha",
        turn_id="turn-1",
        model_name="o1-preview",
        raw_usage=raw_response,
    )

    assert record.turn_id == "turn-1"
    assert record.prefix_cache_hit is True
    assert record.usage.cache_read_tokens == 1000
    assert record.usage.reasoning_tokens == 250

    # Aggregate and health check
    agg = suite.get_session_aggregate("sess-alpha")
    assert agg.input_tokens == 1200

    report = suite.diagnose_session_health("sess-alpha")
    assert report["session_id"] == "sess-alpha"
    assert report["turn_count"] == 1

    # Cleanup
    assert suite.remove_session_ledger("sess-alpha") is True
    assert suite.get_or_create_ledger("sess-alpha").turn_count == 0
