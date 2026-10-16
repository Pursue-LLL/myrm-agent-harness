"""Verification never grades a subagent that is paused for approval: a pause is not output."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents._orchestrator_verification import run_with_verification
from myrm_agent_harness.agent.sub_agents.approval_journal import ApprovalJournal
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus

_VERDICT_FAIL = '{"verdict": "FAIL", "summary": "bad", "confidence": "HIGH", "findings": []}'
_VERDICT_PASS = '{"verdict": "PASS", "summary": "ok", "confidence": "HIGH", "findings": []}'


def _result(task_id: str, status: SubAgentStatus, text: str = "") -> SubAgentResult:
    return SubAgentResult(
        success=status != SubAgentStatus.FAILED,
        task_id=task_id,
        agent_type="w",
        result=text,
        completed_at=time.time(),
        status=status,
    )


async def _verify(manager: MagicMock, *, task_id: str | None = "business", **extra: object) -> SubAgentResult:
    return await run_with_verification(
        manager,
        worker_type="w",
        worker_config=SubagentConfig(system_prompt="worker"),
        worker_task="do work",
        verifier_type="v",
        verifier_config=SubagentConfig(system_prompt="verifier"),
        context={},
        tool_registry_getter=lambda: [],
        max_rounds=2,
        task_id=task_id,
        **extra,
    )


@pytest.fixture
def dropped_threads():
    """Checkpoint threads released for subagents that were abandoned while paused."""
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents._orchestrator_verification.delete_subagent_checkpoint",
            new=AsyncMock(),
        ) as worker_drop,
        patch(
            "myrm_agent_harness.agent.sub_agents._verifier_round.delete_subagent_checkpoint", new=AsyncMock()
        ) as verifier_drop,
    ):
        yield worker_drop, verifier_drop


@pytest.mark.asyncio
async def test_a_paused_worker_without_an_approval_scope_is_blocked_not_verified(dropped_threads) -> None:
    worker_drop, _ = dropped_threads
    spawned: list[str] = []

    async def spawn(**kwargs: object) -> SubAgentResult:
        spawned.append(str(kwargs["task_id"]))
        return _result(str(kwargs["task_id"]), SubAgentStatus.PENDING_APPROVAL)

    manager = MagicMock()
    manager.spawn_child = spawn

    result = await _verify(manager)

    assert spawned == ["business"]
    assert result.status == SubAgentStatus.BLOCKED
    assert result.success is False
    assert "paused for approval" in result.error
    assert result.verification is None
    worker_drop.assert_awaited_once_with("business")


@pytest.mark.asyncio
async def test_a_paused_retry_worker_ends_the_round_blocked_instead_of_failing_the_work(dropped_threads) -> None:
    worker_drop, _ = dropped_threads
    spawned: list[str] = []

    async def spawn(**kwargs: object) -> SubAgentResult:
        task_id = str(kwargs["task_id"])
        spawned.append(task_id)
        if task_id.startswith("verify-check"):
            return _result(task_id, SubAgentStatus.COMPLETED, _VERDICT_FAIL)
        if task_id == "business":
            return _result(task_id, SubAgentStatus.COMPLETED, "first attempt")
        return _result(task_id, SubAgentStatus.PENDING_APPROVAL)

    manager = MagicMock()
    manager.spawn_child = spawn
    scope = ApprovalJournal().scope("business", resume=AsyncMock(), ask=MagicMock())

    with patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_verification.take_workspace_snapshot", return_value={}
    ):
        result = await _verify(manager, approval_scope=scope)

    assert [task_id.split("-")[0] for task_id in spawned] == ["business", "verify", "verify"]
    assert result.status == SubAgentStatus.BLOCKED
    assert "paused for approval" in result.error
    worker_drop.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_paused_verifier_is_inconclusive_and_never_sends_the_worker_back(dropped_threads) -> None:
    _, verifier_drop = dropped_threads
    worker_spawns = 0

    async def spawn(**kwargs: object) -> SubAgentResult:
        nonlocal worker_spawns
        task_id = str(kwargs["task_id"])
        if task_id.startswith("verify-check"):
            return _result(task_id, SubAgentStatus.PENDING_APPROVAL)
        worker_spawns += 1
        return _result(task_id, SubAgentStatus.COMPLETED, "work output")

    manager = MagicMock()
    manager.spawn_child = spawn

    result = await _verify(manager)

    assert worker_spawns == 1
    assert result.status == SubAgentStatus.BLOCKED
    assert "no conclusive verdict" in result.error
    assert "INCOMPLETE" in str(result.result)
    verifier_drop.assert_awaited_once()
    assert str(verifier_drop.await_args.args[0]).startswith("verify-check-1-v-")


@pytest.mark.asyncio
@pytest.mark.usefixtures("verifier_ran_code")
async def test_an_approval_scope_settles_the_visible_worker_before_any_verifier_runs(dropped_threads) -> None:
    order: list[str] = []
    decisions_given: list[object] = []
    paused = _result("business", SubAgentStatus.PENDING_APPROVAL)

    async def spawn(**kwargs: object) -> SubAgentResult:
        task_id = str(kwargs["task_id"])
        order.append(task_id)
        if task_id.startswith("verify-check"):
            return _result(task_id, SubAgentStatus.COMPLETED, _VERDICT_PASS)
        return paused

    async def resume(decisions: object) -> SubAgentResult:
        order.append("resume")
        decisions_given.append(decisions)
        return _result("business", SubAgentStatus.COMPLETED, "finished after approval")

    manager = MagicMock()
    manager.spawn_child = spawn
    scope = ApprovalJournal().scope("business", resume=resume, ask=lambda _pending: "approved")

    result = await _verify(manager, approval_scope=scope)

    assert [step.split("-")[0] for step in order] == ["business", "resume", "verify"]
    assert decisions_given == ["approved"]
    assert result.success is True
    assert "[Verification: PASS" in str(result.result)
