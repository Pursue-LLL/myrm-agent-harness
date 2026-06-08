"""Unit tests for ToolCallBroadcaster — full lifecycle coverage.

Covers:
- PRE_TOOL_USE → "started" event published to EventBus + EventLogger
- POST_TOOL_USE → "completed" event with duration_ms + evicted_ref
- POST_TOOL_USE_FAILURE → "failed" event with error details
- POST_TOOL_USE_CANCELLED → "cancelled" event with cancel_reason
- Duration tracking across start/end events
- Missing tool_call_id graceful handling
- register_to_hook_registry() wiring
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.observability.tool_call_broadcaster import (
    ToolCallBroadcaster,
    register_to_hook_registry,
)
from myrm_agent_harness.agent.observability.types import ToolCallEventData


@pytest.fixture
def mock_event_bus():
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_event_logger():
    logger = AsyncMock()
    logger.log = AsyncMock()
    return logger


@pytest.fixture
def broadcaster(mock_event_logger):
    return ToolCallBroadcaster(event_logger=mock_event_logger)


@pytest.fixture
def _patch_event_bus(broadcaster, mock_event_bus):
    broadcaster._event_bus = mock_event_bus


def _make_payload(
    tool_name: str = "bash_tool",
    tool_call_id: str = "tc_001",
    **extra,
) -> dict:
    return {"tool_name": tool_name, "tool_call_id": tool_call_id, **extra}


# ===========================================================================
# PRE_TOOL_USE → started
# ===========================================================================


class TestPreToolUse:
    @pytest.mark.asyncio
    async def test_publishes_started_event(self, broadcaster, mock_event_bus, _patch_event_bus):
        result = await broadcaster.on_pre_tool_use("pre_tool_use", _make_payload())
        assert result.success is True
        mock_event_bus.publish.assert_awaited_once()
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.tool_name == "bash_tool"
        assert event_data.status == "started"
        assert event_data.tool_call_id == "tc_001"

    @pytest.mark.asyncio
    async def test_logs_to_event_logger(self, broadcaster, mock_event_bus, mock_event_logger, _patch_event_bus):
        await broadcaster.on_pre_tool_use("pre_tool_use", _make_payload())
        mock_event_logger.log.assert_awaited_once()
        args = mock_event_logger.log.call_args
        assert args[0][0] == "tool_start"

    @pytest.mark.asyncio
    async def test_tracks_pending_call(self, broadcaster, mock_event_bus, _patch_event_bus):
        await broadcaster.on_pre_tool_use("pre_tool_use", _make_payload(tool_call_id="tc_track"))
        assert "tc_track" in broadcaster._pending_calls

    @pytest.mark.asyncio
    async def test_captures_tool_input(self, broadcaster, mock_event_bus, _patch_event_bus):
        payload = _make_payload(tool_input={"command": "ls -la"})
        await broadcaster.on_pre_tool_use("pre_tool_use", payload)
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.args == {"command": "ls -la"}

    @pytest.mark.asyncio
    async def test_no_event_logger_ok(self, mock_event_bus):
        b = ToolCallBroadcaster(event_logger=None)
        b._event_bus = mock_event_bus
        result = await b.on_pre_tool_use("pre_tool_use", _make_payload())
        assert result.success is True
        mock_event_bus.publish.assert_awaited_once()


# ===========================================================================
# POST_TOOL_USE → completed
# ===========================================================================


class TestPostToolUse:
    @pytest.mark.asyncio
    async def test_publishes_completed_with_duration(self, broadcaster, mock_event_bus, _patch_event_bus):
        broadcaster._pending_calls["tc_dur"] = time.time() - 1.5
        result = await broadcaster.on_post_tool_use(
            "post_tool_use",
            _make_payload(tool_call_id="tc_dur", tool_output="ok"),
        )
        assert result.success is True
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.status == "completed"
        assert event_data.duration_ms is not None
        assert event_data.duration_ms >= 1000

    @pytest.mark.asyncio
    async def test_extracts_evicted_ref(self, broadcaster, mock_event_bus, _patch_event_bus):
        broadcaster._pending_calls["tc_ev"] = time.time()
        payload = _make_payload(
            tool_call_id="tc_ev",
            tool_output={"evicted_ref": "/tmp/evicted_output_abc.txt", "data": "large"},
        )
        await broadcaster.on_post_tool_use("post_tool_use", payload)
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.evicted_ref == "/tmp/evicted_output_abc.txt"

    @pytest.mark.asyncio
    async def test_missing_pending_call_uses_end_time(self, broadcaster, mock_event_bus, _patch_event_bus):
        result = await broadcaster.on_post_tool_use(
            "post_tool_use",
            _make_payload(tool_call_id="tc_missing", tool_output="x"),
        )
        assert result.success is True
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.duration_ms == 0

    @pytest.mark.asyncio
    async def test_logs_tool_end(self, broadcaster, mock_event_bus, mock_event_logger, _patch_event_bus):
        broadcaster._pending_calls["tc_log"] = time.time()
        await broadcaster.on_post_tool_use("post_tool_use", _make_payload(tool_call_id="tc_log", tool_output="done"))
        assert mock_event_logger.log.call_args[0][0] == "tool_end"


# ===========================================================================
# POST_TOOL_USE_FAILURE → failed
# ===========================================================================


class TestPostToolUseFailure:
    @pytest.mark.asyncio
    async def test_publishes_failed_event(self, broadcaster, mock_event_bus, _patch_event_bus):
        broadcaster._pending_calls["tc_fail"] = time.time() - 0.5
        result = await broadcaster.on_post_tool_use_failure(
            "post_tool_use_failure",
            _make_payload(tool_call_id="tc_fail", error="TimeoutError: 30s limit"),
        )
        assert result.success is True
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.status == "failed"
        assert "TimeoutError" in (event_data.error or "")

    @pytest.mark.asyncio
    async def test_logs_tool_failure(self, broadcaster, mock_event_bus, mock_event_logger, _patch_event_bus):
        broadcaster._pending_calls["tc_fl"] = time.time()
        await broadcaster.on_post_tool_use_failure(
            "post_tool_use_failure",
            _make_payload(tool_call_id="tc_fl", error="oops"),
        )
        assert mock_event_logger.log.call_args[0][0] == "tool_failure"


# ===========================================================================
# POST_TOOL_USE_CANCELLED → cancelled
# ===========================================================================


class TestPostToolUseCancelled:
    @pytest.mark.asyncio
    async def test_publishes_cancelled_event(self, broadcaster, mock_event_bus, _patch_event_bus):
        broadcaster._pending_calls["tc_cancel"] = time.time()
        result = await broadcaster.on_post_tool_use_cancelled(
            "post_tool_use_cancelled",
            _make_payload(tool_call_id="tc_cancel", cancel_reason="user_cancelled"),
        )
        assert result.success is True
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.status == "cancelled"
        assert event_data.cancel_reason == "user_cancelled"
        assert event_data.error == "Tool execution was cancelled"

    @pytest.mark.asyncio
    async def test_logs_tool_cancelled(self, broadcaster, mock_event_bus, mock_event_logger, _patch_event_bus):
        broadcaster._pending_calls["tc_cl"] = time.time()
        await broadcaster.on_post_tool_use_cancelled(
            "post_tool_use_cancelled",
            _make_payload(tool_call_id="tc_cl", cancel_reason="timeout"),
        )
        assert mock_event_logger.log.call_args[0][0] == "tool_cancelled"

    @pytest.mark.asyncio
    async def test_no_cancel_reason_defaults(self, broadcaster, mock_event_bus, _patch_event_bus):
        broadcaster._pending_calls["tc_def"] = time.time()
        await broadcaster.on_post_tool_use_cancelled(
            "post_tool_use_cancelled",
            _make_payload(tool_call_id="tc_def"),
        )
        event_data: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert event_data.cancel_reason is None


# ===========================================================================
# register_to_hook_registry()
# ===========================================================================


class TestRegisterToHookRegistry:
    def test_registers_four_hooks(self, mock_event_logger):
        registry = MagicMock()
        broadcaster = register_to_hook_registry(registry, event_logger=mock_event_logger)
        assert isinstance(broadcaster, ToolCallBroadcaster)
        assert registry.register.call_count == 4

    def test_registers_without_logger(self):
        registry = MagicMock()
        broadcaster = register_to_hook_registry(registry, event_logger=None)
        assert broadcaster._event_logger is None
        assert registry.register.call_count == 4


# ===========================================================================
# Full lifecycle test (start → complete)
# ===========================================================================


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_start_then_complete_computes_correct_duration(self, broadcaster, mock_event_bus, _patch_event_bus):
        await broadcaster.on_pre_tool_use("pre_tool_use", _make_payload(tool_call_id="tc_full"))
        await asyncio.sleep(0.05)
        await broadcaster.on_post_tool_use(
            "post_tool_use",
            _make_payload(tool_call_id="tc_full", tool_output="result"),
        )
        completed_event: ToolCallEventData = mock_event_bus.publish.call_args[0][0]
        assert completed_event.status == "completed"
        assert completed_event.duration_ms >= 30
        assert "tc_full" not in broadcaster._pending_calls

    @pytest.mark.asyncio
    async def test_start_then_fail_cleans_pending(self, broadcaster, mock_event_bus, _patch_event_bus):
        await broadcaster.on_pre_tool_use("pre_tool_use", _make_payload(tool_call_id="tc_sf"))
        await broadcaster.on_post_tool_use_failure(
            "post_tool_use_failure",
            _make_payload(tool_call_id="tc_sf", error="crash"),
        )
        assert "tc_sf" not in broadcaster._pending_calls
