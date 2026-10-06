"""Unit tests for reasoning-preserving context compactor and token compression governor."""

from myrm_agent_harness.runtime.context.reasoning_anchor_extractor import (
    ReasoningAnchorExtractor,
)
from myrm_agent_harness.runtime.context.reasoning_compactor_types import (
    CompactionTier,
    TieredTokenBudget,
)
from myrm_agent_harness.runtime.context.tiered_token_compression_governor import (
    TieredTokenCompressionGovernor,
)


def test_reasoning_anchor_extractor_distillation() -> None:
    """Test extracting hypothesis, counter-arguments, and deduction from lengthy thoughts."""
    extractor = ReasoningAnchorExtractor()
    verbose_filler = (
        "We need to carefully analyze the memory implications of caching.\n"
        "Let's check if the network topology allows low-latency RPC calls.\n"
        "Looking into Redis connection pooling and cluster mode replication.\n"
        "Testing various failover scenarios under simulated network partitions.\n"
        "Considering throughput requirements for up to 100k requests per second.\n"
    ) * 4
    raw_thinking = (
        "<thinking>\n"
        f"{verbose_filler}\n"
        "Let's assume the user wants an in-memory caching layer for redis.\n"
        f"{verbose_filler}\n"
        "However, this fails because distributed consistency cannot be guaranteed without Redis Sentinel.\n"
        f"{verbose_filler}\n"
        "Therefore, we must adopt an external distributed cache pattern instead.\n"
        "</thinking>"
    )

    anchor = extractor.extract_anchor(turn_index=2, raw_reasoning=raw_thinking)

    assert anchor.turn_index == 2
    assert "in-memory caching layer" in anchor.core_hypothesis
    assert "distributed consistency cannot be guaranteed" in anchor.key_counter_arguments
    assert "external distributed cache pattern" in anchor.finalized_deduction
    assert anchor.original_tokens_est > anchor.condensed_tokens_est

    rendered = extractor.render_condensed_anchor_block(anchor)
    assert '<reasoning_anchor turn="2">' in rendered
    assert "<hypothesis>" in rendered
    assert "<counter_argument>" in rendered
    assert "<deduction>" in rendered


def test_tiered_compaction_within_budget_no_op() -> None:
    """Test that conversations within budget are untouched."""
    governor = TieredTokenCompressionGovernor()
    turns = [
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there, how can I help?"},
    ]

    budget = TieredTokenBudget(max_total_tokens=1000)
    result = governor.govern_and_compact(turns, budget=budget)

    assert len(result.tiers_applied) == 0
    assert result.reasoning_anchors_count == 0
    assert len(result.compacted_turns) == 2
    assert result.compacted_turns[0].content == "Hello!"


def test_tiered_compaction_tier1_and_tier3_reasoning_preservation() -> None:
    """Test that older turns have tools folded and reasoning anchored while recent turns are protected."""
    governor = TieredTokenCompressionGovernor()
    turns = [
        # Turn 0 (Old): Has lengthy reasoning and tool calls
        {
            "role": "assistant",
            "content": "Done processing.",
            "thought": (
                "Hypothesis: the bug is in the token counter.\n"
                "Wait, this fails because tests pass for ascii text.\n"
                "Therefore, we decide to audit unicode handling."
            ),
            "tool_calls": [{"name": "run_command", "args": {"cmd": "pytest"}}],
        },
        # Turn 1 (Old): Assistant response
        {
            "role": "user",
            "content": "What about turn 1?",
        },
        # Turn 2 (Recent protected): Lengthy reasoning must NOT be stripped or condensed
        {
            "role": "assistant",
            "content": "Current active response.",
            "thought": "Let's first inspect turn 2 reasoning directly.",
        },
    ]

    # Set small reasoning budget to trigger Tier 3
    budget = TieredTokenBudget(
        max_total_tokens=1000,
        max_reasoning_tokens=20,  # Forces Tier 3
        retain_recent_turns=1,    # Only Turn 2 protected
    )

    result = governor.govern_and_compact(turns, budget=budget)

    assert CompactionTier.TIER_1_TOOLS in result.tiers_applied
    assert CompactionTier.TIER_3_REASONING in result.tiers_applied
    assert result.reasoning_anchors_count == 1  # Turn 0 anchored

    # Turn 0 has reasoning anchor
    assert result.compacted_turns[0].reasoning_anchor is not None
    assert "<reasoning_anchor" in result.compacted_turns[0].content
    assert result.compacted_turns[0].tool_calls_summary == "[Folded 1 tool calls: run_command]"

    # Turn 2 (Protected) keeps full reasoning block intact
    assert result.compacted_turns[2].reasoning_anchor is None
    assert "<reasoning>" in result.compacted_turns[2].content
    assert "inspect turn 2 reasoning directly" in result.compacted_turns[2].content


def test_tiered_compaction_tier2_image_degradation() -> None:
    """Test that older multimodal images are degraded when exceeding image token budget."""
    governor = TieredTokenCompressionGovernor()
    fake_b64_img = "data:image/png;base64," + "A" * 8000

    turns = [
        {"role": "user", "content": f"Look at this screenshot: {fake_b64_img}"},
        {"role": "assistant", "content": "I see the screenshot."},
        {"role": "user", "content": "Active question."},
    ]

    budget = TieredTokenBudget(
        max_total_tokens=10000,
        max_image_tokens=100,  # Forces Tier 2
        retain_recent_turns=1,
    )

    result = governor.govern_and_compact(turns, budget=budget)

    assert CompactionTier.TIER_2_IMAGES in result.tiers_applied
    assert result.compacted_turns[0].is_image_degraded is True
    assert "[Image degraded: base64 omitted" in result.compacted_turns[0].content


def test_tiered_compaction_tier4_fallback_text_truncation() -> None:
    """Test fallback truncation on historical turns when total budget is severely tight."""
    governor = TieredTokenCompressionGovernor()
    long_history = "A" * 4000

    turns = [
        {"role": "user", "content": long_history},
        {"role": "assistant", "content": "Understood."},
    ]

    budget = TieredTokenBudget(
        max_total_tokens=200,  # Extremely strict
        retain_recent_turns=1,
    )

    result = governor.govern_and_compact(turns, budget=budget)

    assert CompactionTier.TIER_4_TEXT_CUT in result.tiers_applied
    assert "[Truncated past content]" in result.compacted_turns[0].content
