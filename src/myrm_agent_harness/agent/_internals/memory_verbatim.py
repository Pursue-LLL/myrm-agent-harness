"""Verbatim conversation capture — opt-in lossless storage of the newest exchange.

[INPUT]
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager)
- toolkits.memory.chunking::chunk_conversation (POS: exchange-pair chunking strategy)
- toolkits.memory.types::ConversationMemory (POS: verbatim conversation type definition)

[OUTPUT]
- create_conversation_memories(): Chunk messages into verbatim ConversationMemory objects
- capture_current_exchange(): Store the trailing user/assistant exchange verbatim

[POS]
Verbatim track of post-turn memory auto-extraction, enabled per call with
``auto_extract_memories(enable_verbatim=True)``. Extraction runs once per turn over
the whole history, so only the trailing exchange is stored; earlier exchanges are
stored by their own turns. A verbatim exchange (user message plus assistant reply)
is a literal record rather than an inference, so it bypasses the approval queue
that gates inferred memories; it still passes the content-safety scan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.chunking import chunk_conversation
from myrm_agent_harness.toolkits.memory.types import ConversationMemory

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

# One user message plus the assistant reply it received.
_EXCHANGE_MESSAGES = 2


def create_conversation_memories(
    messages: list[dict[str, str]],
    source_chat_id: str | None = None,
) -> list[ConversationMemory]:
    """Create verbatim ConversationMemory chunks from messages.

    Uses exchange-pair chunking (MemPalace strategy) to preserve completeness.

    Args:
        messages: List of dicts with 'role' and 'content' keys
        source_chat_id: Source chat/session identifier

    Returns:
        List of ConversationMemory objects
    """
    chunks = chunk_conversation(messages)
    conversation_memories: list[ConversationMemory] = []

    for chunk in chunks:
        memory = ConversationMemory(
            raw_exchange=chunk.raw_text,
            content=chunk.user_turn,
            timestamp=chunk.timestamp,
            source_chat_id=source_chat_id,
            language=("zh" if any(ord(c) > 0x4E00 for c in chunk.user_turn[:50]) else "en"),
        )
        conversation_memories.append(memory)

    return conversation_memories


async def capture_current_exchange(
    memory_manager: MemoryManager,
    messages: list[dict[str, str]],
    *,
    source_chat_id: str | None,
) -> int:
    """Store the trailing user/assistant exchange of ``messages`` verbatim.

    Returns the number of chunks actually stored (a chunk rejected by the
    content-safety scan is not counted). A turn whose user message carried no
    text (image-only message, HITL resume) is not an exchange and stores nothing.
    """
    exchange = messages[-_EXCHANGE_MESSAGES:]
    if [m["role"] for m in exchange] != ["user", "assistant"]:
        return 0
    memories = create_conversation_memories(exchange, source_chat_id=source_chat_id)
    if not memories:
        return 0
    stored = await memory_manager.store_batch(memories, _bypass_approval=True)
    return len(stored)
