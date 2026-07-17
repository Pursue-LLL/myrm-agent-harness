"""Tests for MCP oversized output vault spill.

Covers:
- MCPAgent._handle_oversized_output: handler call, fallback, exception handling
- _wrap_tools_with_timeout: vault spill integration with handler parameter
- OversizedResultHandler type alias export
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.toolkits.mcp.agent import MCPAgent, OversizedResultHandler


class TestHandleOversizedOutput:
    """Test MCPAgent._handle_oversized_output static method."""

    def test_handler_returns_summary(self) -> None:
        handler: OversizedResultHandler = lambda c, t: f"summary of {t}"
        result = MCPAgent._handle_oversized_output("x" * 200_000, "big_tool", 100_000, handler)
        assert result == "summary of big_tool"

    def test_handler_returns_none_falls_back_to_truncation(self) -> None:
        handler: OversizedResultHandler = lambda c, t: None
        content = "a" * 150_000
        result = MCPAgent._handle_oversized_output(content, "tool_x", 100_000, handler)
        assert "[Output truncated" in result
        assert "100,000" in result
        assert "150,000" in result

    def test_handler_raises_falls_back_to_truncation(self) -> None:
        def bad_handler(c: str, t: str) -> str | None:
            raise RuntimeError("vault write failed")

        content = "b" * 120_000
        result = MCPAgent._handle_oversized_output(content, "fail_tool", 100_000, bad_handler)
        assert "[Output truncated" in result
        assert "100,000" in result

    def test_no_handler_truncates(self) -> None:
        content = "c" * 200_000
        result = MCPAgent._handle_oversized_output(content, "no_handler", 100_000, None)
        assert "[Output truncated" in result
        assert len(result) < 200_000

    def test_truncation_preserves_head(self) -> None:
        content = "HEAD_MARKER" + "x" * 200_000
        result = MCPAgent._handle_oversized_output(content, "head_test", 100_000, None)
        assert result.startswith("HEAD_MARKER")

    def test_handler_receives_correct_args(self) -> None:
        captured: list[tuple[str, str]] = []

        def spy_handler(c: str, t: str) -> str | None:
            captured.append((c[:10], t))
            return "spied"

        content = "Z" * 110_000
        MCPAgent._handle_oversized_output(content, "spy_tool", 100_000, spy_handler)
        assert len(captured) == 1
        assert captured[0] == ("Z" * 10, "spy_tool")


class TestWrapToolsVaultSpill:
    """Test _wrap_tools_with_timeout with oversized_result_handler."""

    @staticmethod
    def _make_tool(name: str, coroutine: object) -> BaseTool:
        tool = MagicMock(spec=BaseTool)
        tool.name = name
        tool.coroutine = coroutine
        return tool

    @pytest.mark.asyncio
    async def test_oversized_output_calls_handler(self) -> None:
        big_output = "X" * 150_000

        async def big_fn(*args: object, **kwargs: object) -> str:
            return big_output

        handler_called = False

        def mock_handler(c: str, t: str) -> str | None:
            nonlocal handler_called
            handler_called = True
            return f"vaulted:{t}:{len(c)}"

        tool = self._make_tool("big_mcp", big_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=mock_handler,
        )
        result = await tool.coroutine()
        assert handler_called
        assert "vaulted:big_mcp:150000" in result

    @pytest.mark.asyncio
    async def test_small_output_skips_handler(self) -> None:
        async def small_fn(*args: object, **kwargs: object) -> str:
            return "small result"

        handler_called = False

        def mock_handler(c: str, t: str) -> str | None:
            nonlocal handler_called
            handler_called = True
            return "should not be called"

        tool = self._make_tool("small_mcp", small_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=mock_handler,
        )
        result = await tool.coroutine()
        assert not handler_called
        assert "small result" in result

    @pytest.mark.asyncio
    async def test_handler_failure_falls_back_to_truncation(self) -> None:
        big_output = "Y" * 120_000

        async def big_fn(*args: object, **kwargs: object) -> str:
            return big_output

        def failing_handler(c: str, t: str) -> str | None:
            raise ValueError("vault error")

        tool = self._make_tool("fail_mcp", big_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=failing_handler,
        )
        result = await tool.coroutine()
        assert "[Output truncated" in result

    @pytest.mark.asyncio
    async def test_no_handler_truncates_oversized(self) -> None:
        big_output = "W" * 200_000

        async def big_fn(*args: object, **kwargs: object) -> str:
            return big_output

        tool = self._make_tool("trunc_mcp", big_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
        )
        result = await tool.coroutine()
        assert "[Output truncated" in result
        assert "200,000" in result


class TestBoundaryConditions:
    """Test exact boundary conditions for oversized detection."""

    @staticmethod
    def _make_tool(name: str, coroutine: object) -> BaseTool:
        tool = MagicMock(spec=BaseTool)
        tool.name = name
        tool.coroutine = coroutine
        return tool

    @pytest.mark.asyncio
    async def test_exact_max_chars_not_triggered(self) -> None:
        """Content exactly at max_output_chars should NOT trigger vault spill."""
        content = "X" * 100_000

        async def exact_fn(*args: object, **kwargs: object) -> str:
            return content

        handler_called = False

        def spy_handler(c: str, t: str) -> str | None:
            nonlocal handler_called
            handler_called = True
            return "vaulted"

        tool = self._make_tool("exact", exact_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=spy_handler,
        )
        result = await tool.coroutine()
        assert not handler_called
        assert "UNTRUSTED_DATA" in result

    @pytest.mark.asyncio
    async def test_one_over_max_chars_triggers(self) -> None:
        """Content at max_output_chars+1 should trigger vault spill."""
        content = "X" * 100_001

        async def over_fn(*args: object, **kwargs: object) -> str:
            return content

        handler_called = False

        def spy_handler(c: str, t: str) -> str | None:
            nonlocal handler_called
            handler_called = True
            return "vaulted"

        tool = self._make_tool("over", over_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=spy_handler,
        )
        await tool.coroutine()
        assert handler_called

    @pytest.mark.asyncio
    async def test_empty_content_not_triggered(self) -> None:
        """Empty string should not trigger vault spill."""
        async def empty_fn(*args: object, **kwargs: object) -> str:
            return ""

        handler_called = False

        def spy_handler(c: str, t: str) -> str | None:
            nonlocal handler_called
            handler_called = True
            return "vaulted"

        tool = self._make_tool("empty", empty_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=spy_handler,
        )
        await tool.coroutine()
        assert not handler_called

    @pytest.mark.asyncio
    async def test_unicode_content_handled(self) -> None:
        """Multi-byte UTF-8 content (Chinese, emoji) should be handled correctly."""
        content = "\u4e2d\u6587\u5185\u5bb9\u6d4b\u8bd5" * 20_000  # 120K chars

        async def unicode_fn(*args: object, **kwargs: object) -> str:
            return content

        def handler(c: str, t: str) -> str | None:
            return f"vaulted:{len(c)}"

        tool = self._make_tool("unicode", unicode_fn)
        MCPAgent._wrap_tools_with_timeout(
            [tool], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=handler,
        )
        result = await tool.coroutine()
        assert "vaulted:120000" in result

    def test_handler_returns_empty_string_accepted(self) -> None:
        """Handler returning empty string (not None) should be accepted as valid."""
        handler: OversizedResultHandler = lambda c, t: ""
        result = MCPAgent._handle_oversized_output("x" * 200_000, "empty_ret", 100_000, handler)
        assert result == ""

    @pytest.mark.asyncio
    async def test_concurrent_oversized_tools(self) -> None:
        """Multiple tools with oversized output should each get handler called."""
        call_log: list[str] = []

        def log_handler(c: str, t: str) -> str | None:
            call_log.append(t)
            return f"vaulted:{t}"

        big = "Z" * 150_000

        async def big_a(*args: object, **kwargs: object) -> str:
            return big

        async def big_b(*args: object, **kwargs: object) -> str:
            return big

        tool_a = self._make_tool("tool_a", big_a)
        tool_b = self._make_tool("tool_b", big_b)
        MCPAgent._wrap_tools_with_timeout(
            [tool_a, tool_b], timeout=5.0, max_output_chars=100_000,
            oversized_result_handler=log_handler,
        )
        result_a = await tool_a.coroutine()
        result_b = await tool_b.coroutine()
        assert "vaulted:tool_a" in result_a
        assert "vaulted:tool_b" in result_b
        assert len(call_log) == 2


class TestOversizedResultHandlerExport:
    """Test OversizedResultHandler type is properly exported."""

    def test_import_from_package(self) -> None:
        from myrm_agent_harness.toolkits.mcp import OversizedResultHandler as Exported

        assert Exported is OversizedResultHandler

    def test_type_alias_is_callable(self) -> None:
        import typing

        origin = typing.get_origin(OversizedResultHandler)
        assert origin is not None
