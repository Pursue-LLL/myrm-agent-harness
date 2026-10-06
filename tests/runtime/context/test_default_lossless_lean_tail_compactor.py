"""Comprehensive unit tests for Default Lossless Lean-Tail Conversation Compactor."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.default_lossless_lean_tail_compactor import (
    DefaultLosslessLeanTailCompactor,
)
from myrm_agent_harness.runtime.context.lossless_lean_tail_types import (
    LosslessCompactorConfig,
    MessageImportanceTier,
)
from myrm_agent_harness.runtime.context.message_importance_classifier import (
    MessageImportanceClassifier,
)


def test_message_importance_classification() -> None:
    """Verify messages are correctly classified into CRITICAL, HIGH, MEDIUM, and VOLATILE tiers."""
    classifier = MessageImportanceClassifier(
        LosslessCompactorConfig(
            tool_output_length_threshold=200,
            protected_recent_turns=1,
            always_preserve_initial_user_prompt=True,
        )
    )

    messages = [
        {"role": "system", "content": "You are a senior fullstack engineer."},
        {"role": "user", "content": "Initial user task directive: build auth system."},
        {"role": "assistant", "content": "I will examine the repo files."},
        {
            "role": "tool",
            "name": "read_file",
            "content": "BULKY_TOOL_RESULT_" * 50,  # > 200 chars, older turn -> VOLATILE
        },
        {"role": "assistant", "content": "Files inspected. Now writing models."},
        {"role": "user", "content": "Latest user follow-up prompt."},  # Recent turn -> HIGH
    ]

    classified = classifier.classify_messages(messages)
    assert len(classified) == 6
    assert classified[0].importance == MessageImportanceTier.CRITICAL
    assert classified[1].importance == MessageImportanceTier.CRITICAL
    assert classified[2].importance == MessageImportanceTier.MEDIUM
    assert classified[3].importance == MessageImportanceTier.VOLATILE
    assert classified[4].importance == MessageImportanceTier.HIGH
    assert classified[5].importance == MessageImportanceTier.HIGH


def test_lossless_tool_lean_reducer() -> None:
    """Verify bulky historical tool results are condensed without LLM API overhead."""
    compactor = DefaultLosslessLeanTailCompactor(
        LosslessCompactorConfig(
            tool_output_length_threshold=100,
            protected_recent_turns=1,
            enable_tool_lean_reducer=True,
        )
    )

    messages = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "Task start."},
        {
            "role": "tool",
            "name": "grep",
            "content": "MATCH_LINE_ITEM\n" * 80,  # ~1200 chars -> VOLATILE
        },
        {"role": "assistant", "content": "Grep completed."},
        {"role": "user", "content": "Recent question."},
    ]

    compacted, stats = compactor.compact_conversation(messages)
    assert len(compacted) == 5
    tool_msg = compacted[2]
    assert "[Tool Result Lean Reducer:" in tool_msg["content"]
    assert "status: completed" in tool_msg["content"]
    assert stats.volatile_tool_outputs_reduced == 1
    assert stats.tokens_saved_estimate > 100


def test_initial_user_prompt_absolute_verbatim_preservation() -> None:
    """Verify initial user prompt is NEVER compacted, truncated or modified."""
    compactor = DefaultLosslessLeanTailCompactor()

    initial_prompt = "CRITICAL NON-NEGOTIABLE OBJECTIVE: Build zero-trust proxy with 0 Any."
    messages = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": initial_prompt},
        {"role": "assistant", "content": "Understood."},
        {
            "role": "tool",
            "name": "bash",
            "content": "A" * 800,
        },
        {"role": "assistant", "content": "Bash done."},
        {"role": "user", "content": "Next step."},
    ]

    compacted, _ = compactor.compact_conversation(messages)
    assert compacted[1]["content"] == initial_prompt


def test_core_constraint_anchoring() -> None:
    """Verify core constraints are permanently anchored in system prompt block."""
    compactor = DefaultLosslessLeanTailCompactor(
        LosslessCompactorConfig(enable_core_constraint_anchoring=True)
    )

    messages = [
        {"role": "system", "content": "You are a code agent."},
        {"role": "user", "content": "Do not delete production tables."},
        {"role": "assistant", "content": "Acknowledged."},
    ]

    compacted, stats = compactor.compact_conversation(messages)
    assert "<core_task_constraints>" in compacted[0]["content"]
    assert "Do not delete production tables." in compacted[0]["content"]
    assert stats.anchors_preserved_count == 1


def test_reduction_percentage_and_stats() -> None:
    """Verify significant reduction percentage (50%~70%) on long tool-heavy sessions."""
    compactor = DefaultLosslessLeanTailCompactor(
        LosslessCompactorConfig(
            tool_output_length_threshold=200,
            protected_recent_turns=1,
        )
    )

    # Construct conversation with 3 large historical tool dumps
    messages = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "Analyze logs."},
        {"role": "tool", "content": "LOG_ENTRY_DATA_DUMP_" * 150},   # ~3000 chars
        {"role": "assistant", "content": "Log 1 analyzed. Fetching log 2."},
        {"role": "tool", "content": "LOG_ENTRY_DATA_DUMP_" * 150},   # ~3000 chars
        {"role": "assistant", "content": "Log 2 analyzed. Fetching log 3."},
        {"role": "tool", "content": "LOG_ENTRY_DATA_DUMP_" * 150},   # ~3000 chars
        {"role": "assistant", "content": "All logs collected."},
        {"role": "user", "content": "What is the final summary?"},
    ]

    _, stats = compactor.compact_conversation(messages)
    assert stats.volatile_tool_outputs_reduced == 3
    assert stats.reduction_percentage >= 50.0
    assert stats.tokens_saved_estimate > 1500
