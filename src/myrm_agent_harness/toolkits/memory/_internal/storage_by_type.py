"""Per-memory-type list / count / delete helpers over the relational and vector stores.

[INPUT]
- storage_converters::{doc_to_semantic, doc_to_episodic, doc_to_conversation, _user_filter} (POS: stateless
  conversion layer)
- memory.types::{SemanticMemory, EpisodicMemory, ConversationMemory, ProceduralMemory, MemoryType} (POS: memory
  data models)

[OUTPUT]
- list_by_type, count_by_type, delete_by_type: Type-dispatched CRUD helpers used by the memory management API

[POS]
Per-type CRUD dispatch for the storage facade; re-exported by ``storage``. Not part of the public API.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
    _user_filter,
    doc_to_conversation,
    doc_to_episodic,
    doc_to_semantic,
)
from myrm_agent_harness.toolkits.memory.types import (
    ConversationMemory,
    EpisodicMemory,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.relational import (
        RelationalStoreProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
    from myrm_agent_harness.toolkits.vector.base import FilterDict, VectorDocument


_SORT_FIELD_MAP: dict[str, str] = {
    "created_at": "_created_ts",
    "updated_at": "_updated_ts",
    "importance": "importance",
}


async def list_by_type(
    memory_type: MemoryType,
    *,
    limit: int,
    offset: int,
    relational: RelationalStoreProtocol | None,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    namespaces: list[str] | None = None,
    include_archived: bool = False,
    sort_by: str | None = None,
    sort_order: str = "desc",
    tag_filter: str | None = None,
) -> list[SemanticMemory | EpisodicMemory | ConversationMemory | ProceduralMemory]:
    order_by: tuple[str, str] | None = None
    if sort_by and sort_by in _SORT_FIELD_MAP:
        order_by = (_SORT_FIELD_MAP[sort_by], sort_order)

    if memory_type == MemoryType.PROFILE and relational:
        entries = await relational.list_profiles(limit=limit, offset=offset, namespaces=namespaces)
        visible_entries = [entry for entry in entries if not entry.key.startswith("_system_")]
        return [
            SemanticMemory(
                id=e.id,
                content=f"{e.key}: {e.value}",
                importance=0.8,
                metadata={"key": e.key, "value": str(e.value)},
                created_at=e.created_at,
                updated_at=e.updated_at,
                scope=e.scope,
            )
            for e in visible_entries
        ]
    if memory_type == MemoryType.PROCEDURAL and relational:
        return list(await relational.list_rules(active_only=True, limit=limit, offset=offset, namespaces=namespaces))

    def _build_filters(base_filters: FilterDict) -> FilterDict:
        if tag_filter:
            base_filters["tags"] = tag_filter.lower()
        return base_filters

    async def _scroll_with_offset(
        coll: str, filters: FilterDict, *, fetch_limit: int, skip: int
    ) -> list[VectorDocument]:
        """Qdrant scroll with integer offset emulation.

        Qdrant scroll is cursor-based (point-ID), not offset-based.
        When ``order_by`` is used we fetch ``skip + fetch_limit`` items
        and discard the first ``skip`` in-memory.  Without ``order_by``
        the existing cursor-based behaviour is used (offset=None for
        first page).
        """
        if order_by is not None and skip > 0:
            docs, _ = await vector.scroll(  # type: ignore[union-attr]
                coll, limit=skip + fetch_limit, filters=filters, order_by=order_by
            )
            return docs[skip:]
        docs, _ = await vector.scroll(  # type: ignore[union-attr]
            coll, limit=fetch_limit, filters=filters, order_by=order_by
        )
        return docs

    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = config.semantic_collection if memory_type == MemoryType.SEMANTIC else config.episodic_collection
        filters = _build_filters(_user_filter(namespaces=namespaces, include_archived=include_archived))
        docs = await _scroll_with_offset(coll, filters, fetch_limit=limit, skip=offset)
        converter = doc_to_semantic if memory_type == MemoryType.SEMANTIC else doc_to_episodic
        if not docs and offset == 0:
            # Sparse-authoritative deployments (no embedding backend) keep their
            # writes in the BM25 mirror only; list it so those memories do not
            # vanish from the memory list and the settings UI.
            lister = getattr(vector, "list_sparse_only", None)
            if lister is not None:
                sparse_docs = await lister(coll, limit=limit)
                if sparse_docs:
                    return [converter(d) for d in sparse_docs]
        return [converter(d) for d in docs]
    if memory_type == MemoryType.CONVERSATION and vector:
        filters = _build_filters(_user_filter(namespaces=namespaces, include_archived=include_archived))
        docs = await _scroll_with_offset(config.conversation_collection, filters, fetch_limit=limit, skip=offset)
        return [doc_to_conversation(d, config=config) for d in docs]
    if memory_type == MemoryType.TASK_DIGEST and vector:
        filters = _build_filters(_user_filter(namespaces=namespaces, include_archived=include_archived))
        filters["event_type"] = MemoryType.TASK_DIGEST.value
        docs = await _scroll_with_offset(config.episodic_collection, filters, fetch_limit=limit, skip=offset)
        return [doc_to_episodic(d) for d in docs]
    return []


async def count_by_type(
    memory_type: MemoryType,
    *,
    relational: RelationalStoreProtocol | None,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    namespaces: list[str] | None = None,
    since: datetime | None = None,
    tag_filter: str | None = None,
) -> int:
    def _apply_tag(f: FilterDict) -> FilterDict:
        if tag_filter:
            f["tags"] = tag_filter.lower()
        return f

    if memory_type == MemoryType.PROFILE and relational:
        return await relational.count_profiles(namespaces=namespaces)
    if memory_type == MemoryType.PROCEDURAL and relational:
        return await relational.count_rules(namespaces=namespaces)
    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = config.semantic_collection if memory_type == MemoryType.SEMANTIC else config.episodic_collection
        return await vector.count(coll, filters=_apply_tag(_user_filter(namespaces=namespaces, since=since)))
    if memory_type == MemoryType.CONVERSATION and vector:
        return await vector.count(
            config.conversation_collection,
            filters=_apply_tag(_user_filter(namespaces=namespaces, since=since)),
        )
    if memory_type == MemoryType.TASK_DIGEST and vector:
        filters = _apply_tag(_user_filter(namespaces=namespaces, since=since))
        filters["event_type"] = MemoryType.TASK_DIGEST.value
        return await vector.count(config.episodic_collection, filters=filters)
    return 0


async def delete_by_type(
    memory_type: MemoryType,
    *,
    relational: RelationalStoreProtocol | None,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    namespaces: list[str] | None = None,
) -> int:
    if memory_type == MemoryType.PROFILE and relational:
        entries = await relational.list_profiles(namespaces=namespaces)
        count = 0
        for e in entries:
            if await relational.delete_profile(e.key, namespaces=namespaces):
                count += 1
        return count
    if memory_type == MemoryType.PROCEDURAL and relational:
        count = 0
        while True:
            rules = await relational.list_rules(
                active_only=False,
                limit=500,
                offset=0,
                namespaces=namespaces,
            )
            if not rules:
                break
            for rule in rules:
                if await relational.delete_rule(rule.id):
                    count += 1
        return count
    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = config.semantic_collection if memory_type == MemoryType.SEMANTIC else config.episodic_collection
        return await vector.delete_by_filter(coll, _user_filter(namespaces=namespaces, include_archived=True))
    return 0
