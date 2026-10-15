"""LangGraph resume semantics the approval timeout scheduler's ``reopen`` relies on.

A timer that fires claims its key, then resumes the suspended graph. When that run dies the claim is given back so a
manual reply is not refused, and what that reply can still do is decided by LangGraph, not by the scheduler. These
tests pin that behavior against a real compiled graph with a checkpointer (no mocks) so an upgrade that changes it
fails here instead of in production.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

_CONFIG: RunnableConfig = {"configurable": {"thread_id": "approval-thread"}}
_PAUSE = {"question": "approve?"}


class _State(TypedDict):
    decision: str
    log: Annotated[list[str], operator.add]


_Graph = CompiledStateGraph[_State, None, _State, _State]


@dataclass
class _Faults:
    """Which node raises on its next run, standing in for a provider error or a tool crash."""

    work: bool = False
    ask_after_interrupt: bool = False


def _build_graph(faults: _Faults) -> _Graph:
    """``ask`` pauses for a decision (the approval middleware's node); ``work`` is every later node."""

    async def ask(state: _State) -> dict[str, str]:
        answer = interrupt(_PAUSE)
        if faults.ask_after_interrupt:
            faults.ask_after_interrupt = False
            raise RuntimeError("ask failed after its interrupt was answered")
        return {"decision": answer["decision"]}

    async def work(state: _State) -> dict[str, list[str]]:
        if faults.work:
            raise RuntimeError("work failed")
        return {"log": [f"worked:{state['decision']}"]}

    builder = StateGraph(_State)
    builder.add_node("ask", ask)
    builder.add_node("work", work)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", "work")
    builder.add_edge("work", END)
    return builder.compile(checkpointer=InMemorySaver())


async def _pause_at_interrupt(graph: _Graph) -> None:
    result = await graph.ainvoke({"decision": "", "log": []}, _CONFIG)
    assert "__interrupt__" in result


@pytest.mark.asyncio
async def test_failure_after_the_interrupt_was_answered_retries_the_failed_node_with_the_recorded_decision() -> None:
    """A later node failing leaves no interrupt pending: the manual reply retries, it cannot overturn the auto decision."""
    faults = _Faults(work=True)
    graph = _build_graph(faults)
    await _pause_at_interrupt(graph)

    with pytest.raises(RuntimeError, match="work failed"):
        await graph.ainvoke(Command(resume={"decision": "reject"}), _CONFIG)

    snapshot = await graph.aget_state(_CONFIG)
    assert snapshot.next == ("work",)
    assert snapshot.values["decision"] == "reject"
    assert all(not task.interrupts for task in snapshot.tasks)

    faults.work = False
    result = await graph.ainvoke(Command(resume={"decision": "approve"}), _CONFIG)

    assert result["log"] == ["worked:reject"]


@pytest.mark.asyncio
async def test_failure_inside_the_interrupting_node_keeps_the_interrupt_pending_and_replays_the_first_answer() -> None:
    """The node that asked fails after the answer: the question stays pending and the first answer is replayed."""
    faults = _Faults(ask_after_interrupt=True)
    graph = _build_graph(faults)
    await _pause_at_interrupt(graph)

    with pytest.raises(RuntimeError, match="ask failed"):
        await graph.ainvoke(Command(resume={"decision": "reject"}), _CONFIG)

    snapshot = await graph.aget_state(_CONFIG)
    assert snapshot.next == ("ask",)
    assert [task.interrupts[0].value for task in snapshot.tasks if task.interrupts] == [_PAUSE]

    result = await graph.ainvoke(Command(resume={"decision": "approve"}), _CONFIG)

    assert result["decision"] == "reject"
    assert result["log"] == ["worked:reject"]


@pytest.mark.asyncio
async def test_resume_on_a_finished_thread_changes_nothing() -> None:
    """A reopened key lets a late reply through to a thread that already finished: that must be a no-op."""
    graph = _build_graph(_Faults())
    await _pause_at_interrupt(graph)
    finished = await graph.ainvoke(Command(resume={"decision": "reject"}), _CONFIG)

    late = await graph.ainvoke(Command(resume={"decision": "approve"}), _CONFIG)

    assert late == finished
    assert finished["log"] == ["worked:reject"]
