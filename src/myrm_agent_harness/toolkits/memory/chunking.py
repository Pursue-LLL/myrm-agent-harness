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
    EPISODES = "episodes"


@dataclass
class ConversationChunk:
    """A semantic unit of conversation."""

    raw_text: str
    user_turn: str
    ai_turn: str | None
    timestamp: datetime
    entities: list[str] | None = None
    chunk_index: int = 0


@dataclass
class ConversationEpisode:
    """A cohesive conversational episode preserving temporal and semantic context.

    Groups multiple interaction turns separated by idle time gaps or context budgets,
    with causal sliding overlap to maintain coreference across boundaries.
    """

    index: int
    messages: list[dict[str, str]]
    start_time: datetime | None = None
    end_time: datetime | None = None
    turn_count: int = 0
    estimated_chars: int = 0
    summary_hint: str | None = None


def _parse_message_timestamp(msg: dict[str, str | object]) -> datetime | None:
    """Extract and parse timestamp from message dictionary with wide format tolerance."""
    raw = msg.get("timestamp") or msg.get("created_at")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=UTC)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(raw, str):
        try:
            clean = raw.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(clean)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None
    return None


class EpisodesChunker:
    """Adaptive conversation chunker partitioning long dialogs into cohesive episodes.

    Features:
    1. Temporal idle gap detection (partitions when inactivity exceeds threshold).
    2. Atomic turn preservation (ensures User query and Assistant answer stay intact).
    3. Soft character budgeting (prevents single LLM prompt overflow without truncation).
    4. Causal sliding overlap (injects 1-2 previous turns to preserve cross-boundary context).
    5. Oversized message protection (splits massive code/log pastes into paragraph sub-chunks).
    """

    def __init__(
        self,
        *,
        idle_time_gap_minutes: float = 30.0,
        soft_max_chars: int = 16_000,
        overlap_turns: int = 1,
    ) -> None:
        self.idle_time_gap_minutes = max(1.0, float(idle_time_gap_minutes))
        self.soft_max_chars = max(1_000, int(soft_max_chars))
        self.overlap_turns = max(0, int(overlap_turns))

    def _split_oversized_message(self, msg: dict[str, str]) -> list[dict[str, str]]:
        """Split a gigantic single message (e.g. large log or diff) into paragraph-bounded units."""
        content = msg.get("content", "")
        role = msg.get("role", "user")
        if len(content) <= self.soft_max_chars:
            return [msg]

        paragraphs = content.split("\n\n")
        sub_messages: list[dict[str, str]] = []
        current_buf: list[str] = []
        current_len = 0

        for p in paragraphs:
            p_len = len(p)
            if current_len + p_len > self.soft_max_chars and current_buf:
                sub_messages.append({"role": role, "content": "\n\n".join(current_buf)})
                current_buf = [p]
                current_len = p_len
            else:
                current_buf.append(p)
                current_len += p_len + 2

        if current_buf:
            sub_messages.append({"role": role, "content": "\n\n".join(current_buf)})

        return sub_messages or [msg]

    def _group_into_turns(
        self, messages: list[dict[str, str]]
    ) -> list[tuple[list[dict[str, str]], datetime | None, datetime | None]]:
        """Group linear message stream into atomic user-assistant interaction turns."""
        turns: list[tuple[list[dict[str, str]], datetime | None, datetime | None]] = []
        current_turn: list[dict[str, str]] = []
        first_time: datetime | None = None
        last_time: datetime | None = None

        for raw_msg in messages:
            for msg in self._split_oversized_message(raw_msg):
                role = msg.get("role", "user")
                ts = _parse_message_timestamp(msg)
                if role == "user" and current_turn:
                    turns.append((current_turn, first_time, last_time))
                    current_turn = [msg]
                    first_time = ts
                    last_time = ts
                else:
                    current_turn.append(msg)
                    if first_time is None:
                        first_time = ts
                    if ts is not None:
                        last_time = ts

        if current_turn:
            turns.append((current_turn, first_time, last_time))

        return turns

    def split_into_episodes(
        self, messages: list[dict[str, str]]
    ) -> list[ConversationEpisode]:
        """Split conversation messages into structured episodes with causal sliding overlap."""
        if not messages:
            return []

        turns = self._group_into_turns(messages)
        if not turns:
            return []

        episodes_raw: list[list[tuple[list[dict[str, str]], datetime | None, datetime | None]]] = []
        current_bucket: list[tuple[list[dict[str, str]], datetime | None, datetime | None]] = []
        current_chars = 0
        prev_end_time: datetime | None = None

        for turn_msgs, t_start, t_end in turns:
            turn_chars = sum(len(m.get("content", "")) for m in turn_msgs)
            is_idle_gap = False
            if prev_end_time and t_start:
                gap_sec = (t_start - prev_end_time).total_seconds()
                if gap_sec >= self.idle_time_gap_minutes * 60:
                    is_idle_gap = True

            should_cut = current_bucket and (
                is_idle_gap or (current_chars + turn_chars > self.soft_max_chars)
            )

            if should_cut:
                episodes_raw.append(current_bucket)
                current_bucket = [(turn_msgs, t_start, t_end)]
                current_chars = turn_chars
            else:
                current_bucket.append((turn_msgs, t_start, t_end))
                current_chars += turn_chars

            if t_end:
                prev_end_time = t_end
            elif t_start:
                prev_end_time = t_start

        if current_bucket:
            episodes_raw.append(current_bucket)

        episodes: list[ConversationEpisode] = []
        for ep_idx, raw_bucket in enumerate(episodes_raw):
            final_msgs: list[dict[str, str]] = []
            if ep_idx > 0 and self.overlap_turns > 0:
                prev_bucket = episodes_raw[ep_idx - 1]
                overlap_slice = prev_bucket[-self.overlap_turns :]
                for o_turn, _, _ in overlap_slice:
                    for o_msg in o_turn:
                        final_msgs.append(dict(o_msg))

            bucket_start: datetime | None = None
            bucket_end: datetime | None = None
            for t_msgs, s_t, e_t in raw_bucket:
                final_msgs.extend(t_msgs)
                if bucket_start is None and s_t is not None:
                    bucket_start = s_t
                if e_t is not None:
                    bucket_end = e_t
                elif s_t is not None:
                    bucket_end = s_t

            total_chars = sum(len(m.get("content", "")) for m in final_msgs)
            turn_count = len(raw_bucket)
            episodes.append(
                ConversationEpisode(
                    index=ep_idx,
                    messages=final_msgs,
                    start_time=bucket_start,
                    end_time=bucket_end,
                    turn_count=turn_count,
                    estimated_chars=total_chars,
                    summary_hint=f"Episode {ep_idx + 1} ({turn_count} turns, {total_chars} chars)",
                )
            )

        return episodes


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
        EPISODES: Adaptive episodes chunking preserving causal overlap
    """
    if not messages:
        return []

    if strategy == ChunkingStrategy.EXCHANGE_PAIR:
        return _chunk_by_exchange_pair(messages)
    elif strategy == ChunkingStrategy.USER_ONLY:
        return _chunk_by_user_turn(messages)
    elif strategy == ChunkingStrategy.SESSION:
        return _chunk_by_session(messages)
    elif strategy == ChunkingStrategy.EPISODES:
        return _chunk_by_episodes(messages)
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


def _chunk_by_episodes(messages: list[dict[str, str]]) -> list[ConversationChunk]:
    """Chunk conversation using adaptive episodes strategy."""
    chunker = EpisodesChunker()
    episodes = chunker.split_into_episodes(messages)
    chunks: list[ConversationChunk] = []
    for ep in episodes:
        user_parts: list[str] = []
        ai_parts: list[str] = []
        for m in ep.messages:
            r = m.get("role", "user")
            c = m.get("content", "")
            if r == "user":
                user_parts.append(c)
            elif r == "assistant":
                ai_parts.append(c)

        raw = "\n".join(f"[{m.get('role', 'user').upper()}]: {m.get('content', '')}" for m in ep.messages)
        chunks.append(
            ConversationChunk(
                raw_text=raw,
                user_turn="\n\n".join(user_parts),
                ai_turn="\n\n".join(ai_parts) if ai_parts else None,
                timestamp=ep.start_time or datetime.now(UTC),
                chunk_index=ep.index,
            )
        )
    return chunks

