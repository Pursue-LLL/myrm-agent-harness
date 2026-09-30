"""Single-turn targeted historical refetching engine.

[INPUT]
- langchain_core.messages::BaseMessage (POS: Source message stream or persisted vault)
- turn_index: Target logical turn index to inspect

[OUTPUT]
- HistoricalTurnRefetchResult: Dataclass containing retrieved verbatim text or vault pointer
- refetch_historical_turn: Pure functional targeted single-turn refetcher
- RefetchHistoricalTurnInput: Pydantic schema for turn index parameter
- RefetchHistoricalTurnTool: LangChain BaseTool for on-demand historical turn retrieval
- create_refetch_historical_turn_tool: Factory function creating the tool bound to message history

[POS]
Harness framework layer context management. Allows the agent to pinpoint and
retrieve verbatim outputs from a specific historical turn on-demand without
permanently inflating the active conversational window.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr


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


class RefetchHistoricalTurnInput(BaseModel):
    """Input payload for refetching a historical logical turn."""

    turn_index: int = Field(
        ...,
        description="Zero-based logical turn index to inspect and retrieve verbatim messages or vault pointers from.",
        ge=0,
    )


class RefetchHistoricalTurnTool(BaseTool):
    """Tool enabling the agent to pinpoint and retrieve historical turns verbatim."""

    name: str = "refetch_historical_turn"
    description: str = (
        "Retrieve verbatim messages or a zero-copy vault pointer for a specific historical "
        "logical turn index. Use this tool when you need exact error traces, past code blocks, "
        "or full command outputs that were compacted into summary anchors."
    )
    args_schema: type[BaseModel] = RefetchHistoricalTurnInput

    _get_messages: Callable[[], Sequence[BaseMessage]] = PrivateAttr()
    _chat_id: str | None = PrivateAttr(default=None)
    _max_inline_chars: int = PrivateAttr(default=2048)

    def __init__(
        self,
        get_messages: Callable[[], Sequence[BaseMessage]],
        *,
        chat_id: str | None = None,
        max_inline_chars: int = 2048,
    ) -> None:
        super().__init__()
        self._get_messages = get_messages
        self._chat_id = chat_id
        self._max_inline_chars = max_inline_chars

    def _run(self, turn_index: int, **kwargs: object) -> str:
        messages = self._get_messages()
        result = refetch_historical_turn(
            messages,
            turn_index,
            max_inline_chars=self._max_inline_chars,
            chat_id=self._chat_id,
        )
        if result is None:
            max_valid = len(messages) - 1
            valid_range = f"[0, {max_valid}]" if max_valid >= 0 else "empty"
            return f"Historical turn #{turn_index} not found. Valid turn range is {valid_range}."
        return result.content

    async def _arun(self, turn_index: int, **kwargs: object) -> str:
        return self._run(turn_index, **kwargs)


def create_refetch_historical_turn_tool(
    get_messages: Callable[[], Sequence[BaseMessage]],
    *,
    chat_id: str | None = None,
    max_inline_chars: int = 2048,
) -> RefetchHistoricalTurnTool:
    """Create a LangChain BaseTool bound to conversation message history."""
    return RefetchHistoricalTurnTool(
        get_messages=get_messages,
        chat_id=chat_id,
        max_inline_chars=max_inline_chars,
    )
