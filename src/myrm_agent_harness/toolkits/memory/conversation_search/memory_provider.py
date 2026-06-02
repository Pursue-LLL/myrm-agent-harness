"""MemoryManager-backed provider for conversation recall.

[INPUT]
myrm_agent_harness.toolkits.memory.manager::MemoryManager (POS: unified memory manager and core facade)
myrm_agent_harness.toolkits.memory.types::ConversationMemory (POS: verbatim conversation memory schema)

[OUTPUT]
MemoryConversationSearchProvider: default Harness provider backed by MemoryManager conversation memories.

[POS]
Default conversation search provider for framework users. It reuses the existing MemoryManager and never
introduces product-specific database or deployment semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.conversation_search.types import (
    ConversationSearchHit,
    ConversationSearchRequest,
    ConversationSearchResponse,
    ConversationSearchSource,
    ConversationSourceRef,
)
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager


class MemoryConversationSearchProvider:
    """Search ConversationMemory records through a MemoryManager."""

    def __init__(self, manager: MemoryManager, *, current_conversation_id: str | None = None) -> None:
        self._manager = manager
        self._current_conversation_id = current_conversation_id

    async def search(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
        query = request.query.strip()
        if request.mode == "recent" or not query:
            return await self._recent(request)

        results = await self._manager.search(
            query,
            memory_types=[MemoryType.CONVERSATION],
            limit=request.limit,
            include_raw=False,
            since=request.since,
            until=request.until,
        )
        hits: list[ConversationSearchHit] = []
        for result in results:
            memory = result.memory
            if not isinstance(memory, ConversationMemory):
                continue
            conversation_id = memory.source_chat_id or memory.id
            current_id = request.current_conversation_id or self._current_conversation_id
            if current_id and conversation_id == current_id:
                continue
            score = _clamp_score(result.score)
            if score < request.min_score:
                continue
            hit = _memory_hit(memory, score=score, source="semantic")
            if hit is not None:
                hits.append(hit)
        return ConversationSearchResponse(mode="search", hits=hits[: request.limit], query=query)

    async def _recent(self, request: ConversationSearchRequest) -> ConversationSearchResponse:
        memories = await self._manager.list_memories(MemoryType.CONVERSATION, limit=request.limit * 4)
        hits: list[ConversationSearchHit] = []
        current_id = request.current_conversation_id or self._current_conversation_id
        for memory in sorted(memories, key=lambda item: item.updated_at or item.created_at, reverse=True):
            if not isinstance(memory, ConversationMemory):
                continue
            conversation_id = memory.source_chat_id or memory.id
            if current_id and conversation_id == current_id:
                continue
            if not _within_time_range(memory.updated_at or memory.created_at, request):
                continue
            score = max(request.min_score, 0.9 - len(hits) * 0.03)
            hit = _memory_hit(memory, score=score, source="recent")
            if hit is not None:
                hits.append(hit)
            if len(hits) >= request.limit:
                break
        return ConversationSearchResponse(mode="recent", hits=hits, query="")


def _memory_hit(
    memory: ConversationMemory,
    *,
    score: float,
    source: ConversationSearchSource,
) -> ConversationSearchHit:
    conversation_id = memory.source_chat_id or memory.id
    title = _metadata_str(memory.metadata, "title")
    source_ref = ConversationSourceRef(
        conversation_id=conversation_id,
        message_id=memory.source_message_id,
        title=title,
        snippet=memory.raw_exchange,
        summary=memory.content,
        score=score,
        agent_id=_metadata_str(memory.metadata, "agent_id"),
        surface=_metadata_str(memory.metadata, "source"),
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )
    return ConversationSearchHit(
        conversation_id=conversation_id,
        title=title,
        snippet=memory.raw_exchange,
        summary=memory.content,
        score=score,
        source=source,
        message_id=memory.source_message_id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        metadata=memory.metadata,
        source_ref=source_ref,
    )


def _within_time_range(timestamp: object, request: ConversationSearchRequest) -> bool:
    if not isinstance(timestamp, datetime):
        return True
    value = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
    since = (
        request.since
        if request.since is None or request.since.tzinfo is not None
        else request.since.replace(tzinfo=UTC)
    )
    until = (
        request.until
        if request.until is None or request.until.tzinfo is not None
        else request.until.replace(tzinfo=UTC)
    )
    if since and value < since:
        return False
    return not (until and value > until)


def _metadata_str(metadata: dict[str, str | int | float | bool], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))
