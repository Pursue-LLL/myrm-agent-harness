"""Resume addressing — binds an answer to the pause it was given for

[INPUT]
- agent.streaming.interrupt_events::INTERRUPT_ID_KEY (POS: 流事件与 resume 载荷共用的卡片 id 键)
- agent.streaming.interrupt_identity::AddressedResume, decode_interrupt_id, is_interrupt_id (POS: 卡片 id = 中断 id + 轮次)

[OUTPUT]
- RESUME_CHANNEL: the LangGraph pending-write channel that lists the answers a task has consumed
- address_resume: pure rule that turns a resume command into one LangGraph resolves per interrupt id
- address_resume_to_pending: reads the thread's pending interrupts and rounds and applies ``address_resume``

[POS]
LangGraph answers whichever interrupt is pending when a resume carries no id, and refuses an unaddressed resume
while several interrupts are pending. Both hurt a chat whose parallel tool calls each ask for approval. Its interrupt id
also names only the task, so a task that pauses several times in a row would let an old card answer its next pause.

The client echoes the card id it arrived with (``interruptId``, ``<interrupt id>.<round>``). It is honoured only while
that exact pause is still pending: the interrupt is pending and its task has consumed exactly ``round`` answers. Then
the command becomes ``Command(resume={interrupt_id: answer})``. Any other id (settled, not reached yet, or not of the
``<interrupt id>.<round>`` shape) is rewritten to an interrupt id that nothing has, which LangGraph ignores: the answer
is delivered to nobody and the run pauses again at what is really pending, instead of the answer being mistaken for the
reply to another pause.

A resume without an id is left untouched while at most one interrupt is pending, so every existing caller (IM
replies, voice, timers) behaves exactly as before. With several pending, only a global rejection (the timeout timer's
``{"decision": "reject"}``) is broadcast to all of them: refusing is safe to repeat, approving is never applied to an
interrupt the user did not individually answer. Any other unaddressed answer reaches LangGraph unchanged and is refused
there.

The returned command is an ``AddressedResume``: it also carries the round every pending interrupt announces itself at
after this resume, which the stream dispatcher stamps on the cards of the run (see ``streaming/interrupt_identity.py``).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.interrupt_events import INTERRUPT_ID_KEY
from myrm_agent_harness.agent.streaming.interrupt_identity import (
    AddressedResume,
    decode_interrupt_id,
    is_interrupt_id,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

RESUME_CHANNEL = "__resume__"
# Well-formed, so LangGraph reads the resume as an id map; held by no interrupt, so LangGraph ignores it.
_NO_INTERRUPT_ID = "0" * 32


def address_resume(command: Command[object], pending_rounds: Mapping[str, int]) -> AddressedResume:
    """``command`` rewritten so that LangGraph resolves it per interrupt id.

    ``pending_rounds`` maps every pending interrupt id to the number of answers its task has consumed.
    """
    answer = command.resume
    resume: object
    answered: Collection[str]
    if isinstance(answer, dict) and isinstance(answer.get(INTERRUPT_ID_KEY), str):
        card = decode_interrupt_id(answer[INTERRUPT_ID_KEY])
        content = {key: value for key, value in answer.items() if key != INTERRUPT_ID_KEY}
        if card is not None and pending_rounds.get(card.interrupt_id) == card.round:
            resume, answered = {card.interrupt_id: content}, (card.interrupt_id,)
        else:
            logger.warning(
                "Ignoring an answer addressed to %.80r: that pause is not pending (pending=%s)",
                answer[INTERRUPT_ID_KEY],
                dict(pending_rounds),
            )
            resume, answered = {_NO_INTERRUPT_ID: content}, ()
    elif len(pending_rounds) > 1 and _is_global_rejection(answer):
        logger.warning("Rejecting all %d pending interrupts with one global rejection", len(pending_rounds))
        resume, answered = dict.fromkeys(pending_rounds, answer), tuple(pending_rounds)
    else:
        resume, answered = answer, _answered_by(answer, pending_rounds)
    return AddressedResume(
        graph=command.graph,
        update=command.update,
        resume=resume,
        goto=command.goto,
        announce_rounds={
            interrupt_id: round_ + (interrupt_id in answered) for interrupt_id, round_ in pending_rounds.items()
        },
    )


async def address_resume_to_pending(
    agent_graph: object | None,
    command: Command[object],
    thread_id: str,
) -> Command[object]:
    """``address_resume`` against the interrupts pending on ``thread_id``; unchanged when the thread cannot be read."""
    pending_rounds = await _pending_rounds(agent_graph, thread_id)
    return command if pending_rounds is None else address_resume(command, pending_rounds)


async def _pending_rounds(agent_graph: object | None, thread_id: str) -> dict[str, int] | None:
    """Pending interrupt id → answers its task has consumed; ``None`` when the thread cannot be read."""
    aget_state = getattr(agent_graph, "aget_state", None)
    aget_tuple = getattr(getattr(agent_graph, "checkpointer", None), "aget_tuple", None)
    if aget_state is None or aget_tuple is None:
        return None
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await aget_state(config)
        saved = await aget_tuple(config)
    except (AttributeError, KeyError, LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Failed to read pending interrupts before resume (thread=%s): %s", thread_id, exc)
        return None
    consumed = {
        task_id: len(answers)
        for task_id, channel, answers in getattr(saved, "pending_writes", None) or ()
        if channel == RESUME_CHANNEL and isinstance(answers, list)
    }
    task_of = {interrupt.id: task.id for task in getattr(snapshot, "tasks", ()) or () for interrupt in task.interrupts}
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    return {
        interrupt_id: consumed.get(task_of.get(interrupt_id, ""), 0)
        for interrupt in interrupts
        if isinstance(interrupt_id := getattr(interrupt, "id", None), str)
    }


def _answered_by(answer: object, pending_rounds: Mapping[str, int]) -> Collection[str]:
    """The pending interrupts LangGraph hands an untouched ``answer``, by its own rule for reading a resume value."""
    if answer is None:
        return ()
    if isinstance(answer, dict) and all(is_interrupt_id(key) for key in answer):
        return answer.keys() & pending_rounds.keys()
    return tuple(pending_rounds)


def _is_global_rejection(answer: object) -> bool:
    """The one-decision answer shape (``decision`` without ``decisions``) carrying a rejection."""
    return isinstance(answer, dict) and answer.get("decision") == "reject" and "decisions" not in answer
