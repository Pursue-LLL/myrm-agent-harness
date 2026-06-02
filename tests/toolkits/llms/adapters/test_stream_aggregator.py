"""Tests for stream_aggregator module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
    StreamAggregator,
    StreamFinalization,
    XmlStreamBuffer,
    finalize_stream,
)


class TestStreamAggregator:
    def test_initial_state(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        assert agg.content == []
        assert agg.tool_calls == []
        assert agg.reasoning == []
        assert agg.chunk_count == 0
        assert agg.first_token_time is None
        assert agg.is_empty is True

    def test_ingest_raw_chunk_dict(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        chunk: dict[str, Any] = {
            "model": "gpt-4",
            "choices": [{"delta": {"content": "hi"}, "finish_reason": None}],
        }
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.extract_chunk_metadata",
            return_value=(None, "gpt-4", None),
        ):
            result = agg.ingest_raw_chunk(chunk)
        assert result == chunk
        assert agg.chunk_count == 1
        assert agg.last_model == "gpt-4"

    def test_ingest_raw_chunk_object(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {"choices": [{"delta": {"content": "hi"}}]}
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.extract_chunk_metadata",
            return_value=(None, "gpt-4", "stop"),
        ):
            result = agg.ingest_raw_chunk(mock_chunk)
        assert result == {"choices": [{"delta": {"content": "hi"}}]}
        assert agg.last_model == "gpt-4"
        assert agg.finish_reason == "stop"

    def test_ingest_raw_chunk_object_model_dump_fails(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        mock_chunk = MagicMock(spec=[])
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.extract_chunk_metadata",
            return_value=(None, None, None),
        ):
            result = agg.ingest_raw_chunk(mock_chunk)
        assert result is None

    def test_on_generation_chunk_records_content(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        msg = AIMessageChunk(content="hello")
        chunk = ChatGenerationChunk(message=msg)
        agg.on_generation_chunk(chunk, AIMessageChunk)
        assert agg.content == ["hello"]
        assert agg.first_token_time is not None

    def test_on_generation_chunk_records_reasoning(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        msg = AIMessageChunk(
            content="", additional_kwargs={"reasoning_content": "thinking..."}
        )
        chunk = ChatGenerationChunk(message=msg)
        agg.on_generation_chunk(chunk, AIMessageChunk)
        assert agg.reasoning == ["thinking..."]

    def test_aggregate_tool_calls_from_dict(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        chunk_dict: dict[str, Any] = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "my_tool", "arguments": '{"a":'},
                            }
                        ]
                    }
                }
            ]
        }
        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_tool_call_chunks",
                return_value=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "my_tool", "arguments": '{"a":'},
                    }
                ],
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.aggregate_tool_call_chunk"
            ) as mock_agg,
        ):
            agg.aggregate_tool_calls_from_dict(chunk_dict)
            mock_agg.assert_called_once()

    def test_is_empty_false_after_ingest(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.extract_chunk_metadata",
            return_value=(None, None, None),
        ):
            agg.ingest_raw_chunk({})
        assert agg.is_empty is False

    def test_duration_ms(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        assert agg.duration_ms >= 0

    def test_ttft_ms_none_before_first_token(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        assert agg.ttft_ms is None

    def test_ttft_ms_after_first_token(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.first_token_time = agg.stream_start + 0.05
        ttft = agg.ttft_ms
        assert ttft is not None
        assert abs(ttft - 50.0) < 1.0


class TestStreamTextIntegrity:
    """Verify streaming text accumulation never drops repeated characters/words.

    This suite validates that our pure-append architecture (list[str].append + "".join)
    preserves ALL text exactly as emitted by the LLM, including repeated sequences.
    """

    def test_repeated_words_preserved(self) -> None:
        """LLM outputs 'the the' — must not be deduplicated."""
        agg = StreamAggregator(AIMessageChunk)
        chunks = ["the ", "the ", "world"]
        for c in chunks:
            msg = AIMessageChunk(content=c)
            agg.on_generation_chunk(ChatGenerationChunk(message=msg), AIMessageChunk)
        assert "".join(agg.content) == "the the world"

    def test_repeated_characters_preserved(self) -> None:
        """LLM outputs 'aaa' across chunks — all preserved."""
        agg = StreamAggregator(AIMessageChunk)
        for c in ["a", "a", "a", "b", "b"]:
            msg = AIMessageChunk(content=c)
            agg.on_generation_chunk(ChatGenerationChunk(message=msg), AIMessageChunk)
        assert "".join(agg.content) == "aaabb"

    def test_identical_chunks_preserved(self) -> None:
        """Multiple identical chunks must all be preserved."""
        agg = StreamAggregator(AIMessageChunk)
        for _ in range(5):
            msg = AIMessageChunk(content="data ")
            agg.on_generation_chunk(ChatGenerationChunk(message=msg), AIMessageChunk)
        assert "".join(agg.content) == "data data data data data "

    def test_overlapping_prefix_preserved(self) -> None:
        """Chunks with overlapping content are NOT diff-compared."""
        agg = StreamAggregator(AIMessageChunk)
        chunks = ["Hello World", " World is", " is great"]
        for c in chunks:
            msg = AIMessageChunk(content=c)
            agg.on_generation_chunk(ChatGenerationChunk(message=msg), AIMessageChunk)
        assert "".join(agg.content) == "Hello World World is is great"

    def test_empty_chunks_harmless(self) -> None:
        """Empty content chunks don't corrupt accumulation."""
        agg = StreamAggregator(AIMessageChunk)
        chunks = ["He", "", "llo", "", " ", "World"]
        for c in chunks:
            msg = AIMessageChunk(content=c)
            agg.on_generation_chunk(ChatGenerationChunk(message=msg), AIMessageChunk)
        assert "".join(agg.content) == "Hello World"

    def test_unicode_repeated_preserved(self) -> None:
        """Repeated Unicode characters preserved."""
        agg = StreamAggregator(AIMessageChunk)
        chunks = ["你", "你", "好", "好", "世界"]
        for c in chunks:
            msg = AIMessageChunk(content=c)
            agg.on_generation_chunk(ChatGenerationChunk(message=msg), AIMessageChunk)
        assert "".join(agg.content) == "你你好好世界"

    def test_finalize_preserves_repeated_text(self) -> None:
        """finalize_stream joins all content without dedup."""
        agg = StreamAggregator(AIMessageChunk)
        agg.content = ["the ", "the ", "cat ", "cat ", "sat"]
        agg.last_model = "gpt-4o"
        agg.finish_reason = "stop"

        record_fn = MagicMock()
        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(None, [], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.normalize_usage",
                return_value={},
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, None, "gpt-4o", is_async=False, record_usage_fn=record_fn
            )
        assert (
            result.aggregated_response["choices"][0]["message"]["content"]
            == "the the cat cat sat"
        )


