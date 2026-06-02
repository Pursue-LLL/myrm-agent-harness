"""Tests for ACP AgentBridge — session lifecycle and prompt execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from acp.schema import PromptResponse

from myrm_agent_harness.toolkits.acp.server.bridge import AgentBridge, AgentFactory

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning:unittest.mock")


class _StubAgent:
    """Minimal agent stub that yields configurable events."""

    def __init__(self, events: list[dict[str, object]] | None = None) -> None:
        self._events = events or [{"type": "message", "data": "hello"}]

    async def run(self, **kwargs: object) -> AsyncGenerator[dict[str, object]]:
        for event in self._events:
            yield event


class _ErrorAgent:
    """Agent that raises during streaming."""

    async def run(self, **kwargs: object) -> AsyncGenerator[dict[str, object]]:
        yield {"type": "message", "data": "start"}
        raise RuntimeError("agent_error")


class _CancelAgent:
    """Agent that simulates cancellation."""

    async def run(self, **kwargs: object) -> AsyncGenerator[dict[str, object]]:
        yield {"type": "message", "data": "before_cancel"}
        raise asyncio.CancelledError()


class _StubFactory:
    def __init__(self, agent: object | None = None) -> None:
        self._agent = agent or _StubAgent()

    async def create_agent(self, session_id: str, cwd: str) -> object:
        return self._agent


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_create_session(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")
        assert bridge.has_session(sid)
        assert sid in bridge.list_sessions()

    @pytest.mark.asyncio
    async def test_close_session(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")
        bridge.close_session(sid)
        assert not bridge.has_session(sid)

    @pytest.mark.asyncio
    async def test_close_nonexistent_session_is_noop(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        bridge.close_session("nonexistent")

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        assert bridge.list_sessions() == []

    @pytest.mark.asyncio
    async def test_multiple_sessions(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        s1 = await bridge.create_session("/a")
        s2 = await bridge.create_session("/b")
        assert len(bridge.list_sessions()) == 2
        bridge.close_session(s1)
        assert bridge.list_sessions() == [s2]


class TestPromptExecution:
    @pytest.mark.asyncio
    async def test_prompt_success(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")

        conn = MagicMock()
        conn.session_notification = AsyncMock()

        result = await bridge.prompt(sid, "hello", conn)
        assert isinstance(result, PromptResponse)
        assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_prompt_unknown_session(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        conn = MagicMock()
        result = await bridge.prompt("nonexistent", "hello", conn)
        assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_prompt_sends_notifications(self) -> None:
        bridge = AgentBridge(_StubFactory(_StubAgent([{"type": "message", "data": "hi"}])))  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")

        conn = MagicMock()
        conn.session_notification = AsyncMock()

        await bridge.prompt(sid, "hello", conn)
        assert conn.session_notification.call_count >= 1

    @pytest.mark.asyncio
    async def test_prompt_error_returns_end_turn(self) -> None:
        bridge = AgentBridge(_StubFactory(_ErrorAgent()))  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")

        conn = MagicMock()
        conn.session_notification = AsyncMock()

        result = await bridge.prompt(sid, "hello", conn)
        assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_prompt_cancelled_returns_cancelled(self) -> None:
        bridge = AgentBridge(_StubFactory(_CancelAgent()))  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")

        conn = MagicMock()
        conn.session_notification = AsyncMock()

        result = await bridge.prompt(sid, "hello", conn)
        assert result.stop_reason == "cancelled"

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_break_stream(self) -> None:
        bridge = AgentBridge(
            _StubFactory(
                _StubAgent(
                    [
                        {"type": "message", "data": "m1"},
                        {"type": "message", "data": "m2"},
                    ]
                )
            )
        )  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")

        conn = MagicMock()
        conn.session_notification = AsyncMock(side_effect=ConnectionError("broken"))

        result = await bridge.prompt(sid, "hello", conn)
        assert result.stop_reason == "end_turn"


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_session_is_noop(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        await bridge.cancel("nonexistent")

    @pytest.mark.asyncio
    async def test_cancel_without_active_prompt_is_noop(self) -> None:
        bridge = AgentBridge(_StubFactory())  # type: ignore[arg-type]
        sid = await bridge.create_session("/tmp")
        await bridge.cancel(sid)


class TestAgentFactoryProtocol:
    def test_stub_factory_satisfies_protocol(self) -> None:
        assert isinstance(_StubFactory(), AgentFactory)
