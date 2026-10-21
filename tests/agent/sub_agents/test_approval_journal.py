"""Approval journal: a replayed delegation walks past answered approvals and only acts at the frontier."""

from __future__ import annotations

import re
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from myrm_agent_harness.agent.sub_agents.approval_journal import (
    ApprovalJournal,
    ApprovalScope,
    SpawnResult,
    approvals_unanswerable,
    delegation_task_id,
)
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus


def _result(status: SubAgentStatus, text: str = "") -> SubAgentResult:
    return SubAgentResult(
        success=status != SubAgentStatus.FAILED,
        task_id="child",
        agent_type="coder",
        result=text,
        completed_at=1.0,
        status=status,
    )


class _Subagent:
    """A subagent that needs ``approvals`` answers before it finishes, and counts what is done to it."""

    def __init__(self, approvals: int) -> None:
        self.approvals = approvals
        self.spawned = 0
        self.resumed_with: list[object] = []

    async def spawn(self) -> SpawnResult:
        self.spawned += 1
        return self._state()

    async def resume(self, decisions: object) -> SpawnResult:
        self.resumed_with.append(decisions)
        return self._state()

    def _state(self) -> SubAgentResult:
        if len(self.resumed_with) < self.approvals:
            return _result(SubAgentStatus.PENDING_APPROVAL)
        return _result(SubAgentStatus.COMPLETED, "done")


class _User:
    """The UI side of ``interrupt()``: answered requests return their stored answer, the next one pauses."""

    def __init__(self, answers: list[object]) -> None:
        self.answers = answers
        self._asked = 0

    def begin_execution(self) -> None:
        self._asked = 0

    def ask(self, _pending: SubAgentResult) -> object:
        index = self._asked
        self._asked += 1
        if index >= len(self.answers):
            raise GraphInterrupt  # what ``interrupt()`` raises while no answer is stored yet
        return self.answers[index]


async def _execute(journal: ApprovalJournal, subagent: _Subagent, user: _User) -> SpawnResult:
    """One execution of the delegating tool, as LangGraph runs it again after every answer."""
    user.begin_execution()
    scope = journal.scope("task", resume=subagent.resume, ask=user.ask)
    return await scope.settle(subagent.spawn)


@pytest.mark.asyncio
async def test_a_subagent_that_never_pauses_is_spawned_once_and_forgotten() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=0)

    result = await _execute(journal, subagent, _User([]))

    assert isinstance(result, SubAgentResult) and result.result == "done"
    assert subagent.spawned == 1
    assert not journal.is_replay("task")


@pytest.mark.asyncio
async def test_a_pause_keeps_the_delegation_recorded_for_the_replay() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=1)

    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User([]))

    assert journal.is_replay("task")


@pytest.mark.asyncio
@pytest.mark.parametrize("approvals", [1, 2, 3])
async def test_each_answer_reaches_the_subagent_exactly_once_and_in_order(approvals: int) -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals)
    answers = [f"answer-{n}" for n in range(approvals)]

    for answered in range(approvals):
        with pytest.raises(GraphInterrupt):
            await _execute(journal, subagent, _User(answers[:answered]))
    result = await _execute(journal, subagent, _User(answers))

    assert isinstance(result, SubAgentResult) and result.status == SubAgentStatus.COMPLETED
    assert subagent.spawned == 1
    assert subagent.resumed_with == answers
    assert not journal.is_replay("task")


@pytest.mark.asyncio
async def test_a_replay_that_gets_no_new_answer_changes_nothing() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=2)
    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User([]))
    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User(["first"]))

    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User(["first"]))

    assert subagent.spawned == 1
    assert subagent.resumed_with == ["first"]


@pytest.mark.asyncio
async def test_a_failed_resume_ends_the_delegation() -> None:
    journal = ApprovalJournal()

    async def spawn() -> SpawnResult:
        return _result(SubAgentStatus.PENDING_APPROVAL)

    async def resume(_decisions: object) -> SpawnResult:
        raise RuntimeError("executor down")

    with pytest.raises(GraphInterrupt):
        await journal.scope("task", resume=resume, ask=_User([]).ask).settle(spawn)
    with pytest.raises(RuntimeError, match="executor down"):
        await journal.scope("task", resume=resume, ask=_User(["go"]).ask).settle(spawn)

    assert not journal.is_replay("task")


@pytest.mark.asyncio
async def test_a_failure_while_asking_ends_the_delegation() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=1)

    def ask(_pending: SubAgentResult) -> object:
        raise RuntimeError("no UI")

    with pytest.raises(RuntimeError, match="no UI"):
        await journal.scope("task", resume=subagent.resume, ask=ask).settle(subagent.spawn)

    assert not journal.is_replay("task")


@pytest.mark.asyncio
async def test_delegations_do_not_see_each_others_progress() -> None:
    journal, first, second = ApprovalJournal(), _Subagent(approvals=1), _Subagent(approvals=1)

    with pytest.raises(GraphInterrupt):
        await journal.scope("a", resume=first.resume, ask=_User([]).ask).settle(first.spawn)
    with pytest.raises(GraphInterrupt):
        await journal.scope("b", resume=second.resume, ask=_User([]).ask).settle(second.spawn)
    result = await journal.scope("b", resume=second.resume, ask=_User(["go"]).ask).settle(second.spawn)

    assert isinstance(result, SubAgentResult) and result.status == SubAgentStatus.COMPLETED
    assert (first.spawned, second.spawned) == (1, 1)
    assert (first.resumed_with, second.resumed_with) == ([], ["go"])
    assert journal.is_replay("a") and not journal.is_replay("b")


