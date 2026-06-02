"""Conversation chunking strategies for verbatim storage.

Implements exchange-pair chunking (MemPalace strategy) and other modes.

[INPUT]
- datetime (POS: Standard library utilities)

[OUTPUT]
- ChunkingStrategy: Enum for chunking modes (EXCHANGE_PAIR/USER_ONLY/SESSION)
- ConversationChunk: Chunked conversation unit with metadata
- chunk_conversation(): Split messages into semantic chunks

[POS]
Chunking utilities for ConversationMemory. Provides configurable strategies
for splitting conversations into semantic units while preserving completeness.
Default strategy is EXCHANGE_PAIR: [(User Q1 + AI A1), (User Q2 + AI A2), ...]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class ChunkingStrategy(StrEnum):
    """Chunking strategy for conversation memory."""

    EXCHANGE_PAIR = "exchange_pair"
    USER_ONLY = "user_only"
    SESSION = "session"


@dataclass
class ConversationChunk:
    """A semantic unit of conversation."""

    raw_text: str
    user_turn: str
    ai_turn: str | None
    timestamp: datetime
    entities: list[str] | None = None
    chunk_index: int = 0


def chunk_conversation(
    messages: list[dict[str, str]], strategy: ChunkingStrategy = ChunkingStrategy.EXCHANGE_PAIR
) -> list[ConversationChunk]:
    """Chunk conversation based on strategy.

    Args:
        messages: List of dicts with 'role' and 'content' keys
        strategy: Chunking strategy to use

    Returns:
        List of conversation chunks

    Strategies:
        EXCHANGE_PAIR: User turn + subsequent AI response = 1 chunk (MemPalace)
        USER_ONLY: Each user turn = 1 chunk
        SESSION: Entire session = 1 chunk
    """
    if not messages:
        return []

    if strategy == ChunkingStrategy.EXCHANGE_PAIR:
        return _chunk_by_exchange_pair(messages)
    elif strategy == ChunkingStrategy.USER_ONLY:
        return _chunk_by_user_turn(messages)
    elif strategy == ChunkingStrategy.SESSION:
        return _chunk_by_session(messages)
    else:
        return _chunk_by_exchange_pair(messages)


def _chunk_by_exchange_pair(messages: list[dict[str, str]]) -> list[ConversationChunk]:
    """One user turn + subsequent AI response = one chunk (MemPalace strategy).

    Preserves semantic completeness of Q+A pairs.
    """
    chunks: list[ConversationChunk] = []
    i = 0
    chunk_idx = 0

    while i < len(messages):
        msg = messages[i]

        if msg.get("role") == "user":
            user_turn = msg.get("content", "")
            ai_turn = None

            if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                ai_turn = messages[i + 1].get("content", "")
                i += 2
            else:
                i += 1

            raw_text = f"User: {user_turn}"
            if ai_turn:
                raw_text += f"\nAssistant: {ai_turn}"

            chunk = ConversationChunk(
                raw_text=raw_text,
                user_turn=user_turn,
                ai_turn=ai_turn,
                timestamp=datetime.now(UTC),
                chunk_index=chunk_idx,
            )
            chunks.append(chunk)
            chunk_idx += 1
        else:
            i += 1

    return chunks


def _chunk_by_user_turn(messages: list[dict[str, str]]) -> list[ConversationChunk]:
    """Each user turn = one chunk (ultra-precision mode)."""
    chunks: list[ConversationChunk] = []
    chunk_idx = 0

    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            chunk = ConversationChunk(
                raw_text=f"User: {content}",
                user_turn=content,
                ai_turn=None,
                timestamp=datetime.now(UTC),
                chunk_index=chunk_idx,
            )
            chunks.append(chunk)
            chunk_idx += 1

    return chunks


def _chunk_by_session(messages: list[dict[str, str]]) -> list[ConversationChunk]:
    """Entire session = one chunk (context-rich mode for short sessions)."""
    if not messages:
        return []

    user_turns: list[str] = []
    ai_turns: list[str] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user":
            user_turns.append(f"User: {content}")
        elif role == "assistant":
            ai_turns.append(f"Assistant: {content}")

    raw_text = "\n".join(user_turns + ai_turns)
    user_text = "\n".join([t.replace("User: ", "") for t in user_turns])

    chunk = ConversationChunk(
        raw_text=raw_text,
        user_turn=user_text,
        ai_turn="\n".join([t.replace("Assistant: ", "") for t in ai_turns]) if ai_turns else None,
        timestamp=datetime.now(UTC),
        chunk_index=0,
    )

    return [chunk]
