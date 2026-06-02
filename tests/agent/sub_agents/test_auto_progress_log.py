"""测试SubagentManager自动Progress+Log转发系统"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.hooks.types import HookEvent
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.mark.asyncio
async def test_emit_error_handling():
    """测试sink.emit()错误处理：失败时不影响子agent运行"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=100)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 50}}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    mock_sink = AsyncMock()
    mock_sink.emit = AsyncMock(side_effect=Exception("Sink failed"))

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.logger") as mock_logger,
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-emit-error",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-emit-error",
        )

        assert result.success
        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "Failed to emit" in warning_msg


@pytest.mark.asyncio
async def test_tool_based_progress_without_budget():
    """测试budget_tokens=None时基于工具调用次数的进度计算"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=100)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOOL_END.value, "data": {"tool_name": "tool1"}, "duration_ms": 100}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 50}}}
        yield {"type": AgentEventType.TOOL_END.value, "data": {"tool_name": "tool2"}, "duration_ms": 200}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 100}}}
        yield {"type": AgentEventType.TOOL_END.value, "data": {"tool_name": "tool3"}, "duration_ms": 150}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=None, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-tool-based",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-tool-based",
        )

        assert result.success

        progress_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_PROGRESS.value]
        assert len(progress_events) >= 2

        assert progress_events[0]["data"]["is_estimated"] is True
        assert progress_events[0]["data"]["tool_count"] == 1
        assert abs(progress_events[0]["data"]["progress"] - 0.125) < 0.01

        assert progress_events[1]["data"]["tool_count"] == 2
        assert abs(progress_events[1]["data"]["progress"] - 0.25) < 0.01


@pytest.mark.asyncio
async def test_progress_throttling():
    """测试事件节流机制：progress变化<5%且时间<1s时不发送重复事件"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=100)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 10}}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 15}}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 20}}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 100}}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-throttle",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-throttle",
        )

        assert result.success

        progress_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_PROGRESS.value]

        assert len(progress_events) == 2


@pytest.mark.asyncio
async def test_current_step_tracking():
    """测试current_step字段：追踪当前工具名称"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=200)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOOL_START.value, "data": {"tool_name": "web_search"}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 100}}}
        yield {"type": AgentEventType.TOOL_END.value, "data": {"tool_name": "web_search"}, "duration_ms": 1000}
        yield {"type": AgentEventType.TOOL_START.value, "data": {"tool_name": "analyze"}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 200}}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-current-step",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-current-step",
        )

        assert result.success

        progress_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_PROGRESS.value]
        assert len(progress_events) >= 2

        assert progress_events[0]["data"]["current_step"] == "web_search"
        assert progress_events[1]["data"]["current_step"] == "analyze"


@pytest.mark.asyncio
async def test_tool_error_forwarding():
    """测试TOOL_ERROR事件转发：将工具错误转换为LOG事件"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOOL_START.value, "data": {"tool_name": "web_search"}}
        yield {
            "type": AgentEventType.TOOL_FAILURE.value,
            "data": {"tool_name": "web_search", "error": "Connection timeout"},
        }
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-tool-error",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-tool-error",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        error_logs = [e for e in log_events if e["data"]["level"] == "ERROR"]

        assert len(error_logs) == 1
        assert error_logs[0]["data"]["tool_name"] == "web_search"
        assert "Connection timeout" in error_logs[0]["data"]["message"]
        assert error_logs[0]["data"]["error"] == "Connection timeout"


@pytest.mark.asyncio
async def test_progress_deduplication():
    """测试progress值去重：完全相同的progress值不会重复发送"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=100)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 100}}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 100}}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 100}}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 200}}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-dedup",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-dedup",
        )

        assert result.success

        progress_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_PROGRESS.value]

        assert len(progress_events) == 2
        assert progress_events[0]["data"]["progress"] == 0.1
        assert progress_events[1]["data"]["progress"] == 0.2


@pytest.mark.asyncio
async def test_custom_progress_calculator():
    """测试自定义ProgressCalculator：业务层可注入自定义进度计算逻辑"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=150)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 50}}}
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 150}}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    class CustomCalculator:
        def calculate_progress(
            self, current_tokens: int, budget_tokens: int | None, tool_count: int, elapsed_seconds: float
        ) -> dict[str, object]:
            return {
                "progress": 0.99,
                "current_tokens": current_tokens,
                "custom_field": "custom_value",
                "elapsed_seconds": elapsed_seconds,
            }

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(
            system_prompt="You are a test agent",
            budget_tokens=1000,
            max_result_tokens=5000,
            progress_calculator=CustomCalculator(),
        )

        result = await manager._executor._run_single_attempt(
            task_id="test-custom-calc",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-custom-calc",
        )

        assert result.success

        progress_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_PROGRESS.value]
        assert len(progress_events) >= 1

        assert progress_events[0]["data"]["progress"] == 0.99
        assert progress_events[0]["data"]["custom_field"] == "custom_value"
        assert "elapsed_seconds" in progress_events[0]["data"]


