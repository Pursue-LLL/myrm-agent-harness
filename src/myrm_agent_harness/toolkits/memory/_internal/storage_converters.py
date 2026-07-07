"""Vector Document <-> Memory Schema converters and shared metadata helpers.

[INPUT]
- memory.protocols.vector::{VectorDocument, FilterDict} (POS: vector store protocol and data models)
- memory.types::{SemanticMemory, EpisodicMemory, ConversationMemory, ...} (POS: memory data models)

[OUTPUT]
- Scope helpers: _scope_payload, _scope_from_metadata, _user_filter
- Lifecycle helpers: _lifecycle_payload, _lifecycle_from_metadata
- to_doc: semantic_to_doc, episodic_to_doc
- from_doc: doc_to_semantic, doc_to_episodic, doc_to_conversation

[POS]
Stateless conversion layer between vector-store documents and typed memory models.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.protocols.vector import (
    FilterDict,
    VectorDocument,
)
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    ConversationMemory,
    DigestKind,
    EpisodicMemory,
    EvaporationState,
    MemoryLifecycle,
    MemoryScope,
    MemoryTier,
    MemoryType,
    SemanticMemory,
)
from myrm_agent_harness.utils.coercion import parse_float, parse_int

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


def _safe_float(val: object, default: float = 0.0) -> float:
    return parse_float(val, default)


def _safe_int(val: object, default: int = 0) -> int:
    return parse_int(val, default)


# ======================================================================
# Filter / Scope / Lifecycle helpers
# ======================================================================


def _user_filter(
    *,
    namespaces: list[str] | None = None,
    include_archived: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
) -> FilterDict:
    """Build the standard user-scoped filter for vector queries.

    Centralizes archived-exclusion and time-range filtering so every
    query path uses the same logic.
    """
    f: FilterDict = {"archived": False}
    if namespaces:
        f["namespaces"] = namespaces
    if include_archived:
        del f["archived"]
    if since is not None or until is not None:
        time_range: dict[str, str | int | float] = {}
        if since is not None:
            time_range["gte"] = since.isoformat()
        if until is not None:
            time_range["lte"] = until.isoformat()
        f["created_at"] = time_range
    return f


def _scope_payload(scope: MemoryScope) -> dict[str, str | list[str]]:
    return {
        "primary_namespace": scope.primary_namespace,
        "namespaces": list(scope.namespaces),
        "agent_id": scope.agent_id or "",
        "channel_id": scope.channel_id or "",
        "conversation_id": scope.conversation_id or "",
        "task_id": scope.task_id or "",
    }


def _scope_from_metadata(meta: dict[str, object]) -> MemoryScope:
    raw_namespaces = meta.get("namespaces", [])
    namespaces = (
        [value for value in raw_namespaces if isinstance(value, str)] if isinstance(raw_namespaces, list) else []
    )
    return MemoryScope(
        primary_namespace=str(meta.get("primary_namespace", "")),
        namespaces=namespaces,
        agent_id=str(meta.get("agent_id", "")) or None,
        channel_id=str(meta.get("channel_id", "")) or None,
        conversation_id=str(meta.get("conversation_id", "")) or None,
        task_id=str(meta.get("task_id", "")) or None,
    )


def _lifecycle_payload(lifecycle: MemoryLifecycle | None) -> dict[str, str]:
    if lifecycle is None:
        return {}
    return {
        "memory_tier": lifecycle.tier.value,
        "digest_kind": (lifecycle.digest_kind.value if lifecycle.digest_kind is not None else ""),
        "evaporation_state": (lifecycle.evaporation_state.value if lifecycle.evaporation_state is not None else ""),
        "evaporated_at": (lifecycle.evaporated_at.isoformat() if lifecycle.evaporated_at is not None else ""),
        "claim_graph_state": (lifecycle.claim_graph_state.value if lifecycle.claim_graph_state is not None else ""),
        "claim_graph_node_id": lifecycle.claim_graph_node_id or "",
        "claim_graph_updated_at": (
            lifecycle.claim_graph_updated_at.isoformat() if lifecycle.claim_graph_updated_at is not None else ""
        ),
        "claim_graph_conflict": (
            lifecycle.claim_graph_conflict.value if lifecycle.claim_graph_conflict is not None else ""
        ),
    }


def _lifecycle_from_metadata(meta: dict[str, object]) -> MemoryLifecycle | None:
    raw_tier = str(meta.get("memory_tier", "")).strip()
    if raw_tier not in {tier.value for tier in MemoryTier}:
        return None

    raw_digest_kind = str(meta.get("digest_kind", "")).strip()
    digest_kind = DigestKind(raw_digest_kind) if raw_digest_kind in {kind.value for kind in DigestKind} else None

    raw_evaporation_state = str(meta.get("evaporation_state", "")).strip()
    evaporation_state = (
        EvaporationState(raw_evaporation_state)
        if raw_evaporation_state in {state.value for state in EvaporationState}
        else None
    )

    raw_claim_graph_state = str(meta.get("claim_graph_state", "")).strip()
    claim_graph_state = (
        ClaimGraphState(raw_claim_graph_state)
        if raw_claim_graph_state in {state.value for state in ClaimGraphState}
        else None
    )

    raw_claim_graph_conflict = str(meta.get("claim_graph_conflict", "")).strip()
    claim_graph_conflict = (
        ClaimConflictState(raw_claim_graph_conflict)
        if raw_claim_graph_conflict in {state.value for state in ClaimConflictState}
        else None
    )

    raw_evaporated_at = str(meta.get("evaporated_at", "")).strip()
    try:
        evaporated_at = datetime.fromisoformat(raw_evaporated_at) if raw_evaporated_at else None
    except ValueError:
        evaporated_at = None

    raw_claim_graph_updated_at = str(meta.get("claim_graph_updated_at", "")).strip()
    try:
        claim_graph_updated_at = (
            datetime.fromisoformat(raw_claim_graph_updated_at) if raw_claim_graph_updated_at else None
        )
    except ValueError:
        claim_graph_updated_at = None

    return MemoryLifecycle(
        tier=MemoryTier(raw_tier),
        digest_kind=digest_kind,
        evaporation_state=evaporation_state,
        evaporated_at=evaporated_at,
        claim_graph_state=claim_graph_state,
        claim_graph_node_id=str(meta.get("claim_graph_node_id", "")) or None,
        claim_graph_updated_at=claim_graph_updated_at,
        claim_graph_conflict=claim_graph_conflict,
    )


# ======================================================================
# Document -> Schema converters
# ======================================================================


_SEMANTIC_KNOWN_KEYS = frozenset(
    {
        "user_id",
        "memory_type",
        "importance",
        "confidence",
        "source_chat_id",
        "preference_type",
        "preference_strength",
        "correction_of",
        "source_error",
        "access_count",
        "user_rating",
        "tags",
        "merge_count",
        "merge_history",
        "language",
        "pinned",
        "archived",
        "archived_at",
        "archive_reason",
        "created_at",
        "updated_at",
        "primary_namespace",
        "namespaces",
        "agent_id",
        "channel_id",
        "conversation_id",
        "task_id",
        "memory_tier",
        "digest_kind",
        "evaporation_state",
        "evaporated_at",
        "claim_graph_state",
        "claim_graph_node_id",
        "claim_graph_updated_at",
        "claim_graph_conflict",
    }
)


def doc_to_semantic(doc: VectorDocument) -> SemanticMemory:
    meta = doc.metadata
    raw_pref = str(meta.get("preference_type", ""))
    pref_type = raw_pref if raw_pref in ("explicit", "implicit") else None
    raw_corr = str(meta.get("correction_of", ""))
    raw_lang = str(meta.get("language", "en"))
    lang = raw_lang if raw_lang in ("zh", "en") else "en"
    extra: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if k not in _SEMANTIC_KNOWN_KEYS and isinstance(v, (str, int, float, bool)):
            extra[k] = v
    return SemanticMemory(
        id=doc.id,
        user_id=str(meta.get("user_id", "")),
        content=doc.content,
        embedding=doc.vector,
        importance=_safe_float(meta.get("importance", 0.5), 0.5),
        confidence=_safe_float(meta.get("confidence", 1.0), 1.0),
        source_chat_id=str(meta.get("source_chat_id", "")) or None,
        preference_type=pref_type,
        preference_strength=_safe_float(meta.get("preference_strength", 0.0)),
        correction_of=raw_corr or None,
        source_error=str(meta.get("source_error", "")) or None,
        access_count=_safe_int(meta.get("access_count", 0)),
        user_rating=_safe_float(meta.get("user_rating", 0.5), 0.5),
        pinned=bool(meta.get("pinned", False)),
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        language=lang,
        merge_count=_safe_int(meta.get("merge_count", 0)),
        merge_history=str(meta.get("merge_history", "")),
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
    )


_EPISODIC_KNOWN_KEYS = frozenset(
    {
        "user_id",
        "memory_type",
        "event_type",
        "importance",
        "source_chat_id",
        "access_count",
        "user_rating",
        "related_entities",
        "merge_count",
        "merge_history",
        "language",
        "pinned",
        "archived",
        "archived_at",
        "archive_reason",
        "created_at",
        "updated_at",
        "primary_namespace",
        "namespaces",
        "agent_id",
        "channel_id",
        "conversation_id",
        "task_id",
        "memory_tier",
        "digest_kind",
        "evaporation_state",
        "evaporated_at",
        "claim_graph_state",
        "claim_graph_node_id",
        "claim_graph_updated_at",
        "claim_graph_conflict",
    }
)


def doc_to_episodic(doc: VectorDocument) -> EpisodicMemory:
    meta = doc.metadata
    raw_lang = str(meta.get("language", "en"))
    lang = raw_lang if raw_lang in ("zh", "en") else "en"
    extra: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if k not in _EPISODIC_KNOWN_KEYS and isinstance(v, (str, int, float, bool)):
            extra[k] = v
    return EpisodicMemory(
        id=doc.id,
        user_id=str(meta.get("user_id", "")),
        content=doc.content,
        embedding=doc.vector,
        event_type=str(meta.get("event_type", "conversation")),
        importance=_safe_float(meta.get("importance", 0.5), 0.5),
        source_chat_id=str(meta.get("source_chat_id", "")) or None,
        access_count=_safe_int(meta.get("access_count", 0)),
        user_rating=_safe_float(meta.get("user_rating", 0.5), 0.5),
        pinned=bool(meta.get("pinned", False)),
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        language=lang,
        merge_count=_safe_int(meta.get("merge_count", 0)),
        merge_history=str(meta.get("merge_history", "")),
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
    )


_CONVERSATION_KNOWN_KEYS = frozenset(
    {
        "user_id",
        "archived",
        "content",
        "timestamp",
        "user_turn_only",
        "related_entities",
        "source_chat_id",
        "source_message_id",
        "project_id",
        "topic_id",
        "importance",
        "language",
        "primary_namespace",
        "namespaces",
        "agent_id",
        "channel_id",
        "conversation_id",
        "task_id",
        "memory_tier",
        "digest_kind",
        "evaporation_state",
        "evaporated_at",
        "claim_graph_state",
        "claim_graph_node_id",
        "claim_graph_updated_at",
        "claim_graph_conflict",
    }
)


def doc_to_conversation(
    doc: VectorDocument,
    *,
    include_raw: bool = False,
    config: MemoryConfig | None = None,
) -> ConversationMemory:
    """Convert VectorDocument to ConversationMemory.

    Args:
        doc: Source vector document with conversation metadata.
        include_raw: If True, populate raw_exchange field (default False for lazy loading).
        config: Memory configuration for blob storage path resolution.

    Returns:
        ConversationMemory instance.
    """
    meta = doc.metadata
    raw_lang = str(meta.get("language", "en"))
    lang = raw_lang if raw_lang in ("zh", "en") else "en"
    extra: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if k not in _CONVERSATION_KNOWN_KEYS and isinstance(v, (str, int, float, bool)):
            extra[k] = v

    raw_entities = meta.get("related_entities", [])
    related_entities = raw_entities if isinstance(raw_entities, list) else []

    raw_timestamp = meta.get("timestamp")
    timestamp: datetime
    if isinstance(raw_timestamp, datetime):
        timestamp = raw_timestamp
    elif isinstance(raw_timestamp, str):
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
        except (ValueError, TypeError):
            timestamp = doc.created_at
    else:
        timestamp = doc.created_at

    raw_exchange_value = ""
    if include_raw:
        raw_data = meta.get("raw_exchange", "")

        if isinstance(raw_data, str) and raw_data.startswith("blob://"):
            from myrm_agent_harness.toolkits.memory.compression import (
                internalize_payload,
            )

            blob_dir = config.blob_storage_path if config else "~/.myrm/blobs"
            raw_exchange_value = internalize_payload(raw_data, blob_dir=blob_dir)
        else:
            is_compressed_flag = bool(meta.get("raw_exchange_compressed", False))
            if is_compressed_flag and isinstance(raw_data, str):
                import base64

                from myrm_agent_harness.toolkits.memory.compression import (
                    decompress_payload,
                )

                try:
                    compressed_bytes = base64.b64decode(raw_data)
                    raw_exchange_value = decompress_payload(compressed_bytes)
                except Exception:
                    raw_exchange_value = raw_data
            else:
                raw_exchange_value = str(raw_data) if raw_data else ""

    return ConversationMemory(
        id=doc.id,
        user_id=str(meta.get("user_id", "")),
        content=doc.content,
        raw_exchange=raw_exchange_value,
        raw_embedding=None,
        summary_embedding=doc.vector,
        timestamp=timestamp,
        user_turn_only=bool(meta.get("user_turn_only", True)),
        related_entities=related_entities,
        source_chat_id=str(meta.get("source_chat_id", "")) or None,
        source_message_id=str(meta.get("source_message_id", "")) or None,
        project_id=str(meta.get("project_id", "")) or None,
        topic_id=str(meta.get("topic_id", "")) or None,
        importance=_safe_float(meta.get("importance", 0.5), 0.5),
        language=lang,  # type: ignore[arg-type]
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
    )


# ======================================================================
# Schema -> Document converters
# ======================================================================


def semantic_to_doc(m: SemanticMemory) -> VectorDocument:
    payload: dict[str, str | int | float | bool | list[str]] = {
        "memory_type": MemoryType.SEMANTIC.value,
        "importance": m.importance,
        "confidence": m.confidence,
        "source_chat_id": m.source_chat_id or "",
        "preference_type": m.preference_type or "",
        "preference_strength": m.preference_strength,
        "correction_of": m.correction_of or "",
        "source_error": m.source_error or "",
        "access_count": m.access_count,
        "user_rating": m.user_rating,
        "language": m.language,
        "merge_count": m.merge_count,
        "merge_history": m.merge_history,
        "pinned": m.pinned,
        "status": m.status,
        "archived": m.status == "archived",
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        **_scope_payload(m.scope),
        **_lifecycle_payload(m.lifecycle),
    }
    for k, v in m.metadata.items():
        if k not in payload:
            payload[k] = v
    return VectorDocument(
        id=m.id,
        content=m.content,
        vector=m.embedding,
        metadata=payload,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def episodic_to_doc(m: EpisodicMemory) -> VectorDocument:
    payload: dict[str, str | int | float | bool | list[str]] = {
        "memory_type": MemoryType.EPISODIC.value,
        "event_type": m.event_type,
        "importance": m.importance,
        "source_chat_id": m.source_chat_id or "",
        "access_count": m.access_count,
        "user_rating": m.user_rating,
        "language": m.language,
        "merge_count": m.merge_count,
        "merge_history": m.merge_history,
        "pinned": m.pinned,
        "status": m.status,
        "archived": m.status == "archived",
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        **_scope_payload(m.scope),
        **_lifecycle_payload(m.lifecycle),
    }
    for k, v in m.metadata.items():
        if k not in payload:
            payload[k] = v
    return VectorDocument(
        id=m.id,
        content=m.content,
        vector=m.embedding,
        metadata=payload,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
