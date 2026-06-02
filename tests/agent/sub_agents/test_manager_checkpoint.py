"""Tests for SubagentManager checkpoint and resume capabilities."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.sub_agents.checkpoint.saver import SubagentCheckpoint, SubagentCheckpointStorage
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.types import (
    CancellationStrategy,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.agent.types import AgentRuntimeConfig

_DEFAULT_PROMPT = "You are a helpful assistant."


class _FakeLLM:
    def bind(self, **kwargs: object) -> _FakeLLM:
        return self

    def bind_tools(self, tools: list[BaseTool], **kwargs: object) -> _FakeLLM:
        return self

    async def ainvoke(self, messages: object, config: object | None = None) -> AIMessage:
        return AIMessage(content="done")


class _FakeStatus(Enum):
    COMPLETED = "completed"


@dataclass
class _FakeTokenUsage:
    total_tokens: int = 100

    def to_dict(self) -> dict[str, int]:
        return {"total_tokens": self.total_tokens}


@dataclass
class _FakeRunStats:
    token_usage: _FakeTokenUsage | None = field(default_factory=_FakeTokenUsage)
    duration_seconds: float = 5.0
    status: _FakeStatus | None = _FakeStatus.COMPLETED


class _FakeChildAgent:
    """Minimal child agent stub for checkpoint tests."""

    def __init__(self) -> None:
        self._last_context: dict[str, object] = {"session_id": "s1", "workspace_path": "/tmp"}
        self.last_run_stats = _FakeRunStats()
        self.session_id = "s1"

    async def get_checkpoint_state(self, thread_id: str = "") -> dict[str, object]:
        return {
            "messages": [{"role": "user", "content": "test"}],
            "context": self._last_context,
            "progress": 0.7,
            "last_tool": "web_search",
        }


def _make_manager() -> SubagentManager:
    agent = BaseAgent(llm=_FakeLLM(), config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=30))
    agent.session_id = "test-session"
    return agent._subagent_manager


def _make_config(**overrides: object) -> SubagentConfig:
    """Create a SubagentConfig with required system_prompt."""
    defaults: dict[str, object] = {"system_prompt": _DEFAULT_PROMPT}
    defaults.update(overrides)
    return SubagentConfig(**defaults)  # type: ignore[arg-type]


# =========================================================================
# _create_checkpoint (sync)
# =========================================================================


class TestCreateCheckpointSync:
    def test_raises_when_no_config(self) -> None:
        manager = _make_manager()
        with pytest.raises(ValueError, match="No config found"):
            manager._checkpoint_manager.create_checkpoint("missing-task", manager._children_agents, manager._children_configs, manager._children_types, manager._parent_agent)

    def test_minimal_checkpoint_when_no_agent(self) -> None:
        manager = _make_manager()
        manager._children_configs["task-1"] = _make_config()
        manager._children_types["task-1"] = "researcher"

        cp = manager._checkpoint_manager.create_checkpoint("task-1", manager._children_agents, manager._children_configs, manager._children_types, manager._parent_agent)
        assert cp.task_id == "task-1"
        assert cp.agent_type == "researcher"
        assert cp.resumable is False
        assert cp.messages == []

    def test_checkpoint_with_agent(self) -> None:
        manager = _make_manager()
        manager._children_configs["task-1"] = _make_config()
        manager._children_types["task-1"] = "researcher"

        child = _FakeChildAgent()
        child._last_context = {"session_id": "s1", "key": "val"}
        child.last_run_stats = _FakeRunStats()
        manager._children_agents["task-1"] = child  # type: ignore[assignment]

        cp = manager._checkpoint_manager.create_checkpoint("task-1", manager._children_agents, manager._children_configs, manager._children_types, manager._parent_agent)
        assert cp.task_id == "task-1"
        assert cp.resumable is False
        assert cp.progress == 1.0

    def test_agent_type_from_children_types(self) -> None:
        """Verify agent_type is read from _children_types, not config."""
        manager = _make_manager()
        manager._children_configs["task-1"] = _make_config()
        manager._children_types["task-1"] = "custom_coder"

        cp = manager._checkpoint_manager.create_checkpoint("task-1", manager._children_agents, manager._children_configs, manager._children_types, manager._parent_agent)
        assert cp.agent_type == "custom_coder"


# =========================================================================
# _create_checkpoint_async
# =========================================================================


class TestCreateCheckpointAsync:
    @pytest.mark.asyncio
    async def test_raises_when_no_config(self) -> None:
        manager = _make_manager()
        with pytest.raises(ValueError, match="No config found"):
            await manager._checkpoint_manager.create_checkpoint_async("missing-task", manager._children_agents, manager._children_configs, manager._children_types)

    @pytest.mark.asyncio
    async def test_minimal_checkpoint_when_no_agent(self) -> None:
        manager = _make_manager()
        manager._children_configs["task-2"] = _make_config()
        manager._children_types["task-2"] = "coder"

        cp = await manager._checkpoint_manager.create_checkpoint_async("task-2", manager._children_agents, manager._children_configs, manager._children_types)
        assert cp.resumable is False
        assert cp.messages == []
        assert cp.agent_type == "coder"

    @pytest.mark.asyncio
    async def test_checkpoint_with_agent_async(self) -> None:
        manager = _make_manager()
        manager._children_configs["task-1"] = _make_config()
        manager._children_types["task-1"] = "researcher"

        child = _FakeChildAgent()
        manager._children_agents["task-1"] = child  # type: ignore[assignment]

        cp = await manager._checkpoint_manager.create_checkpoint_async("task-1", manager._children_agents, manager._children_configs, manager._children_types)
        assert cp.task_id == "task-1"
        assert cp.progress == 0.7
        assert cp.last_tool == "web_search"
        assert cp.resumable is True
        assert len(cp.messages) == 1


# =========================================================================
# resume_from_checkpoint
# =========================================================================


class TestResumeFromCheckpoint:
    @pytest.mark.asyncio
    async def test_raises_when_no_checkpoint(self, tmp_path) -> None:
        manager = _make_manager()
        manager._checkpoint_storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        with pytest.raises(ValueError, match="No checkpoint found"):
            await manager.resume_from_checkpoint("no-such-task")

    @pytest.mark.asyncio
    async def test_raises_when_not_resumable(self, tmp_path) -> None:
        manager = _make_manager()
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        manager._checkpoint_storage = storage
        manager._checkpoint_manager._storage = storage

        cp = SubagentCheckpoint(
            task_id="task-x", agent_type="coder", session_id="s1", timestamp=time.time(), resumable=False
        )
        await storage.save(cp)

        with pytest.raises(ValueError, match="not resumable"):
            await manager.resume_from_checkpoint("task-x")

    @pytest.mark.asyncio
    async def test_successful_resume(self, tmp_path) -> None:
        manager = _make_manager()
        storage = SubagentCheckpointStorage(storage_path=tmp_path / "ckpts")
        manager._checkpoint_storage = storage
        manager._checkpoint_manager._storage = storage

        cp = SubagentCheckpoint(
            task_id="task-ok",
            agent_type="researcher",
            session_id="s1",
            timestamp=time.time(),
            messages=[{"role": "user", "content": "hello"}],
            variables={"key": "val"},
            progress=0.6,
            last_tool="search",
            resumable=True,
        )
        await storage.save(cp)

        result = await manager.resume_from_checkpoint("task-ok")
        assert result.success is True
        assert result.task_id == "task-ok"
        assert result.agent_type == "researcher"
        assert result.status == SubAgentStatus.COMPLETED
        assert result.checkpoint_data is not None
        assert result.checkpoint_data["progress"] == 0.6
        assert result.checkpoint_data["last_tool"] == "search"
        assert len(result.checkpoint_data["messages"]) == 1

        # Checkpoint is NOT deleted on resume (by design: caller deletes after
        # successful restoration to avoid data loss on failure).
        assert await storage.load("task-ok") is not None


# =========================================================================
# _save_all_checkpoints
# =========================================================================


class TestSaveAllCheckpoints:
    def test_no_running_tasks_no_op(self) -> None:
        manager = _make_manager()
        manager._save_all_checkpoints()

    @pytest.mark.asyncio
    async def test_skips_non_checkpoint_strategy(self) -> None:
        manager = _make_manager()

        async def _never_done() -> SubAgentResult:
            await asyncio.sleep(999)
            return SubAgentResult(
                success=True, task_id="t1", agent_type="a", completed_at=0.0, status=SubAgentStatus.COMPLETED
            )

        task = asyncio.create_task(_never_done())
        manager._children["t1"] = task
        manager._children_configs["t1"] = _make_config(cancellation_strategy=CancellationStrategy.IMMEDIATE)

        manager._save_all_checkpoints()
        task.cancel()


# =========================================================================
# cancel_child with CHECKPOINT strategy
# =========================================================================


class TestCancelChildCheckpointStrategy:
    @pytest.mark.asyncio
    async def test_cancel_with_checkpoint_strategy(self) -> None:
        manager = _make_manager()
        config = _make_config(cancellation_strategy=CancellationStrategy.CHECKPOINT)

        async def _long_run() -> SubAgentResult:
            await asyncio.sleep(999)
            return SubAgentResult(
                success=True,
                task_id="ckpt-task",
                agent_type="researcher",
                completed_at=0.0,
                status=SubAgentStatus.COMPLETED,
            )

        task = asyncio.create_task(_long_run())
        manager._children["ckpt-task"] = task
        manager._children_configs["ckpt-task"] = config
        manager._children_types["ckpt-task"] = "researcher"

        child = _FakeChildAgent()
        manager._children_agents["ckpt-task"] = child  # type: ignore[assignment]

        result = manager.cancel_child("ckpt-task")
        assert result is True
        assert manager._cancel_flags.get("ckpt-task") is True

        task.cancel()
        # Clean up timeout task
        timeout_task = manager._graceful_cancel_timeouts.get("ckpt-task")
        if timeout_task:
            timeout_task.cancel()

    @pytest.mark.asyncio
    async def test_cancel_checkpoint_strategy_no_agent(self) -> None:
        """cancel_child CHECKPOINT works even without agent (logs error for checkpoint creation)."""
        manager = _make_manager()
        config = _make_config(cancellation_strategy=CancellationStrategy.CHECKPOINT)

        async def _long_run() -> SubAgentResult:
            await asyncio.sleep(999)
            return SubAgentResult(
                success=True,
                task_id="no-agent",
                agent_type="researcher",
                completed_at=0.0,
                status=SubAgentStatus.COMPLETED,
            )

        task = asyncio.create_task(_long_run())
        manager._children["no-agent"] = task
        manager._children_configs["no-agent"] = config
        manager._children_types["no-agent"] = "researcher"

        result = manager.cancel_child("no-agent")
        assert result is True
        assert manager._cancel_flags.get("no-agent") is True

        task.cancel()
        timeout_task = manager._graceful_cancel_timeouts.get("no-agent")
        if timeout_task:
            timeout_task.cancel()


# =========================================================================
# cancel_child with GRACEFUL strategy
# =========================================================================


class TestCancelChildGracefulStrategy:
    @pytest.mark.asyncio
    async def test_cancel_graceful_sets_flag(self) -> None:
        manager = _make_manager()
        config = _make_config(cancellation_strategy=CancellationStrategy.GRACEFUL)

        async def _long_run() -> SubAgentResult:
            await asyncio.sleep(999)
            return SubAgentResult(
                success=True, task_id="g-task", agent_type="coder", completed_at=0.0, status=SubAgentStatus.COMPLETED
            )

        task = asyncio.create_task(_long_run())
        manager._children["g-task"] = task
        manager._children_configs["g-task"] = config

        result = manager.cancel_child("g-task")
        assert result is True
        assert manager._cancel_flags.get("g-task") is True
        assert "g-task" in manager._graceful_cancel_timeouts

        task.cancel()
        timeout_task = manager._graceful_cancel_timeouts.get("g-task")
        if timeout_task:
            timeout_task.cancel()


# =========================================================================
# cancel_child with no config (IMMEDIATE fallback)
# =========================================================================


class TestCancelChildNoConfig:
    @pytest.mark.asyncio
    async def test_cancel_no_config_uses_immediate(self) -> None:
        manager = _make_manager()

        async def _long_run() -> SubAgentResult:
            await asyncio.sleep(999)
            return SubAgentResult(
                success=True, task_id="nc-task", agent_type="coder", completed_at=0.0, status=SubAgentStatus.COMPLETED
            )

        task = asyncio.create_task(_long_run())
        manager._children["nc-task"] = task

        result = manager.cancel_child("nc-task")
        assert result is True

        await asyncio.sleep(0.01)
        assert task.cancelled()


# =========================================================================
# Graceful cancel timeout handler
# =========================================================================


class TestGracefulCancelTimeoutHandler:
    @pytest.mark.asyncio
    async def test_timeout_handler_cancels_task(self) -> None:
        manager = _make_manager()

        async def _long_run() -> SubAgentResult:
            await asyncio.sleep(999)
            return SubAgentResult(
                success=True, task_id="timeout-test", agent_type="a", completed_at=0.0, status=SubAgentStatus.COMPLETED
            )

        task = asyncio.create_task(_long_run())
        await manager._graceful_cancel_timeout_handler("timeout-test", task, 0.05)

        await asyncio.sleep(0.01)
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_timeout_handler_no_op_if_already_done(self) -> None:
        manager = _make_manager()

        async def _instant() -> SubAgentResult:
            return SubAgentResult(
                success=True, task_id="done-test", agent_type="a", completed_at=0.0, status=SubAgentStatus.COMPLETED
            )

        task = asyncio.create_task(_instant())
        await task

        await manager._graceful_cancel_timeout_handler("done-test", task, 0.01)