@pytest.mark.asyncio
async def test_eta_calculation():
    """测试ETA计算：基于token消耗速率估算剩余时间"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=400)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 100}}}
        await asyncio.sleep(0.1)
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 200}}}
        await asyncio.sleep(0.1)
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 300}}}
        await asyncio.sleep(0.1)
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 400}}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-eta",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-eta",
        )

        assert result.success

        progress_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_PROGRESS.value]

        eta_events = [e for e in progress_events if "eta_seconds" in e["data"]]
        assert len(eta_events) >= 1

        assert "eta_readable" in eta_events[-1]["data"]


@pytest.mark.asyncio
async def test_auto_progress_emission():
    """测试自动进度事件发送"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=500)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOKEN_USAGE.value, "data": {"usage": {"total_tokens": 250}}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "test result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-123",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-123",
        )

        assert result.success

        progress_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_PROGRESS.value]
        assert len(progress_events) == 1
        assert progress_events[0]["data"]["progress"] == 0.25
        assert progress_events[0]["data"]["current_tokens"] == 250
        assert progress_events[0]["data"]["budget_tokens"] == 1000


@pytest.mark.asyncio
async def test_auto_log_emission():
    """测试自动日志事件转发"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=100)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TOOL_START.value, "data": {"tool_name": "web_search"}}
        yield {"type": AgentEventType.TOOL_END.value, "data": {"tool_name": "web_search"}, "duration_ms": 1500}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []
    mock_sink = AsyncMock()

    async def capture_emit(event):
        emitted_events.append(event)

    mock_sink.emit = capture_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-456",
            agent_type="test_agent",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-456",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        assert len(log_events) == 2
        assert "calling_tool" in log_events[0]["data"]["message"]
        assert "tool_execution_completed" in log_events[1]["data"]["message"]
        assert log_events[1]["data"]["duration_ms"] == 1500


@pytest.mark.asyncio
async def test_reasoning_event_forwarding():
    """测试REASONING事件转发为SUBAGENT_LOG"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.REASONING.value, "data": "Analyzing the problem..."}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []

    async def mock_emit(event):
        emitted_events.append(event)

    mock_sink = AsyncMock()
    mock_sink.emit = mock_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-task",
            agent_type="generalPurpose",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-reasoning",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        reasoning_logs = [e for e in log_events if "Thinking:" in e["data"]["message"]]
        assert len(reasoning_logs) == 1
        assert " Thinking: Analyzing the problem..." in reasoning_logs[0]["data"]["message"]
        assert reasoning_logs[0]["data"]["level"] == "DEBUG"


@pytest.mark.asyncio
async def test_tasks_steps_event_forwarding():
    """测试TASKS_STEPS事件转发为SUBAGENT_LOG"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.TASKS_STEPS.value, "step_key": "analyzing", "tool_name": "web_search"}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []

    async def mock_emit(event):
        emitted_events.append(event)

    mock_sink = AsyncMock()
    mock_sink.emit = mock_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-task",
            agent_type="generalPurpose",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-tasks-steps",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        steps_logs = [e for e in log_events if "analyzing" in e["data"]["message"]]
        assert len(steps_logs) == 1
        assert "analyzing" in steps_logs[0]["data"]["message"]
        assert steps_logs[0]["data"]["level"] == "INFO"
        assert steps_logs[0]["data"]["step_key"] == "analyzing"


@pytest.mark.asyncio
async def test_ui_update_event_forwarding():
    """测试UI_UPDATE事件直接透传"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.UI_UPDATE.value, "data": {"action": "open_form", "content": "test form"}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []

    async def mock_emit(event):
        emitted_events.append(event)

    mock_sink = AsyncMock()
    mock_sink.emit = mock_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-task",
            agent_type="generalPurpose",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-ui-update",
        )

        assert result.success

        ui_events = [e for e in emitted_events if e["type"] == AgentEventType.UI_UPDATE.value]
        assert len(ui_events) == 1
        assert ui_events[0]["data"]["action"] == "open_form"
        assert ui_events[0]["data"]["content"] == "test form"