class TestStreamFinalization:
    def test_slots(self) -> None:
        sf = StreamFinalization(
            final_tool_chunk=None, aggregated_response={"model": "test"}
        )
        assert sf.final_tool_chunk is None
        assert sf.aggregated_response["model"] == "test"


class TestFinalizeStream:
    def test_basic_finalization(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.content = ["Hello ", "World"]
        agg.last_model = "gpt-4o"
        agg.finish_reason = "stop"

        record_fn = MagicMock()

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(None, [], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.normalize_usage",
                return_value={},
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, None, "gpt-4o", is_async=False, record_usage_fn=record_fn
            )

        assert isinstance(result, StreamFinalization)
        assert result.aggregated_response["model"] == "gpt-4o"
        assert (
            result.aggregated_response["choices"][0]["message"]["content"]
            == "Hello World"
        )
        assert result.aggregated_response["choices"][0]["finish_reason"] == "stop"
        record_fn.assert_called_once()

    def test_finalization_with_reasoning(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.content = ["answer"]
        agg.reasoning = ["step1 ", "step2"]
        agg.last_model = "o1"
        agg.finish_reason = "stop"

        record_fn = MagicMock()

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(None, [], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, None, "o1", is_async=True, record_usage_fn=record_fn
            )

        msg = result.aggregated_response["choices"][0]["message"]
        assert msg["reasoning_content"] == "step1 step2"

    def test_finalization_with_tool_calls(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.content = [""]
        agg.tool_calls = [
            {
                "function": {"name": "search", "arguments": "{}"},
                "id": "call_1",
                "type": "function",
            }
        ]
        agg.last_model = "gpt-4o"
        agg.finish_reason = "tool_calls"

        mock_chunk = MagicMock(spec=ChatGenerationChunk)
        corrected = [
            {
                "function": {"name": "search", "arguments": "{}"},
                "id": "call_1",
                "type": "function",
            }
        ]
        metadata = [
            {
                "tool_name": "search",
                "strategy": "standard_json",
                "safe": True,
                "degraded": False,
            }
        ]

        record_fn = MagicMock()

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(mock_chunk, corrected, metadata),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, {"search": {}}, "gpt-4o", is_async=False, record_usage_fn=record_fn
            )

        assert result.final_tool_chunk is mock_chunk
        assert (
            result.aggregated_response["choices"][0]["message"]["tool_calls"]
            == corrected
        )


class TestFinalizeStreamSafetyTermination:
    """Tests for safety termination detection in finalize_stream."""

    def _make_agg_with_tool_calls(
        self, finish_reason: str
    ) -> StreamAggregator:
        agg = StreamAggregator(AIMessageChunk)
        agg.content = ["partial response"]
        agg.tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "write_file", "arguments": '{"path": "x"'},
            }
        ]
        agg.finish_reason = finish_reason
        agg.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}
        return agg

    def test_safety_termination_suppresses_tool_calls(self) -> None:
        agg = self._make_agg_with_tool_calls("content_filter")
        record_fn = MagicMock()

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(
                    ChatGenerationChunk(
                        message=AIMessageChunk(content=""),
                    ),
                    agg.tool_calls,
                    [],
                ),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, {}, "gpt-4o", is_async=False, record_usage_fn=record_fn
            )

        msg = result.aggregated_response["choices"][0]["message"]
        assert "tool_calls" not in msg
        assert "[Safety]" in msg["content"]
        assert result.final_tool_chunk is None

    def test_safety_termination_clears_recovery_metadata(self) -> None:
        agg = self._make_agg_with_tool_calls("SAFETY")
        record_fn = MagicMock()

        recovery_meta = [{"strategy": "json_repair", "degraded": False, "safe": True}]

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(
                    ChatGenerationChunk(
                        message=AIMessageChunk(content=""),
                    ),
                    agg.tool_calls,
                    recovery_meta,
                ),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, {}, "gpt-4o", is_async=False, record_usage_fn=record_fn
            )

        msg = result.aggregated_response["choices"][0]["message"]
        assert "tool_calls" not in msg
        assert "tool_call_recovery" not in msg
        assert "[Safety]" in msg["content"]

    def test_non_safety_reason_preserves_tool_calls(self) -> None:
        agg = self._make_agg_with_tool_calls("stop")
        record_fn = MagicMock()

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(
                    ChatGenerationChunk(
                        message=AIMessageChunk(content=""),
                    ),
                    agg.tool_calls,
                    [],
                ),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, {}, "gpt-4o", is_async=False, record_usage_fn=record_fn
            )

        msg = result.aggregated_response["choices"][0]["message"]
        assert "tool_calls" in msg
        assert result.final_tool_chunk is not None

    def test_safety_without_tool_calls_passes_through(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.content = ["I cannot help with that"]
        agg.tool_calls = []
        agg.finish_reason = "content_filter"
        agg.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}
        record_fn = MagicMock()

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(None, [], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, {}, "gpt-4o", is_async=False, record_usage_fn=record_fn
            )

        msg = result.aggregated_response["choices"][0]["message"]
        assert msg["content"] == "I cannot help with that"
        assert "tool_calls" not in msg


