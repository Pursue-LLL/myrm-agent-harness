"""Tests for sub_agents/manager.py — core methods (validation, cancel, steer, notifications, etc.)."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.manager import _MAX_GLOBAL_SPAWN_DEPTH, SubagentManager
from myrm_agent_harness.agent.sub_agents.notifications import SubagentNotification
from myrm_agent_harness.agent.sub_agents.types import (
    CancellationStrategy,
    ControlScope,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)


def _make_manager() -> SubagentManager:
    parent = MagicMock()
    with patch("myrm_agent_harness.agent.hooks.graceful_shutdown.get_shutdown_manager") as mock_sm:
        mock_sm.return_value = MagicMock()
        return SubagentManager(parent_agent=parent)


def _ok(task_id: str = "t1", agent_type: str = "w") -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id=task_id,
        agent_type=agent_type,
        result="done",
        completed_at=time.time(),
        status=SubAgentStatus.COMPLETED,
    )


def _fail(task_id: str = "t1", agent_type: str = "w", error: str = "boom") -> SubAgentResult:
    return SubAgentResult(
        success=False,
        task_id=task_id,
        agent_type=agent_type,
        error=error,
        completed_at=time.time(),
        status=SubAgentStatus.FAILED,
    )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestManagerProperties:
    def test_children_returns_immutable(self):
        mgr = _make_manager()
        children = mgr.children
        assert len(children) == 0
        with pytest.raises(TypeError):
            children["new"] = MagicMock()

    def test_child_results_returns_immutable(self):
        mgr = _make_manager()
        results = mgr.child_results
        assert len(results) == 0

    def test_current_depth(self):
        mgr = _make_manager()
        assert mgr.current_depth == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_task_id_exists_running(self):
        mgr = _make_manager()
        mgr._children["t1"] = MagicMock()
        assert mgr._task_id_exists("t1")

    def test_task_id_exists_completed(self):
        mgr = _make_manager()
        mgr._children_results["t1"] = _ok("t1")
        assert mgr._task_id_exists("t1")

    def test_task_id_not_exists(self):
        mgr = _make_manager()
        assert not mgr._task_id_exists("nope")

    def test_validate_depth_ok(self):
        mgr = _make_manager()
        cfg = SubagentConfig(system_prompt="s", max_spawn_depth=3)
        assert mgr._validate_depth("t1", cfg) is None

    def test_validate_depth_global_limit(self):
        mgr = _make_manager()
        mgr._current_depth = _MAX_GLOBAL_SPAWN_DEPTH
        cfg = SubagentConfig(system_prompt="s")
        result = mgr._validate_depth("t1", cfg)
        assert result is not None
        assert not result.success
        assert "Max spawn depth" in result.error

    def test_validate_depth_leaf_ignores_config_limit(self):
        mgr = _make_manager()
        mgr._current_depth = 2
        cfg = SubagentConfig(system_prompt="s", max_spawn_depth=1)
        assert mgr._validate_depth("t1", cfg) is None

    def test_validate_depth_orchestrator_enforces_config_limit(self):
        mgr = _make_manager()
        mgr._current_depth = 2
        cfg = SubagentConfig(system_prompt="s", control_scope=ControlScope.ORCHESTRATOR, max_spawn_depth=1)
        result = mgr._validate_depth("t1", cfg)
        assert result is not None
        assert "max_spawn_depth" in result.error

    def test_validate_capacity_enforces_active_child_limit(self):
        mgr = _make_manager()
        running_task = MagicMock()
        running_task.done.return_value = False
        mgr._children["existing"] = running_task
        cfg = SubagentConfig(system_prompt="s", max_children_per_agent=1)

        result = mgr._validate_capacity("t2", "worker", cfg)

        assert result is not None
        assert result.payload is not None
        assert result.payload["reason"] == "budget_exceeded"
        assert result.payload["limit_type"] == "max_children_per_agent"

    def test_validate_capacity_enforces_descendant_budget(self):
        mgr = _make_manager()
        mgr._budget_state.max_descendants = 0
        cfg = SubagentConfig(system_prompt="s")

        result = mgr._validate_capacity("t1", "worker", cfg)

        assert result is not None
        assert result.payload is not None
        assert result.payload["reason"] == "budget_exceeded"
        assert result.payload["limit_type"] == "max_descendants_per_run"


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancelChild:
    def test_cancel_not_found(self):
        mgr = _make_manager()
        assert not mgr.cancel_child("nonexistent")

    def test_cancel_already_done(self):
        mgr = _make_manager()
        task = MagicMock()
        task.done.return_value = True
        mgr._children["t1"] = task
        assert not mgr.cancel_child("t1")

    def test_cancel_no_config_uses_immediate(self):
        mgr = _make_manager()
        task = MagicMock()
        task.done.return_value = False
        mgr._children["t1"] = task
        assert mgr.cancel_child("t1")
        task.cancel.assert_called_once()

    def test_cancel_immediate_strategy(self):
        mgr = _make_manager()
        task = MagicMock()
        task.done.return_value = False
        mgr._children["t1"] = task
        mgr._children_configs["t1"] = SubagentConfig(
            system_prompt="s", cancellation_strategy=CancellationStrategy.IMMEDIATE
        )
        assert mgr.cancel_child("t1")
        task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_graceful_strategy(self):
        mgr = _make_manager()
        task = MagicMock()
        task.done.return_value = False
        mgr._children["t1"] = task
        mgr._children_configs["t1"] = SubagentConfig(
            system_prompt="s", cancellation_strategy=CancellationStrategy.GRACEFUL
        )
        assert mgr.cancel_child("t1")
        assert mgr._cancel_flags.get("t1") is True
        await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_cancel_all(self):
        mgr = _make_manager()
        t1, t2 = MagicMock(), MagicMock()
        t1.done.return_value = False
        t2.done.return_value = True
        mgr._children = {"t1": t1, "t2": t2}
        count = mgr.cancel_all()
        assert count == 1
        t1.cancel.assert_called_once()
        t2.cancel.assert_not_called()


# ---------------------------------------------------------------------------
# Steer
# ---------------------------------------------------------------------------


class TestSteerChild:
    def test_steer_success(self):
        mgr = _make_manager()
        st = MagicMock()
        mgr._children_steering["t1"] = st
        assert mgr.steer_child("t1", "do something else")
        st.steer.assert_called_once_with("do something else")

    def test_steer_no_token_task_not_found(self):
        mgr = _make_manager()
        assert not mgr.steer_child("nonexistent", "msg")

    def test_steer_no_token_task_exists(self):
        mgr = _make_manager()
        mgr._children["t1"] = MagicMock()
        assert not mgr.steer_child("t1", "msg")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestDrainNotifications:
    def test_no_notifications(self):
        mgr = _make_manager()
        assert mgr.drain_notifications() is None

    def test_fresh_notifications(self):
        mgr = _make_manager()
        now = time.time()
        mgr._notification_manager._pending_notifications = deque(
            [
                SubagentNotification(content="task1 done", timestamp=now),
                SubagentNotification(content="task2 done", timestamp=now),
            ]
        )
        result = mgr.drain_notifications()
        assert result is not None
        assert "task1 done" in result
        assert "task2 done" in result
        assert "---" in result
        assert mgr.drain_notifications() is None

    def test_expired_notifications(self):
        mgr = _make_manager()
        old_time = time.time() - 400
        mgr._notification_manager._pending_notifications = deque(
            [
                SubagentNotification(content="old", timestamp=old_time),
            ]
        )
        result = mgr.drain_notifications()
        assert result is None


# ---------------------------------------------------------------------------
# Cleanup & Purge
# ---------------------------------------------------------------------------


class TestCleanupAndPurge:
    def test_cleanup_child_cancelled(self):
        mgr = _make_manager()
        task = MagicMock()
        task.cancelled.return_value = True
        task.done.return_value = True
        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"
        mgr._cleanup_child("t1", task)
        assert "t1" in mgr._children_results
        assert mgr._children_results["t1"].status == SubAgentStatus.CANCELLED
        assert len(mgr._notification_manager._pending_notifications) == 1

    def test_cleanup_child_success(self):
        mgr = _make_manager()
        task = MagicMock()
        task.cancelled.return_value = False
        task.done.return_value = True
        task.result.return_value = _ok("t1")
        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"
        mgr._cleanup_child("t1", task)
        assert mgr._children_results["t1"].success

    def test_cleanup_child_exception(self):
        mgr = _make_manager()
        task = MagicMock()
        task.cancelled.return_value = False
        task.done.return_value = True
        task.result.side_effect = RuntimeError("crash")
        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"
        mgr._cleanup_child("t1", task)
        assert not mgr._children_results["t1"].success
        assert "RuntimeError" in mgr._children_results["t1"].error

    def test_purge_expired_under_limit(self):
        mgr = _make_manager()
        for i in range(10):
            mgr._children_results[f"t{i}"] = _ok(f"t{i}")
        mgr._purge_expired_results()
        assert len(mgr._children_results) == 10

    def test_purge_expired_over_limit(self):
        mgr = _make_manager()
        for i in range(55):
            r = _ok(f"t{i}")
            r.completed_at = float(i)
            mgr._children_results[f"t{i}"] = r
        mgr._purge_expired_results()
        assert len(mgr._children_results) == 50

    def test_cleanup_removes_timeout_task(self):
        mgr = _make_manager()
        timeout_task = MagicMock()
        timeout_task.done.return_value = False
        mgr._graceful_cancel_timeouts["t1"] = timeout_task
        task = MagicMock()
        task.cancelled.return_value = True
        task.done.return_value = True
        mgr._children["t1"] = task
        mgr._children_types["t1"] = "w"
        mgr._cleanup_child("t1", task)
        timeout_task.cancel.assert_called_once()


# ---------------------------------------------------------------------------
# wait_children (manager method, delegates to orchestrator)
# ---------------------------------------------------------------------------


class TestCascadeCancelInFinally:
    """Verify that _run_subagent_core's finally block cascade-cancels descendants."""

    @pytest.mark.asyncio
    async def test_graceful_exit_cascades_cancel_to_grandchildren(self):
        """When a child exits normally (GRACEFUL), its descendants must still be cancelled."""
        mgr = _make_manager()

        child_agent = MagicMock()
        child_agent.cancel_all_children = MagicMock(return_value=1)

        mgr._children_agents["t1"] = child_agent

        mock_result = _ok("t1")
        mgr._executor = MagicMock()
        mgr._executor.run_with_retry = AsyncMock(return_value=mock_result)

        result = await mgr._run_subagent_core(
            task_id="t1",
            agent_type="worker",
            task_description="test task",
            config=SubagentConfig(system_prompt="s"),
            context={},
            tool_registry_getter=lambda: [],
        )

        assert result.success
        child_agent.cancel_all_children.assert_called_once()
        assert "t1" not in mgr._children_agents

    @pytest.mark.asyncio
    async def test_exception_exit_cascades_cancel(self):
        """When executor raises an exception, descendants are still cancelled."""
        mgr = _make_manager()

        child_agent = MagicMock()
        child_agent.cancel_all_children = MagicMock(return_value=2)
        mgr._children_agents["t1"] = child_agent

        mgr._executor = MagicMock()
        mgr._executor.run_with_retry = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await mgr._run_subagent_core(
                task_id="t1",
                agent_type="worker",
                task_description="test task",
                config=SubagentConfig(system_prompt="s"),
                context={},
                tool_registry_getter=lambda: [],
            )

        child_agent.cancel_all_children.assert_called_once()
        assert "t1" not in mgr._children_agents

    @pytest.mark.asyncio
    async def test_no_child_agent_does_not_error(self):
        """When child agent is already removed, finally block should not raise."""
        mgr = _make_manager()

        mock_result = _ok("t1")
        mgr._executor = MagicMock()
        mgr._executor.run_with_retry = AsyncMock(return_value=mock_result)

        result = await mgr._run_subagent_core(
            task_id="t1",
            agent_type="worker",
            task_description="test task",
            config=SubagentConfig(system_prompt="s"),
            context={},
            tool_registry_getter=lambda: [],
        )

        assert result.success

    @pytest.mark.asyncio
    async def test_cascade_cancel_exception_is_suppressed(self):
        """If cancel_all_children raises, it must be suppressed to not break cleanup."""
        mgr = _make_manager()

        child_agent = MagicMock()
        child_agent.cancel_all_children = MagicMock(side_effect=RuntimeError("cascade boom"))
        mgr._children_agents["t1"] = child_agent

        mock_result = _ok("t1")
        mgr._executor = MagicMock()
        mgr._executor.run_with_retry = AsyncMock(return_value=mock_result)

        result = await mgr._run_subagent_core(
            task_id="t1",
            agent_type="worker",
            task_description="test task",
            config=SubagentConfig(system_prompt="s"),
            context={},
            tool_registry_getter=lambda: [],
        )

        assert result.success
        child_agent.cancel_all_children.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancelled_error_cascades_cancel(self):
        """When asyncio CancelledError occurs, finally block still cascade-cancels."""
        mgr = _make_manager()

        child_agent = MagicMock()
        child_agent.cancel_all_children = MagicMock(return_value=1)
        mgr._children_agents["t1"] = child_agent
        mgr._cancel_flags["t1"] = True

        mgr._executor = MagicMock()
        mgr._executor.run_with_retry = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await mgr._run_subagent_core(
                task_id="t1",
                agent_type="worker",
                task_description="test task",
                config=SubagentConfig(system_prompt="s"),
                context={},
                tool_registry_getter=lambda: [],
            )

        child_agent.cancel_all_children.assert_called_once()
        assert "t1" not in mgr._children_agents
        assert "t1" not in mgr._cancel_flags

    @pytest.mark.asyncio
    async def test_cancel_flags_cleared_on_normal_exit(self):
        """Cancel flags are cleaned up even without cascade cancel."""
        mgr = _make_manager()
        mgr._cancel_flags["t1"] = True

        mgr._executor = MagicMock()
        mgr._executor.run_with_retry = AsyncMock(return_value=_ok("t1"))

        await mgr._run_subagent_core(
            task_id="t1",
            agent_type="worker",
            task_description="test task",
            config=SubagentConfig(system_prompt="s"),
            context={},
            tool_registry_getter=lambda: [],
        )

        assert "t1" not in mgr._cancel_flags


