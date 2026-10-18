"""The note a human writes on an approval reaches the model, after the tool result.

End-to-end through the real middleware chain (``build_middlewares``) on langchain's real
``create_agent``: a gated tool pauses on ``interrupt``, the harness's own
``core.security.hitl_decision`` reads the answer, the gate stashes the note it found with
``core.context_vars.stash_approval_note``, and ``approval_guidance_delivery`` appends it as a
trailing ``HumanMessage`` once the tool has returned.

Ordering is the load-bearing assertion: an ``AIMessage`` carrying tool calls must be followed
immediately by the matching ``ToolMessage``, so the note goes **after** the result — exactly what
the resume payload cannot do.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from myrm_agent_harness.agent._internals._agent_build import build_middlewares
from myrm_agent_harness.agent._internals._agent_helpers import reset_all_guards
from myrm_agent_harness.core.context_vars import stash_approval_note
from myrm_agent_harness.core.security.hitl_decision import approval_guidance, is_approved

GATED_TOOL = "gated_dom_click_tool"


@tool(GATED_TOOL)  # type: ignore[misc]
def gated_dom_click(action: str) -> str:
    """A high-risk DOM action (stands in for browser_interact_tool's guarded click)."""
    answer = interrupt({"action_type": "high_risk_dom_action", "reason": action})
    if is_approved(answer):
        # What every standalone gate does on the approve path.
        stash_approval_note(approval_guidance(answer))
        return "clicked"
    return "rejected"


class _ScriptedModel(BaseChatModel):
    """Returns scripted assistant turns; supports ``bind_tools`` so ``create_agent`` accepts it."""

    script: list[AIMessage]
    index: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> _ScriptedModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def _shape(messages: Sequence[object]) -> list[str]:
    """The message-order signature an LLM provider would accept or reject."""
    out: list[str] = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            out.append("AI(calls)")
        elif isinstance(message, ToolMessage):
            out.append("TOOL")
        elif isinstance(message, HumanMessage):
            out.append("HUMAN(guidance)" if message.additional_kwargs.get("approval_guidance") else "HUMAN")
        else:
            out.append(type(message).__name__)
    return out


def _ordering_valid(shape: Sequence[str]) -> bool:
    """Every ``AI(calls)`` is followed immediately by its tool result."""
    return all(shape[i + 1] == "TOOL" for i in range(len(shape) - 1) if shape[i] == "AI(calls)")


def _build_agent(script: list[AIMessage]):
    # The real chain: whatever build_middlewares returns is what an agent runs with.
    middlewares = build_middlewares(create_registry_for_test(), [])
    return create_agent(
        model=_ScriptedModel(script=script),
        tools=[gated_dom_click],
        middleware=middlewares,  # type: ignore[arg-type]
        checkpointer=InMemorySaver(),
    )


def create_registry_for_test():
    from myrm_agent_harness.agent._internals._agent_build import create_registry

    return create_registry()


@pytest.fixture(autouse=True)
def _fresh_run() -> None:
    """Each test starts the run the way a real run starts: guards reset, note store opened."""
    reset_all_guards()


async def _run_to_pause(agent: object, config: dict[str, object]) -> None:
    async for _ in agent.astream(  # type: ignore[attr-defined]
        {"messages": [HumanMessage("publish the promo")]}, config
    ):
        pass


async def _answer_the_middleware_ask(agent: object, config: dict[str, object], *, count: int = 1) -> None:
    """Approve the batch ask the approval middleware raises before the tool body runs.

    A browser tool is ASK-governed, so the middleware pauses first; the in-tool gate (the pause
    that carries the human's note) is the one after it. The batch ask answers every requested call
    in one command, so a two-call turn needs two decisions.
    """
    snapshot = await agent.aget_state(config)  # type: ignore[attr-defined]
    if not snapshot.interrupts:
        return
    assert snapshot.interrupts[0].value.get("actionType") is None
    async for _ in agent.astream(  # type: ignore[attr-defined]
        Command(resume={"decisions": [{"type": "approve"}] * count}), config
    ):
        pass


def _config() -> dict[str, object]:
    return {"configurable": {"thread_id": "guidance-delivery"}}


@pytest.mark.asyncio
async def test_the_hook_passes_a_result_through_untouched_when_no_note_was_left() -> None:
    """Called directly: no note means the tool result is returned exactly as it came."""
    from langgraph.types import Command as _Command

    from myrm_agent_harness.agent.middlewares.approval.guidance_delivery import (
        approval_guidance_delivery,
    )
    from myrm_agent_harness.core.context_vars import publish_approval_notes

    publish_approval_notes()
    tool_message = ToolMessage(content="clicked", tool_call_id="c9", name=GATED_TOOL)

    async def handler(request: object) -> ToolMessage:
        return tool_message

    request = type("R", (), {"tool_call": {"id": "c9", "name": GATED_TOOL}})()
    result = await approval_guidance_delivery.awrap_tool_call(request, handler)

    assert result is tool_message
    assert not isinstance(result, _Command)


@pytest.mark.asyncio
async def test_the_hook_leaves_the_note_for_a_tool_that_answers_with_its_own_command() -> None:
    """A tool owning the message list must not have the note consumed against it."""
    from langgraph.types import Command as _Command

    from myrm_agent_harness.agent.middlewares.approval.guidance_delivery import (
        approval_guidance_delivery,
    )
    from myrm_agent_harness.core.context_vars import (
        claim_approval_note,
        current_tool_call_id_var,
        publish_approval_notes,
        stash_approval_note,
    )

    publish_approval_notes()
    token = current_tool_call_id_var.set("c10")
    stash_approval_note("kept for later")
    current_tool_call_id_var.reset(token)

    owned = _Command(update={"messages": []})

    async def handler(request: object) -> _Command[object]:
        return owned

    request = type("R", (), {"tool_call": {"id": "c10", "name": GATED_TOOL}})()
    result = await approval_guidance_delivery.awrap_tool_call(request, handler)

    assert result is owned
    assert claim_approval_note("c10") == "kept for later", "the note must not be consumed"


def test_claiming_a_note_without_a_published_store_is_empty() -> None:
    """A run that never published degrades to the old behaviour instead of raising."""
    from myrm_agent_harness.core.context_vars import approval_notes_var, claim_approval_note

    approval_notes_var.set(None)
    assert claim_approval_note("c11") == ""


@pytest.mark.asyncio
async def test_a_note_too_long_to_be_an_instruction_is_bounded() -> None:
    """The approval box has no input limit; a paste must not become an unbounded request block."""
    from myrm_agent_harness.agent.middlewares.approval.guidance_delivery import MAX_NOTE_CHARS

    agent = _build_agent(
        [
            AIMessage(content="", tool_calls=[{"name": GATED_TOOL, "args": {"action": "publish"}, "id": "c1"}]),
            AIMessage(content="done"),
        ]
    )
    config = _config()
    await _run_to_pause(agent, config)
    await _answer_the_middleware_ask(agent, config)

    oversized = "a" * (MAX_NOTE_CHARS + 500)
    async for _ in agent.astream(
        Command(resume={"decision": "approve", "guidance": oversized}),
        config,
    ):
        pass

    snapshot = await agent.aget_state(config)
    notes = [
        str(m.content) for m in snapshot.values["messages"] if m.additional_kwargs.get("approval_guidance") is True
    ]
    assert len(notes) == 1
    assert len(notes[0]) <= MAX_NOTE_CHARS + 100, "the note must be bounded before it reaches the model"
    assert notes[0].endswith("\u2026"), "a shortened note says so"


@pytest.mark.asyncio
async def test_the_note_reaches_the_model_after_the_result() -> None:
    agent = _build_agent(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": GATED_TOOL, "args": {"action": "publish"}, "id": "c1"}],
            ),
            AIMessage(content="done"),
        ]
    )
    config = _config()
    await _run_to_pause(agent, config)
    await _answer_the_middleware_ask(agent, config)

    # The in-tool gate is the pause that carries the human's note.
    snapshot = await agent.aget_state(config)
    assert snapshot.interrupts, "the gated tool must pause for approval"
    assert snapshot.interrupts[0].value.get("action_type") == "high_risk_dom_action"

    async for _ in agent.astream(
        Command(resume={"decision": "approve", "guidance": "only staging, not prod"}),
        config,
    ):
        pass

    snapshot = await agent.aget_state(config)
    shape = _shape(snapshot.values["messages"])
    texts = [str(m.content) for m in snapshot.values["messages"]]

    assert _ordering_valid(shape), f"a tool result must follow its call immediately: {shape}"
    assert any("only staging, not prod" in text for text in texts), "the note must reach the model"
    guidance_at = shape.index("HUMAN(guidance)")
    assert guidance_at > shape.index("TOOL"), "the note is appended after the tool result, not before it"


