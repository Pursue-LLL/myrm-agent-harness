"""Streamed answer text that honours the stream's restart contract.

[INPUT]
- myrm_agent_harness.core.events.types::AgentEventType (POS: event type vocabulary)

[OUTPUT]
- AnswerDraft: accumulates the ``message`` text of one run; a recovery that re-runs the in-flight segment
  drops only that segment
- is_answer_restart: whether an event announces that the in-flight segment will be streamed again

[POS]
The one consumer-side definition of the restart contract that ``StreamExecutor`` recoveries emit
(``restart`` on STATUS events, ``data.restart`` on MODEL_ESCALATED). A segment is the text since the last
``tool_start``: completed tool steps are checkpointed, so a recovery resumes after them and never re-sends the
text that preceded them. Consumers that build a final answer from ``process_stream`` events use this class
instead of re-deriving the rule.
"""

from __future__ import annotations

from collections.abc import Mapping

from myrm_agent_harness.core.events.types import AgentEventType


def is_answer_restart(event: Mapping[str, object]) -> bool:
    """Whether ``event`` announces that the in-flight answer segment will be streamed again."""
    if event.get("restart") is True:
        return True
    payload = event.get("data")
    return isinstance(payload, Mapping) and payload.get("restart") is True


class AnswerDraft:
    """The answer text streamed so far, minus any segment a recovery has superseded."""

    __slots__ = ("_chunks", "_segment_start")

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._segment_start = 0

    @property
    def text(self) -> str:
        return "".join(self._chunks)

    def __bool__(self) -> bool:
        return bool(self._chunks)

    def feed(self, event: Mapping[str, object]) -> bool:
        """Apply one stream event; return whether the draft text changed."""
        event_type = event.get("type")
        if event_type == AgentEventType.MESSAGE:
            data = event.get("data")
            if not isinstance(data, str) or not data:
                return False
            self._chunks.append(data)
            return True
        if event_type == AgentEventType.TOOL_START:
            self._segment_start = len(self._chunks)
            return False
        if is_answer_restart(event):
            return self.restart()
        return False

    def restart(self) -> bool:
        """Drop the in-flight segment; return whether anything was dropped."""
        if len(self._chunks) <= self._segment_start:
            return False
        del self._chunks[self._segment_start :]
        return True
