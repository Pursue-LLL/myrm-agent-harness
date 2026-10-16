"""Resume addressing — binds an answer to the interrupt it was given for

[INPUT]
- agent.streaming.interrupt_events::INTERRUPT_ID_KEY (POS: 流事件与 resume 载荷共用的中断 id 键)

[OUTPUT]
- address_resume: pure rule that turns a resume command into one LangGraph resolves per interrupt id
- address_resume_to_pending: reads the thread's pending interrupts and applies ``address_resume``

[POS]
LangGraph answers whichever interrupt is pending when a resume carries no id, and refuses an unaddressed resume
while several interrupts are pending. Both hurt a chat whose parallel tool calls each ask for approval, and an old
card answered after its interrupt was already settled would land on the next approval the user never saw.

The client echoes the id its card arrived with (``interruptId``); this module turns that into
``Command(resume={interrupt_id: answer})``. LangGraph ignores an id that is no longer pending, so a stale answer
changes nothing and the run pauses again at what is really pending.

A resume without an id is left untouched while at most one interrupt is pending, so every existing caller (IM
replies, voice, timers) behaves exactly as before. With several pending, only a global rejection (the timeout timer's
``{"decision": "reject"}``) is broadcast to all of them: refusing is safe to repeat, approving is never applied to an
interrupt the user did not individually answer. Any other unaddressed answer reaches LangGraph unchanged and is refused
there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.interrupt_events import INTERRUPT_ID_KEY
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


def address_resume(command: Command[object], pending_ids: Sequence[str]) -> Command[object]:
    """``command`` rewritten so that LangGraph resolves it per interrupt id; unchanged when nothing needs addressing."""
    answer = command.resume
    if isinstance(answer, dict) and isinstance(answer.get(INTERRUPT_ID_KEY), str):
        target = str(answer[INTERRUPT_ID_KEY])
        if target not in pending_ids:
            logger.warning(
                "Resume addressed to interrupt %s which is not pending (pending=%s)", target, list(pending_ids)
            )
        content = {key: value for key, value in answer.items() if key != INTERRUPT_ID_KEY}
        return replace(command, resume={target: content})
    if len(pending_ids) > 1 and _is_global_rejection(answer):
        logger.warning("Rejecting all %d pending interrupts with one global rejection", len(pending_ids))
        return replace(command, resume=dict.fromkeys(pending_ids, answer))
    return command


async def address_resume_to_pending(
    agent_graph: object | None,
    command: Command[object],
    thread_id: str,
) -> Command[object]:
    """``address_resume`` against the interrupts pending on ``thread_id``; unchanged when the thread cannot be read."""
    aget_state = getattr(agent_graph, "aget_state", None)
    if aget_state is None:
        return command
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await aget_state(config)
    except (AttributeError, KeyError, LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Failed to read pending interrupts before resume (thread=%s): %s", thread_id, exc)
        return command
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    pending_ids = [
        interrupt_id for interrupt in interrupts if isinstance(interrupt_id := getattr(interrupt, "id", None), str)
    ]
    return address_resume(command, pending_ids)


def _is_global_rejection(answer: object) -> bool:
    """The one-decision answer shape (``decision`` without ``decisions``) carrying a rejection."""
    return isinstance(answer, dict) and answer.get("decision") == "reject" and "decisions" not in answer
