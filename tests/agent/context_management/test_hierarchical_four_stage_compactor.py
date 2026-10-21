# ============================================================================
# Unit Tests for HierarchicalFourStageCompactor (Item 154)
# Verifies priority tool budget trimming, segmented dialogue compaction,
# core asset & goal invariant enforcement, and memory-only view derivation.
# ============================================================================

from __future__ import annotations

from myrm_agent_harness.agent.context_management.pipeline.hierarchical_compaction import (
    CompactionStage,
    HierarchicalCompactionConfig,
    HierarchicalFourStageCompactor,
    MessageRole,
    PipelineMessage,
)


def test_under_budget_direct_view_derivation() -> None:
    """Verifies that within-budget sessions skip lossy compression and derive view directly."""
    config = HierarchicalCompactionConfig(max_context_chars=5000)
    compactor = HierarchicalFourStageCompactor(config=config)

    messages = [
        PipelineMessage(
            message_id="sys-1",
            role=MessageRole.SYSTEM,
            content="You are an expert AI architect.",
            is_system=True,
        ),
        PipelineMessage(
            message_id="u-1",
            role=MessageRole.USER,
            content="Hello!",
        ),
        PipelineMessage(
            message_id="a-1",
            role=MessageRole.ASSISTANT,
            content="Greetings! How can I assist you today?",
        ),
    ]

    view = compactor.compact(messages)

    assert len(view.derived_messages) == 3
    assert view.metrics.initial_chars == view.metrics.final_chars
    assert view.metrics.reduction_ratio == 0.0
    assert CompactionStage.STAGE_1_TOOL_TRIM not in view.metrics.stages_applied
    assert CompactionStage.STAGE_3_CORE_ASSET_PROTECTION in view.metrics.stages_applied
    assert CompactionStage.STAGE_4_VIEW_DERIVATION in view.metrics.stages_applied


def test_stage_1_tool_result_budget_trimming_priority() -> None:
    """Verifies that giant tool outputs are trimmed first without invoking model summary."""
    config = HierarchicalCompactionConfig(
        max_context_chars=5000,
        tool_result_budget_chars=400,
        tool_result_head_lines=3,
        tool_result_tail_lines=3,
    )
    compactor = HierarchicalFourStageCompactor(config=config)

    # 10 bloated tool results with 100 lines each (~2000 chars each = 20,000 chars)
    giant_lines = [f"log line {i}: process trace details with extra padding info" for i in range(100)]
    giant_content = "\n".join(giant_lines)

    messages: list[PipelineMessage] = [
        PipelineMessage(
            message_id="sys-1",
            role=MessageRole.SYSTEM,
            content="System instructions",
            is_system=True,
        )
    ]

    for idx in range(10):
        messages.append(
            PipelineMessage(
                message_id=f"tool-{idx}",
                role=MessageRole.TOOL,
                content=giant_content,
                tool_name="run_command",
            )
        )

    view = compactor.compact(messages)

    # Stage 1 must be applied
    assert CompactionStage.STAGE_1_TOOL_TRIM in view.metrics.stages_applied
    # Stage 2 must NOT be applied since Stage 1 brought it within budget (5000 chars)
    assert CompactionStage.STAGE_2_SEGMENTED_HISTORY not in view.metrics.stages_applied
    assert view.metrics.trimmed_tools_count == 10
    assert view.metrics.reduction_ratio > 0.5

    # Check trimmed tool output structure
    first_tool_msg = view.derived_messages[1]
    assert "[TRUNCATED:" in first_tool_msg.content
    assert "Restore Hint: run_command" in first_tool_msg.content
    assert "log line 0:" in first_tool_msg.content
    assert "log line 99:" in first_tool_msg.content


