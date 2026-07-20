"""Tests for tools.py — delegate_to_agent tool and _run_turn_and_collect."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.acp.acp_agent_tools import (
    MAX_TASK_BYTES,
    _run_turn_and_collect,
    create_delegate_to_agent_tool,
)
from myrm_agent_harness.toolkits.acp.types import (
    AcpError,
    AcpErrorCode,
    RuntimeConfig,
    RuntimeEventType,
    create_event,
)


def _make_pool(backends: dict[str, RuntimeConfig] | None = None) -> MagicMock:
    pool = MagicMock()
    _configs = backends or {}
    pool.available_backends = list(_configs.keys())
    pool.get_config = MagicMock(side_effect=lambda name: _configs.get(name))
    pool.cancel = AsyncMock()
    return pool


def _cfg(desc: str = "", max_turns: int = 25) -> RuntimeConfig:
    return RuntimeConfig(
        backend_type="cli",
        command="claude",
        description=desc,
        max_turns=max_turns,
    )


class TestStableDelegateSchema:
    def test_description_identical_regardless_of_pool_backends(self) -> None:
        pool_empty = _make_pool()
        pool_many = _make_pool({"claude": _cfg("Claude"), "codex": _cfg("Codex")})
        desc_empty = create_delegate_to_agent_tool(pool_empty, cwd="/workspace").description
        desc_many = create_delegate_to_agent_tool(pool_many, cwd="/workspace").description
        assert desc_empty == desc_many
        assert "Available agents" not in desc_empty

    @pytest.mark.asyncio
    async def test_key_error_lists_runtime_backends(self) -> None:
        pool = _make_pool({"claude": _cfg(), "codex": _cfg()})

        async def raise_key_error(*args, **kwargs):
            raise KeyError("Unknown backend 'nope'")
            yield  # type: ignore[misc]

        pool.run_turn = raise_key_error
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        result = await tool_func.ainvoke({"agent_name": "nope", "task": "test", "mode": "persistent"})
        assert "Unknown backend" in result
        assert "Available backends: claude, codex" in result


class TestCreateDelegateTool:
    def test_returns_tool_function(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        assert tool_func.name == "delegate_to_agent_tool"
        assert "Available agents" not in tool_func.description
        assert "configured backend" in tool_func.description

    @pytest.mark.asyncio
    async def test_invalid_mode(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        result = await tool_func.ainvoke({"agent_name": "claude", "task": "test", "mode": "bad"})
        assert "[error]" in result
        assert "Invalid mode" in result

    @pytest.mark.asyncio
    async def test_task_too_large(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        huge_task = "x" * (MAX_TASK_BYTES + 100)
        result = await tool_func.ainvoke({"agent_name": "claude", "task": huge_task, "mode": "persistent"})
        assert "[error]" in result
        assert "too large" in result

    @pytest.mark.asyncio
    async def test_successful_delegation(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name: str, task: str, session_id: str, mode: str = "persistent"):
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="response text")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        result = await tool_func.ainvoke({"agent_name": "claude", "task": "write tests", "mode": "persistent"})
        assert "response text" in result
        assert "[Delegation:" in result

    @pytest.mark.asyncio
    async def test_unknown_agent_key_error(self) -> None:
        pool = _make_pool()

        async def raise_key_error(*args, **kwargs):
            raise KeyError("Unknown backend 'nope'")
            yield  # type: ignore[misc]

        pool.run_turn = raise_key_error
        pool.get_config = MagicMock(return_value=None)
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        result = await tool_func.ainvoke({"agent_name": "nope", "task": "test", "mode": "persistent"})
        assert "Unknown backend" in result

    @pytest.mark.asyncio
    async def test_runtime_error_non_retryable(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def raise_error(*args, **kwargs):
            raise RuntimeError("boom")
            yield  # type: ignore[misc]

        pool.run_turn = raise_error
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        result = await tool_func.ainvoke({"agent_name": "claude", "task": "test", "mode": "persistent"})
        assert "[error]" in result
        assert "boom" in result

    @pytest.mark.asyncio
    async def test_retryable_error_retries(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        call_count = 0

        async def fail_then_succeed(name, task, session_id, mode="persistent"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                exc = RuntimeError("transient")
                exc.retryable = True  # type: ignore[attr-defined]
                raise exc
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="ok")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fail_then_succeed
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        result = await tool_func.ainvoke({"agent_name": "claude", "task": "test", "mode": "persistent"})
        assert "ok" in result
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retryable_error_exhausts_retries(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def always_fail(name, task, session_id, mode="persistent"):
            exc = RuntimeError("always transient")
            exc.retryable = True  # type: ignore[attr-defined]
            raise exc
            yield  # type: ignore[misc]

        pool.run_turn = always_fail
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        result = await tool_func.ainvoke({"agent_name": "claude", "task": "test", "mode": "persistent"})
        assert "[error]" in result
        assert "always transient" in result


class TestRunTurnAndCollect:
    @pytest.mark.asyncio
    async def test_text_collection(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="hello ")
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="world")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        result, meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert result == "hello world"
        assert meta["tool_calls"] == 0
        assert meta["errors"] == 0

    @pytest.mark.asyncio
    async def test_tool_start_counting(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TOOL_START, session_id, tool_name="bash")
            yield create_event(RuntimeEventType.TOOL_START, session_id, tool_name="read")
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="done")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        _result, meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert meta["tool_calls"] == 2

    @pytest.mark.asyncio
    async def test_max_turns_exceeded(self) -> None:
        pool = _make_pool({"claude": _cfg(max_turns=2)})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TOOL_START, session_id, tool_name="bash")
            yield create_event(RuntimeEventType.TOOL_START, session_id, tool_name="read")
            yield create_event(RuntimeEventType.TOOL_START, session_id, tool_name="write")

        pool.run_turn = fake_run_turn
        result, _meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert "max turns limit reached" in result
        pool.cancel.assert_awaited()

    @pytest.mark.asyncio
    async def test_usage_tracking(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.USAGE_UPDATE, session_id, input_tokens=100, output_tokens=50)
            yield create_event(RuntimeEventType.USAGE_UPDATE, session_id, input_tokens=200, output_tokens=100)
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        _result, meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert "usage" in meta
        assert meta["usage"]["input_tokens"] == 300
        assert meta["usage"]["output_tokens"] == 150
        assert meta["usage"]["total_tokens"] == 450

    @pytest.mark.asyncio
    async def test_error_event_raises(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(
                RuntimeEventType.ERROR,
                session_id,
                error=AcpError(code=AcpErrorCode.UNKNOWN, message="API error", retryable=True),
            )

        pool.run_turn = fake_run_turn
        with pytest.raises(RuntimeError, match="API error"):
            await _run_turn_and_collect(pool, "claude", "task", mode="persistent")

    @pytest.mark.asyncio
    async def test_cancellation_propagation(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        class FakeCancelToken:
            is_cancelled = True

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="partial")

        pool.run_turn = fake_run_turn
        with patch("myrm_agent_harness.toolkits.acp.acp_agent_tools.get_cancel_token", return_value=FakeCancelToken()):
            result, _meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert "cancelled" in result
        pool.cancel.assert_awaited()

    @pytest.mark.asyncio
    async def test_reasoning_delta_forwarded_to_sink(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        sink = AsyncMock()

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.REASONING_DELTA, session_id, content="thinking...")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        with patch("myrm_agent_harness.toolkits.acp.acp_agent_tools.get_tool_progress_sink", return_value=sink):
            _result, _meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        sink.emit.assert_awaited()

    @pytest.mark.asyncio
    async def test_status_update_forwarded_to_sink(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        sink = AsyncMock()

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.STATUS_UPDATE, session_id, status="starting", message="boot")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        with patch("myrm_agent_harness.toolkits.acp.acp_agent_tools.get_tool_progress_sink", return_value=sink):
            _result, _meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        sink.emit.assert_awaited()

    @pytest.mark.asyncio
    async def test_tool_start_forwarded_to_sink(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        sink = AsyncMock()

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TOOL_START, session_id, tool_name="bash")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        with patch("myrm_agent_harness.toolkits.acp.acp_agent_tools.get_tool_progress_sink", return_value=sink):
            _result, _meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        sink.emit.assert_awaited()

    @pytest.mark.asyncio
    async def test_oneshot_session_id_unique(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        captured_sessions: list[str] = []

        async def capture_session(name, task, session_id, mode="persistent"):
            captured_sessions.append(session_id)
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = capture_session
        await _run_turn_and_collect(pool, "claude", "t1", mode="oneshot")
        await _run_turn_and_collect(pool, "claude", "t2", mode="oneshot")
        assert len(captured_sessions) == 2
        assert captured_sessions[0] != captured_sessions[1]
        assert "oneshot" in captured_sessions[0]

    @pytest.mark.asyncio
    async def test_persistent_session_id_stable(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        captured_sessions: list[str] = []

        async def capture_session(name, task, session_id, mode="persistent"):
            captured_sessions.append(session_id)
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = capture_session
        await _run_turn_and_collect(pool, "claude", "t1", mode="persistent")
        await _run_turn_and_collect(pool, "claude", "t2", mode="persistent")
        assert captured_sessions[0] == captured_sessions[1]
        assert "default" in captured_sessions[0]

    @pytest.mark.asyncio
    async def test_persistent_session_id_uses_scope(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        captured_sessions: list[str] = []

        async def capture_session(name, task, session_id, mode="persistent"):
            captured_sessions.append(session_id)
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = capture_session
        await _run_turn_and_collect(
            pool,
            "claude",
            "t1",
            mode="persistent",
            session_scope="chat-abc",
        )
        assert captured_sessions[0] == "claude-chat-abc"

    @pytest.mark.asyncio
    async def test_text_delta_non_string_content_skipped(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content=None)
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="real text")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        result, _meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert result == "real text"

    @pytest.mark.asyncio
    async def test_no_usage_when_zero_tokens(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="result")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        _result, meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert "usage" not in meta

    @pytest.mark.asyncio
    async def test_truncation_applied(self) -> None:
        pool = _make_pool({"claude": _cfg()})

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="x" * 100_000)
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        result, _meta = await _run_turn_and_collect(pool, "claude", "task", mode="persistent")
        assert len(result) <= 50_100


class TestDelegateToolWithUsageEmit:
    @pytest.mark.asyncio
    async def test_usage_emitted_to_sink(self) -> None:
        pool = _make_pool({"claude": _cfg()})
        sink = AsyncMock()

        async def fake_run_turn(name, task, session_id, mode="persistent"):
            yield create_event(RuntimeEventType.USAGE_UPDATE, session_id, input_tokens=100, output_tokens=50)
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="done")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        pool.run_turn = fake_run_turn
        tool_func = create_delegate_to_agent_tool(pool, cwd="/workspace")
        with patch("myrm_agent_harness.toolkits.acp.acp_agent_tools.get_tool_progress_sink", return_value=sink):
            result = await tool_func.ainvoke({"agent_name": "claude", "task": "test", "mode": "persistent"})
        assert "tokens=" in result
        sink.emit.assert_awaited()