@pytest.mark.asyncio
async def test_an_approval_without_a_note_injects_nothing() -> None:
    """A plain approve is byte-for-byte what it was before this feature existed."""
    agent = _build_agent(
        [
            AIMessage(content="", tool_calls=[{"name": GATED_TOOL, "args": {"action": "publish"}, "id": "c1"}]),
            AIMessage(content="done"),
        ]
    )
    config = _config()
    await _run_to_pause(agent, config)
    await _answer_the_middleware_ask(agent, config)

    async for _ in agent.astream(Command(resume={"decision": "approve"}), config):
        pass

    snapshot = await agent.aget_state(config)
    assert "HUMAN(guidance)" not in _shape(snapshot.values["messages"])


@pytest.mark.asyncio
async def test_a_rejection_note_is_not_delivered_as_approval_guidance() -> None:
    """On a rejection the person's words belong on the tool error, not in a guidance message."""
    agent = _build_agent(
        [
            AIMessage(content="", tool_calls=[{"name": GATED_TOOL, "args": {"action": "publish"}, "id": "c1"}]),
            AIMessage(content="done"),
        ]
    )
    config = _config()
    await _run_to_pause(agent, config)
    await _answer_the_middleware_ask(agent, config)

    async for _ in agent.astream(
        Command(resume={"decision": "reject", "feedback": "too risky"}),
        config,
    ):
        pass

    snapshot = await agent.aget_state(config)
    assert "HUMAN(guidance)" not in _shape(snapshot.values["messages"])


