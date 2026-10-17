"""A task that pauses several times in a row announces every pause under its own card id.

The tool below calls ``interrupt()`` three times in one body, exactly like a delegation that asks for approval before
each of its steps. LangGraph names all three pauses with one interrupt id (it names the task), so the card id must carry
the round. The graph is the production builder (langchain ``create_agent``) on the production SQLite checkpointer, and
every run is announced through the same ``interrupt_events`` / ``announced_rounds`` pair the stream dispatcher uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.types import Command, interrupt

from myrm_agent_harness.agent._internals.resume_addressing import address_resume_to_pending
from myrm_agent_harness.agent.streaming.interrupt_events import INTERRUPT_ID_KEY, interrupt_events
from myrm_agent_harness.agent.streaming.interrupt_identity import announced_rounds
from myrm_agent_harness.runtime.checkpointing.factory import create_checkpointer

_THREAD = "chat"
_CONFIG = {"configurable": {"thread_id": _THREAD}}
_ROUNDS = 3


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        return self


@tool
async def walk(topic: str) -> str:
    """Ask the user three times before finishing."""
    answers = [interrupt({"topic": topic, "step": step})["answer"] for step in range(_ROUNDS)]
    return f"{topic}:{'+'.join(answers)}"


@pytest_asyncio.fixture
async def saver(tmp_path: Path) -> AsyncIterator[object]:
    checkpointer, cleanup = await create_checkpointer("sqlite", str(tmp_path / "checkpoints.db"))
    yield checkpointer
    await cleanup()


def _agent(saver: object, topics: tuple[str, ...]) -> object:
    calls = [{"name": "walk", "args": {"topic": topic}, "id": f"call-{topic}"} for topic in topics]
    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=calls), AIMessage(content="all done")])
    return create_agent(model=model, tools=[walk], checkpointer=saver)


async def _run(agent: object, agent_input: object) -> dict[str, str]:
    """Run to the next pause and return the card id announced per topic, as the stream dispatcher stamps it."""
    cards: dict[str, str] = {}
    async for chunk in agent.astream(agent_input, _CONFIG, stream_mode="updates"):  # type: ignore[attr-defined]
        if "__interrupt__" in chunk:
            for event in interrupt_events(chunk["__interrupt__"], "msg-1", announced_rounds(agent_input)):
                cards[event["data"]["topic"]] = event[INTERRUPT_ID_KEY]  # type: ignore[index]
    return cards


async def _answer(agent: object, card_id: str, answer: str) -> dict[str, str]:
    reply = Command[object](resume={"answer": answer, INTERRUPT_ID_KEY: card_id})
    return await _run(agent, await address_resume_to_pending(agent, reply, _THREAD))


async def _tool_outputs(agent: object) -> dict[str, str]:
    snapshot = await agent.aget_state(_CONFIG)  # type: ignore[attr-defined]
    return {m.tool_call_id: m.content for m in snapshot.values["messages"] if getattr(m, "type", "") == "tool"}


def _rounds(cards: dict[str, str]) -> dict[str, int]:
    return {topic: int(card_id.rsplit(".", 1)[1]) for topic, card_id in cards.items()}


@pytest.mark.asyncio
async def test_every_pause_of_one_task_has_its_own_card_id(saver: object) -> None:
    agent = _agent(saver, ("alpha",))
    seen = [(await _run(agent, {"messages": [("user", "go")]}))["alpha"]]

    seen.append((await _answer(agent, seen[-1], "a0"))["alpha"])
    seen.append((await _answer(agent, seen[-1], "a1"))["alpha"])
    assert await _answer(agent, seen[-1], "a2") == {}

    assert len(set(seen)) == _ROUNDS
    assert {card_id.split(".")[0] for card_id in seen} == {seen[0].split(".")[0]}
    assert [card_id.split(".")[1] for card_id in seen] == ["0", "1", "2"]
    assert await _tool_outputs(agent) == {"call-alpha": "alpha:a0+a1+a2"}


@pytest.mark.asyncio
async def test_a_card_answered_earlier_cannot_answer_the_next_pause(saver: object) -> None:
    agent = _agent(saver, ("alpha",))
    first = (await _run(agent, {"messages": [("user", "go")]}))["alpha"]
    second = (await _answer(agent, first, "a0"))["alpha"]

    assert await _answer(agent, first, "late click on the first card") == {"alpha": second}

    third = (await _answer(agent, second, "a1"))["alpha"]
    assert await _answer(agent, third, "a2") == {}
    assert await _tool_outputs(agent) == {"call-alpha": "alpha:a0+a1+a2"}


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda card: "abc", id="not-an-id"),
        pytest.param(lambda card: card.split(".")[0], id="bare-langgraph-id"),
        pytest.param(lambda card: card.split(".")[0] + ".x", id="round-not-a-number"),
        pytest.param(lambda card: card.split(".")[0] + ".01", id="round-not-canonical"),
        pytest.param(lambda card: card.split(".")[0] + ".7", id="round-not-reached"),
        pytest.param(lambda card: "0" * 32 + ".0", id="interrupt-not-pending"),
    ],
)
@pytest.mark.asyncio
async def test_an_answer_without_a_valid_card_id_is_delivered_to_nobody(
    saver: object, tamper: Callable[[str], str]
) -> None:
    agent = _agent(saver, ("alpha",))
    first = (await _run(agent, {"messages": [("user", "go")]}))["alpha"]

    assert await _answer(agent, tamper(first), "must not be delivered") == {"alpha": first}

    second = (await _answer(agent, first, "a0"))["alpha"]
    third = (await _answer(agent, second, "a1"))["alpha"]
    assert await _answer(agent, third, "a2") == {}
    assert await _tool_outputs(agent) == {"call-alpha": "alpha:a0+a1+a2"}


@pytest.mark.asyncio
async def test_parallel_tasks_advance_their_rounds_independently(saver: object) -> None:
    agent = _agent(saver, ("alpha", "beta"))
    cards = await _run(agent, {"messages": [("user", "go")]})
    assert _rounds(cards) == {"alpha": 0, "beta": 0}

    after_alpha = await _answer(agent, cards["alpha"], "a0")
    assert _rounds(after_alpha) == {"alpha": 1, "beta": 0}
    assert after_alpha["beta"] == cards["beta"]

    after_beta = await _answer(agent, after_alpha["beta"], "b0")
    assert _rounds(after_beta) == {"alpha": 1, "beta": 1}
    assert after_beta["alpha"] == after_alpha["alpha"]


@pytest.mark.asyncio
async def test_rounds_do_not_depend_on_how_fast_the_checkpoint_is_written(saver: object) -> None:
    """A slow disk lags the writes of the pause being announced; the card ids must not notice."""
    write = saver.aput_writes  # type: ignore[attr-defined]

    async def slow_write(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(0.05)
        return await write(*args, **kwargs)

    saver.aput_writes = slow_write  # type: ignore[attr-defined]
    agent = _agent(saver, ("alpha", "beta"))
    cards = await _run(agent, {"messages": [("user", "go")]})

    for round_ in (1, 2):
        cards = {**cards, **await _answer(agent, cards["alpha"], f"a{round_ - 1}")}
        assert _rounds(cards) == {"alpha": round_, "beta": 0}
