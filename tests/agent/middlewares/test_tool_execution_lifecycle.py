"""Tests for _tool_execution_lifecycle module."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
    emit_tool_heartbeat,
    handle_execution_error,
    resolve_dynamic_tool,
)


class TestResolveDynamicTool:
    def test_returns_request_when_tool_is_set(self) -> None:
        request = ToolCallRequest(
            tool_call={"name": "bash_tool", "id": "c1", "args": {}},
            tool=MagicMock(),
            state=None,
            runtime=MagicMock(),
        )
        result = resolve_dynamic_tool(request)
        assert result is request

    def test_resolves_from_registry_exact_match(self) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "bash_tool"
        mock_registry = MagicMock()
        mock_registry.resolve.return_value = [mock_tool]
        mock_registry.get_deferred_tools.return_value = []

        request = ToolCallRequest(
            tool_call={"name": "bash_tool", "id": "c1", "args": {}},
            tool=None,
            state=None,
            runtime=MagicMock(),
        )

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
                return_value=mock_registry,
            ),
        ):
            result = resolve_dynamic_tool(request)
            assert result.tool is mock_tool

    def test_resolves_with_tool_suffix(self) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "search_tool"
        mock_registry = MagicMock()
        mock_registry.resolve.return_value = [mock_tool]
        mock_registry.get_deferred_tools.return_value = []

        request = ToolCallRequest(
            tool_call={"name": "search", "id": "c1", "args": {}},
            tool=None,
            state=None,
            runtime=MagicMock(),
        )

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
                return_value=mock_registry,
            ),
        ):
            result = resolve_dynamic_tool(request)
            assert result.tool is mock_tool

    def test_resolves_without_tool_suffix(self) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_registry = MagicMock()
        mock_registry.resolve.return_value = [mock_tool]
        mock_registry.get_deferred_tools.return_value = []

        request = ToolCallRequest(
            tool_call={"name": "search_tool", "id": "c1", "args": {}},
            tool=None,
            state=None,
            runtime=MagicMock(),
        )

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
                return_value=mock_registry,
            ),
        ):
            result = resolve_dynamic_tool(request)
            assert result.tool is mock_tool

    def test_no_match_with_registry(self) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "other_tool"
        mock_registry = MagicMock()
        mock_registry.resolve.return_value = [mock_tool]
        mock_registry.get_deferred_tools.return_value = []

        request = ToolCallRequest(
            tool_call={"name": "bash_tool", "id": "c1", "args": {}},
            tool=None,
            state=None,
            runtime=MagicMock(),
        )

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
                return_value=mock_registry,
            ),
        ):
            result = resolve_dynamic_tool(request)
            assert result.tool is None

    def test_no_registry(self) -> None:
        request = ToolCallRequest(
            tool_call={"name": "bash_tool", "id": "c1", "args": {}},
            tool=None,
            state=None,
            runtime=MagicMock(),
        )

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
                return_value=None,
            ),
        ):
            result = resolve_dynamic_tool(request)
            assert result.tool is None

    def test_resolves_from_active_tools(self) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "bash_tool"

        request = ToolCallRequest(
            tool_call={"name": "bash_tool", "id": "c1", "args": {}},
            tool=None,
            state=None,
            runtime=MagicMock(),
        )

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
                return_value=[mock_tool],
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
                return_value=None,
            ),
        ):
            result = resolve_dynamic_tool(request)
            assert result.tool is mock_tool


class TestHandleExecutionError:
    @pytest.mark.asyncio
    async def test_reraises_graph_interrupt(self) -> None:
        from langgraph.errors import GraphInterrupt

        with pytest.raises(GraphInterrupt):
            await handle_execution_error(
                GraphInterrupt(), "test_tool", "c1", {}
            )

    @pytest.mark.asyncio
    async def test_handles_tool_stuck_exception(self) -> None:
        from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException

        exc = ToolStuckException("stuck")
        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch("langgraph.types.interrupt") as mock_interrupt,
            patch("myrm_agent_harness.agent.hooks.executor.fire_hook", return_value=MagicMock()),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.record_mutation_result"
            ),
        ):
            result = await handle_execution_error(exc, "test_tool", "c1", {})
            mock_interrupt.assert_called_once()
            assert isinstance(result, ToolMessage)

    @pytest.mark.asyncio
    async def test_handles_generic_exception(self) -> None:
        exc = RuntimeError("something broke")
        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_execution_lifecycle.logger"
            ),
            patch("myrm_agent_harness.agent.hooks.executor.fire_hook", return_value=MagicMock()),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.record_mutation_result"
            ),
        ):
            result = await handle_execution_error(exc, "test_tool", "c1", {})
            assert isinstance(result, ToolMessage)
            assert result.status == "error"


class TestEmitToolHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_emits_events(self) -> None:
        with (
            patch(
                "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink"
            ) as mock_sink_fn,
            patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]),
        ):
            from unittest.mock import AsyncMock

            mock_sink = AsyncMock()
            mock_sink_fn.return_value = mock_sink

            with pytest.raises(asyncio.CancelledError):
                await emit_tool_heartbeat("test_tool", "c1", 0.0)

            assert mock_sink.emit.call_count == 1

    @pytest.mark.asyncio
    async def test_heartbeat_handles_exception(self) -> None:
        with (
            patch(
                "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
                side_effect=RuntimeError("sink error"),
            ),
            patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]),pytest.raises(asyncio.CancelledError)
        ):
            await emit_tool_heartbeat("test_tool", "c1", 0.0)