@pytest.mark.asyncio
async def test_two_parallel_approvals_each_deliver_their_own_note() -> None:
    """Two pauses of the same gated tool must not swap notes."""
    agent = _build_agent(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": GATED_TOOL, "args": {"action": "publish"}, "id": "c1"},
                    {"name": GATED_TOOL, "args": {"action": "archive"}, "id": "c2"},
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    config = _config()
    await _run_to_pause(agent, config)
    await _answer_the_middleware_ask(agent, config, count=2)

    # Answer each pending pause by its own id: after one is answered the graph re-parks on the
    # other, and `interrupts[0]` keeps the id of the one still waiting, so track what was answered.
    answered: set[str] = set()
    for note in ("note-for-publish", "note-for-archive"):
        snapshot = await agent.aget_state(config)
        pending = [i for i in snapshot.interrupts if i.id not in answered]
        assert pending, "each pause is answered in turn"
        interrupt_id = pending[0].id
        answered.add(interrupt_id)
        async for _ in agent.astream(
            Command(resume={interrupt_id: {"decision": "approve", "guidance": note}}),
            config,
        ):
            pass

    snapshot = await agent.aget_state(config)
    shape = _shape(snapshot.values["messages"])
    texts = [str(m.content) for m in snapshot.values["messages"]]
    notes = [text for text in texts if "User Guidance during approval of" in text]

    assert _ordering_valid(shape), f"ordering must stay valid: {shape}"
    assert sum("note-for-publish" in note for note in notes) == 1
    assert sum("note-for-archive" in note for note in notes) == 1
