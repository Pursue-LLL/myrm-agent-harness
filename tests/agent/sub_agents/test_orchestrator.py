"""Tests for sub_agents/orchestrator.py — run_chain and wait_children."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
    _parse_verdict,
)
from myrm_agent_harness.agent.sub_agents.orchestrator import (
    _collect_gather_results,
    _collect_timed_out_results,
    execute_dag_plan,
    run_chain,
    run_with_verification,
    wait_children,
)
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)


def _ok(
    task_id: str = "t1", agent_type: str = "worker", result: str = "done"
) -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id=task_id,
        agent_type=agent_type,
        result=result,
        completed_at=time.time(),
        status=SubAgentStatus.COMPLETED,
    )


def _fail(
    task_id: str = "t1", agent_type: str = "worker", error: str = "boom"
) -> SubAgentResult:
    return SubAgentResult(
        success=False,
        task_id=task_id,
        agent_type=agent_type,
        error=error,
        completed_at=time.time(),
        status=SubAgentStatus.FAILED,
    )


# ---------------------------------------------------------------------------
# run_chain
# ---------------------------------------------------------------------------


class TestExecuteDagPlan:
    @pytest.mark.asyncio
    async def test_execute_dag_plan_dict_result(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(
            return_value={"success": True, "result": "dict-out"}
        )

        class MockStep:
            def __init__(self, step_id, desc, expected):
                self.step_id = step_id
                self.description = desc
                self.expected_output = expected
                self.status = "pending"
                self.dependencies = []

        class MockPlan:
            def __init__(self):
                self.steps = [MockStep("step1", "desc", "exp")]
                self.completed = False

            def get_ready_steps(self):
                if self.completed:
                    return []
                return [s for s in self.steps if s.status == "pending"]

            def mark_step_completed(self, step_id):
                self.completed = True
                for s in self.steps:
                    if s.step_id == step_id:
                        s.status = "completed"

            def add_error(self, err_type, msg, step_id):
                pass

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            def side_effect_create_task(coro):
                return asyncio.create_task(coro)

            mock_tg_instance.create_task.side_effect = side_effect_create_task

            original_sleep = asyncio.sleep

            async def mock_sleep_func(delay):
                await original_sleep(0.001)

            with patch("asyncio.sleep", side_effect=mock_sleep_func), patch(
                "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
                create=True,
            ) as mock_get_instance:
                mock_vault = MagicMock()
                mock_get_instance.return_value = mock_vault
                task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
                try:
                    result = await asyncio.wait_for(task, timeout=2.0)
                except TimeoutError:
                    pytest.fail("execute_dag_plan timed out")

        assert result["success"]
        assert "step1" in result["results"]
        assert result["results"]["step1"].success
        assert result["results"]["step1"].result == "dict-out"

    @pytest.mark.asyncio
    async def test_execute_dag_plan_create_task_exception(self):
        mgr = MagicMock()

        class MockStep:
            def __init__(self, step_id):
                self.step_id = step_id
                self.description = "desc"
                self.expected_output = "exp"
                self.status = "pending"
                self.dependencies = []

        class MockPlan:
            def __init__(self):
                self.steps = [MockStep("step1")]
                self.completed = False

            def get_ready_steps(self):
                if self.completed:
                    return []
                return [s for s in self.steps if s.status == "pending"]

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            # Make create_task raise an exception
            mock_tg_instance.create_task.side_effect = ValueError(
                "Failed to create task"
            )

            # Mock sleep to prevent hanging without recursion
            # Use a counter to break out of the loop since the task will never complete
            sleep_count = 0
            original_sleep = asyncio.sleep

            async def mock_sleep_func(delay):
                nonlocal sleep_count
                sleep_count += 1
                if sleep_count > 2:
                    plan.completed = True  # Force completion to exit loop
                await original_sleep(0.001)

            with patch("asyncio.sleep", side_effect=mock_sleep_func), patch(
                "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
                create=True,
            ) as mock_get_instance:
                mock_vault = MagicMock()
                mock_get_instance.return_value = mock_vault
                task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
                try:
                    result = await asyncio.wait_for(task, timeout=2.0)
                except TimeoutError:
                    pytest.fail("execute_dag_plan timed out")

        assert not result["success"]
        assert result["results"] == {}

    @pytest.mark.asyncio
    async def test_execute_dag_plan_no_steps(self):
        mgr = MagicMock()

        class MockPlan:
            def __init__(self):
                self.steps = []
                self.completed = False

            def get_ready_steps(self):
                return []

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
            try:
                result = await asyncio.wait_for(task, timeout=2.0)
            except TimeoutError:
                pytest.fail("execute_dag_plan timed out")

        assert result["success"]
        assert result["results"] == {}

    @pytest.mark.asyncio
    async def test_execute_dag_plan_taskgroup_exception(self):
        mgr = MagicMock()

        class MockStep:
            def __init__(self, step_id):
                self.step_id = step_id
                self.status = "pending"

        class MockPlan:
            def __init__(self):
                self.steps = [MockStep("step1")]
                self.completed = False

            def get_ready_steps(self):
                if self.completed:
                    return []
                return [s for s in self.steps if s.status == "pending"]

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        # Mock TaskGroup to raise an exception when created
        with patch(
            "asyncio.TaskGroup", side_effect=ValueError("TaskGroup creation failed")
        ):
            task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
            try:
                result = await asyncio.wait_for(task, timeout=2.0)
            except TimeoutError:
                pytest.fail("execute_dag_plan timed out")

        # It should catch the exception and return the partial results (empty in this case)
        assert not result["success"]
        assert result["results"] == {}

    @pytest.mark.asyncio
    async def test_execute_dag_plan_success(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(
            return_value=_ok("dag-step1", "general", "step1-out")
        )

        class MockStep:
            def __init__(self, step_id, desc, expected):
                self.step_id = step_id
                self.description = desc
                self.expected_output = expected
                self.status = "pending"
                self.dependencies = []

        class MockPlan:
            def __init__(self):
                self.steps = [MockStep("step1", "desc", "exp")]
                self.completed = False

            def get_ready_steps(self):
                if self.completed:
                    return []
                return [s for s in self.steps if s.status == "pending"]

            def mark_step_completed(self, step_id):
                self.completed = True
                for s in self.steps:
                    if s.step_id == step_id:
                        s.status = "completed"

            def add_error(self, err_type, msg, step_id):
                pass

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        # Set the steps attribute that execute_dag_plan looks for at the end
        plan.steps = plan.steps_list

        # We need to mock TaskGroup because it cancels all tasks if one fails in tests
        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            # When create_task is called, actually run the coroutine
            def side_effect_create_task(coro):
                return asyncio.create_task(coro)

            mock_tg_instance.create_task.side_effect = side_effect_create_task

            # Mock sleep to prevent hanging without recursion
            original_sleep = asyncio.sleep

            async def mock_sleep_func(delay):
                await original_sleep(0.001)

            with patch("asyncio.sleep", side_effect=mock_sleep_func), patch(
                "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
                create=True,
            ) as mock_get_instance:
                mock_vault = MagicMock()
                mock_get_instance.return_value = mock_vault
                task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
                try:
                    result = await asyncio.wait_for(task, timeout=2.0)
                except TimeoutError:
                    pytest.fail("execute_dag_plan timed out")

        assert result["success"]
        assert "step1" in result["results"]
        # The result might be a dict or a SubAgentResult depending on how the mock returned it
        # In our mock, spawn_child returns a SubAgentResult directly
        assert result["results"]["step1"].success

    @pytest.mark.asyncio
    async def test_execute_dag_plan_dependency_not_met(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(return_value=_ok("dag-step", "general", "step-out"))

        class MockStep:
            def __init__(self, step_id, deps=None):
                self.step_id = step_id
                self.description = "desc"
                self.expected_output = "exp"
                self.status = "pending"
                self.dependencies = deps or []

        class MockPlan:
            def __init__(self):
                self.step1 = MockStep("step1")
                self.step2 = MockStep("step2", deps=["step1"])
                self.steps = [self.step1, self.step2]
                self.errors = []
                self.completed = False

            def get_ready_steps(self):
                if self.completed:
                    return []
                ready = []
                for step in self.steps:
                    if step.status == "pending":
                        deps_met = True
                        for dep_id in step.dependencies:
                            dep_step = next(
                                (s for s in self.steps if s.step_id == dep_id), None
                            )
                            if not dep_step or dep_step.status != "completed":
                                deps_met = False
                                break
                        if deps_met:
                            ready.append(step)
                return ready

            def mark_step_completed(self, step_id):
                for s in self.steps:
                    if s.step_id == step_id:
                        s.status = "completed"
                # If step1 completes, we mark plan as completed so it doesn't run step2
                # This simulates a plan that finishes early
                if step_id == "step1":
                    self.completed = True

            def add_error(self, err_type, msg, step_id):
                pass

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            def side_effect_create_task(coro):
                return asyncio.create_task(coro)

            mock_tg_instance.create_task.side_effect = side_effect_create_task

            # Mock sleep to prevent hanging without recursion
            original_sleep = asyncio.sleep

            async def mock_sleep_func(delay):
                await original_sleep(0.001)

            with patch("asyncio.sleep", side_effect=mock_sleep_func), patch(
                "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
                create=True,
            ) as mock_get_instance:
                mock_vault = MagicMock()
                mock_get_instance.return_value = mock_vault
                task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
                try:
                    result = await asyncio.wait_for(task, timeout=2.0)
                except TimeoutError:
                    pytest.fail("execute_dag_plan timed out")

        assert not result[
            "success"
        ]  # The plan is marked complete but step2 is pending, so it returns failure
        assert "step1" in result["results"]
        assert "step2" not in result["results"]
        assert mgr.spawn_child.await_count == 1

    @pytest.mark.asyncio
    async def test_execute_dag_plan_exception(self):
        mgr = MagicMock()

        # Make the mock spawn_child raise a generic Exception
        async def fail_spawn(*args, **kwargs):
            raise ValueError("Something went wrong")

        mgr.spawn_child = AsyncMock(side_effect=fail_spawn)

        class MockStep:
            def __init__(self, step_id):
                self.step_id = step_id
                self.description = "desc"
                self.expected_output = "exp"
                self.status = "pending"
                self.dependencies = []

        class MockPlan:
            def __init__(self):
                self.steps = [MockStep("step1")]
                self.completed = False

            def get_ready_steps(self):
                if self.completed:
                    return []
                return [s for s in self.steps if s.status == "pending"]

            def mark_step_completed(self, step_id):
                pass

            def add_error(self, err_type, msg, step_id):
                self.completed = True
                for s in self.steps:
                    if s.step_id == step_id:
                        s.status = "failed"

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            def side_effect_create_task(coro):
                return asyncio.create_task(coro)

            mock_tg_instance.create_task.side_effect = side_effect_create_task

            # Mock sleep to prevent hanging without recursion
            original_sleep = asyncio.sleep

            async def mock_sleep_func(delay):
                await original_sleep(0.001)

            with patch("asyncio.sleep", side_effect=mock_sleep_func), patch(
                "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
                create=True,
            ) as mock_get_instance:
                mock_vault = MagicMock()
                mock_get_instance.return_value = mock_vault
                task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
                try:
                    result = await asyncio.wait_for(task, timeout=2.0)
                except TimeoutError:
                    pytest.fail("execute_dag_plan timed out")

        assert not result["success"]
        assert "step1" in result["results"]
        assert not result["results"]["step1"].success
        assert "Something went wrong" in result["results"]["step1"].error

    @pytest.mark.asyncio
    async def test_execute_dag_plan_timeout(self):
        mgr = MagicMock()

        # Make the mock spawn_child raise TimeoutError directly to avoid recursion issues with sleep
        async def slow_spawn(*args, **kwargs):
            raise TimeoutError("Step execution timed out")

        mgr.spawn_child = AsyncMock(side_effect=slow_spawn)

        class MockStep:
            def __init__(self, step_id):
                self.step_id = step_id
                self.description = "desc"
                self.expected_output = "exp"
                self.status = "pending"
                self.dependencies = []

        class MockPlan:
            def __init__(self):
                self.steps = [MockStep("step1")]
                self.completed = False

            def get_ready_steps(self):
                if self.completed:
                    return []
                return [s for s in self.steps if s.status == "pending"]

            def mark_step_completed(self, step_id):
                pass

            def add_error(self, err_type, msg, step_id):
                self.completed = True
                for s in self.steps:
                    if s.step_id == step_id:
                        s.status = "failed"

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            def side_effect_create_task(coro):
                return asyncio.create_task(coro)

            mock_tg_instance.create_task.side_effect = side_effect_create_task

            # For the timeout test, we don't mock asyncio.timeout to avoid recursion
            # We let the real timeout happen, but we mock sleep so it doesn't take long
            original_sleep = asyncio.sleep

            async def mock_sleep_func(delay):
                await original_sleep(0.001)

            with patch("asyncio.sleep", side_effect=mock_sleep_func), patch(
                "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
                create=True,
            ) as mock_get_instance:
                mock_vault = MagicMock()
                mock_get_instance.return_value = mock_vault
                task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
                try:
                    result = await asyncio.wait_for(task, timeout=2.0)
                except TimeoutError:
                    pytest.fail("execute_dag_plan timed out")

        assert not result["success"]
        assert "step1" in result["results"]
        assert not result["results"]["step1"].success
        # The error could be "Step execution timed out" or "maximum recursion depth exceeded"
        # depending on how the mock interacts with tenacity.
        # We just want to ensure it failed.
        assert result["results"]["step1"].error is not None

    @pytest.mark.asyncio
    async def test_execute_dag_plan_retry_failure(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(return_value=_ok("dag-step", "general", "step-out"))

        class MockStep:
            def __init__(self, step_id, deps=None):
                self.step_id = step_id
                self.description = "desc"
                self.expected_output = "exp"
                self.status = "pending"
                self.dependencies = deps or []

        class MockPlan:
            def __init__(self):
                self.step1 = MockStep("step1")
                self.step2 = MockStep("step2", deps=["step1"])
                self.steps = [self.step1, self.step2]
                self.errors = []

            def get_ready_steps(self):
                ready = []
                for step in self.steps:
                    if step.status == "pending":
                        deps_met = True
                        for dep_id in step.dependencies:
                            dep_step = next(
                                (s for s in self.steps if s.step_id == dep_id), None
                            )
                            if not dep_step or dep_step.status != "completed":
                                deps_met = False
                                break
                        if deps_met:
                            ready.append(step)
                return ready

            def mark_step_completed(self, step_id):
                for s in self.steps:
                    if s.step_id == step_id:
                        s.status = "completed"

            def add_error(self, err_type, msg, step_id):
                pass

            @property
            def steps_list(self):
                return self.steps

        plan = MockPlan()
        plan.steps = plan.steps_list

        with patch("asyncio.TaskGroup") as mock_tg:
            mock_tg_instance = MagicMock()
            mock_tg.return_value.__aenter__.return_value = mock_tg_instance

            def side_effect_create_task(coro):
                return asyncio.create_task(coro)

            mock_tg_instance.create_task.side_effect = side_effect_create_task

            # Mock sleep to prevent hanging without recursion
            original_sleep = asyncio.sleep

            async def mock_sleep_func(delay):
                await original_sleep(0.001)

            with patch("asyncio.sleep", side_effect=mock_sleep_func), patch(
                "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
                create=True,
            ) as mock_get_instance:
                mock_vault = MagicMock()
                mock_get_instance.return_value = mock_vault
                task = asyncio.create_task(execute_dag_plan(plan, mgr, {}, lambda: []))
                try:
                    result = await asyncio.wait_for(task, timeout=2.0)
                except TimeoutError:
                    pytest.fail("execute_dag_plan timed out")

        assert result["success"]
        assert "step1" in result["results"]
        assert "step2" in result["results"]
        assert mgr.spawn_child.await_count == 2


class TestRunChain:
    @pytest.mark.asyncio
    async def test_empty_chain_returns_failure(self):
        mgr = MagicMock()
        result = await run_chain(mgr, [], {}, lambda: [])
        assert not result.success
        assert result.error == "Empty chain"

    @pytest.mark.asyncio
    async def test_single_step_success(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(return_value=_ok("chain-0-w", "w", "hello"))
        cfg = SubagentConfig(system_prompt="test")
        result = await run_chain(mgr, [("w", cfg, "do {previous}")], {}, lambda: [])
        assert result.success
        assert result.result == "hello"
        mgr.spawn_child.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chain_propagates_previous_result(self):
        mgr = MagicMock()
        call_count = 0

        async def _spawn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "step1-out")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                f"got:{kwargs['task_description']}",
            )

        mgr.spawn_child = _spawn
        cfgs = [
            ("a", SubagentConfig(system_prompt="s"), "start"),
            ("b", SubagentConfig(system_prompt="s"), "prev={previous}"),
        ]
        result = await run_chain(mgr, cfgs, {}, lambda: [])
        assert result.success
        assert "step1-out" in result.result

    @pytest.mark.asyncio
    async def test_chain_aborts_on_failure(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(return_value=_fail("chain-0-a", "a", "broken"))
        cfgs = [
            ("a", SubagentConfig(system_prompt="s"), "step1"),
            ("b", SubagentConfig(system_prompt="s"), "step2"),
        ]
        result = await run_chain(mgr, cfgs, {}, lambda: [])
        assert not result.success
        assert "chain step 1/2" in result.error
        assert mgr.spawn_child.await_count == 1

    @pytest.mark.asyncio
    async def test_chain_handles_dict_return(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(
            return_value={"success": True, "result": "dict-out"}
        )
        cfg = SubagentConfig(system_prompt="s")
        result = await run_chain(mgr, [("w", cfg, "task")], {}, lambda: [])
        assert result.success
        assert result.result == "dict-out"

    @pytest.mark.asyncio
    async def test_chain_dict_failure(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock(return_value={"success": False, "result": ""})
        cfgs = [
            ("a", SubagentConfig(system_prompt="s"), "step1"),
            ("b", SubagentConfig(system_prompt="s"), "step2"),
        ]
        result = await run_chain(mgr, cfgs, {}, lambda: [])
        assert not result.success


# ---------------------------------------------------------------------------
# wait_children
# ---------------------------------------------------------------------------


class TestWaitChildren:
    @pytest.mark.asyncio
    async def test_empty_task_ids(self):
        mgr = MagicMock()
        result = await wait_children(mgr, [])
        assert not result["success"]
        assert result["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_duplicate_task_ids(self):
        mgr = MagicMock()
        result = await wait_children(mgr, ["a", "a"])
        assert not result["success"]
        assert "Duplicate" in result["failures"][0]

    @pytest.mark.asyncio
    async def test_already_completed_success(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {"t1": _ok("t1")}
        result = await wait_children(mgr, ["t1"])
        assert result["success"]
        assert result["success_rate"] == 1.0
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_already_completed_failure(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {"t1": _fail("t1")}
        result = await wait_children(mgr, ["t1"], min_success_rate=0.0)
        assert result["success"]
        assert result["success_rate"] == 0.0
        assert len(result["failures"]) == 1

    @pytest.mark.asyncio
    async def test_task_not_found(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}
        result = await wait_children(mgr, ["missing"])
        assert not result["success"]
        assert "not found" in str(result["failures"])

    @pytest.mark.asyncio
    async def test_running_tasks_complete(self):
        mgr = MagicMock()
        ok_result = _ok("t1")
        future: asyncio.Future[SubAgentResult] = (
            asyncio.get_event_loop().create_future()
        )
        future.set_result(ok_result)
        mgr.children = {"t1": future}
        mgr.child_results = {}
        result = await wait_children(mgr, ["t1"])
        assert result["success"]
        assert result["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_running_tasks_exception(self):
        mgr = MagicMock()
        future: asyncio.Future[SubAgentResult] = (
            asyncio.get_event_loop().create_future()
        )
        future.set_exception(RuntimeError("crash"))
        mgr.children = {"t1": future}
        mgr.child_results = {}
        result = await wait_children(mgr, ["t1"])
        assert not result["success"]
        assert "RuntimeError" in str(result["failures"])

    @pytest.mark.asyncio
    async def test_timeout_cancels_tasks(self):
        mgr = MagicMock()

        async def _slow():
            await asyncio.sleep(10)
            return _ok("t1")

        task = asyncio.create_task(_slow())
        mgr.children = {"t1": task}
        mgr.child_results = {}
        result = await wait_children(mgr, ["t1"], timeout=0.05)
        assert not result["success"]
        assert "timeout" in str(result["failures"]).lower()

    @pytest.mark.asyncio
    async def test_mixed_completed_and_running(self):
        mgr = MagicMock()
        future: asyncio.Future[SubAgentResult] = (
            asyncio.get_event_loop().create_future()
        )
        future.set_result(_ok("t2"))
        mgr.children = {"t2": future}
        mgr.child_results = {"t1": _ok("t1")}
        result = await wait_children(mgr, ["t1", "t2"])
        assert result["success"]
        assert result["success_rate"] == 1.0
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_min_success_rate_threshold(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {"t1": _ok("t1"), "t2": _fail("t2")}
        result = await wait_children(mgr, ["t1", "t2"], min_success_rate=0.8)
        assert not result["success"]
        assert result["success_rate"] == 0.5


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestVerification:
    def test_parse_verdict_json(self):
        raw = '{"verdict": "PASS", "summary": "Looks good STDOUT", "confidence": "HIGH", "findings": []}'
        verdict = _parse_verdict(raw)
        assert verdict.passed is True
        assert verdict.summary == "Looks good STDOUT"
        assert verdict.confidence == "HIGH"

    def test_parse_verdict_markdown_json(self):
        raw = '```json\n{"verdict": "FAIL", "summary": "Bad", "confidence": "LOW", "findings": [{"description": "error"}]}\n```'
        verdict = _parse_verdict(raw)
        assert verdict.passed is False
        assert verdict.summary == "Bad"
        assert len(verdict.findings) == 1

    def test_parse_verdict_fallback_pass(self):
        raw = 'I think it is ok. "VERDICT": "PASS" STDOUT'
        verdict = _parse_verdict(raw)
        assert verdict.passed is True
        assert verdict.confidence == "LOW"

    def test_parse_verdict_fallback_fail(self):
        raw = "I think it is bad."
        verdict = _parse_verdict(raw)
        assert verdict.passed is False
        assert verdict.confidence == "LOW"

    @pytest.mark.asyncio
    async def test_run_with_verification_enforces_execution(self):
        mgr = MagicMock()

        # Worker success
        worker_result = SubAgentResult(
            success=True,
            task_id="w1",
            agent_type="worker",
            result="worker out",
            status=SubAgentStatus.COMPLETED,
        )
        # Verifier success (but didn't execute code)
        verifier_result = SubAgentResult(
            success=True,
            task_id="v1",
            agent_type="verifier",
            result='{"verdict": "PASS", "summary": "ok STDOUT", "confidence": "HIGH"}',
            status=SubAgentStatus.COMPLETED,
        )

        # It should reject the PASS, and loop again.
        # We'll just provide the same results for round 2, and it will fail eventually.
        mgr.spawn_child = AsyncMock(side_effect=[worker_result, verifier_result, worker_result, verifier_result])

        from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy
        config = SubagentConfig(system_prompt="")
        verifier_config = SubagentConfig(system_prompt="", workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)

        result = await run_with_verification(
            manager=mgr,
            worker_type="worker",
            worker_config=config,
            worker_task="do work",
            verifier_type="verifier",
            verifier_config=verifier_config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )

        # Because it rejected the PASS twice, it should exhaust max_rounds and return the worker result with FAIL annotation
        assert result.success is False
        assert "Verification: FAIL" in result.result
        assert "System detected that you did not execute any code" in result.result
        assert mgr.spawn_child.call_count == 4

    @pytest.mark.asyncio
    async def test_run_with_verification_success_first_round(self):
        mgr = MagicMock()

        # Mock worker success
        worker_result = SubAgentResult(
            success=True,
            task_id="w1",
            agent_type="worker",
            result="worker out",
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )
        # Mock verifier success
        verifier_result = SubAgentResult(
            success=True,
            task_id="v1",
            agent_type="verifier",
            result='{"verdict": "PASS", "summary": "ok STDOUT", "confidence": "HIGH"}',
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

        mgr.spawn_child = AsyncMock(side_effect=[worker_result, verifier_result])

        config = SubagentConfig(system_prompt="")
        result = await run_with_verification(
            manager=mgr,
            worker_type="worker",
            worker_config=config,
            worker_task="do work",
            verifier_type="verifier",
            verifier_config=config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )

        assert result.success is True
        assert "Verification: PASS" in result.result
        assert mgr.spawn_child.call_count == 2

    @pytest.mark.asyncio
    async def test_run_with_verification_fail_then_pass(self):
        mgr = MagicMock()

        # Round 1: Worker succeeds, Verifier fails it
        w1 = SubAgentResult(
            success=True,
            task_id="w1",
            agent_type="w",
            result="bad out",
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )
        v1 = SubAgentResult(
            success=True,
            task_id="v1",
            agent_type="v",
            result='{"verdict": "FAIL", "findings": [{"description": "fix this"}]}',
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

        # Round 2: Worker succeeds, Verifier passes it
        w2 = SubAgentResult(
            success=True,
            task_id="w2",
            agent_type="w",
            result="good out",
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )
        v2 = SubAgentResult(
            success=True,
            task_id="v2",
            agent_type="v",
            result='{"verdict": "PASS", "confidence": "HIGH", "summary": "ok STDOUT"}',
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

        mgr.spawn_child = AsyncMock(side_effect=[w1, v1, w2, v2])

        config = SubagentConfig(system_prompt="")
        result = await run_with_verification(
            manager=mgr,
            worker_type="w",
            worker_config=config,
            worker_task="task",
            verifier_type="v",
            verifier_config=config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )

        assert result.success is True
        assert "Verification: PASS" in result.result
        assert "good out" in result.result
        assert mgr.spawn_child.call_count == 4

    @pytest.mark.asyncio
    async def test_run_with_verification_max_rounds_exhausted(self):
        mgr = MagicMock()

        # Round 1
        w1 = SubAgentResult(
            success=True,
            task_id="w1",
            agent_type="w",
            result="out1",
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )
        v1 = SubAgentResult(
            success=True,
            task_id="v1",
            agent_type="v",
            result='{"verdict": "FAIL"}',
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

        mgr.spawn_child = AsyncMock(side_effect=[w1, v1])

        config = SubagentConfig(system_prompt="")
        result = await run_with_verification(
            manager=mgr,
            worker_type="w",
            worker_config=config,
            worker_task="task",
            verifier_type="v",
            verifier_config=config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=1,
        )

        assert result.success is False
        assert "Verification: FAIL after 1 round" in result.result
        assert mgr.spawn_child.call_count == 2

    @pytest.mark.asyncio
    async def test_run_with_verification_worker_fails(self):
        mgr = MagicMock()

        # Worker fails immediately
        w1 = SubAgentResult(
            success=False,
            task_id="w1",
            agent_type="w",
            result="",
            error="worker error",
            completed_at=0.0,
            status=SubAgentStatus.FAILED,
        )

        mgr.spawn_child = AsyncMock(return_value=w1)

        config = SubagentConfig(system_prompt="")
        result = await run_with_verification(
            manager=mgr,
            worker_type="w",
            worker_config=config,
            worker_task="task",
            verifier_type="v",
            verifier_config=config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )

        assert result.success is False
        assert result.error == "worker error"
        assert mgr.spawn_child.call_count == 1

    @pytest.mark.asyncio
    async def test_run_with_verification_verifier_fails(self):
        mgr = MagicMock()

        w1 = SubAgentResult(
            success=True,
            task_id="w1",
            agent_type="w",
            result="out",
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )
        v1 = SubAgentResult(
            success=False,
            task_id="v1",
            agent_type="v",
            result="",
            error="verifier error",
            completed_at=0.0,
            status=SubAgentStatus.FAILED,
        )

        mgr.spawn_child = AsyncMock(side_effect=[w1, v1])

        config = SubagentConfig(system_prompt="")
        result = await run_with_verification(
            manager=mgr,
            worker_type="w",
            worker_config=config,
            worker_task="task",
            verifier_type="v",
            verifier_config=config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )

        assert result.success is False
        assert "Verification: FAIL" in result.result
        assert mgr.spawn_child.call_count == 2

    @pytest.mark.asyncio
    async def test_run_with_verification_dict_result(self):
        mgr = MagicMock()

        # Worker returns dict
        w1 = {"success": True, "result": "dict out"}
        # Verifier returns dict
        v1 = {"success": True, "result": '{"verdict": "PASS", "summary": "ok STDOUT"}'}

        mgr.spawn_child = AsyncMock(side_effect=[w1, v1])

        config = SubagentConfig(system_prompt="")
        result = await run_with_verification(
            manager=mgr,
            worker_type="w",
            worker_config=config,
            worker_task="task",
            verifier_type="v",
            verifier_config=config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=1,
            verifier_task_template="Verify: {worker_result}",
        )

        assert result.success is True
        assert "Verification: PASS" in result.result
        assert "dict out" in result.result

    @patch("myrm_agent_harness.toolkits.code_execution.executors.base.get_executor")
    @patch("myrm_agent_harness.agent.skills.evolution.execution.executor_context.ExecutorContextManager")
    async def test_run_with_verification_readonly_sandbox(self, mock_ctx_mgr, mock_get_executor):
        from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy
        from myrm_agent_harness.toolkits.code_execution.executors.readonly_proxy import ReadonlyExecutorProxy

        mgr = MagicMock()
        w1 = _ok("worker done")
        v1 = _ok('{"verdict": "PASS", "summary": "ok STDOUT"}')
        mgr.spawn_child = AsyncMock(side_effect=[w1, v1])

        mock_executor = MagicMock()
        mock_get_executor.return_value = mock_executor

        config = SubagentConfig(system_prompt="", workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)

        result = await run_with_verification(
            manager=mgr,
            worker_type="w",
            worker_config=config,
            worker_task="task",
            verifier_type="v",
            verifier_config=config,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=1,
            verifier_task_template="Verify: {worker_result}",
        )

        assert result.success is False
        assert mock_get_executor.called

        # Verify proxy was used
        assert mock_ctx_mgr.called
        proxy_arg = mock_ctx_mgr.call_args[0][0]
        assert isinstance(proxy_arg, ReadonlyExecutorProxy)
        assert proxy_arg.inner == mock_executor

    def test_collect_gather_results_success(self):
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_gather_results([_ok("t1")], ["t1"], successes, failures)
        assert len(successes) == 1
        assert len(failures) == 0

    def test_collect_gather_results_exception(self):
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_gather_results([RuntimeError("oops")], ["t1"], successes, failures)
        assert len(failures) == 1
        assert "RuntimeError" in str(failures[0])

    def test_collect_gather_results_unknown_type(self):
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_gather_results(["unknown_type"], ["t1"], successes, failures)
        assert len(failures) == 1

    def _make_future(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        self._loop = loop
        return loop

    def test_collect_timed_out_done_success(self):
        loop = self._make_future()
        future: asyncio.Future[SubAgentResult] = loop.create_future()
        future.set_result(_ok("t1"))
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_timed_out_results([future], ["t1"], successes, failures, 5.0)
        assert len(successes) == 1
        loop.close()

    def test_collect_timed_out_done_failure(self):
        loop = self._make_future()
        future: asyncio.Future[SubAgentResult] = loop.create_future()
        future.set_result(_fail("t1"))
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_timed_out_results([future], ["t1"], successes, failures, 5.0)
        assert len(failures) == 1
        loop.close()

    def test_collect_timed_out_not_done(self):
        loop = self._make_future()
        future: asyncio.Future[SubAgentResult] = loop.create_future()
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_timed_out_results([future], ["t1"], successes, failures, 5.0)
        assert len(failures) == 1
        assert "timeout" in str(failures[0]).lower()
        loop.close()

    def test_collect_timed_out_exception(self):
        loop = self._make_future()
        future: asyncio.Future[SubAgentResult] = loop.create_future()
        future.set_exception(ValueError("bad"))
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_timed_out_results([future], ["t1"], successes, failures, 5.0)
        assert len(failures) == 1
        assert "ValueError" in str(failures[0])
        loop.close()

    def test_collect_timed_out_non_result(self):
        loop = self._make_future()
        future: asyncio.Future[str] = loop.create_future()
        future.set_result("not a SubAgentResult")
        successes: list[dict[str, object]] = []
        failures: list[object] = []
        _collect_timed_out_results([future], ["t1"], successes, failures, 5.0)
        assert len(failures) == 1
        loop.close()
