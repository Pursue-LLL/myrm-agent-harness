"""Pre-compaction callback types for context management schemas.

[POS]
Pre-compaction callback types for context pipeline processors.
"""

from __future__ import annotations

from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import BaseMessage

@dataclass(frozen=True, slots=True)
class PreCompactInjection:
    """Result of a pre-compaction semantic memory recall."""

    message: BaseMessage
    recalled_ids: tuple[str, ...]
    token_estimate: int
    query: str
    compaction_tier: str


class ContextPreCompactCallback(Protocol):
    """Pre-compaction memory recall callback (dependency inversion).

    Invoked before Compress / SessionNotes / Summarize mutates the message list.
    Returns injection content to prepend into the protected compaction zone, or None to skip.
    """

    def __call__(
        self,
        *,
        messages: list[BaseMessage],
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> Coroutine[object, object, PreCompactInjection | None]: ...


PRE_COMPACT_MESSAGE_METADATA_KEY = "pre_compact_message"
PRE_COMPACT_INJECTION_METADATA_KEY = "pre_compact_injection"
