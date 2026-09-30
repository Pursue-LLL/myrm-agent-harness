"""Single-turn targeted historical refetching engine.

[INPUT]
- langchain_core.messages::BaseMessage (POS: Source message stream or persisted vault)
- turn_index: Target logical turn index to inspect

[OUTPUT]
- HistoricalTurnRefetchResult: Dataclass containing retrieved verbatim text or vault pointer
- refetch_historical_turn: Pure functional targeted single-turn refetcher

[POS]
Harness framework layer context management. Allows the agent to pinpoint and
retrieve verbatim outputs from a specific historical turn on-demand without
permanently inflating the active conversational window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


@dataclass(frozen=True, slots=True)
class HistoricalTurnRefetchResult:
    """Outcome of a single-turn targeted refetch operation."""

    turn_index: int
    content: str
    is_vault_pointer: bool
    char_count: int


def refetch_historical_turn(
    messages: Sequence[BaseMessage],
    turn_index: int,
    *,
    max_inline_chars: int = 2048,
    chat_id: str | None = None,
) -> HistoricalTurnRefetchResult | None:
    """Retrieve verbatim messages from a specific historical logical turn.

    If the content exceeds max_inline_chars, it formats a vault:// reference
    to prevent secondary context explosion in active turns.
    """
    if turn_index < 0 or turn_index >= len(messages):
        return None

    msg = messages[turn_index]
    raw_content = msg.content if isinstance(msg.content, str) else str(msg.content)
    char_len = len(raw_content)

    if char_len <= max_inline_chars:
        formatted = f"[Retrieved Historical Turn #{turn_index} ({msg.__class__.__name__})]\n{raw_content}"
        return HistoricalTurnRefetchResult(
            turn_index=turn_index,
            content=formatted,
            is_vault_pointer=False,
            char_count=char_len,
        )

    # Large payload: generate zero-copy vault pointer
    vault_uri = f"vault://{chat_id or 'default'}/turns/{turn_index}/transcript.log"
    truncated_head = raw_content[:512]
    truncated_tail = raw_content[-512:]
    pointer_text = (
        f"[Retrieved Historical Turn #{turn_index} - Large Payload Exceeded {max_inline_chars} chars]\n"
        f"Pointer: {vault_uri}\n"
        f"--- Snippet Head ---\n{truncated_head}\n\n"
        f"[... truncated {char_len - 1024} characters — full verbatim available in vault ...]\n\n"
        f"--- Snippet Tail ---\n{truncated_tail}"
    )
    return HistoricalTurnRefetchResult(
        turn_index=turn_index,
        content=pointer_text,
        is_vault_pointer=True,
        char_count=char_len,
    )
