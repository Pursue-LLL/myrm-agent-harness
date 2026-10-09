"""Comprehensive tests for PromptCacheLookbackPositionAlignedPruneFloorSuite.

[INPUT]
- lookback_aligned_prune package contracts and implementations.

[OUTPUT]
- Deterministic verification of provider emitted content block projections,
  conservative lookback floor calculation, and cache-preserving prune gating.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_lookback_aligned_prune_suite.py
"""

from typing import Dict, List

import pytest

from myrm_agent_harness.agent.context_management.lookback_aligned_prune import (
    ContentBlockKind,
    LookbackAlignedPruneConfig,
    LookbackAlignedPruner,
    LookbackFloorCalculator,
    LookbackFloorResult,
    LookbackPruneDecision,
    ProjectedContentBlock,
    PromptCacheLookbackPositionAlignedPruneFloorSuite,
    ProviderBlockProjector,
    ProviderCacheKind,
)


def test_provider_block_projector_discrete_blocks() -> None:
    """Verifies that conversation turns correctly expand into discrete emitted blocks."""
    projector = ProviderBlockProjector()

    messages: List[Dict[str, str]] = [
        # Msg 0: User text
        {"role": "user", "content": "Analyze system load."},
        # Msg 1: Assistant calling two tools concurrently
        {"role": "assistant", "content": "I will run diagnostics.", "tool_calls": "top,vmstat"},
        # Msg 2: Tool result 1
        {"role": "tool", "content": "CPU: 45%, Mem: 80%", "tool_name": "top"},
        # Msg 3: Tool result 2
        {"role": "tool", "content": "swap: 0%", "tool_name": "vmstat"},
        # Msg 4: User attaching image and file reference
        {
            "role": "user",
            "content": "Check this screenshot.",
            "has_image": "true",
            "has_file_ref": "true",
        },
    ]

    projected = projector.project_messages(messages)

    # Breakdown:
    # Msg 0: 1 text block
    # Msg 1: 1 text block + 2 tool_use blocks = 3 blocks
    # Msg 2: 1 tool_result block (prunable)
    # Msg 3: 1 tool_result block (prunable)
    # Msg 4: 1 image + 1 file_ref + 1 text = 3 blocks
    # Total = 1 + 3 + 1 + 1 + 3 = 9 blocks
    assert len(projected) == 9

    # Check block kinds
    assert projected[0].block_kind == ContentBlockKind.TEXT
    assert projected[1].block_kind == ContentBlockKind.TEXT
    assert projected[2].block_kind == ContentBlockKind.TOOL_USE
    assert projected[3].block_kind == ContentBlockKind.TOOL_USE
    assert projected[4].block_kind == ContentBlockKind.TOOL_RESULT
    assert projected[4].is_prunable_tool_output is True
    assert projected[5].block_kind == ContentBlockKind.TOOL_RESULT
    assert projected[5].is_prunable_tool_output is True
    assert projected[6].block_kind == ContentBlockKind.IMAGE
    assert projected[7].block_kind == ContentBlockKind.FILE_REFERENCE
    assert projected[8].block_kind == ContentBlockKind.TEXT


def test_lookback_floor_calculator_anthropic_and_openai() -> None:
    """Verifies lookback window sizing, headroom buffer addition, and floor boundaries."""
    config = LookbackAlignedPruneConfig(
        default_lookback_positions=20,
        reserved_headroom_positions=6,
    )
    calculator = LookbackFloorCalculator(config=config)

    # Create synthetic sequence of 30 blocks across 10 messages (3 blocks per message)
    synthetic_blocks: List[ProjectedContentBlock] = []
    for m_idx in range(10):
        for b_idx in range(3):
            synthetic_blocks.append(
                ProjectedContentBlock(
                    message_index=m_idx,
                    block_kind=ContentBlockKind.TEXT,
                    token_count=100,
                    is_prunable_tool_output=False,
                )
            )

    # Total blocks = 30
    # Anthropic lookback = 20, headroom = 6 -> window = min(30, 26) = 26
    # floor_block_idx = 30 - 26 = 4 -> block 4 belongs to message_index = 4 // 3 = 1
    floor_anthropic = calculator.calculate_floor(synthetic_blocks, provider_name="anthropic")
    assert floor_anthropic.total_projected_blocks == 30
    assert floor_anthropic.lookback_window_positions == 20
    assert floor_anthropic.reserved_headroom_positions == 6
    assert floor_anthropic.protected_floor_block_index == 4
    assert floor_anthropic.protected_floor_message_index == 1

    # Empty blocks check
    floor_empty = calculator.calculate_floor([], provider_name="anthropic")
    assert floor_empty.total_projected_blocks == 0
    assert floor_empty.protected_floor_message_index == 0


