"""Tests for conversation search format output."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.conversation_search.format_output import (
    format_conversation_hit,
)
from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    ConversationSearchHit,
)


def test_format_conversation_hit_includes_message_id() -> None:
    hit = ConversationSearchHit(
        conversation_id="chat-1",
        title="Planning session",
        snippet="Discussed Redis caching.",
        score=0.82,
        message_id="msg-42",
    )

    block = format_conversation_hit(1, hit)

    assert "message_id: msg-42" in block
    assert "conversation_id: chat-1" in block
    assert "Discussed Redis caching." in block
