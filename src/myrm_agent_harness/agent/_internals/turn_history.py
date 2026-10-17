"""Turn history — which conversation a turn starts from, and how the thread gets there.

[INPUT]
- langchain_core.messages::BaseMessage, ToolMessage (POS: thread message types)
- langgraph.checkpoint.base::BaseCheckpointSaver (POS: thread storage a ``replace`` turn clears)
- runtime.checkpointing.read_access::read_checkpoint_messages (POS: raw thread read that degrades to empty)
- runtime.context.session.session_continuity::HistoryMode (POS: the modes a caller can declare)

[OUTPUT]
- TurnHistory: the resolved mode, the thread messages a ``continue`` turn extends, and what a ``replace`` discarded
- resolve_turn_history(): read or clear the thread according to the declared mode
- resumed_turn_facts(): telemetry of a resume, which continues a paused thread without resolving history

[POS]
Single authority for the conversation of a turn. A caller that keeps its own record of the
conversation (the server's chat database) declares ``continue`` when the thread still mirrors that
record, so the model sees the thread as it was and only the new message is sent (an unchanged
prefix is what the provider prompt cache keys on). When the record and the thread diverged it
declares ``replace``: the thread is cleared and the caller's ``chat_history`` becomes the whole
conversation. A caller that declares nothing gets ``append``: ``chat_history`` is fed on top of
whatever the thread holds, the behavior of callers that have not taken over thread hygiene.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, ToolMessage

from myrm_agent_harness.runtime.checkpointing.read_access import read_checkpoint_messages
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from myrm_agent_harness.runtime.context.session.session_continuity import HistoryMode

logger = get_agent_logger(__name__)


@dataclass(frozen=True, slots=True)
class TurnHistory:
    """Resolved history source of one turn.

    ``mode`` is the effective mode: a requested ``continue`` over an empty thread resolves to
    ``replace`` because there is nothing to continue from.
    """

    mode: HistoryMode
    thread_messages: tuple[BaseMessage, ...] = ()
    discarded_messages: int = 0
    discarded_tool_messages: int = 0

    @property
    def feeds_history(self) -> bool:
        """Whether the caller's ``chat_history`` is turned into messages for this turn."""
        return self.mode != "continue"

    def telemetry(self) -> dict[str, int | str]:
        facts: dict[str, int | str] = {"history_mode": self.mode}
        if self.discarded_messages:
            facts["history_discarded_messages"] = self.discarded_messages
            facts["history_discarded_tool_messages"] = self.discarded_tool_messages
        return facts


def _requested_mode(requested: object) -> HistoryMode:
    if requested == "continue" or requested == "replace":
        return requested
    return "append"


def _thread_messages(raw: list[object]) -> tuple[BaseMessage, ...]:
    return tuple(message for message in raw if isinstance(message, BaseMessage))


async def resolve_turn_history(
    checkpointer: BaseCheckpointSaver[str] | None,
    thread_id: str,
    requested: object,
) -> TurnHistory:
    """Resolve the history source of a new-message turn (a resume never calls this).

    A ``replace`` that cannot clear the thread raises: running on top of the stale thread would
    silently double the history the caller just rebuilt.
    """
    mode = _requested_mode(requested)
    if mode == "append":
        return TurnHistory(mode="append")

    existing = _thread_messages(await read_checkpoint_messages(checkpointer, thread_id))
    if mode == "continue":
        if existing:
            return TurnHistory(mode="continue", thread_messages=existing)
        return TurnHistory(mode="replace")

    if checkpointer is not None:
        try:
            await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.error("Failed to clear thread %s for a history replace", thread_id, exc_info=True)
            raise
    discarded_tools = sum(1 for message in existing if isinstance(message, ToolMessage))
    return TurnHistory(
        mode="replace",
        discarded_messages=len(existing),
        discarded_tool_messages=discarded_tools,
    )


def resumed_turn_facts() -> dict[str, int | str]:
    """Telemetry of a resume turn: it continues the thread it paused on, so no history is resolved."""
    return {"history_mode": "resume"}


__all__ = [
    "TurnHistory",
    "resolve_turn_history",
    "resumed_turn_facts",
]