class TestXmlStreamBuffer:
    """Tests for XmlStreamBuffer — DSML tag interception across streaming chunks."""

    def test_plain_text_passes_through(self) -> None:
        buf = XmlStreamBuffer()
        assert buf.process("Hello world") == "Hello world"

    def test_empty_string_returns_empty(self) -> None:
        buf = XmlStreamBuffer()
        assert buf.process("") == ""

    def test_dsml_tag_swallowed(self) -> None:
        buf = XmlStreamBuffer()
        result = buf.process("<｜DSML｜tool_calls>some_tool</｜DSML｜tool_calls>")
        assert result == ""

    def test_tool_call_tag_swallowed(self) -> None:
        buf = XmlStreamBuffer()
        result = buf.process("<tool_call>data</tool_call>")
        assert result == ""

    def test_invoke_tag_swallowed(self) -> None:
        buf = XmlStreamBuffer()
        result = buf.process("<invoke name='test'>body</invoke>")
        assert result == ""

    def test_text_before_tag_preserved(self) -> None:
        buf = XmlStreamBuffer()
        result = buf.process("Hello <tool_call>data</tool_call>")
        assert result == "Hello "

    def test_text_after_tag_preserved(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("<tool_call>data</tool_call>")
        r2 = buf.process("World")
        assert r1 + r2 == "World"

    def test_tag_split_across_chunks(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("Hello <tool")
        r2 = buf.process("_call>data</tool_call>")
        assert r1 == "Hello "
        assert r2 == ""

    def test_dsml_tag_split_across_chunks(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("Text <｜DSM")
        r2 = buf.process("L｜tool_calls>content</｜DSML｜tool_calls>")
        r3 = buf.process("done")
        assert r1 == "Text "
        assert r2 == ""
        assert r3 == "done"

    def test_non_tag_angle_bracket_passes(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("a < b")
        r2 = buf.flush()
        assert r1 + r2 == "a < b"

    def test_incomplete_non_matching_prefix(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("test <div>")
        assert "<" in r1

    def test_swallowing_without_end_tag_buffers(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("<tool_call>partial")
        assert r1 == ""
        r2 = buf.process(" more data")
        assert r2 == ""
        r3 = buf.process("</tool_call>after")
        assert r3 == "after"

    def test_flush_returns_buffer_when_not_swallowing(self) -> None:
        buf = XmlStreamBuffer()
        buf.process("Hello <to")
        result = buf.flush()
        assert "<to" in result

    def test_flush_returns_empty_when_swallowing(self) -> None:
        buf = XmlStreamBuffer()
        buf.process("<tool_call>in_progress")
        result = buf.flush()
        assert result == ""

    def test_flush_resets_state(self) -> None:
        buf = XmlStreamBuffer()
        buf.process("<tool_call>data")
        buf.flush()
        assert buf.buffer == ""
        assert buf.is_swallowing is False

    def test_lone_angle_bracket_buffered(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("text <")
        assert r1 == "text "
        r2 = buf.process("not a tag")
        assert "<" in r2

    def test_multiple_tags_in_sequence(self) -> None:
        buf = XmlStreamBuffer()
        r1 = buf.process("a<tool_call>x</tool_call>")
        r2 = buf.process("b<tool_call>y</tool_call>")
        r3 = buf.process("c")
        assert r1 + r2 + r3 == "abc"

    def test_invoke_with_quoted_name(self) -> None:
        buf = XmlStreamBuffer()
        result = buf.process('<invoke name="search">body</invoke>')
        assert result == ""

    def test_pipe_variant_dsml_tag(self) -> None:
        buf = XmlStreamBuffer()
        result = buf.process("<|DSML|tool_calls>data</|DSML|tool_calls>")
        assert result == ""

    def test_prefix_detection_partial_invoke(self) -> None:
        buf = XmlStreamBuffer()
        assert buf._is_prefix_of_start_tag("<") is True
        assert buf._is_prefix_of_start_tag("<inv") is True
        assert buf._is_prefix_of_start_tag("<invoke") is True
        assert buf._is_prefix_of_start_tag("<invoke ") is True
        assert buf._is_prefix_of_start_tag("<invoke n") is True
        assert buf._is_prefix_of_start_tag("<invoke name=") is True
        assert buf._is_prefix_of_start_tag("<invoke name=\"test") is True

    def test_prefix_detection_non_matching(self) -> None:
        buf = XmlStreamBuffer()
        assert buf._is_prefix_of_start_tag("hello") is False
        assert buf._is_prefix_of_start_tag("") is False

    def test_prefix_detection_tool_call(self) -> None:
        buf = XmlStreamBuffer()
        assert buf._is_prefix_of_start_tag("<tool") is True
        assert buf._is_prefix_of_start_tag("<tool_") is True
        assert buf._is_prefix_of_start_tag("<tool_c") is True

    def test_prefix_detection_dsml(self) -> None:
        buf = XmlStreamBuffer()
        assert buf._is_prefix_of_start_tag("<D") is True
        assert buf._is_prefix_of_start_tag("<DS") is True
        assert buf._is_prefix_of_start_tag("<DSM") is True

    def test_prefix_detection_dsml_invoke(self) -> None:
        buf = XmlStreamBuffer()
        assert buf._is_prefix_of_start_tag("<｜DSML｜inv") is True
        assert buf._is_prefix_of_start_tag("<|DSML|inv") is True
        assert buf._is_prefix_of_start_tag("<DSMLi") is True


class TestStreamAggregatorIngestEdgeCases:
    """Additional edge cases for StreamAggregator.ingest_raw_chunk and
    aggregate_tool_calls_from_dict to cover uncovered branches."""

    def test_ingest_updates_usage(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.extract_chunk_metadata",
            return_value=(usage, None, None),
        ):
            agg.ingest_raw_chunk({})
        assert agg.last_usage == usage
        assert agg.is_empty is False

    def test_aggregate_tool_calls_empty_choices(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        chunk_dict: dict[str, Any] = {"choices": [{}]}
        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_tool_call_chunks",
                return_value=[],
            ),
        ):
            agg.aggregate_tool_calls_from_dict(chunk_dict)
        assert agg.tool_calls == []


class TestFinalizeStreamHallucinationFiltering:
    """Cover the available_tools hallucination filtering branch."""

    def test_hallucinated_tool_calls_filtered(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.content = ["response"]
        agg.tool_calls = [
            {"function": {"name": "real_tool"}, "id": "c1", "type": "function"},
            {"function": {"name": "fake_tool"}, "id": "c2", "type": "function"},
        ]
        agg.last_model = "gpt-4o"
        agg.finish_reason = "tool_calls"

        record_fn = MagicMock()

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                return_value=(MagicMock(spec=ChatGenerationChunk), [{"function": {"name": "real_tool"}, "id": "c1", "type": "function"}], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, {"real_tool": {}}, "gpt-4o",
                is_async=False, record_usage_fn=record_fn,
                available_tools=["real_tool"],
            )

        msg = result.aggregated_response["choices"][0]["message"]
        assert "tool_calls" in msg


class TestFinalizeStreamContentParsedToolCalls:
    """Cover lines 316-325: parse_tool_calls finds calls in content,
    finish_reason overridden from 'stop' to 'tool_calls'."""

    def test_parsed_tool_calls_from_content_overrides_finish_reason(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.content = ["<tool_call>search</tool_call>"]
        agg.tool_calls = []
        agg.last_model = "gpt-4o"
        agg.finish_reason = "stop"

        record_fn = MagicMock()
        fake_tc = {"function": {"name": "search", "arguments": "{}"}, "id": "pc1", "type": "function"}

        def _build_side_effect(tool_calls, schemas):
            if tool_calls:
                return (MagicMock(spec=ChatGenerationChunk), [fake_tc], [])
            return (MagicMock(spec=ChatGenerationChunk), [], [])

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.build_final_tool_call_chunk",
                side_effect=_build_side_effect,
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.stream_aggregator.parse_tool_calls_from_reasoning",
                return_value=([], []),
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers.parse_tool_calls",
                return_value=[fake_tc],
            ),
            patch("myrm_agent_harness.toolkits.llms.utils.logger.log_llm_response"),
            patch(
                "myrm_agent_harness.utils.token_economics.tracker.record_finish_reason"
            ),
        ):
            result = finalize_stream(
                agg, {"search": {}}, "gpt-4o",
                is_async=False, record_usage_fn=record_fn,
            )

        assert agg.finish_reason == "tool_calls"
        msg = result.aggregated_response["choices"][0]["message"]
        assert "tool_calls" in msg
