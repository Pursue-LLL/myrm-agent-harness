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

    @pytest.mark.asyncio
    async def test_multiline_json_content_parsed(self) -> None:
        """Multiline JSON in content must be parsed instead of degraded to garbage."""
        sf = SemanticFilter(llm=AsyncMock())
        sf.llm.ainvoke = AsyncMock(
            return_value=AIMessage(
                content='{"main_topic": "Training optimization\nfor tensorflow", '
                '"structure": "1. Intro\n2. Data", "reading_suggestion": "Read section 3"}',
                additional_kwargs={},
            )
        )
        result = await sf.filter(_make_context())
        assert result.llm_generated is True
        assert "Training optimization" in result.summary
        assert "1. Intro" in result.structure_overview
        assert "Read section 3" in result.read_suggestions[0]

    @pytest.mark.asyncio
    async def test_fenced_json_content_parsed(self) -> None:
        """Fenced JSON block in content must be parsed."""
        sf = SemanticFilter(llm=AsyncMock())
        sf.llm.ainvoke = AsyncMock(
            return_value=AIMessage(
                content='```json\n{"main_topic": "Fenced topic"}\n```',
                additional_kwargs={},
            )
        )
        result = await sf.filter(_make_context())
        assert result.llm_generated is True
        assert "Fenced topic" in result.summary

    @pytest.mark.asyncio
    async def test_plain_text_content_degraded_to_preview(self) -> None:
        """Non-JSON response must degrade to a text preview, not crash."""
        sf = SemanticFilter(llm=AsyncMock())
        sf.llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="This page explains basic concepts.", additional_kwargs={})
        )
        result = await sf.filter(_make_context())
        assert result.llm_generated is True
        assert "basic concepts" in result.summary