class TestCleanupChild:
    """Tests for _cleanup_child callback — result collection, notification, purging."""

    def test_cleanup_completed_task(self):
        mgr = _make_manager()
        result = _ok("t1")

        task = MagicMock()
        task.cancelled.return_value = False
        task.result.return_value = result

        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"
        mgr._children_configs["t1"] = SubagentConfig(system_prompt="s")
        mgr._children_descriptions["t1"] = "test"
        mgr._children_observability["t1"] = {"role": "leaf"}

        with patch("myrm_agent_harness.agent.sub_agents.manager._emit_global_subagent_event"):
            mgr._cleanup_child("t1", task)

        assert "t1" in mgr._children_results
        assert mgr._children_results["t1"].success

    def test_cleanup_cancelled_task(self):
        mgr = _make_manager()

        task = MagicMock()
        task.cancelled.return_value = True

        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"

        with patch("myrm_agent_harness.agent.sub_agents.manager._emit_global_subagent_event"):
            mgr._cleanup_child("t1", task)

        assert mgr._children_results["t1"].status == SubAgentStatus.CANCELLED

    def test_cleanup_exception_task(self):
        mgr = _make_manager()

        task = MagicMock()
        task.cancelled.return_value = False
        task.result.side_effect = RuntimeError("inner error")

        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"

        with patch("myrm_agent_harness.agent.sub_agents.manager._emit_global_subagent_event"):
            mgr._cleanup_child("t1", task)

        assert mgr._children_results["t1"].status == SubAgentStatus.FAILED
        assert "RuntimeError" in (mgr._children_results["t1"].error or "")

    def test_cleanup_cancels_timeout_task(self):
        mgr = _make_manager()
        result = _ok("t1")

        task = MagicMock()
        task.cancelled.return_value = False
        task.result.return_value = result

        timeout_task = MagicMock()
        timeout_task.done.return_value = False
        mgr._graceful_cancel_timeouts["t1"] = timeout_task

        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"

        with patch("myrm_agent_harness.agent.sub_agents.manager._emit_global_subagent_event"):
            mgr._cleanup_child("t1", task)

        timeout_task.cancel.assert_called_once()

    def test_cleanup_sets_completed_at_if_missing(self):
        mgr = _make_manager()
        result = SubAgentResult(
            success=True,
            task_id="t1",
            agent_type="w",
            result="done",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

        task = MagicMock()
        task.cancelled.return_value = False
        task.result.return_value = result

        mgr._children["t1"] = task
        mgr._children_types["t1"] = "worker"

        with patch("myrm_agent_harness.agent.sub_agents.manager._emit_global_subagent_event"):
            mgr._cleanup_child("t1", task)

        assert mgr._children_results["t1"].completed_at > 0


class TestObservabilityMetadata:
    """Tests for _build_observability_metadata and _child_observability_metadata."""

    def test_build_observability_basic(self):
        mgr = _make_manager()
        config = SubagentConfig(system_prompt="s")
        meta = mgr._build_observability_metadata(config)
        assert "role" in meta
        assert "control_scope" in meta
        assert "budget" in meta
        budget = meta["budget"]
        assert isinstance(budget, dict)
        assert "timeout_seconds" in budget

    def test_build_observability_with_cost_and_tokens(self):
        mgr = _make_manager()
        config = SubagentConfig(
            system_prompt="s",
            max_cost_usd=1.0,
            budget_tokens=5000,
        )
        meta = mgr._build_observability_metadata(config)
        budget = meta["budget"]
        assert isinstance(budget, dict)
        assert budget["max_cost_usd"] == 1.0
        assert budget["budget_tokens"] == 5000

    def test_child_observability_from_cache(self):
        mgr = _make_manager()
        mgr._children_observability["t1"] = {"role": "leaf", "budget": {}}
        result = mgr._child_observability_metadata("t1")
        assert result["role"] == "leaf"

    def test_child_observability_fallback_to_config(self):
        mgr = _make_manager()
        config = SubagentConfig(system_prompt="s")
        mgr._children_configs["t1"] = config
        result = mgr._child_observability_metadata("t1")
        assert "role" in result

    def test_child_observability_missing_returns_empty(self):
        mgr = _make_manager()
        result = mgr._child_observability_metadata("nonexistent")
        assert result == {}


class TestRunSubagent:
    """Tests for _run_subagent with timeout handling."""

    @pytest.mark.asyncio
    async def test_hard_timeout(self):
        mgr = _make_manager()

        async def slow_inner(self, *args, **kwargs):
            await asyncio.sleep(100)

        config = SubagentConfig(system_prompt="s", timeout_seconds=0.05)
        with patch.object(SubagentManager, "_run_subagent_inner", slow_inner):
            result = await mgr._run_subagent(
                task_id="t1",
                agent_type="worker",
                task_description="test",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
            )

        assert not result.success
        assert result.status == SubAgentStatus.TIMED_OUT

    @pytest.mark.asyncio
    async def test_normal_completion(self):
        mgr = _make_manager()
        expected = _ok("t1")

        async def fast_inner(self, *args, **kwargs):
            return expected

        config = SubagentConfig(system_prompt="s", timeout_seconds=5.0)
        with patch.object(SubagentManager, "_run_subagent_inner", fast_inner):
            result = await mgr._run_subagent(
                task_id="t1",
                agent_type="worker",
                task_description="test",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
            )

        assert result.success


class TestListChildren:
    """Tests for list_children combining running + completed."""

    def test_list_running_and_completed(self):
        mgr = _make_manager()

        running_task = MagicMock()
        running_task.done.return_value = False
        running_task.cancelled.return_value = False
        mgr._children["t1"] = running_task
        mgr._children_types["t1"] = "worker"
        mgr._children_descriptions["t1"] = "running task"

        mgr._children_results["t2"] = _ok("t2")

        children = mgr.list_children()
        assert len(children) == 2
        task_ids = [c.get("task_id") for c in children]
        assert "t1" in task_ids
        assert "t2" in task_ids

    def test_list_empty(self):
        mgr = _make_manager()
        assert mgr.list_children() == []


class TestGracefulCancelTimeout:
    """Tests for _graceful_cancel_timeout_handler."""

    @pytest.mark.asyncio
    async def test_timeout_forces_cancel(self):
        mgr = _make_manager()

        task = MagicMock()
        task.done.return_value = False

        await mgr._graceful_cancel_timeout_handler("t1", task, 0.01)
        task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_completes_before_timeout(self):
        mgr = _make_manager()

        task = MagicMock()
        task.done.return_value = True

        await mgr._graceful_cancel_timeout_handler("t1", task, 0.01)
        task.cancel.assert_not_called()


class TestCancelChildStrategies:
    """Extended cancel_child tests for CHECKPOINT strategy."""

    @pytest.mark.asyncio
    async def test_cancel_checkpoint_strategy(self):
        mgr = _make_manager()

        task = MagicMock()
        task.done.return_value = False
        mgr._children["t1"] = task
        mgr._children_configs["t1"] = SubagentConfig(
            system_prompt="s",
            cancellation_strategy=CancellationStrategy.CHECKPOINT,
        )
        mgr._children_agents["t1"] = MagicMock()

        checkpoint_mock = MagicMock()
        checkpoint_mock.progress = 0.5
        with patch.object(mgr, "_checkpoint_manager") as ckpt_mgr:
            ckpt_mgr.create_checkpoint.return_value = checkpoint_mock
            result = mgr.cancel_child("t1")

        assert result is True
        assert mgr._cancel_flags.get("t1") is True

    @pytest.mark.asyncio
    async def test_cancel_checkpoint_checkpoint_failure(self):
        mgr = _make_manager()

        task = MagicMock()
        task.done.return_value = False
        mgr._children["t1"] = task
        mgr._children_configs["t1"] = SubagentConfig(
            system_prompt="s",
            cancellation_strategy=CancellationStrategy.CHECKPOINT,
        )
        mgr._children_agents["t1"] = MagicMock()

        with patch.object(mgr, "_checkpoint_manager") as ckpt_mgr:
            ckpt_mgr.create_checkpoint.side_effect = RuntimeError("ckpt fail")
            result = mgr.cancel_child("t1")

        assert result is True
        assert mgr._cancel_flags.get("t1") is True


class TestRunSubagentInner:
    """Tests for _run_subagent_inner — workspace policy dispatching."""

    @pytest.mark.asyncio
    async def test_delegates_to_core(self):
        mgr = _make_manager()
        expected = _ok("t1")

        async def mock_core(self, *args, **kwargs):
            return expected

        with patch.object(SubagentManager, "_run_subagent_core", mock_core):
            result = await mgr._run_subagent_inner(
                task_id="t1",
                agent_type="worker",
                task_description="test",
                config=SubagentConfig(system_prompt="s"),
                context={},
                tool_registry_getter=lambda: [],
            )

        assert result.success


class TestEmitGlobalSubagentEvent:
    """Tests for _emit_global_subagent_event error handling."""

    def test_event_emission_error_suppressed(self):
        from myrm_agent_harness.agent.sub_agents.manager import _emit_global_subagent_event
        from myrm_agent_harness.runtime.events.system_events import SubagentLifecycleData

        mock_bus = MagicMock()
        mock_bus.publish.side_effect = RuntimeError("bus error")
        with patch("myrm_agent_harness.runtime.events.get_event_bus", return_value=mock_bus):
            _emit_global_subagent_event(
                "spawn",
                "t1",
                "sess1",
                SubagentLifecycleData(agent_type="worker", description="test"),
            )


class TestCapacitySnapshot:
    """Tests for get_capacity_snapshot."""

    def test_snapshot_values(self):
        mgr = _make_manager()

        task = MagicMock()
        task.done.return_value = False
        mgr._children["t1"] = task

        snapshot = mgr.get_capacity_snapshot()
        assert snapshot.active_children == 1
        assert snapshot.remaining_slots == mgr._max_children_per_agent - 1


class TestInheritRuntimeLimits:
    """Tests for inherit_runtime_limits."""

    def test_inherit_sets_values(self):
        mgr = _make_manager()
        from myrm_agent_harness.agent.sub_agents.budget import DelegationBudgetState

        budget = DelegationBudgetState(max_descendants=10)
        mgr.inherit_runtime_limits(
            current_depth=2,
            budget_state=budget,
            max_children_per_agent=5,
        )
        assert mgr._current_depth == 2
        assert mgr._budget_state is budget
        assert mgr._max_children_per_agent == 5

    def test_budget_state_property(self):
        mgr = _make_manager()
        assert mgr.budget_state is mgr._budget_state


class TestManagerWaitChildren:
    @pytest.mark.asyncio
    async def test_delegates_to_orchestrator(self):
        mgr = _make_manager()
        mgr._children_results["t1"] = _ok("t1")
        result = await mgr.wait_children(["t1"])
        assert result["success"]
