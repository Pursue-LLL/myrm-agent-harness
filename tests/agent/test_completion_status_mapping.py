"""Completion status mapping: provider finish reasons and dropped-stream sentinel."""

from myrm_agent_harness.agent.types import (
    CompletionStatus,
    map_to_completion_status,
)
from myrm_agent_harness.utils.token_economics.usage_ledger import (
    DROPPED_STREAM_FINISH_REASON,
)


def test_dropped_stream_maps_to_truncated():
    """A stream cut before the final chunk must surface as truncated, not complete."""
    assert map_to_completion_status(DROPPED_STREAM_FINISH_REASON) is CompletionStatus.TRUNCATED


def test_length_truncation_maps_to_truncated():
    assert map_to_completion_status("length") is CompletionStatus.TRUNCATED
    assert map_to_completion_status("max_tokens") is CompletionStatus.TRUNCATED


def test_safety_termination_maps_to_filtered():
    assert map_to_completion_status("content_filter") is CompletionStatus.CONTENT_FILTERED
    assert map_to_completion_status("refusal") is CompletionStatus.CONTENT_FILTERED


def test_normal_and_missing_finish_reason_map_to_complete():
    assert map_to_completion_status("stop") is CompletionStatus.COMPLETE
    assert map_to_completion_status("tool_calls") is CompletionStatus.COMPLETE
    # Non-streaming paths may omit finish_reason entirely; that is not a drop.
    assert map_to_completion_status(None) is CompletionStatus.COMPLETE
    assert map_to_completion_status("") is CompletionStatus.COMPLETE
