"""Memory session — buffers writes during a conversation, batch-flushes on end.


[INPUT]
- memory._internal.hash_utils::compute_normalized_hash (POS: text normalization and hashing)
- memory.types::{AnyMemory, EpisodicMemory, ProceduralMemory, SemanticMemory} (POS: memory data models)
- memory.manager::MemoryManager (POS: unified memory manager facade)
- memory.tool_capture::ToolMemoryCaptureHook (POS: tool-scoped memory capture via regex edicts + failure counting)

[OUTPUT]
- MemorySession: Conversation-level write buffer with session-scoped dedup hash cache

[POS]
Conversation-level memory buffer. Buffers memory writes during a session and batch-flushes
on end_session(). Session-level normalized hash cache prevents duplicates within a conversation.
Integrates with ToolMemoryCaptureHook to persist tool failure rules on flush.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.hash_utils import NormalizationLevel, compute_normalized_hash
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    EpisodicMemory,
    ProceduralMemory,
    RuleSource,
    SemanticMemory,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.tool_capture import ToolMemoryCaptureHook

logger = logging.getLogger(__name__)


@dataclass
class MemorySession:
    """Buffers memory writes during a conversation, batch-flushes on end.

    Normalized hash cache prevents duplicate content within the conversation.
    Catches both exact matches and text variants based on configured normalization level.
    ``user_id`` is derived from ``manager.user_id`` — no separate field needed.
    """

    manager: MemoryManager
    chat_id: str
    tool_capture_hook: ToolMemoryCaptureHook | None = field(default=None)
    _buffer: list[AnyMemory] = field(default_factory=list, init=False)
    _content_hashes: set[str] = field(default_factory=set, init=False)

    @property
    def user_id(self) -> str:
        return self.manager.user_id

    @property
    def _normalization_level(self) -> NormalizationLevel:
        """Get normalization level from manager's config."""
        return self.manager.config.dedup.normalization_level

    def _check_duplicate(self, content: str) -> bool:
        """Check if content already exists in session buffer.

        Uses normalized hash to catch both exact matches and variants.
        """
        content_hash = compute_normalized_hash(content, self._normalization_level)
        if content_hash in self._content_hashes:
            logger.warning("Session duplicate detected, skipping: %s...", content[:50])
            return True

        self._content_hashes.add(content_hash)
        return False

    def add_knowledge(
        self, content: str, *, importance: float = 0.5, tags: list[str] | None = None
    ) -> SemanticMemory | None:
        """Add semantic knowledge to session buffer.

        Returns:
            SemanticMemory if added, None if duplicate detected
        """
        if self._check_duplicate(content):
            return None

        mem = SemanticMemory(
            user_id=self.user_id, content=content, importance=importance, tags=tags or [], source_chat_id=self.chat_id
        )
        self._buffer.append(mem)
        return mem

    def add_event(
        self, content: str, *, event_type: str = "conversation", related_entities: list[str] | None = None
    ) -> EpisodicMemory | None:
        """Add episodic event to session buffer.

        Returns:
            EpisodicMemory if added, None if duplicate detected
        """
        if self._check_duplicate(content):
            return None

        mem = EpisodicMemory(
            user_id=self.user_id,
            content=content,
            event_type=event_type,
            related_entities=related_entities or [],
            source_chat_id=self.chat_id,
        )
        self._buffer.append(mem)
        return mem

    def add_rule(
        self,
        trigger: str,
        action: str,
        *,
        priority: int = 0,
        source: RuleSource = RuleSource.USER_EXTRACTED,
        trigger_keywords: list[str] | None = None,
    ) -> ProceduralMemory | None:
        """Add procedural rule to session buffer.

        Returns:
            ProceduralMemory if added, None if duplicate detected
        """
        content = f"When: {trigger} → Do: {action}"
        if self._check_duplicate(content):
            return None

        mem = ProceduralMemory(
            user_id=self.user_id,
            content=content,
            trigger=trigger,
            action=action,
            priority=priority,
            trigger_keywords=trigger_keywords or [],
            source=source,
        )
        self._buffer.append(mem)
        return mem

    async def set_profile(self, key: str, value: str) -> None:
        await self.manager.set_profile_attribute(key, value)

    def search_buffer(self, query: str, *, limit: int = 5) -> list[AnyMemory]:
        q = query.lower()
        return [m for m in self._buffer if q in m.content.lower()][:limit]

    async def flush(self) -> list[AnyMemory]:
        """Flush buffered memories to storage and clear session state.

        If a ToolMemoryCaptureHook is attached, its pending rules
        (from repeated tool failures) are drained and included in the batch.
        """
        if self.tool_capture_hook is not None:
            for rule in self.tool_capture_hook.drain_pending():
                if not self._check_duplicate(rule.content):
                    self._buffer.append(rule)

        if not self._buffer:
            return []
        batch = list(self._buffer)
        self._buffer.clear()
        self._content_hashes.clear()
        return await self.manager.store_batch(batch)

    def discard(self) -> int:
        """Discard all buffered memories without persisting."""
        n = len(self._buffer)
        self._buffer.clear()
        self._content_hashes.clear()
        return n

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)
