"""Tests for FilterProcessor."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import ToolProtectionConfig
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor import FilterProcessor


def _make_context(messages: list, user_query: str = "test", llm: object | None = None, **kwargs) -> ProcessorContext:
    return ProcessorContext(messages=messages, user_query=user_query, llm=llm, **kwargs)


class TestFilterProcessor:
    def test_name(self) -> None:
        fp = FilterProcessor()
        assert fp.name == "filter"

    @pytest.mark.asyncio
    async def test_should_process_no_tool_messages(self) -> None:
        fp = FilterProcessor()
        ctx = _make_context([HumanMessage(content="hi"), AIMessage(content="hello")])
        assert await fp.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_should_process_small_tool_result(self) -> None:
        fp = FilterProcessor()
        ctx = _make_context([ToolMessage(content="short result", tool_call_id="t1")])
        assert await fp.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_should_process_large_tool_result(self) -> None:
        fp = FilterProcessor()
        large_content = "word " * 25_000  # ~25k tokens
        ctx = _make_context([ToolMessage(content=large_content, tool_call_id="t1")])
        assert await fp.should_process(ctx) is True

    @pytest.mark.asyncio
    async def test_should_process_non_string_content(self) -> None:
        fp = FilterProcessor()
        msg = ToolMessage(content="", tool_call_id="t1")
        msg.content = 12345
        ctx = _make_context([msg])
        assert await fp.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_process_skips_resume_session(self) -> None:
        fp = FilterProcessor()
        large_content = "word " * 25_000
        ctx = _make_context([ToolMessage(content=large_content, tool_call_id="t1")], is_resume=True)
        result = await fp.process(ctx)
        assert result.messages[0].content == large_content

    @pytest.mark.asyncio
    async def test_process_skips_hitl_session(self) -> None:
        fp = FilterProcessor()
        large_content = "word " * 25_000
        ctx = _make_context(
            [ToolMessage(content=large_content, tool_call_id="t1")], merged_context={"hitl_session_active": True}
        )
        result = await fp.process(ctx)
        assert result.messages[0].content == large_content

    @pytest.mark.asyncio
    async def test_process_filters_large_tool_output(self) -> None:
        fp = FilterProcessor()
        large_content = "word " * 25_000
        ctx = _make_context([ToolMessage(content=large_content, tool_call_id="t1", name="some_tool")])

        mock_result = AsyncMock()
        mock_result.return_value = type("R", (), {"estimated_tokens": 5000, "structured_summary": "summary"})()

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
                new_callable=AsyncMock,
                return_value="/tmp/saved.txt",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
                new_callable=AsyncMock,
                return_value=type("R", (), {"estimated_tokens": 5000, "structured_summary": "summary"})(),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.format_filtered_message",
                return_value="[Filtered] summary /tmp/saved.txt",
            ),
        ):
            result = await fp.process(ctx)
            assert result.messages[0].content == "[Filtered] summary /tmp/saved.txt"
            assert result.tokens_saved == 5000

    @pytest.mark.asyncio
    async def test_process_protects_tool(self) -> None:
        protection = ToolProtectionConfig(business_protected={"critical_tool"})
        fp = FilterProcessor(protection_config=protection)
        large_content = "word " * 25_000
        ctx = _make_context([ToolMessage(content=large_content, tool_call_id="t1", name="critical_tool")])

        result = await fp.process(ctx)
        assert result.messages[0].content == large_content
        assert any("protected_tools" in op for op in result.operations)

    @pytest.mark.asyncio
    async def test_process_no_llm_warning(self) -> None:
        fp = FilterProcessor()
        large_content = "word " * 25_000
        ctx = _make_context([ToolMessage(content=large_content, tool_call_id="t1", name="tool")], llm=None)

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
                new_callable=AsyncMock,
                return_value="/tmp/saved.txt",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
                new_callable=AsyncMock,
                return_value=type("R", (), {"estimated_tokens": 3000, "structured_summary": "s"})(),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.format_filtered_message",
                return_value="[Filtered]",
            ),
        ):
            result = await fp.process(ctx)
            assert result.tokens_saved == 3000

    @pytest.mark.asyncio
    async def test_process_retains_failed_tool_with_structure_trim(self) -> None:
        fp = FilterProcessor()
        error_body = ("Traceback (most recent call last):\nValueError: boom\n" + "detail line\n") * 800
        ctx = _make_context(
            [
                ToolMessage(
                    content=error_body,
                    tool_call_id="call_failed",
                    name="web_search_tool",
                )
            ],
            metadata={
                "compression_intent": {
                    "failed_tool_call_ids": ["call_failed"],
                }
            },
        )

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
                new_callable=AsyncMock,
                return_value="/tmp/saved.txt",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
                new_callable=AsyncMock,
            ) as mock_llm_filter,
        ):
            result = await fp.process(ctx)
            mock_llm_filter.assert_not_called()
            assert "RETAINED TOOL OUTPUT" in str(result.messages[0].content)
            assert "Traceback" in str(result.messages[0].content)
            assert "ValueError" in str(result.messages[0].content)

    @pytest.mark.asyncio
    async def test_process_retains_focus_file_tool_with_structure_trim(self) -> None:
        fp = FilterProcessor()
        large_body = ("Read myrm-agent-server/app/main.py\n" + "line\n") * 1200
        ctx = _make_context(
            [
                ToolMessage(
                    content=large_body,
                    tool_call_id="call_read",
                    name="grep_tool",
                )
            ],
            metadata={
                "compression_intent": {
                    "focus_files": ["myrm-agent-server/app/main.py"],
                }
            },
        )

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
                new_callable=AsyncMock,
                return_value="/tmp/saved.txt",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
                new_callable=AsyncMock,
            ) as mock_llm_filter,
        ):
            result = await fp.process(ctx)
            mock_llm_filter.assert_not_called()
            assert "RETAINED TOOL OUTPUT" in str(result.messages[0].content)
            assert "myrm-agent-server/app/main.py" in str(result.messages[0].content)

    @pytest.mark.asyncio
    async def test_process_turn_aggregate_filters_latest_parallel_tools(self) -> None:
        fp = FilterProcessor()
        large_chunk = "word " * 8_000
        ctx = _make_context(
            [
                HumanMessage(content="hi"),
                AIMessage(
                    content="parallel tools",
                    tool_calls=[
                        {"id": "t1", "name": "grep_tool", "args": {}},
                        {"id": "t2", "name": "grep_tool", "args": {}},
                    ],
                ),
                ToolMessage(content=large_chunk, tool_call_id="t1", name="grep_tool"),
                ToolMessage(content=large_chunk, tool_call_id="t2", name="grep_tool"),
            ]
        )

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
                new_callable=AsyncMock,
                return_value="/tmp/saved.txt",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
                new_callable=AsyncMock,
                return_value=type("R", (), {"estimated_tokens": 4000, "structured_summary": "summary"})(),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.format_filtered_message",
                return_value="[Filtered] aggregate",
            ),
        ):
            result = await fp.process(ctx)

        assert result.tokens_saved > 0
        assert "[Filtered]" in str(result.messages[-1].content)

    @pytest.mark.asyncio
    async def test_process_turn_aggregate_filters_medium_parallel_tools(self) -> None:
        fp = FilterProcessor()
        medium_chunk = "word " * 3_500
        ctx = _make_context(
            [
                HumanMessage(content="hi"),
                AIMessage(
                    content="parallel",
                    tool_calls=[
                        {"id": "t1", "name": "grep_tool", "args": {}},
                        {"id": "t2", "name": "grep_tool", "args": {}},
                        {"id": "t3", "name": "grep_tool", "args": {}},
                        {"id": "t4", "name": "grep_tool", "args": {}},
                        {"id": "t5", "name": "grep_tool", "args": {}},
                    ],
                ),
                ToolMessage(content=medium_chunk, tool_call_id="t1", name="grep_tool"),
                ToolMessage(content=medium_chunk, tool_call_id="t2", name="grep_tool"),
                ToolMessage(content=medium_chunk, tool_call_id="t3", name="grep_tool"),
                ToolMessage(content=medium_chunk, tool_call_id="t4", name="grep_tool"),
                ToolMessage(content=medium_chunk, tool_call_id="t5", name="grep_tool"),
            ]
        )

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
                new_callable=AsyncMock,
                return_value="/tmp/saved.txt",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
                new_callable=AsyncMock,
                return_value=type("R", (), {"estimated_tokens": 2000, "structured_summary": "summary"})(),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.format_filtered_message",
                return_value="[Filtered] medium aggregate",
            ),
        ):
            result = await fp.process(ctx)

        assert result.tokens_saved > 0
        assert any("[Filtered]" in str(msg.content) for msg in result.messages if isinstance(msg, ToolMessage))

    @pytest.mark.asyncio
    async def test_process_skips_zero_savings_single_tool(self) -> None:
        fp = FilterProcessor()
        large_content = "word " * 25_000
        ctx = _make_context([ToolMessage(content=large_content, tool_call_id="t1", name="some_tool")])

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
                new_callable=AsyncMock,
                return_value="/tmp/saved.txt",
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
                new_callable=AsyncMock,
                return_value=type("R", (), {"estimated_tokens": 0, "structured_summary": "summary"})(),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.format_filtered_message",
                return_value="[Filtered]",
            ),
        ):
            result = await fp.process(ctx)

        assert result.tokens_saved == 0
        assert result.messages[0].content == "[Filtered]"
