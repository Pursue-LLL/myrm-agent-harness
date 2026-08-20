"""Unit tests for evicted persister (FilterProcessor delegate)."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.context_management.infra.evicted import (
    sanitize_evicted_source,
)
from myrm_agent_harness.agent.context_management.infra.evicted import (
    persist_large_tool_output,
)

_MOCK_PERSIST = "myrm_agent_harness.agent.context_management.infra.evicted.persister.persist_evicted_content"


class TestSanitizeEvictedSource:
    def test_normal_name(self) -> None:
        result = sanitize_evicted_source("tool")
        assert result == "tool"

    def test_mcp_name(self) -> None:
        result = sanitize_evicted_source("mcp")
        assert result == "mcp"

    def test_filter_name(self) -> None:
        result = sanitize_evicted_source("filter")
        assert result == "filter"

    def test_unknown_source_falls_back(self) -> None:
        result = sanitize_evicted_source("some_random_thing")
        assert result == "tool"

    def test_empty_source(self) -> None:
        result = sanitize_evicted_source("")
        assert result == "tool"

    def test_special_chars_sanitized(self) -> None:
        result = sanitize_evicted_source("server/tool.name")
        assert result == "tool"


class TestPersistLargeToolOutput:
    @pytest.mark.asyncio
    async def test_successful_persist(self) -> None:
        mock_result = AsyncMock()
        mock_result.return_value.rel_path = ".context/abc/evicted/tool_123.txt"

        with patch(_MOCK_PERSIST, mock_result):
            result = await persist_large_tool_output("content", "test_tool")

        assert result == ".context/abc/evicted/tool_123.txt"
        mock_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mcp_tool_uses_mcp_source(self) -> None:
        mock_result = AsyncMock()
        mock_result.return_value.rel_path = ".context/abc/evicted/mcp_123.txt"

        with patch(_MOCK_PERSIST, mock_result) as mock_fn:
            result = await persist_large_tool_output("content", "mcp_server_query")

        assert result is not None
        call_args = mock_fn.call_args
        assert call_args[0][1] == "mcp"

    @pytest.mark.asyncio
    async def test_none_tool_name_uses_filter(self) -> None:
        mock_result = AsyncMock()
        mock_result.return_value.rel_path = ".context/abc/evicted/filter_123.txt"

        with patch(_MOCK_PERSIST, mock_result) as mock_fn:
            result = await persist_large_tool_output("content", None)

        assert result is not None
        call_args = mock_fn.call_args
        assert call_args[0][1] == "filter"

    @pytest.mark.asyncio
    async def test_persist_failure_returns_none(self) -> None:
        mock_result = AsyncMock()
        mock_result.return_value.rel_path = None

        with patch(_MOCK_PERSIST, mock_result):
            result = await persist_large_tool_output("content", "tool")

        assert result is None


class TestFormatFilteredMessageWithSavedPath:
    def test_without_saved_path(self) -> None:
        """Persist may fail (saved_path=None); header still guides file_read_tool recovery."""
        from myrm_agent_harness.agent.context_management.strategies.filter import (
            FilteredResult,
            format_filtered_message,
        )

        result = FilteredResult(
            content_type="json",
            total_lines=100,
            total_chars=5000,
            estimated_tokens=2500,
            summary="JSON data",
            structure_overview="keys: [a, b, c]",
            read_suggestions=["re-execute tool"],
        )
        msg = format_filtered_message(result)
        assert "LARGE OUTPUT TRUNCATED - USE file_read_tool TO RECOVER" in msg
        assert "Full output saved to:" not in msg
        assert ".context/" not in msg

    def test_with_saved_path(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.filter import (
            FilteredResult,
            format_filtered_message,
        )

        result = FilteredResult(
            content_type="json",
            total_lines=100,
            total_chars=5000,
            estimated_tokens=2500,
            summary="JSON data",
            structure_overview="keys: [a, b, c]",
            read_suggestions=["re-execute tool"],
        )
        msg = format_filtered_message(
            result, saved_path=".context/abc/evicted/tool_123.txt"
        )
        assert "Full output saved to:" in msg
        assert ".context/abc/evicted/tool_123.txt" in msg
        assert "file_read_tool" in msg
