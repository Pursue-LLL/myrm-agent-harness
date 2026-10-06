"""Unit tests for model-free deterministic tool result pruner and zero-cost context compactor."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.internal_external_message_pipeline_types import (
    AgentMessage,
    AgentMessageKind,
)
from myrm_agent_harness.runtime.context.model_free_tool_pruner import (
    ModelFreeDeterministicToolResultPruner,
)
from myrm_agent_harness.runtime.context.model_free_tool_pruner_types import (
    ModelFreePrunerConfig,
)


@pytest.fixture
def pruner() -> ModelFreeDeterministicToolResultPruner:
    return ModelFreeDeterministicToolResultPruner()


def test_recent_immune_turns_preservation(
    pruner: ModelFreeDeterministicToolResultPruner,
) -> None:
    """Validate that the most recent N tool execution outputs are strictly immune to pruning."""
    large_payload = "LINE OF OUTPUT\n" * 50  # ~750 chars

    messages = [
        AgentMessage(message_id="u1", kind=AgentMessageKind.USER, content="Step 1"),
        AgentMessage(
            message_id="t1",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="read_file",
            content=large_payload,
        ),
        AgentMessage(message_id="u2", kind=AgentMessageKind.USER, content="Step 2"),
        AgentMessage(
            message_id="t2",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="read_file",
            content=large_payload,
        ),
        AgentMessage(message_id="u3", kind=AgentMessageKind.USER, content="Step 3"),
        AgentMessage(
            message_id="t3",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="read_file",
            content=large_payload,
        ),
    ]

    config = ModelFreePrunerConfig(recent_immune_turns=2, min_prune_char_threshold=100)
    pruned, report = pruner.prune_messages(messages, config)

    assert len(pruned) == 6
    # t1 is historical -> folded
    assert "[Tool 'read_file' succeeded:" in pruned[1].content
    # t2 and t3 are in the recent immune window -> preserved in full
    assert pruned[3].content == large_payload
    assert pruned[5].content == large_payload
    assert report.tools_pruned_count == 1


def test_historical_readonly_tool_folding(
    pruner: ModelFreeDeterministicToolResultPruner,
) -> None:
    """Validate zero-cost algorithmic folding of historical successful tool outputs."""
    verbose_dump = "DEBUG LOG: scanning dependency tree node...\n" * 60

    messages = [
        AgentMessage(
            message_id="t_hist",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="read_file",
            content=verbose_dump,
        ),
        # Add two dummy tool turns at the end to make t_hist historical
        AgentMessage(
            message_id="t_recent1",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="active_tool",
            content="short output",
        ),
        AgentMessage(
            message_id="t_recent2",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="active_tool",
            content="short output",
        ),
    ]

    pruned, report = pruner.prune_messages(messages)

    assert "[Tool 'read_file' succeeded: 60 lines folded" in pruned[0].content
    assert report.chars_freed > 1000
    assert report.tokens_freed_estimate > 200
    assert report.savings_ratio > 0.5


def test_error_signal_preservation(
    pruner: ModelFreeDeterministicToolResultPruner,
) -> None:
    """Validate that failed tools preserve critical stack trace and error tail without data loss."""
    early_logs = "STEP INIT: compiling packages...\n" * 40
    critical_error_lines = [
        "Traceback (most recent call last):",
        "  File '/src/app.py', line 102, in run",
        "    raise DatabaseConnectionTimeout('TCP 5432 timed out after 30s')",
        "DatabaseConnectionTimeout: TCP 5432 timed out after 30s",
    ]
    full_error_content = early_logs + "\n".join(critical_error_lines)

    messages = [
        AgentMessage(
            message_id="t_err",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="run_tests",
            content=full_error_content,
            is_error=True,
        ),
        AgentMessage(
            message_id="t_rec1",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="inspect",
            content="active",
        ),
        AgentMessage(
            message_id="t_rec2",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="inspect",
            content="active",
        ),
    ]

    config = ModelFreePrunerConfig(error_tail_lines=4, min_prune_char_threshold=100)
    pruned, report = pruner.prune_messages(messages, config)

    assert "[Tool 'run_tests' failed:" in pruned[0].content
    assert "preserving last 4 error lines]" in pruned[0].content
    assert "DatabaseConnectionTimeout: TCP 5432 timed out after 30s" in pruned[0].content
    assert "STEP INIT: compiling packages..." not in pruned[0].content
    assert report.tools_pruned_count == 1


def test_small_output_not_pruned(
    pruner: ModelFreeDeterministicToolResultPruner,
) -> None:
    """Validate that outputs under character threshold are skipped to preserve context."""
    short_content = "commit 78b86389\nAuthor: myrm\n"

    messages = [
        AgentMessage(
            message_id="t_short",
            kind=AgentMessageKind.TOOL_EXECUTION,
            tool_name="git_log",
            content=short_content,
        ),
        AgentMessage(message_id="t_rec1", kind=AgentMessageKind.TOOL_EXECUTION, tool_name="x", content="1"),
        AgentMessage(message_id="t_rec2", kind=AgentMessageKind.TOOL_EXECUTION, tool_name="y", content="2"),
    ]

    config = ModelFreePrunerConfig(min_prune_char_threshold=300)
    pruned, report = pruner.prune_messages(messages, config)

    assert pruned[0].content == short_content
    assert report.tools_pruned_count == 0


def test_non_tool_messages_untouched(
    pruner: ModelFreeDeterministicToolResultPruner,
) -> None:
    """Validate that user and assistant conversational turns are completely unmodified."""
    messages = [
        AgentMessage(message_id="u1", kind=AgentMessageKind.USER, content="Hello"),
        AgentMessage(message_id="a1", kind=AgentMessageKind.ASSISTANT, content="Hi there!"),
    ]

    pruned, report = pruner.prune_messages(messages)
    assert pruned == messages
    assert report.tools_pruned_count == 0
    assert report.chars_freed == 0
