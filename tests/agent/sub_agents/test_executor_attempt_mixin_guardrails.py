"""Guardrail tests for executor_attempt_mixin (SCIP zero-tool fail-fast + run loop branches)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentStatus
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError


@pytest.fixture
def executor() -> SubagentExecutor:
    return SubagentExecutor()


@pytest.fixture
def basic_config() -> SubagentConfig:
    return SubagentConfig(system_prompt="system prompt here.", timeout_seconds=60)


@pytest.mark.asyncio
async def test_run_single_attempt_cancel_flag_exits(executor: SubagentExecutor, basic_config: SubagentConfig) -> None:
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}

    child_agent = MagicMock()

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": "partial"}

    child_agent.run = mock_run

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child_agent,
    ):
        with pytest.raises(asyncio.CancelledError):
            await executor._run_single_attempt(
                task_id="cancel-me",
                agent_type="browser",
                task_description="task",
                config=basic_config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_tracker=None,
                parent_taint=MagicMock(),
                parent_agent=parent_agent,
                cancel_flags={"cancel-me": True},
                children_agents={},
                fire_hook=AsyncMock(),
                hook_event_cls=MagicMock(SUBAGENT_CANCEL_START="cancel_start"),
            )


@pytest.mark.asyncio
async def test_run_single_attempt_raises_on_child_error_event(
    executor: SubagentExecutor, basic_config: SubagentConfig
) -> None:
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}

    child_agent = MagicMock()

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.ERROR.value, "error": "boom"}

    child_agent.run = mock_run

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child_agent,
    ):
        with pytest.raises(MyrmLLMError, match="Subagent error"):
            await executor._run_single_attempt(
                task_id="err",
                agent_type="browser",
                task_description="task",
                config=basic_config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_tracker=None,
                parent_taint=MagicMock(),
                parent_agent=parent_agent,
                cancel_flags={},
                children_agents={},
                fire_hook=AsyncMock(),
                hook_event_cls=MagicMock(),
            )


@pytest.mark.asyncio
async def test_run_single_attempt_pending_approval_interrupt(
    executor: SubagentExecutor, basic_config: SubagentConfig
) -> None:
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}

    child_agent = MagicMock()
    child_agent.last_run_stats = MagicMock(token_usage=None)

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": "done"}

    child_agent.run = mock_run

    interrupt = MagicMock(value={"action_type": "approval"})
    task = MagicMock(interrupts=[interrupt])
    state = MagicMock(next=True, tasks=[task])
    child_agent.checkpointer = MagicMock(aget=AsyncMock(return_value=state))

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child_agent,
    ), patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin._auto_vault_or_truncate",
        return_value="done",
    ), patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin._parse_handover_state",
        return_value=None,
    ):
        result = await executor._run_single_attempt(
            task_id="approve",
            agent_type="browser",
            task_description="task",
            config=basic_config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_tracker=None,
            parent_taint=MagicMock(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            fire_hook=AsyncMock(),
            hook_event_cls=MagicMock(),
        )

    assert result.success is True
    assert result.status == SubAgentStatus.PENDING_APPROVAL


@pytest.mark.asyncio
async def test_run_single_attempt_swarm_fission_yield(
    executor: SubagentExecutor, basic_config: SubagentConfig
) -> None:
    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}

    child_agent = MagicMock()
    child_agent.last_run_stats = MagicMock(token_usage=None)

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": "yield"}

    child_agent.run = mock_run

    interrupt = MagicMock(value={"action_type": "swarm_fission"})
    task = MagicMock(interrupts=[interrupt])
    state = MagicMock(next=True, tasks=[task])
    child_agent.checkpointer = MagicMock(aget=AsyncMock(return_value=state))

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child_agent,
    ), patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin._auto_vault_or_truncate",
        return_value="yield",
    ), patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin._parse_handover_state",
        return_value=None,
    ):
        result = await executor._run_single_attempt(
            task_id="fission",
            agent_type="browser",
            task_description="task",
            config=basic_config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_tracker=None,
            parent_taint=MagicMock(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            fire_hook=AsyncMock(),
            hook_event_cls=MagicMock(),
        )

    assert result.success is True
    assert result.status == SubAgentStatus.YIELDED


@pytest.mark.asyncio
async def test_run_single_attempt_strips_handover_block(
    executor: SubagentExecutor, basic_config: SubagentConfig
) -> None:
    from myrm_agent_harness.agent.sub_agents.types import AgentHandoverState

    parent_agent = MagicMock()
    parent_agent._subagent_manager = None
    parent_agent._last_context = {}

    child_agent = MagicMock()
    child_agent.last_run_stats = MagicMock(token_usage=None)
    child_agent.checkpointer = None

    raw = 'Summary<body/><handover>{"task_completed": ["x"], "pending_todos": [], "risks_or_notes": [], "relevant_files": []}</handover>'

    async def mock_run(**kwargs: object):
        yield {"type": AgentEventType.MESSAGE.value, "data": raw}

    child_agent.run = mock_run

    handover = AgentHandoverState(task_completed=["x"], pending_todos=[], risks_or_notes=[], relevant_files=[])

    with patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
        return_value=child_agent,
    ), patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin._auto_vault_or_truncate",
        side_effect=lambda text, *args, **kwargs: text,
    ), patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin._parse_handover_state",
        return_value=handover,
    ), patch(
        "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.merge_child_stats",
    ):
        result = await executor._run_single_attempt(
            task_id="handover",
            agent_type="browser",
            task_description="task",
            config=basic_config,
            context={},
            tool_registry_getter=lambda: [],
            start_time=0.0,
            parent_tracker=MagicMock(),
            parent_taint=MagicMock(),
            parent_agent=parent_agent,
            cancel_flags={},
            children_agents={},
            fire_hook=AsyncMock(),
            hook_event_cls=MagicMock(SUBAGENT_STOP="stop"),
        )

    assert result.success is True
    assert result.status == SubAgentStatus.COMPLETED
    assert result.handover_state is not None
    assert "<handover>" not in (result.result or "")
