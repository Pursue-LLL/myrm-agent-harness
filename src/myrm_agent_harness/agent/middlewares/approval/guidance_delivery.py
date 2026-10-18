"""Deliver the human's note on an approval to the model, after the tool result.

[INPUT]
- langchain.agents.middleware::wrap_tool_call (POS: LangChain tool-call middleware hook)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: the call being dispatched)
- langchain_core.messages::HumanMessage (POS: the message the model reads as the user's)
- core.context_vars::current_tool_call_id_var, claim_approval_note (POS: per-call note hand-off)

[OUTPUT]
- approval_guidance_delivery: mid-chain hook that scopes the call id and appends the note

[POS]
A gate that a human answered (high-risk DOM action, privileged browser script, batch cost) reads
its answer through ``core.security.hitl_decision`` and stashes the note the human wrote with
``core.context_vars.stash_approval_note``. That note has to reach the model **after** the tool
result, or the provider request is malformed: an ``AIMessage`` with tool calls must be followed
immediately by the matching ``ToolMessage``. So the note cannot ride the resume payload — it is
appended here, once the tool has returned, as a trailing ``HumanMessage`` carrying
``additional_kwargs={"approval_guidance": True}`` (the same marker the approval middleware uses).

The hook also publishes the call id a tool body is running inside, because LangGraph runs the
body in a copied context: a gate can read the call it belongs to, but cannot rebind a ContextVar
in a way this hook would see.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.core.context_vars import (
    claim_approval_note,
    current_tool_call_id_var,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

MAX_NOTE_CHARS = 4000
"""How much of a person's note reaches the model. The approval box has no input limit, so a paste
could otherwise drop an unbounded block into every later request of the turn; the head of the note
is what carries the instruction, and the tail is dropped rather than summarized."""


def bounded_note(note: str) -> str:
    """A note shortened to `MAX_NOTE_CHARS`, marked with an ellipsis when it was longer."""
    return note if len(note) <= MAX_NOTE_CHARS else note[:MAX_NOTE_CHARS] + "\u2026"


def _guidance_message(tool_name: str, note: str) -> HumanMessage:
    """The trailing message that hands the human's note to the model."""
    return HumanMessage(
        content=f"[User Guidance during approval of {tool_name}]: {bounded_note(note)}",
        additional_kwargs={"approval_guidance": True},
    )


@wrap_tool_call
async def approval_guidance_delivery(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[object]]],
) -> ToolMessage | Command[object]:
    """Dispatch the tool, then append the note the human left on its approval, if any."""
    call_id = str(request.tool_call.get("id") or "")
    token = current_tool_call_id_var.set(call_id)
    try:
        result = await handler(request)
    finally:
        current_tool_call_id_var.reset(token)

    if not isinstance(result, ToolMessage):
        # A tool that answers with its own Command owns the message list; leaving the note in the store
        # keeps it from being consumed and silently dropped (the store is replaced at the next run).
        return result
    note = claim_approval_note(call_id) if call_id else ""
    if not note:
        return result

    tool_name = str(request.tool_call.get("name") or "unknown")
    logger.info("[APPROVAL] Tool %s: delivering the note given with its approval", tool_name)
    return Command(update={"messages": [result, _guidance_message(tool_name, note)]})
