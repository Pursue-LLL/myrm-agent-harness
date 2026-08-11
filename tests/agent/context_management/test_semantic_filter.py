"""Tests for SemanticFilter reasoning-model content extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.context_management.strategies.filters.semantic_filter import (
    SemanticFilter,
)
from myrm_agent_harness.agent.context_management.strategies.filters.base import FilterContext


def _make_context(content: str = "<h1>Title</h1>\n<p>Body</p>") -> FilterContext:
    return FilterContext(
        file_path="preview.html",
        content=content,
        content_type="html",
    )


class TestSemanticFilterReasoningModel:
    @pytest.mark.asyncio
    async def test_reasoning_model_content_empty_falls_back(self) -> None:
        """Reasoning models returning empty content must still yield a description."""
        sf = SemanticFilter(llm=AsyncMock())
        sf.llm.ainvoke = AsyncMock(
            return_value=AIMessage(
                content="",
                additional_kwargs={"reasoning_content": '{"main_topic": "A landing page"}'},
            )
        )
        result = await sf.filter(_make_context())
        assert result.llm_generated is True
        assert "landing page" in result.summary

    @pytest.mark.asyncio
    async def test_content_list_empty_falls_back(self) -> None:
        """Anthropic-style empty block list must fall back to reasoning_content."""
        sf = SemanticFilter(llm=AsyncMock())
        sf.llm.ainvoke = AsyncMock(
            return_value=AIMessage(
                content=[],
                additional_kwargs={"reasoning_content": '{"main_topic": "Fallback topic", "structure": "flat"}'},
            )
        )
        result = await sf.filter(_make_context())
        assert result.llm_generated is True
        assert "Fallback topic" in result.summary

    @pytest.mark.asyncio
    async def test_empty_response_no_crash(self) -> None:
        """Fully empty response (no content, no reasoning) must not crash."""
        sf = SemanticFilter(llm=AsyncMock())
        sf.llm.ainvoke = AsyncMock(return_value=AIMessage(content="", additional_kwargs={}))
        result = await sf.filter(_make_context())
        assert result.file_path == "preview.html"
        assert result.llm_generated is True
        assert "unknown" in result.structure_overview
