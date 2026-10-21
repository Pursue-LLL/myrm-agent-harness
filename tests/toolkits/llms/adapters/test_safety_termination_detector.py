"""Tests for safety_termination_detector module."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.adapters.safety_termination_detector import (
    SAFETY_FINISH_REASONS,
    detect_safety_termination,
    suppress_tool_calls_for_safety,
)


class TestDetectSafetyTermination:
    @pytest.mark.parametrize(
        "reason",
        [
            "content_filter",
            "refusal",
            "SAFETY",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "SPII",
            "RECITATION",
            "IMAGE_SAFETY",
        ],
    )
    def test_detects_all_known_safety_reasons(self, reason: str) -> None:
        assert detect_safety_termination(reason) is True

    @pytest.mark.parametrize(
        "reason",
        ["stop", "tool_calls", "length", "max_tokens", "end_turn", None, ""],
    )
    def test_non_safety_reasons_return_false(self, reason: str | None) -> None:
        assert detect_safety_termination(reason) is False

    def test_frozenset_matches_function(self) -> None:
        for reason in SAFETY_FINISH_REASONS:
            assert detect_safety_termination(reason) is True


class TestSuppressToolCallsForSafety:
    def test_suppresses_tool_calls_and_adds_explanation(self) -> None:
        msg: dict = {
            "content": "",
            "tool_calls": [
                {"function": {"name": "write_file", "arguments": '{"path": "x"'}},
            ],
        }
        count = suppress_tool_calls_for_safety(msg, "content_filter")
        assert count == 1
        assert "tool_calls" not in msg
        assert "Safety" in msg["content"]
        assert "content_filter" in msg["content"]

    def test_suppresses_multiple_tool_calls(self) -> None:
        msg: dict = {
            "content": "partial",
            "tool_calls": [
                {"function": {"name": "write_file", "arguments": "{}"}},
                {"function": {"name": "run_cmd", "arguments": "{}"}},
            ],
            "additional_kwargs": {
                "tool_calls": [{"id": "1"}],
                "function_call": {"name": "x"},
            },
        }
        count = suppress_tool_calls_for_safety(msg, "SAFETY")
        assert count == 2
        assert "tool_calls" not in msg
        assert msg["additional_kwargs"].get("tool_calls") is None
        assert msg["additional_kwargs"].get("function_call") is None
        assert msg["content"].startswith("partial\n\n")

    def test_no_tool_calls_returns_zero(self) -> None:
        msg: dict = {"content": "hello"}
        count = suppress_tool_calls_for_safety(msg, "content_filter")
        assert count == 0
        assert msg["content"] == "hello"

    def test_empty_tool_calls_returns_zero(self) -> None:
        msg: dict = {"content": "", "tool_calls": []}
        count = suppress_tool_calls_for_safety(msg, "refusal")
        assert count == 0

    def test_preserves_reasoning_content(self) -> None:
        """Safety suppression should not touch reasoning_content."""
        msg: dict = {
            "content": "",
            "reasoning_content": "I was thinking about...",
            "tool_calls": [{"function": {"name": "exec", "arguments": ""}}],
        }
        suppress_tool_calls_for_safety(msg, "BLOCKLIST")
        assert msg["reasoning_content"] == "I was thinking about..."

    def test_no_additional_kwargs_key(self) -> None:
        """Message without additional_kwargs should not raise."""
        msg: dict = {
            "content": "x",
            "tool_calls": [{"function": {"name": "a", "arguments": "{}"}}],
        }
        count = suppress_tool_calls_for_safety(msg, "PROHIBITED_CONTENT")
        assert count == 1
        assert "additional_kwargs" not in msg

    def test_tool_call_with_missing_function_key(self) -> None:
        """Tool call entries with missing 'function' key should still be counted."""
        msg: dict = {
            "content": "",
            "tool_calls": [{"id": "call_1"}],
        }
        count = suppress_tool_calls_for_safety(msg, "SPII")
        assert count == 1
        assert "tool_calls" not in msg

    def test_case_sensitive_detection(self) -> None:
        """Safety reasons are case-sensitive (providers use specific casing)."""
        assert detect_safety_termination("safety") is False
        assert detect_safety_termination("CONTENT_FILTER") is False
        assert detect_safety_termination("Refusal") is False


class TestIntegrationWithFinalization:
    """Integration tests verifying safety detection works in finalize_stream context."""

    def test_finalize_stream_suppresses_on_content_filter(self) -> None:
        from unittest.mock import MagicMock

        from langchain_core.messages import AIMessageChunk

        from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
            StreamAggregator,
            finalize_stream,
        )

        agg = StreamAggregator(default_chunk_class=AIMessageChunk)
        agg.content.append("partial response")
        agg.tool_calls = [
            {"function": {"name": "write_file", "arguments": '{"path": "/tmp/x"'}, "id": "call_1", "type": "function"}
        ]
        agg.finish_reason = "content_filter"
        agg.last_usage = {"prompt_tokens": 100, "completion_tokens": 50}

        record_fn = MagicMock()
        result = finalize_stream(
            agg,
            tool_schemas=None,
            model_name="test-model",
            is_async=False,
            record_usage_fn=record_fn,
        )

        msg = result.aggregated_response["choices"][0]["message"]
        assert "tool_calls" not in msg
        assert "Safety" in msg["content"]
        assert result.final_tool_chunk is None

    def test_finalize_stream_no_suppression_on_stop(self) -> None:
        from unittest.mock import MagicMock

        from langchain_core.messages import AIMessageChunk

        from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
            StreamAggregator,
            finalize_stream,
        )

        agg = StreamAggregator(default_chunk_class=AIMessageChunk)
        agg.content.append("")
        agg.tool_calls = [
            {"function": {"name": "read_file", "arguments": '{"path": "/x"}'}, "id": "call_1", "type": "function"}
        ]
        agg.finish_reason = "stop"
        agg.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}

        record_fn = MagicMock()
        result = finalize_stream(
            agg,
            tool_schemas=None,
            model_name="test-model",
            is_async=False,
            record_usage_fn=record_fn,
        )

        msg = result.aggregated_response["choices"][0]["message"]
        assert "tool_calls" in msg
        assert result.final_tool_chunk is not None

    def test_finalize_stream_safety_without_tool_calls_passes_through(self) -> None:
        """If safety-terminated but no tool_calls, content should remain unchanged."""
        from unittest.mock import MagicMock

        from langchain_core.messages import AIMessageChunk

        from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
            StreamAggregator,
            finalize_stream,
        )

        agg = StreamAggregator(default_chunk_class=AIMessageChunk)
        agg.content.append("I cannot help with that.")
        agg.tool_calls = []
        agg.finish_reason = "refusal"
        agg.last_usage = {"prompt_tokens": 10, "completion_tokens": 8}

        record_fn = MagicMock()
        result = finalize_stream(
            agg,
            tool_schemas=None,
            model_name="test-model",
            is_async=False,
            record_usage_fn=record_fn,
        )

        msg = result.aggregated_response["choices"][0]["message"]
        assert msg["content"] == "I cannot help with that."
        assert "tool_calls" not in msg