def test_lookback_aligned_pruner_protects_cache_window() -> None:
    """Verifies that pruning candidates inside the lookback window are strictly forbidden."""
    pruner = LookbackAlignedPruner()

    blocks = [
        # Msg 0: Older prunable tool result (outside floor)
        ProjectedContentBlock(
            message_index=0,
            block_kind=ContentBlockKind.TOOL_RESULT,
            token_count=1500,
            is_prunable_tool_output=True,
        ),
        # Msg 1: Text
        ProjectedContentBlock(
            message_index=1,
            block_kind=ContentBlockKind.TEXT,
            token_count=100,
            is_prunable_tool_output=False,
        ),
        # Msg 2: Recent prunable tool result (inside protected floor)
        ProjectedContentBlock(
            message_index=2,
            block_kind=ContentBlockKind.TOOL_RESULT,
            token_count=2000,
            is_prunable_tool_output=True,
        ),
    ]

    floor = LookbackFloorResult(
        total_projected_blocks=3,
        lookback_window_positions=20,
        reserved_headroom_positions=6,
        protected_floor_message_index=2,  # Floor protects msg 2 and newer
        protected_floor_block_index=2,
        diagnostic_reason="Test floor",
    )

    decisions = pruner.evaluate_pruning_candidates(blocks, floor_result=floor)
    assert len(decisions) == 2

    # Msg 0: Outside floor -> allowed to prune
    d0 = decisions[0]
    assert d0.message_index == 0
    assert d0.can_prune is True
    assert d0.is_protected_by_floor is False
    assert d0.estimated_saved_tokens == 1500

    # Msg 2: Inside floor -> forbidden to prune (protected)
    d2 = decisions[1]
    assert d2.message_index == 2
    assert d2.can_prune is False
    assert d2.is_protected_by_floor is True
    assert d2.estimated_saved_tokens == 0
    assert "Pruning forbidden to prevent cache rupture" in d2.reason


def test_prompt_cache_lookback_aligned_prune_suite_facade() -> None:
    """Verifies full end-to-end flow of PromptCacheLookbackPositionAlignedPruneFloorSuite."""
    suite = PromptCacheLookbackPositionAlignedPruneFloorSuite()

    # Create a realistic multi-turn conversation
    messages: List[Dict[str, str]] = []

    # Old turns: 0 to 4
    for i in range(5):
        messages.append({"role": "user", "content": f"Task {i}"})
        messages.append({"role": "assistant", "content": f"Running {i}", "tool_calls": f"tool_{i}"})
        messages.append({"role": "tool", "content": f"Output of tool {i}", "tool_name": f"tool_{i}"})

    # Recent turns: 5 to 15
    for i in range(5, 16):
        messages.append({"role": "user", "content": f"Recent query {i}"})
        messages.append({"role": "assistant", "content": f"Result {i}", "tool_calls": f"tool_{i}"})
        messages.append({"role": "tool", "content": f"Output of recent tool {i}", "tool_name": f"tool_{i}"})

    decisions = suite.evaluate_safe_prune_decisions(
        messages=messages,
        provider_name="anthropic",
    )

    # Some older tool messages are eligible for pruning
    can_prune_items = [d for d in decisions if d.can_prune]
    assert len(can_prune_items) > 0

    # The most recent tool messages MUST be protected
    protected_items = [d for d in decisions if d.is_protected_by_floor]
    assert len(protected_items) > 0

    # The latest tool message in the conversation must be in the protected window
    latest_msg_idx = len(messages) - 1
    assert suite.is_message_in_cache_lookback_window(messages, latest_msg_idx, "anthropic") is True

    # The earliest tool message is outside the lookback window
    assert suite.is_message_in_cache_lookback_window(messages, 2, "anthropic") is False
