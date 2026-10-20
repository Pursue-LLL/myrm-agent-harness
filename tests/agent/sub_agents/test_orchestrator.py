"""Tests for sub_agents/orchestrator.py — run_chain, wait_children, and run_alternatives."""

from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
    _parse_verdict,
)
from myrm_agent_harness.agent.sub_agents.orchestrator import (
    run_alternatives,
    run_chain,
    run_with_verification,
    wait_children,
)
from myrm_agent_harness.agent.sub_agents.result_output import answer_text
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.utils.token_economics.tracker import TokenUsage


def _ok(task_id: str = "t1", agent_type: str = "worker", result: str = "done") -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id=task_id,
        agent_type=agent_type,
        result=result,
        completed_at=time.time(),
        status=SubAgentStatus.COMPLETED,
    )


def _fail(task_id: str = "t1", agent_type: str = "worker", error: str = "boom") -> SubAgentResult:
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
    async def test_chain_hands_the_answer_text_of_an_isolated_step_to_the_next_step(self):
        # An isolated-workspace step reports a dict (answer text plus merge metadata), not a string.
        mgr = MagicMock()
        briefs: list[str] = []

        async def _spawn(**kwargs):
            briefs.append(kwargs["task_description"])
            if len(briefs) == 1:
                step = _ok(kwargs["task_id"], kwargs["agent_type"])
                step.result = {"text": "step1-out", "_isolated_child_workspace": "/tmp/iso"}
                return step
            return _ok(kwargs["task_id"], kwargs["agent_type"], "done")

        mgr.spawn_child = _spawn
        cfgs = [
            ("a", SubagentConfig(system_prompt="s"), "start"),
            ("b", SubagentConfig(system_prompt="s"), "prev={previous}"),
        ]
        result = await run_chain(mgr, cfgs, {}, lambda: [])
        assert result.success
        assert briefs == ["start", "prev=step1-out"]

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
        mgr.spawn_child = AsyncMock(return_value={"success": True, "result": "dict-out"})
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

    @pytest.mark.asyncio
    async def test_repeated_chains_generate_unique_task_ids(self):
        """Completed business nodes persist in _children_results, so chain ids
        must be batch-scoped to avoid 'Task id already exists' on repeat calls."""
        mgr = MagicMock()
        spawned: list[str] = []

        async def _spawn(**kwargs):
            spawned.append(kwargs["task_id"])
            return _ok(kwargs["task_id"], kwargs["agent_type"], "out")

        mgr.spawn_child = _spawn
        cfg = SubagentConfig(system_prompt="s")
        for _ in range(2):
            result = await run_chain(mgr, [("w", cfg, "t")], {}, lambda: [])
            assert result.success

        assert len(spawned) == 2
        assert len(set(spawned)) == 2
        assert all(tid.startswith("chain-") and tid.endswith("-0-w") for tid in spawned)

    @pytest.mark.asyncio
    async def test_chain_cancel_returns_cancelled(self):
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock()
        cancel_token = MagicMock()
        cancel_token.is_cancelled = True
        cfg = SubagentConfig(system_prompt="s")

        result = await run_chain(
            mgr,
            [("w", cfg, "step1"), ("v", cfg, "step2")],
            {},
            lambda: [],
            cancel_token=cancel_token,
        )

        assert not result.success
        assert result.status == SubAgentStatus.CANCELLED
        assert result.error == "Chain cancelled by user"
        mgr.spawn_child.assert_not_awaited()


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
        future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
        future.set_result(ok_result)
        mgr.children = {"t1": future}
        mgr.child_results = {}
        result = await wait_children(mgr, ["t1"])
        assert result["success"]
        assert result["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_running_tasks_exception(self):
        mgr = MagicMock()
        future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
        future.set_exception(RuntimeError("crash"))
        mgr.children = {"t1": future}
        mgr.child_results = {}
        result = await wait_children(mgr, ["t1"])
        assert not result["success"]
        assert "RuntimeError" in str(result["failures"])

    @pytest.mark.asyncio
    async def test_timeout_nonfatal_still_running(self):
        """Timeout returns still_running=True without cancelling the task."""
        mgr = MagicMock()

        async def _slow():
            await asyncio.sleep(10)
            return _ok("t1")

        task = asyncio.create_task(_slow())
        mgr.children = {"t1": task}
        mgr.child_results = {}
        result = await wait_children(mgr, ["t1"], timeout=0.05)
        assert not result["success"]
        assert any("still_running" in str(f) for f in result["failures"])
        assert not task.cancelled(), "task must NOT be cancelled after timeout"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_mixed_completed_and_running(self):
        mgr = MagicMock()
        future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
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
# Non-fatal timeout — SubAgentResult.still_running
# ---------------------------------------------------------------------------


class TestAnswerText:
    def test_text_of_a_plain_result_is_the_result(self):
        assert answer_text("answer") == "answer"

    def test_text_of_a_dict_result_is_the_text_it_carries(self):
        assert answer_text({"text": "answer", "_isolated_child_workspace": "/tmp/iso"}) == "answer"

    def test_text_of_a_dict_result_without_text_is_empty(self):
        assert answer_text({"note": 1}) == ""


class TestSubAgentResultStillRunning:
    def test_still_running_defaults_false(self):
        r = SubAgentResult(success=True, task_id="t1", agent_type="w")
        assert r.still_running is False

    def test_still_running_in_to_dict_when_true(self):
        r = SubAgentResult(
            success=False,
            task_id="t1",
            agent_type="w",
            status=SubAgentStatus.TIMED_OUT,
            still_running=True,
        )
        d = r.to_dict()
        assert d["still_running"] is True
        assert "completed_at" not in d

    def test_still_running_absent_in_to_dict_when_false(self):
        r = SubAgentResult(success=True, task_id="t1", agent_type="w", completed_at=100.0)
        d = r.to_dict()
        assert "still_running" not in d
        assert d["completed_at"] == 100.0

    def test_completed_at_zero_included_when_not_still_running(self):
        """Edge: completed_at defaults to 0.0 but must still be present when still_running=False."""
        r = SubAgentResult(success=True, task_id="t1", agent_type="w")
        d = r.to_dict()
        assert d["completed_at"] == 0.0
        assert "still_running" not in d

    def test_still_running_true_with_all_optional_fields(self):
        """Edge: still_running=True with token_usage, error, trace_id, payload, handover."""
        from myrm_agent_harness.agent.sub_agents.types import AgentHandoverState

        r = SubAgentResult(
            success=False,
            task_id="t1",
            agent_type="w",
            result="partial",
            error="timed out",
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            duration_seconds=59.9999,
            completed_at=999.0,
            status=SubAgentStatus.TIMED_OUT,
            trace_id="trace-abc",
            payload={"key": "val"},
            handover_state=AgentHandoverState(task_completed=["x"]),
            accumulated_duration_seconds=120.5,
            still_running=True,
        )
        d = r.to_dict()
        assert "completed_at" not in d, "completed_at must be omitted when still_running=True"
        assert d["still_running"] is True
        assert d["trace_id"] == "trace-abc"
        assert d["error"] == "timed out"
        tu = d["token_usage"]
        assert tu["prompt_tokens"] == 10
        assert tu["completion_tokens"] == 5
        assert tu["total_tokens"] == 15
        assert d["payload"] == {"key": "val"}
        assert d["handover_state"]["task_completed"] == ["x"]
        assert d["accumulated_duration_seconds"] == 120.5
        assert d["duration_seconds"] == 60.0

    def test_to_dict_status_values_preserved(self):
        """Verify to_dict preserves status enum value for every SubAgentStatus."""
        for status in SubAgentStatus:
            r = SubAgentResult(
                success=(status == SubAgentStatus.COMPLETED),
                task_id="t",
                agent_type="w",
                status=status,
            )
            d = r.to_dict()
            assert d["status"] == status.value

    def test_to_dict_keys_are_deterministic(self):
        """Minimal result produces exactly the expected base keys + completed_at."""
        r = SubAgentResult(success=True, task_id="t", agent_type="w")
        d = r.to_dict()
        expected_keys = {
            "success",
            "task_id",
            "agent_type",
            "result",
            "status",
            "duration_seconds",
            "completed_at",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_still_running_keys_are_deterministic(self):
        """still_running=True produces base keys + still_running, without completed_at."""
        r = SubAgentResult(
            success=False,
            task_id="t",
            agent_type="w",
            status=SubAgentStatus.TIMED_OUT,
            still_running=True,
        )
        d = r.to_dict()
        expected_keys = {
            "success",
            "task_id",
            "agent_type",
            "result",
            "status",
            "duration_seconds",
            "still_running",
        }
        assert set(d.keys()) == expected_keys


class TestNonfatalTimeoutSpawnChild:
    """Verify _HARD_TIMEOUT_MULTIPLIER and non-fatal wait behavior in spawn."""

    def test_hard_timeout_multiplier_value(self):
        from myrm_agent_harness.agent.sub_agents._manager_spawn import (
            _HARD_TIMEOUT_MULTIPLIER,
        )

        assert _HARD_TIMEOUT_MULTIPLIER == 3


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestVerification:
    def test_parse_verdict_json(self):
        raw = '{"verdict": "PASS", "summary": "Looks good", "confidence": "HIGH", "findings": []}'
        verdict = _parse_verdict(raw)
        assert verdict.passed is True
        assert verdict.summary == "Looks good"
        assert verdict.confidence == "HIGH"

    def test_parse_verdict_markdown_json(self):
        raw = '```json\n{"verdict": "FAIL", "summary": "Bad", "confidence": "LOW", "findings": [{"description": "error"}]}\n```'
        verdict = _parse_verdict(raw)
        assert verdict.passed is False
        assert verdict.summary == "Bad"
        assert len(verdict.findings) == 1

    def test_parse_verdict_fallback_pass(self):
        raw = 'I think it is ok. "VERDICT": "PASS"'
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
            result='{"verdict": "PASS", "summary": "ok", "confidence": "HIGH"}',
            status=SubAgentStatus.COMPLETED,
        )

        # The PASS has no execution evidence behind it, so the round is inconclusive: no rework follows.
        mgr.spawn_child = AsyncMock(side_effect=[worker_result, verifier_result])

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

        assert result.success is False
        assert result.status == SubAgentStatus.BLOCKED
        assert result.verification is None
        assert "Verification: INCOMPLETE" in result.result
        assert "Verification: FAIL" not in result.result
        assert mgr.spawn_child.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_run_with_verification_success_first_round(self):
        mgr = MagicMock()

        worker_result = SubAgentResult(
            success=True,
            task_id="w1",
            agent_type="worker",
            result="worker out",
            error="",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )
        verifier_result = SubAgentResult(
            success=True,
            task_id="v1",
            agent_type="verifier",
            result='{"verdict": "PASS", "summary": "ok", "confidence": "HIGH"}',
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
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_run_with_verification_fail_then_pass(self):
        mgr = MagicMock()

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
            result='{"verdict": "PASS", "confidence": "HIGH", "summary": "ok"}',
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
        assert result.status == SubAgentStatus.BLOCKED
        assert result.verification is None
        assert "Verification: INCOMPLETE" in result.result
        assert "Verification: FAIL" not in result.result
        assert mgr.spawn_child.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_run_with_verification_dict_result(self):
        mgr = MagicMock()

        w1 = {"success": True, "result": "dict out"}
        v1 = {"success": True, "result": '{"verdict": "PASS", "summary": "ok"}'}

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

    async def test_run_with_verification_readonly_sandbox_verifier_holds_no_write_capability(self):
        from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy
        from myrm_agent_harness.core.security.ocap import CapabilityAction, get_current_capability

        mgr = MagicMock()
        seen_actions: list[frozenset[CapabilityAction] | None] = []

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok("worker done")
            handle = get_current_capability()
            seen_actions.append(None if handle is None else handle.actions)
            return _ok('{"verdict": "PASS", "summary": "ok"}')

        mgr.spawn_child = _spawn

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

        assert seen_actions == [frozenset({CapabilityAction.READ, CapabilityAction.EXECUTE})]
        # The verifier never launched a command, so its PASS is rejected.
        assert result.success is False


# ---------------------------------------------------------------------------
# run_alternatives
# ---------------------------------------------------------------------------


class TestRunAlternatives:
    @pytest.mark.asyncio
    async def test_empty_configs_returns_empty(self):
        mgr = MagicMock()
        result = await run_alternatives(mgr, "task", [], {}, lambda: [])
        assert result == []

    @pytest.mark.asyncio
    async def test_single_alternative_success(self):
        mgr = MagicMock()
        _ok("alt-xxxxxxxx-0-writer", "writer", "solution A")
        mgr.children = {}
        mgr.child_results = {}

        async def _spawn(**kwargs):
            tid = kwargs["task_id"]
            mgr.child_results[tid] = SubAgentResult(
                success=True,
                task_id=tid,
                agent_type=kwargs["agent_type"],
                result="solution A",
                status=SubAgentStatus.COMPLETED,
                completed_at=time.time(),
            )
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(mgr.child_results[tid])
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        config = SubagentConfig(system_prompt="write something")
        results = await run_alternatives(mgr, "write a landing page", [("writer", config)], {}, lambda: [])

        assert len(results) == 1
        assert results[0].success
        assert results[0].result == "solution A"

    @pytest.mark.asyncio
    async def test_multiple_alternatives_preserve_order(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}

        async def _spawn(**kwargs):
            tid = kwargs["task_id"]
            idx = int(tid.split("-")[2])
            mgr.child_results[tid] = SubAgentResult(
                success=True,
                task_id=tid,
                agent_type=kwargs["agent_type"],
                result=f"solution-{idx}",
                status=SubAgentStatus.COMPLETED,
                completed_at=time.time(),
            )
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(mgr.child_results[tid])
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        configs = [
            ("writer-a", SubagentConfig(system_prompt="formal")),
            ("writer-b", SubagentConfig(system_prompt="casual")),
            ("writer-c", SubagentConfig(system_prompt="creative")),
        ]
        results = await run_alternatives(mgr, "write", configs, {}, lambda: [])

        assert len(results) == 3
        assert results[0].result == "solution-0"
        assert results[1].result == "solution-1"
        assert results[2].result == "solution-2"

    @pytest.mark.asyncio
    async def test_spawn_early_failure_preserved(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}

        call_count = 0

        async def _spawn(**kwargs):
            nonlocal call_count
            call_count += 1
            tid = kwargs["task_id"]
            if call_count == 1:
                return SubAgentResult(
                    success=False,
                    task_id=tid,
                    agent_type=kwargs["agent_type"],
                    error="capacity exceeded",
                    status=SubAgentStatus.FAILED,
                )
            mgr.child_results[tid] = _ok(tid, kwargs["agent_type"], "ok")
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(mgr.child_results[tid])
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        configs = [
            ("a", SubagentConfig(system_prompt="s")),
            ("b", SubagentConfig(system_prompt="s")),
        ]
        results = await run_alternatives(mgr, "task", configs, {}, lambda: [])

        assert len(results) == 2
        assert not results[0].success
        assert "capacity exceeded" in results[0].error
        assert results[1].success

    @pytest.mark.asyncio
    async def test_all_spawn_failures(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}

        async def _spawn(**kwargs):
            return SubAgentResult(
                success=False,
                task_id=kwargs["task_id"],
                agent_type=kwargs["agent_type"],
                error="depth exceeded",
                status=SubAgentStatus.FAILED,
            )

        mgr.spawn_child = _spawn

        configs = [
            ("a", SubagentConfig(system_prompt="s")),
            ("b", SubagentConfig(system_prompt="s")),
        ]
        results = await run_alternatives(mgr, "task", configs, {}, lambda: [])

        assert len(results) == 2
        assert all(not r.success for r in results)

    @pytest.mark.asyncio
    async def test_workspace_policy_forced_to_isolated_copy(self):
        from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy

        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}
        captured_configs: list[SubagentConfig] = []
        captured_contexts: list[dict[str, object]] = []

        async def _spawn(**kwargs):
            captured_configs.append(kwargs["config"])
            captured_contexts.append(kwargs["context"])
            tid = kwargs["task_id"]
            mgr.child_results[tid] = _ok(tid, kwargs["agent_type"])
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(mgr.child_results[tid])
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        config = SubagentConfig(system_prompt="s", workspace_policy=WorkspacePolicy.INHERIT)
        await run_alternatives(mgr, "task", [("w", config)], {}, lambda: [])

        assert captured_configs[0].workspace_policy == WorkspacePolicy.ISOLATED_COPY
        assert captured_contexts[0]["_defer_workspace_merge"] is True

    @pytest.mark.asyncio
    async def test_unique_batch_ids_across_calls(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}
        captured_task_ids: list[str] = []

        async def _spawn(**kwargs):
            tid = kwargs["task_id"]
            captured_task_ids.append(tid)
            mgr.child_results[tid] = _ok(tid, kwargs["agent_type"])
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(mgr.child_results[tid])
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        config = SubagentConfig(system_prompt="s")
        await run_alternatives(mgr, "task", [("w", config)], {}, lambda: [])
        await run_alternatives(mgr, "task", [("w", config)], {}, lambda: [])

        assert len(captured_task_ids) == 2
        assert captured_task_ids[0] != captured_task_ids[1]

    @pytest.mark.asyncio
    async def test_cancel_token_propagated(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}
        captured_cancel_tokens: list[object] = []

        async def _spawn(**kwargs):
            captured_cancel_tokens.append(kwargs.get("cancel_token"))
            tid = kwargs["task_id"]
            mgr.child_results[tid] = _ok(tid, kwargs["agent_type"])
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(mgr.child_results[tid])
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        sentinel = object()
        config = SubagentConfig(system_prompt="s")
        await run_alternatives(mgr, "task", [("w", config)], {}, lambda: [], cancel_token=sentinel)

        assert len(captured_cancel_tokens) == 1
        assert captured_cancel_tokens[0] is sentinel

    @pytest.mark.asyncio
    async def test_existing_context_not_mutated(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}

        async def _spawn(**kwargs):
            tid = kwargs["task_id"]
            mgr.child_results[tid] = _ok(tid, kwargs["agent_type"])
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(mgr.child_results[tid])
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        original_ctx = {"workspace_path": "/tmp/ws", "some_key": "val"}
        ctx_copy = dict(original_ctx)
        config = SubagentConfig(system_prompt="s")
        await run_alternatives(mgr, "task", [("w", config)], original_ctx, lambda: [])

        assert original_ctx == ctx_copy, "Original context must not be mutated"

    @pytest.mark.asyncio
    async def test_mixed_runtime_success_and_failure(self):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}

        async def _spawn(**kwargs):
            tid = kwargs["task_id"]
            idx = int(tid.split("-")[2])
            if idx == 0:
                r = _ok(tid, kwargs["agent_type"], "good")
            else:
                r = _fail(tid, kwargs["agent_type"], "runtime error")
            mgr.child_results[tid] = r
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(r)
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        configs = [
            ("a", SubagentConfig(system_prompt="s")),
            ("b", SubagentConfig(system_prompt="s")),
        ]
        results = await run_alternatives(mgr, "task", configs, {}, lambda: [])

        assert len(results) == 2
        assert results[0].success
        assert results[0].result == "good"
        assert not results[1].success
        assert "runtime error" in results[1].error

    @pytest.mark.asyncio
    async def test_isolated_workspace_is_discarded_and_internal_keys_stripped(self, tmp_path):
        mgr = MagicMock()
        mgr.children = {}
        mgr.child_results = {}

        child_ws = tmp_path / "alt_child"
        child_ws.mkdir()
        (child_ws / "draft.txt").write_text("draft", encoding="utf-8")

        async def _spawn(**kwargs):
            tid = kwargs["task_id"]
            r = SubAgentResult(
                success=True,
                task_id=tid,
                agent_type=kwargs["agent_type"],
                result={
                    "text": "solution",
                    "_workspace_sync_back": AsyncMock(),
                    "_isolated_child_workspace": str(child_ws),
                    "_isolated_parent_workspace": str(tmp_path / "parent"),
                },
                status=SubAgentStatus.COMPLETED,
                completed_at=time.time(),
            )
            mgr.child_results[tid] = r
            future: asyncio.Future[SubAgentResult] = asyncio.get_event_loop().create_future()
            future.set_result(r)
            mgr.children[tid] = future
            return future

        mgr.spawn_child = _spawn

        config = SubagentConfig(system_prompt="s")
        results = await run_alternatives(mgr, "task", [("w", config)], {}, lambda: [])

        assert len(results) == 1
        assert results[0].success
        result_dict = results[0].result
        assert isinstance(result_dict, dict)
        assert "_workspace_sync_back" not in result_dict
        assert "_isolated_child_workspace" not in result_dict
        assert result_dict.get("text") == "solution"
        assert not child_ws.exists()
