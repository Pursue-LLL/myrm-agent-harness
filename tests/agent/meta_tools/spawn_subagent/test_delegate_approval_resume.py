"""delegate_task under real LangGraph interrupts: LangGraph re-executes the tool call after every UI approval."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool
from myrm_agent_harness.agent.sub_agents._verification_parsing import VerificationVerdict
from myrm_agent_harness.agent.sub_agents.approval_journal import ApprovalJournal
from myrm_agent_harness.agent.sub_agents.manager import CapacitySnapshot
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus

_BASH = "bash_code_execute_tool"
_ARGS = {"agent_type": "coder", "objective": "Write a function", "wait": True}


def _result(status: SubAgentStatus, text: str = "Done", task_id: str = "child") -> SubAgentResult:
    return SubAgentResult(
        success=status != SubAgentStatus.FAILED,
        task_id=task_id,
        agent_type="coder",
        result=text,
        completed_at=1.0,
        status=status,
    )


class _Subagent:
    """A subagent that asks for approval ``approvals`` times, one shell command each, then finishes."""

    def __init__(self, approvals: int, label: str = "step") -> None:
        self.approvals = approvals
        self.label = label
        self.calls: list[dict[str, object]] = []
        self.decisions: list[object] = []

    async def spawn_child(self, **kwargs: object) -> SubAgentResult:
        self.calls.append(kwargs)
        command = kwargs.get("resume_command")
        if isinstance(command, Command):
            self.decisions.append(command.resume)
        task_id = str(kwargs["task_id"])
        if len(self.decisions) < self.approvals:
            request = {"action": _BASH, "args": {"command": f"{self.label}-{len(self.decisions)}"}}
            pending = _result(SubAgentStatus.PENDING_APPROVAL, task_id=task_id)
            pending.payload = {"actionRequests": [request]}
            return pending
        return _result(SubAgentStatus.COMPLETED, "All steps finished", task_id=task_id)

    @property
    def fresh_spawns(self) -> list[dict[str, object]]:
        return [call for call in self.calls if "resume_command" not in call]

    @property
    def resumes(self) -> list[dict[str, object]]:
        return [call for call in self.calls if "resume_command" in call]


def _parent(subagent: _Subagent) -> MagicMock:
    parent = MagicMock()
    parent._last_context = {"session_id": "s1"}
    parent._subagent_manager = MagicMock(
        current_depth=0,
        approval_journal=ApprovalJournal(),
        get_capacity_snapshot=lambda: CapacitySnapshot(0, 5, 5, 0, 20, 20),
    )
    parent._subagent_manager.spawn_child = subagent.spawn_child
    parent._spawn_child = subagent.spawn_child
    return parent


def _catalog() -> AsyncMock:
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="You are a mock agent", tools=(_BASH,)))
    return catalog


def _graph(parent: MagicMock, checkpointer: InMemorySaver | None = None) -> object:
    tool = create_delegate_task_tool(parent, list, _catalog())
    builder = StateGraph(MessagesState)
    builder.add_node("tools", ToolNode([tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def _call(args: dict[str, object], call_id: str) -> dict[str, object]:
    message = AIMessage(content="", tool_calls=[{"name": "delegate_task_tool", "args": args, "id": call_id}])
    return {"messages": [message]}


def _tool_output(state: dict[str, object]) -> dict[str, object]:
    content = state["messages"][-1].content  # type: ignore[index]
    parsed = json.loads(content) if content.startswith('{"') else ast.literal_eval(content)
    assert isinstance(parsed, dict)
    return parsed


def _requested_commands(state: dict[str, object]) -> list[str]:
    (interrupt_,) = state["__interrupt__"]  # type: ignore[misc]
    return [str(call["args"]["command"]) for call in interrupt_.value["tool_calls"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("context_survives_resume", [True, False])
async def test_one_approval_resumes_the_subagent_that_asked_for_it(context_survives_resume: bool) -> None:
    subagent = _Subagent(approvals=1)
    parent = _parent(subagent)
    graph = _graph(parent)
    config = {"configurable": {"thread_id": "chat"}}

    paused = await graph.ainvoke(_call(_ARGS, "c1"), config)  # type: ignore[attr-defined]
    if not context_survives_resume:
        parent._last_context = {"session_id": "s1"}
    decisions = {"decisions": [{"type": "approve"}]}
    done = await graph.ainvoke(Command(resume=decisions), config)  # type: ignore[attr-defined]

    assert _requested_commands(paused) == ["step-0"]
    output = _tool_output(done)
    assert output["success"] is True
    assert "Safety interception" not in str(output)
    assert len(subagent.fresh_spawns) == 1
    (resume,) = subagent.resumes
    assert resume["task_id"] == subagent.fresh_spawns[0]["task_id"] == output["task_id"]
    assert subagent.decisions == [decisions]


@pytest.mark.asyncio
@pytest.mark.parametrize("context_survives_resume", [True, False])
async def test_every_approval_of_a_subagent_is_answered_once_and_in_order(context_survives_resume: bool) -> None:
    subagent = _Subagent(approvals=3)
    parent = _parent(subagent)
    graph = _graph(parent)
    config = {"configurable": {"thread_id": "chat"}}
    answers = [{"decisions": [{"type": "approve", "n": n}]} for n in range(3)]

    state = await graph.ainvoke(_call(_ARGS, "c1"), config)  # type: ignore[attr-defined]
    requested = [_requested_commands(state)]
    for answer in answers[:2]:
        if not context_survives_resume:
            parent._last_context = {"session_id": "s1"}
        state = await graph.ainvoke(Command(resume=answer), config)  # type: ignore[attr-defined]
        requested.append(_requested_commands(state))
    if not context_survives_resume:
        parent._last_context = {"session_id": "s1"}
    done = await graph.ainvoke(Command(resume=answers[2]), config)  # type: ignore[attr-defined]

    assert requested == [["step-0"], ["step-1"], ["step-2"]]
    assert _tool_output(done)["success"] is True
    assert subagent.decisions == answers
    assert len(subagent.fresh_spawns) == 1
    assert {call["task_id"] for call in subagent.calls} == {subagent.fresh_spawns[0]["task_id"]}


@pytest.mark.asyncio
async def test_a_model_that_repeats_a_delegation_in_a_later_call_is_still_stopped() -> None:
    subagent = _Subagent(approvals=1)
    graph = _graph(_parent(subagent))
    config = {"configurable": {"thread_id": "chat"}}

    await graph.ainvoke(_call(_ARGS, "c1"), config)  # type: ignore[attr-defined]
    await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), config)  # type: ignore[attr-defined]
    repeated = await graph.ainvoke(_call(_ARGS, "c2"), config)  # type: ignore[attr-defined]

    assert "Safety interception" in str(_tool_output(repeated)["error"])
    assert len(subagent.fresh_spawns) == 1


@pytest.mark.asyncio
async def test_a_verified_worker_is_verified_after_its_approvals_and_against_its_first_baseline(
    tmp_path: Path,
) -> None:
    subagent = _Subagent(approvals=1)
    parent = _parent(subagent)
    parent._last_context = {"session_id": "s1", "workspace_path": str(tmp_path)}
    graph = _graph(parent)
    config = {"configurable": {"thread_id": "chat"}}
    events: list[str] = []
    snapshots = iter(range(1, 10))
    verdict = VerificationVerdict(passed=True, summary="ok", confidence="HIGH", findings=[], raw="{}")

    async def verify(*_args: object, **kwargs: object) -> VerificationVerdict:
        events.append(f"verify:{kwargs['pre_snapshot']}")
        return verdict

    args = {**_ARGS, "verifier_prompt": "Run the tests"}
    with (
        patch(
            "myrm_agent_harness.agent.sub_agents.verifier_selection.resolve_verifier",
            new=AsyncMock(return_value=("coder", SubagentConfig(system_prompt="verifier", tools=(_BASH,)))),
        ),
        patch(
            "myrm_agent_harness.agent.sub_agents._orchestrator_verification.take_workspace_snapshot",
            side_effect=lambda _path: {"baseline": (float(next(snapshots)), 0)},
        ),
        patch("myrm_agent_harness.agent.sub_agents._orchestrator_verification._execute_verifier_round", new=verify),
    ):
        await graph.ainvoke(_call(args, "c1"), config)  # type: ignore[attr-defined]
        assert events == []
        done = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), config)  # type: ignore[attr-defined]

    output = _tool_output(done)
    assert output["success"] is True
    assert "[Verification: PASS" in str(output["result"])
    assert events == ["verify:{'baseline': (1.0, 0)}"]
    assert len(subagent.fresh_spawns) == 1
    assert subagent.decisions == [{"decisions": [{"type": "approve"}]}]


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_answers", [1, 2])
async def test_answers_given_to_a_lost_subagent_are_never_applied_to_its_replacement(stale_answers: int) -> None:
    """A restart empties the journal while the checkpoint still holds the answers the user gave before it."""
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "chat"}}
    before = _Subagent(approvals=stale_answers + 1)
    graph = _graph(_parent(before), saver)
    state = await graph.ainvoke(_call(_ARGS, "c1"), config)  # type: ignore[attr-defined]
    for n in range(stale_answers):
        state = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve", "n": n}]}), config)  # type: ignore[attr-defined]
    assert _requested_commands(state) == [f"step-{stale_answers}"]

    after = _Subagent(approvals=1, label="other")
    restarted = _graph(_parent(after), saver)
    asked = await restarted.ainvoke(Command(resume={"decisions": [{"type": "approve", "n": "last"}]}), config)  # type: ignore[attr-defined]

    assert _requested_commands(asked) == ["other-0"]
    assert after.decisions == []
    fresh = {"decisions": [{"type": "approve", "n": "new"}]}
    done = await restarted.ainvoke(Command(resume=fresh), config)  # type: ignore[attr-defined]
    assert _tool_output(done)["success"] is True
    assert after.decisions == [fresh]
    assert len(after.fresh_spawns) == 1
