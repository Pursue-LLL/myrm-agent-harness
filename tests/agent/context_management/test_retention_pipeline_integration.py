"""Integration: server-style compression_intent through default ContextPipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.engine import ContextPipeline, build_default_processors


def _large_error_body() -> str:
    return ("Traceback (most recent call last):\nValueError: integration boom\n" + "line\n") * 900


@pytest.mark.asyncio
async def test_pipeline_retains_failed_tool_without_llm_filter() -> None:
    """Full default pipeline: Filter must retain failed tool output (no LLM summary)."""
    error_body = _large_error_body()
    messages = [
        HumanMessage(content="run tests"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_failed", "name": "bash_code_execute_tool", "args": {}}],
        ),
        ToolMessage(content=error_body, tool_call_id="call_failed", name="bash_code_execute_tool"),
    ]
    context = ProcessorContext(
        messages=messages,
        user_query="run tests",
        chat_id="integration-retention",
        metadata={
            "compression_intent": {
                "failed_tool_call_ids": ["call_failed"],
            }
        },
    )
    pipeline = ContextPipeline(build_default_processors(max_context_tokens=128000))

    with (
        patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.persist_large_tool_output",
            new_callable=AsyncMock,
            return_value="/tmp/integration-evicted.txt",
        ),
        patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.filter_processor.create_filtered_result",
            new_callable=AsyncMock,
        ) as mock_llm_filter,
    ):
        result = await pipeline.process(context)

    mock_llm_filter.assert_not_called()
    tool_msg = result.messages[2]
    assert isinstance(tool_msg, ToolMessage)
    content = str(tool_msg.content)
    assert "RETAINED TOOL OUTPUT" in content
    assert "Traceback" in content
    assert "ValueError" in content