def test_stage_2_segmented_history_compaction_when_still_bloated() -> None:
    """Verifies that when tool trimming alone is insufficient, early turns are compacted."""
    config = HierarchicalCompactionConfig(
        max_context_chars=1200,
        tool_result_budget_chars=300,
        keep_recent_turns=2,  # Keep last 2 turns (4 messages)
    )
    compactor = HierarchicalFourStageCompactor(config=config)

    messages: list[PipelineMessage] = [
        PipelineMessage(
            message_id="sys-1",
            role=MessageRole.SYSTEM,
            content="System prompt invariant",
            is_system=True,
        )
    ]

    # Add 6 turns (12 messages) with substantial conversational text
    for t in range(6):
        messages.append(
            PipelineMessage(
                message_id=f"u-{t}",
                role=MessageRole.USER,
                content=f"User prompt turn {t}: " + "detailed requirement " * 15,
            )
        )
        messages.append(
            PipelineMessage(
                message_id=f"a-{t}",
                role=MessageRole.ASSISTANT,
                content=f"Agent response turn {t}: " + "architectural plan " * 15,
            )
        )

    view = compactor.compact(messages)

    # Stage 2 must have been applied
    assert CompactionStage.STAGE_2_SEGMENTED_HISTORY in view.metrics.stages_applied
    assert view.metrics.compressed_turns_count > 0
    assert view.summary_block is not None
    assert "<compacted_history_summary>" in view.summary_block

    # Recent 2 turns (last 4 dialogue messages) must be preserved intact
    msg_ids = [m.message_id for m in view.derived_messages]
    assert "u-4" in msg_ids
    assert "a-4" in msg_ids
    assert "u-5" in msg_ids
    assert "a-5" in msg_ids


def test_stage_3_core_assets_and_goals_invariant_protection() -> None:
    """Verifies that system instructions, goals, and pinned items cannot be erased."""
    config = HierarchicalCompactionConfig(max_context_chars=500)
    compactor = HierarchicalFourStageCompactor(config=config)

    messages = [
        PipelineMessage(
            message_id="sys-root",
            role=MessageRole.SYSTEM,
            content="Crucial system guidelines",
            is_system=True,
        ),
        PipelineMessage(
            message_id="goal-card",
            role=MessageRole.SYSTEM,
            content="Pending Goal: Refactor auth system",
            is_goal_state=True,
        ),
        PipelineMessage(
            message_id="pin-key-decision",
            role=MessageRole.USER,
            content="Pinned: Database must be SQLite",
            is_pinned=True,
        ),
        PipelineMessage(
            message_id="bloated-tool",
            role=MessageRole.TOOL,
            content="huge output " * 500,
            tool_name="bash",
        ),
    ]

    view = compactor.compact(messages)

    derived_ids = {m.message_id for m in view.derived_messages}
    assert "sys-root" in derived_ids
    assert "goal-card" in derived_ids
    assert "pin-key-decision" in derived_ids


def test_stage_4_view_level_immutability_and_storage_decoupling() -> None:
    """Verifies that original messages are strictly unmutated (compaction only in derived view)."""
    config = HierarchicalCompactionConfig(
        max_context_chars=500,
        tool_result_budget_chars=100,
    )
    compactor = HierarchicalFourStageCompactor(config=config)

    raw_tool_content = "initial original untouched tool output " * 30
    orig_msg = PipelineMessage(
        message_id="tool-orig",
        role=MessageRole.TOOL,
        content=raw_tool_content,
        tool_name="grep",
    )
    messages = [orig_msg]

    view = compactor.compact(messages)

    # Derived message is trimmed
    assert "[TRUNCATED:" in view.derived_messages[0].content

    # Original message MUST remain completely untouched
    assert orig_msg.content == raw_tool_content
    assert "[TRUNCATED:" not in orig_msg.content


def test_compaction_dataclass_serialization() -> None:
    """Verifies dictionary serialization across all typed data structures."""
    msg = PipelineMessage(
        message_id="m-1",
        role=MessageRole.USER,
        content="hello",
        is_pinned=True,
    )
    m_dict = msg.to_dict()
    assert m_dict["message_id"] == "m-1"
    assert m_dict["role"] == "user"
    assert m_dict["is_pinned"] is True
