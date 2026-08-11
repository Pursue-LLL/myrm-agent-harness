"""Tests for AcpRuntime — ACP protocol backend full turn lifecycle.

Covers process spawn, session creation/reuse, prompt streaming, cancel,
close, status, and the error path that surfaces as an ERROR event.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.acp.runtime.acp_runtime import AcpRuntime
from myrm_agent_harness.toolkits.acp.types import RuntimeConfig, RuntimeEventType


def _make_config(**overrides: object) -> RuntimeConfig:
    defaults: dict[str, object] = {"backend_type": "acp", "command": "claude", "cwd": "/tmp/ws"}
    defaults.update(overrides)
    return RuntimeConfig(**defaults)  # type: ignore[arg-type]


def _fake_ctx(conn: MagicMock, process: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=(conn, process))
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _live_process() -> MagicMock:
    proc = MagicMock()
    proc.returncode = None
    return proc


class TestAcpRuntimeProperties:
    def test_capabilities(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        caps = rt.capabilities
        assert caps.supports_resume is True
        assert caps.supports_mcp is True
        assert caps.supports_streaming is True
        assert caps.supports_tools is True

    def test_is_alive_no_process(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        assert rt.is_alive is False

    def test_is_alive_with_live_process(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        rt._process = _live_process()
        assert rt.is_alive is True

    def test_is_alive_with_exited_process(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        proc = MagicMock()
        proc.returncode = 0
        rt._process = proc
        assert rt.is_alive is False


class TestAcpRuntimeTurn:
    @pytest.mark.asyncio
    async def test_do_run_turn_full_lifecycle(self) -> None:
        """Spawn -> session -> prompt -> DONE event in a single turn."""
        rt = AcpRuntime("acp", _make_config())
        conn = MagicMock()
        conn.initialize = AsyncMock()
        conn.new_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
        conn.prompt = AsyncMock(return_value=MagicMock(stop_reason="end_turn"))
        ctx = _fake_ctx(conn, _live_process())

        with patch("acp.spawn_agent_process", return_value=ctx) as spawn_mock:
            events = [e async for e in rt._do_run_turn("hello", "s1")]

        spawn_mock.assert_called_once()
        conn.initialize.assert_awaited_once()
        conn.new_session.assert_awaited_once()
        conn.prompt.assert_awaited_once()
        assert rt._session_id == "sess-1"
        assert any(e.type == RuntimeEventType.DONE for e in events)

    @pytest.mark.asyncio
    async def test_do_run_turn_reuses_session(self) -> None:
        """Connection and session survive across turns; prompt runs per turn."""
        rt = AcpRuntime("acp", _make_config())
        conn = MagicMock()
        conn.initialize = AsyncMock()
        conn.new_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
        conn.prompt = AsyncMock(return_value=MagicMock(stop_reason="end_turn"))
        ctx = _fake_ctx(conn, _live_process())

        with patch("acp.spawn_agent_process", return_value=ctx) as spawn_mock:
            _ = [e async for e in rt._do_run_turn("first", "s1")]
            _ = [e async for e in rt._do_run_turn("second", "s1")]

        spawn_mock.assert_called_once()
        conn.new_session.assert_called_once()
        assert conn.prompt.await_count == 2

    @pytest.mark.asyncio
    async def test_run_turn_prompt_error_yields_error_and_cancels(self) -> None:
        """A failed prompt surfaces as an ERROR event and cancels the session."""
        rt = AcpRuntime("acp", _make_config())
        conn = MagicMock()
        conn.initialize = AsyncMock()
        conn.new_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
        conn.prompt = AsyncMock(side_effect=RuntimeError("kaboom"))
        conn.cancel = AsyncMock()
        ctx = _fake_ctx(conn, _live_process())

        with patch("acp.spawn_agent_process", return_value=ctx):
            events = [e async for e in rt.run_turn("hi", "s1")]

        assert any(e.type == RuntimeEventType.ERROR for e in events)
        conn.cancel.assert_awaited_once_with(session_id="sess-1")


class TestAcpRuntimeLifecycle:
    @pytest.mark.asyncio
    async def test_do_cancel_with_connection(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        conn = MagicMock()
        conn.cancel = AsyncMock()
        rt._conn = conn
        rt._session_id = "sess-1"
        await rt._do_cancel("s1")
        conn.cancel.assert_awaited_once_with(session_id="sess-1")

    @pytest.mark.asyncio
    async def test_do_cancel_without_connection_is_noop(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        await rt._do_cancel("s1")

    @pytest.mark.asyncio
    async def test_do_resume(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        assert await rt._do_resume("s1") is False
        rt._process = _live_process()
        rt._session_id = "sess-1"
        assert await rt._do_resume("s1") is True

    @pytest.mark.asyncio
    async def test_do_get_status_stopped(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        assert await rt._do_get_status() == "stopped"

    @pytest.mark.asyncio
    async def test_do_get_status_ready(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        rt._process = _live_process()
        assert await rt._do_get_status() == "ready"

    @pytest.mark.asyncio
    async def test_do_get_status_error(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        proc = MagicMock()
        proc.returncode = 1
        rt._process = proc
        assert await rt._do_get_status() == "error"

    @pytest.mark.asyncio
    async def test_do_close_with_ctx_manager(self) -> None:
        """Close path that exits the spawn context manager."""
        rt = AcpRuntime("acp", _make_config())
        conn = MagicMock()
        conn.close_session = AsyncMock()
        ctx = MagicMock()
        ctx.__aexit__ = AsyncMock()
        rt._conn = conn
        rt._session_id = "sess-1"
        rt._ctx_manager = ctx
        rt._handler = MagicMock()
        rt._process = _live_process()

        await rt._do_close()

        conn.close_session.assert_awaited_once_with(session_id="sess-1")
        ctx.__aexit__.assert_awaited_once()
        assert rt._conn is None
        assert rt._process is None
        assert rt._session_id is None
        assert rt._handler is None

    @pytest.mark.asyncio
    async def test_do_close_without_ctx_manager(self) -> None:
        """Close path that closes the connection and terminates the process."""
        rt = AcpRuntime("acp", _make_config())
        conn = MagicMock()
        conn.close = AsyncMock()
        proc = _live_process()
        rt._conn = conn
        rt._process = proc

        await rt._do_close()

        conn.close.assert_awaited_once()
        proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_connection_requires_command(self) -> None:
        rt = AcpRuntime("acp", _make_config(command=None))
        with pytest.raises(ValueError):
            await rt._ensure_connection()

    @pytest.mark.asyncio
    async def test_create_session_without_connection(self) -> None:
        rt = AcpRuntime("acp", _make_config())
        with pytest.raises(RuntimeError):
            await rt._create_session()