def test_a_remembered_value_is_computed_once_per_delegation() -> None:
    journal = ApprovalJournal()
    scope: ApprovalScope = journal.scope("task", resume=_Subagent(0).resume, ask=_User([]).ask)
    calls: list[str] = []

    def make() -> list[str]:
        calls.append("made")
        return ["baseline"]

    first = scope.remember("snapshot", make)
    second = scope.remember("snapshot", make)

    assert first is second
    assert calls == ["made"]


class _State(TypedDict):
    ids: list[str]


def _ids_per_execution(turns: int) -> list[tuple[str, str]]:
    """Ids for two payloads a node computes in every execution; LangGraph runs it twice per turn (interrupt, resume)."""
    seen: list[tuple[str, str]] = []

    def node(_state: _State) -> _State:
        seen.append((delegation_task_id("payload-a"), delegation_task_id("payload-b")))
        interrupt("approve?")
        return {"ids": []}

    builder = StateGraph(_State)
    builder.add_node("tools", node)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "chat"}}
    for _ in range(turns):
        graph.invoke({"ids": []}, config)
        graph.invoke(Command(resume="yes"), config)
    return seen


def test_the_task_id_is_stable_across_replays_and_differs_between_turns_and_payloads() -> None:
    seen = _ids_per_execution(turns=2)
    first_turn, second_turn = seen[:2], seen[2:]

    assert first_turn[0] == first_turn[1]
    assert second_turn[0] == second_turn[1]
    assert first_turn[0] != second_turn[0]
    assert first_turn[0][0] != first_turn[0][1]
    assert all(re.fullmatch(r"[0-9a-f]{8}", task_id) for pair in seen for task_id in pair)


def test_the_task_id_outside_a_graph_run_is_random() -> None:
    assert delegation_task_id("payload") != delegation_task_id("payload")


def test_each_manager_owns_one_journal_that_lives_as_long_as_it_does() -> None:
    first, second = SubagentManager(MagicMock()), SubagentManager(MagicMock())

    assert isinstance(first.approval_journal, ApprovalJournal)
    assert first.approval_journal is first.approval_journal
    assert first.approval_journal is not second.approval_journal


@pytest.mark.asyncio
async def test_answers_that_exist_before_a_subagent_has_asked_are_not_its_answers() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=1)

    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User(["given-to-a-lost-subagent", "given-last"]))
    result = await _execute(journal, subagent, _User(["given-to-a-lost-subagent", "given-last", "new"]))

    assert isinstance(result, SubAgentResult) and result.status == SubAgentStatus.COMPLETED
    assert subagent.spawned == 1
    assert subagent.resumed_with == ["new"]


@pytest.mark.asyncio
async def test_a_replay_stays_aligned_after_stale_answers_were_discarded() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=2)
    stale = ["old-0", "old-1"]

    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User(stale))
    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User([*stale, "first"]))
    result = await _execute(journal, subagent, _User([*stale, "first", "second"]))

    assert isinstance(result, SubAgentResult) and result.status == SubAgentStatus.COMPLETED
    assert subagent.resumed_with == ["first", "second"]


@pytest.mark.asyncio
async def test_a_fresh_delegation_starts_on_an_empty_thread_and_its_replays_do_not_clear_it() -> None:
    cleaner, subagent = AsyncMock(), _Subagent(approvals=1)
    journal = ApprovalJournal(discard_stale_thread=cleaner)

    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User([]))
    cleaner.assert_awaited_once_with("task")
    await _execute(journal, subagent, _User(["go"]))

    cleaner.assert_awaited_once_with("task")


@pytest.mark.asyncio
async def test_an_unanswerable_approval_is_declined_and_frees_the_paused_subagent() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=1)
    ask = MagicMock()
    paused = _result(SubAgentStatus.PENDING_APPROVAL)
    paused.payload = {"actionRequests": [{"action": "bash_code_execute_tool"}]}

    async def spawn() -> SpawnResult:
        return paused

    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.approval_journal.delete_subagent_checkpoint", new=AsyncMock()
        ) as free,
        approvals_unanswerable(),
    ):
        result = await journal.scope("task", resume=subagent.resume, ask=ask).settle(spawn)

    assert isinstance(result, SubAgentResult)
    assert (result.success, result.status, result.payload) == (False, SubAgentStatus.BLOCKED, None)
    assert "needs the user's approval" in result.error
    ask.assert_not_called()
    free.assert_awaited_once_with("child")
    assert subagent.resumed_with == []
    assert not journal.is_replay("task")


@pytest.mark.asyncio
async def test_approvals_are_asked_again_once_the_unanswerable_block_ends() -> None:
    journal, subagent = ApprovalJournal(), _Subagent(approvals=1)
    with approvals_unanswerable():
        pass

    with pytest.raises(GraphInterrupt):
        await _execute(journal, subagent, _User([]))