@pytest.mark.asyncio
async def test_status_event_forwarding():
    """测试STATUS事件转发为SUBAGENT_LOG"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {"type": AgentEventType.STATUS.value, "data": {"message": "Compacting history..."}}
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []

    async def mock_emit(event):
        emitted_events.append(event)

    mock_sink = AsyncMock()
    mock_sink.emit = mock_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-task",
            agent_type="generalPurpose",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-status",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        status_logs = [e for e in log_events if "ℹ Compacting history..." in e["data"]["message"]]
        assert len(status_logs) == 1
        assert status_logs[0]["data"]["level"] == "INFO"


@pytest.mark.asyncio
async def test_tool_cancelled_forwarding():
    """测试TOOL_CANCELLED事件转发为SUBAGENT_LOG"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {
            "type": AgentEventType.TOOL_CANCELLED.value,
            "data": {
                "tool_name": "web_search",
                "cancel_reason": "user_cancelled",
                "duration_ms": 2500,
            },
        }
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []

    async def mock_emit(event):
        emitted_events.append(event)

    mock_sink = AsyncMock()
    mock_sink.emit = mock_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-task",
            agent_type="generalPurpose",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-tool-cancelled",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        cancelled_logs = [e for e in log_events if "Tool cancelled" in e["data"]["message"]]
        assert len(cancelled_logs) == 1
        assert cancelled_logs[0]["data"]["level"] == "WARNING"
        assert cancelled_logs[0]["data"]["tool_name"] == "web_search"
        assert cancelled_logs[0]["data"]["cancel_reason"] == "user_cancelled"
        assert cancelled_logs[0]["data"]["duration_ms"] == 2500


@pytest.mark.asyncio
async def test_tool_timeout_forwarding():
    """测试TOOL_TIMEOUT事件转发为SUBAGENT_LOG"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {
            "type": AgentEventType.TOOL_TIMEOUT.value,
            "data": {
                "tool_name": "bash_tool",
                "timeout_seconds": 30,
                "attempt": 1,
                "elapsed_ms": 30100,
            },
        }
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []

    async def mock_emit(event):
        emitted_events.append(event)

    mock_sink = AsyncMock()
    mock_sink.emit = mock_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-task",
            agent_type="generalPurpose",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-tool-timeout",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        timeout_logs = [e for e in log_events if "Tool timeout" in e["data"]["message"]]
        assert len(timeout_logs) == 1
        assert timeout_logs[0]["data"]["level"] == "WARNING"
        assert timeout_logs[0]["data"]["tool_name"] == "bash_tool"
        assert timeout_logs[0]["data"]["timeout_seconds"] == 30
        assert timeout_logs[0]["data"]["attempt"] == 1
        assert timeout_logs[0]["data"]["elapsed_ms"] == 30100


@pytest.mark.asyncio
async def test_tool_retry_forwarding():
    """测试TOOL_RETRY事件转发为SUBAGENT_LOG"""
    mock_parent = MagicMock()
    manager = SubagentManager(parent_agent=mock_parent, current_depth=0)

    mock_child_agent = MagicMock()
    mock_child_agent.last_run_stats = MagicMock()
    mock_child_agent.last_run_stats.token_usage = MagicMock(total_tokens=50)

    async def mock_run(*args, **kwargs):
        yield {
            "type": AgentEventType.TOOL_RETRY.value,
            "data": {
                "tool_name": "file_read",
                "attempt": 2,
                "max_attempts": 2,
                "reason": "timeout",
                "backoff_seconds": 1.5,
            },
        }
        yield {"type": AgentEventType.MESSAGE.value, "data": "result"}

    mock_child_agent.run = mock_run

    emitted_events = []

    async def mock_emit(event):
        emitted_events.append(event)

    mock_sink = AsyncMock()
    mock_sink.emit = mock_emit

    mock_fire_hook = AsyncMock()
    mock_parent_tracker = MagicMock()
    mock_parent_taint = MagicMock()
    mock_parent_taint.is_tainted = False

    with (
            patch("myrm_agent_harness.agent.sub_agents.event_forwarder.get_tool_progress_sink", return_value=mock_sink),
        patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=mock_child_agent),
        patch("myrm_agent_harness.agent.sub_agents.executor.get_taint_tracker", return_value=mock_parent_taint),
    ):
        config = SubagentConfig(system_prompt="You are a test agent", budget_tokens=1000, max_result_tokens=5000)

        result = await manager._executor._run_single_attempt(
            task_id="test-task",
            agent_type="generalPurpose",
            task_description="Test task",
            config=config,
            context={},
            tool_registry_getter=lambda: [],
                start_time=time.time(),
                parent_tracker=mock_parent_tracker,
                parent_taint=mock_parent_taint,
                parent_agent=mock_parent,
                cancel_flags=manager._cancel_flags,
                children_agents=manager._children_agents,
                fire_hook=mock_fire_hook,
            hook_event_cls=HookEvent,
            trace_id="trace-tool-retry",
        )

        assert result.success

        log_events = [e for e in emitted_events if e["type"] == AgentEventType.SUBAGENT_LOG.value]
        retry_logs = [e for e in log_events if "Tool retry" in e["data"]["message"]]
        assert len(retry_logs) == 1
        assert retry_logs[0]["data"]["level"] == "INFO"
        assert retry_logs[0]["data"]["tool_name"] == "file_read"
        assert retry_logs[0]["data"]["attempt"] == 2
        assert retry_logs[0]["data"]["max_attempts"] == 2
        assert retry_logs[0]["data"]["reason"] == "timeout"
        assert retry_logs[0]["data"]["backoff_seconds"] == 1.5
