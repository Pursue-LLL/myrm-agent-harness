"""Adapter tests for llm_map_tool — item cap and empty input guards."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.meta_tools.llm_map.llm_map_tool import create_llm_map_tool


def _make_llm() -> BaseChatModel:
    llm = MagicMock(spec=BaseChatModel)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    return llm


@pytest.mark.asyncio
async def test_llm_map_tool_rejects_empty_items() -> None:
    tool = create_llm_map_tool(_make_llm(), max_items=5)
    result = await tool.ainvoke({"instruction": "summarise", "items": []})
    assert result["success"] is False
    assert "empty" in result["error"].lower()


@pytest.mark.asyncio
async def test_llm_map_tool_rejects_items_over_cap() -> None:
    tool = create_llm_map_tool(_make_llm(), max_items=3)
    result = await tool.ainvoke(
        {
            "instruction": "classify",
            "items": ["a", "b", "c", "d"],
        }
    )
    assert result["success"] is False
    assert result["max_items"] == 3
    assert result["received_items"] == 4
    assert "Split into batches" in result["error"]


@pytest.mark.asyncio
async def test_llm_map_tool_accepts_items_at_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.toolkits.llms.batch.llm_map import LlmMapReport

    mock_report = LlmMapReport(total=2, succeeded=2, failed=0, cancelled=0, items=[])
    mock_llm_map = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(
        "myrm_agent_harness.agent.meta_tools.llm_map.llm_map_tool.llm_map",
        mock_llm_map,
    )

    tool = create_llm_map_tool(_make_llm(), max_items=2)
    result = await tool.ainvoke(
        {
            "instruction": "tag",
            "items": ["x", "y"],
        }
    )
    assert result["success"] is True
    mock_llm_map.assert_awaited_once()
    assert mock_llm_map.await_args.args[1] == ["x", "y"]


@pytest.mark.asyncio
async def test_llm_map_tool_rejects_invalid_output_keys() -> None:
    tool = create_llm_map_tool(_make_llm(), max_items=5)
    result = await tool.ainvoke(
        {
            "instruction": "classify",
            "items": ["one"],
            "output_keys": ["valid-key"],
        }
    )
    assert result["success"] is False
    assert "identifier" in result["error"].lower()
