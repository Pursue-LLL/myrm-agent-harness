"""delegate_task under the production graph builder: parallel delegations pause and resume independently.

The agent graph (langchain ``create_agent``) runs every tool call of one model message as its own task, so each
delegation re-executes alone after an approval and a finished sibling is never run again.
"""

from __future__ import annotations

import ast
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool
from myrm_agent_harness.agent.sub_agents.approval_journal import ApprovalJournal
from myrm_agent_harness.agent.sub_agents.manager import CapacitySnapshot
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus

_BASH = "bash_code_execute_tool"
_CONFIG = {"configurable": {"thread_id": "chat"}}


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        return self


def _result(status: SubAgentStatus, text: str, task_id: str) -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id=task_id,
        agent_type="coder",
        result=text,
        completed_at=1.0,
        status=status,
    )


class _Subagents:
    """Subagents that ask for approval ``approvals[objective]`` times, one shell command each, then finish."""

    def __init__(self, approvals: dict[str, int]) -> None:
        self.approvals = approvals
        self.calls: list[dict[str, object]] = []
        self.decisions: dict[str, list[object]] = {}

    async def spawn_child(self, **kwargs: object) -> SubAgentResult:
        self.calls.append(kwargs)
        objective = str(kwargs["task_description"])
        decided = self.decisions.setdefault(objective, [])
        command = kwargs.get("resume_command")
        if isinstance(command, Command):
            decided.append(command.resume)
        task_id = str(kwargs["task_id"])
        if len(decided) < self.approvals[objective]:
            pending = _result(SubAgentStatus.PENDING_APPROVAL, "", task_id)
            pending.payload = {
                "actionRequests": [{"action": _BASH, "args": {"command": f"{objective}-{len(decided)}"}}]
            }
            return pending
        return _result(SubAgentStatus.COMPLETED, f"{objective} finished", task_id)

    def fresh_spawns(self, objective: str) -> int:
        return sum(1 for c in self.calls if c["task_description"] == objective and "resume_command" not in c)

    def resumes(self, objective: str) -> int:
        return sum(1 for c in self.calls if c["task_description"] == objective and "resume_command" in c)


def _agent(subagents: _Subagents, objectives: list[str]) -> object:
    """An agent whose first model message delegates every objective in parallel."""
    parent = MagicMock()
    parent._last_context = {"session_id": "s1"}
    parent._subagent_manager = MagicMock(
        current_depth=0,
        approval_journal=ApprovalJournal(),
        get_capacity_snapshot=lambda: CapacitySnapshot(0, 5, 5, 0, 20, 20),
    )
    parent._subagent_manager.spawn_child = subagents.spawn_child
    parent._spawn_child = subagents.spawn_child
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="You are a mock agent", tools=(_BASH,)))
    tool = create_delegate_task_tool(parent, list, catalog)
    calls = [
        {
            "name": "delegate_task_tool",
            "args": {"agent_type": "coder", "objective": objective, "wait": True},
            "id": f"call-{index}",
        }
        for index, objective in enumerate(objectives)
    ]
    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=calls), AIMessage(content="all done")])
    return create_agent(model=model, tools=[tool], checkpointer=InMemorySaver())


def _tool_outputs(state: dict[str, object]) -> dict[str, dict[str, object]]:
    outputs: dict[str, dict[str, object]] = {}
    for message in state["messages"]:  # type: ignore[attr-defined]
        if message.type == "tool":
            content = message.content
            outputs[message.tool_call_id] = (
                json.loads(content) if content.startswith('{"') else ast.literal_eval(content)
            )
    return outputs


def _requested_command(interrupt_: object) -> str:
    return str(interrupt_.value["tool_calls"][0]["args"]["command"])  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_finished_delegation_is_not_run_again_while_its_sibling_waits_for_approval() -> None:
    subagents = _Subagents({"alpha": 0, "beta": 1})
    agent = _agent(subagents, ["alpha", "beta"])

    paused = await agent.ainvoke({"messages": [("user", "go")]}, _CONFIG)  # type: ignore[attr-defined]
    done = await agent.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), _CONFIG)  # type: ignore[attr-defined]

    assert [_requested_command(i) for i in paused["__interrupt__"]] == ["beta-0"]
    outputs = _tool_outputs(done)
    assert {call_id: output["success"] for call_id, output in outputs.items()} == {"call-0": True, "call-1": True}
    assert (subagents.fresh_spawns("alpha"), subagents.resumes("alpha")) == (1, 0)
    assert (subagents.fresh_spawns("beta"), subagents.resumes("beta")) == (1, 1)


@pytest.mark.asyncio
async def test_parallel_delegations_each_receive_only_their_own_answers() -> None:
    subagents = _Subagents({"alpha": 2, "beta": 1})
    agent = _agent(subagents, ["alpha", "beta"])

    state = await agent.ainvoke({"messages": [("user", "go")]}, _CONFIG)  # type: ignore[attr-defined]
    while state.get("__interrupt__"):
        answers = {
            i.id: {"decisions": [{"type": "approve", "for": _requested_command(i)}]} for i in state["__interrupt__"]
        }
        state = await agent.ainvoke(Command(resume=answers), _CONFIG)  # type: ignore[attr-defined]

    assert {call_id: output["success"] for call_id, output in _tool_outputs(state).items()} == {
        "call-0": True,
        "call-1": True,
    }
    assert subagents.decisions == {
        "alpha": [
            {"decisions": [{"type": "approve", "for": "alpha-0"}]},
            {"decisions": [{"type": "approve", "for": "alpha-1"}]},
        ],
        "beta": [{"decisions": [{"type": "approve", "for": "beta-0"}]}],
    }
    assert [subagents.fresh_spawns(o) for o in ("alpha", "beta")] == [1, 1]


@pytest.mark.asyncio
async def test_the_same_delegation_twice_in_one_message_is_still_stopped() -> None:
    subagents = _Subagents({"alpha": 0})
    agent = _agent(subagents, ["alpha", "alpha"])

    state = await agent.ainvoke({"messages": [("user", "go")]}, _CONFIG)  # type: ignore[attr-defined]

    outputs = _tool_outputs(state)
    assert sorted(bool(output["success"]) for output in outputs.values()) == [False, True]
    assert "Safety interception" in str(next(o["error"] for o in outputs.values() if not o["success"]))
    assert subagents.fresh_spawns("alpha") == 1
