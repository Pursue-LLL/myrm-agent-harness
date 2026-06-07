"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._manager.shared import (
    EpisodicMemory,
    MemoryWriteTarget,
    ProceduralMemory,
    ProfileAttributeSnapshot,
    RuleSource,
    SemanticMemory,
)


class MemoryManagerConvenienceMixin:
    # ── Convenience: Profile ──

    async def set_profile_attribute(self, key: str, value: str) -> str | None:
        """Set a profile attribute. Returns pending_id if approval is required, else None."""
        return await self._governance.set_profile_attribute(key, value, approval_required=self.approval_required)

    async def get_profile_attribute(self, key: str) -> str | None:
        return await self._governance.get_profile_attribute(key)

    async def get_profile_attribute_snapshot(self, key: str) -> ProfileAttributeSnapshot:
        return await self._rel().get_profile_snapshot(key, namespaces=self._namespaces)

    async def restore_profile_attributes(self, values: dict[str, str | None]) -> int:
        """Restore profile keys directly for audited rollback flows."""

        restored = 0
        relational = self._rel()
        for key, value in values.items():
            if value is None:
                if await relational.delete_profile(key, namespaces=self._namespaces):
                    restored += 1
            else:
                await relational.set_profile(key, value, scope=self._scope)
                restored += 1
        return restored

    # ── Convenience: Knowledge (Semantic) ──

    async def add_knowledge(
        self,
        content: str,
        *,
        importance: float = 0.5,
        tags: list[str] | None = None,
        source_chat_id: str | None = None,
        write_target: MemoryWriteTarget = "bound",
    ) -> SemanticMemory:
        memory = self._writer.build_knowledge(
            content=content,
            importance=importance,
            tags=tags,
            source_chat_id=source_chat_id,
            write_target=write_target,
        )
        result = await self.store(memory)
        return result if isinstance(result, SemanticMemory) else memory

    # ── Convenience: Events (Episodic) ──

    async def add_event(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        related_entities: list[str] | None = None,
        source_chat_id: str | None = None,
        source_message_id: str | None = None,
        write_target: MemoryWriteTarget = "bound",
    ) -> EpisodicMemory:
        memory = self._writer.build_event(
            content=content,
            event_type=event_type,
            related_entities=related_entities,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            write_target=write_target,
        )
        result = await self.store(memory)
        return result if isinstance(result, EpisodicMemory) else memory

    # ── Convenience: Rules (Procedural) ──

    async def add_rule(
        self,
        trigger: str,
        action: str,
        *,
        priority: int = 0,
        trigger_keywords: list[str] | None = None,
        source: RuleSource = RuleSource.USER_EXTRACTED,
    ) -> ProceduralMemory:
        memory = self._writer.build_rule(
            trigger=trigger,
            action=action,
            priority=priority,
            trigger_keywords=trigger_keywords,
            source=source,
        )
        result = await self.store(memory)
        return result if isinstance(result, ProceduralMemory) else memory
