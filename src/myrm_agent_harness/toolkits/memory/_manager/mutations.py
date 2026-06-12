"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

import asyncio

from myrm_agent_harness.toolkits.memory._internal.scope import validate_namespaces
from myrm_agent_harness.toolkits.memory._manager.shared import (
    UTC,
    AnyMemory,
    ConversationMemory,
    EpisodicMemory,
    MemoryError,
    MemoryNotFoundError,
    MemoryScope,
    MemoryStatus,
    ProceduralMemory,
    SemanticMemory,
    datetime,
    doc_to_episodic,
    doc_to_semantic,
    get_from_vector,
    logger,
    scan_and_clean_memory,
    timedelta,
    update_vector_memory,
)


class MemoryManagerMutationsMixin:
    # ── User Feedback Rating ──

    async def rate_memory(self, memory_id: str, score: int, collection: str | None = None) -> bool:
        """Update a memory's user_rating using asymmetric Exponential Moving Average.

        Score is an integer in [1, 5] (user-facing Likert scale).
        Internally normalized to [0, 1] and applied via asymmetric EMA:
            alpha = alpha_negative if normalized < old_rating else alpha_positive
            rating_new = rating_old + alpha * (normalized - rating_old)

        Asymmetric design: negative feedback decays rating faster than positive
        feedback recovers it, requiring more positive validations to restore trust.

        Args:
            memory_id: Target memory ID.
            score: User feedback score (1=bad, 5=excellent).
            collection: Explicit vector collection. If None, searches both.

        Returns:
            True if the memory was found and updated.
        """
        if self._vector is None:
            return False

        clamped = max(1, min(5, score))
        normalized = (clamped - 1) / 4.0
        alpha_positive = self._config.rating_alpha
        alpha_negative = self._config.rating_alpha_negative

        collections = (
            [collection] if collection else [self._config.semantic_collection, self._config.episodic_collection]
        )
        for coll in collections:
            try:
                docs = await self._vector.get(coll, [memory_id])
            except Exception:
                continue
            if not docs:
                continue
            doc = docs[0]
            stored_uid = doc.metadata.get("user_id")
            if stored_uid and stored_uid != self._user_id:
                continue

            old_rating = float(doc.metadata.get("user_rating", 0.5))
            alpha = alpha_negative if normalized < old_rating else alpha_positive
            new_rating = old_rating + alpha * (normalized - old_rating)
            new_rating = max(0.0, min(1.0, round(new_rating, 4)))
            doc.metadata["user_rating"] = new_rating
            await self._vector.upsert(coll, [doc])
            return True
        return False

    # ── Get / Update single memory ──

    async def get_memory(self, memory_id: str) -> AnyMemory | None:
        tasks: list[asyncio.Task[AnyMemory | None]] = []
        if self._vector is not None:
            tasks.append(
                asyncio.create_task(
                    get_from_vector(
                        memory_id,
                        self._vector,
                        self._config,
                        namespaces=self._namespaces,
                    )
                )
            )
        if self._relational is not None:
            tasks.append(asyncio.create_task(self._relational.get_rule(memory_id, namespaces=self._namespaces)))
        for r in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(r, BaseException):
                logger.warning("Get memory error: %s", r)
            elif r is not None:
                return r
        return None

    async def correct_memory(self, memory_id: str, corrected_content: str) -> SemanticMemory:
        """Correct a factually wrong memory: demote the old one and create a linked correction.

        Returns the newly created correction memory.
        """
        existing = await self.get_memory(memory_id)
        if existing is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")
        if not isinstance(existing, SemanticMemory):
            raise MemoryError(f"Correction only supports SemanticMemory, got {type(existing).__name__}")

        demoted = existing.model_copy(deep=True)
        demoted.importance = max(existing.importance * 0.3, 0.05)
        demoted.confidence = 0.1
        demoted.metadata = {**demoted.metadata, "corrected": True}
        demoted.updated_at = datetime.now(UTC)
        v, e = self._vec()
        await update_vector_memory(demoted, False, v, self._config, e, self._cache)

        pref_strength = min(existing.preference_strength + 0.1, 1.0) if existing.preference_strength > 0 else 0.0
        correction = SemanticMemory(
            content=corrected_content,
            importance=min(existing.importance + 0.2, 1.0),
            confidence=0.95,
            tags=existing.tags,
            source_chat_id=existing.source_chat_id,
            preference_type=existing.preference_type,
            preference_strength=pref_strength,
            correction_of=memory_id,
        )
        return await self._store_semantic(correction)

    async def pin_memory(self, memory_id: str) -> AnyMemory:
        """Mark a memory as user-pinned (immune to forgetting)."""
        return await self._set_pinned(memory_id, pinned=True)

    async def unpin_memory(self, memory_id: str) -> AnyMemory:
        """Remove user-pinned protection from a memory."""
        return await self._set_pinned(memory_id, pinned=False)

    async def _set_pinned(self, memory_id: str, *, pinned: bool) -> AnyMemory:
        if self._vector is None:
            raise MemoryError("Vector backend is required but not provided")

        for coll, converter in (
            (self._config.semantic_collection, doc_to_semantic),
            (self._config.episodic_collection, doc_to_episodic),
        ):
            docs = await self._vector.get(coll, [memory_id])
            if not docs:
                continue
            doc = docs[0]
            if doc.metadata.get("user_id") != self._user_id:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
            if bool(doc.metadata.get("pinned", False)) == pinned:
                return converter(doc)
            doc.metadata["pinned"] = pinned
            await self._vector.upsert(coll, [doc])
            return converter(doc)

        raise MemoryNotFoundError(f"Memory {memory_id} not found")

    async def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, str | int | float | bool] | None = None,
        is_active: bool | None = None,
        status: MemoryStatus | None = None,
        reasoning: str | None = None,
        application: str | None = None,
        namespaces: list[str] | None = None,
    ) -> AnyMemory:
        existing = await self.get_memory(memory_id)
        if existing is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")

        updated = existing.model_copy(deep=True)

        if namespaces is not None:
            validated = validate_namespaces(namespaces)
            primary = next(
                (ns for ns in reversed(validated) if not ns.startswith("shared:")),
                validated[0],
            )
            updated.scope = MemoryScope(
                primary_namespace=primary,
                namespaces=validated,
                agent_id=updated.scope.agent_id,
                channel_id=updated.scope.channel_id,
                conversation_id=updated.scope.conversation_id,
                task_id=updated.scope.task_id,
            )

        content_changed = content is not None
        if content_changed:
            updated.metadata = {
                **updated.metadata,
                "previous_content": existing.content,
            }
            updated.content = content
        if importance is not None and isinstance(updated, (SemanticMemory, EpisodicMemory, ConversationMemory)):
            updated.importance = importance
        if tags is not None and isinstance(updated, SemanticMemory):
            updated.tags = tags
        if status is not None:
            updated.status = status
            if status == MemoryStatus.ARCHIVED:
                now = datetime.now(UTC)
                updated.metadata = {
                    **updated.metadata,
                    "archived_at": now.isoformat(),
                    "archive_expires_at": (now + timedelta(days=7)).isoformat(),
                    "archive_reason": "user_deleted",
                }
            elif existing.status == MemoryStatus.ARCHIVED and status == MemoryStatus.ACTIVE:
                updated.metadata.pop("archived_at", None)
                updated.metadata.pop("archive_expires_at", None)
                updated.metadata.pop("archive_reason", None)
            if isinstance(updated, ProceduralMemory):
                updated.is_active = status == MemoryStatus.ACTIVE
        elif is_active is not None and isinstance(updated, ProceduralMemory):
            updated.is_active = is_active
            updated.status = MemoryStatus.ACTIVE if is_active else MemoryStatus.DISABLED
        if metadata is not None:
            updated.metadata = {**updated.metadata, **metadata}
        if isinstance(updated, ProceduralMemory):
            if reasoning is not None:
                updated.reasoning = reasoning
            if application is not None:
                updated.application = application
        updated.updated_at = datetime.now(UTC)

        if content_changed and self._config.security_scan_enabled:
            scan_and_clean_memory(updated, block_threshold=self._config.injection_block_threshold)

        if isinstance(updated, (SemanticMemory, EpisodicMemory)):
            v, e = self._vec()
            return await update_vector_memory(
                self._bind_scope(updated),
                content_changed,
                v,
                self._config,
                e,
                self._cache,
            )
        if isinstance(updated, ProceduralMemory):
            return await self._rel().update_rule(memory_id, updated)
        raise ValueError(f"Cannot update memory type: {type(updated).__name__}")
