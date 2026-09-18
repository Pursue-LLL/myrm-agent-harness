"""Vector Document <-> Memory Schema converters and shared metadata helpers.

[INPUT]
- memory.protocols.vector::{VectorDocument, FilterDict} (POS: vector store protocol and data models)
- memory.types::{SemanticMemory, EpisodicMemory, ConversationMemory, ...} (POS: memory data models)
- memory.domain_types::{MemoryDomain, DomainCategory} (POS: domain & category taxonomy)

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

from myrm_agent_harness.toolkits.memory._internal._storage_payload_helpers import (
    _lifecycle_from_metadata,
    _lifecycle_payload,
    _safe_float,
    _safe_int,
    _scope_from_metadata,
    _scope_payload,
    _status_from_metadata,
    _user_filter,
)
from myrm_agent_harness.toolkits.memory.domain_types import MemoryDomain
from myrm_agent_harness.toolkits.memory.protocols.vector import (
    VectorDocument,
)
from myrm_agent_harness.toolkits.memory.types import (
    ConversationMemory,
    EpisodicMemory,
    MemoryType,
    SemanticMemory,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig

logger = logging.getLogger(__name__)

__all__ = [
    "_safe_float",
    "_safe_int",
    "_status_from_metadata",
    "_user_filter",
    "_scope_payload",
    "_scope_from_metadata",
    "_lifecycle_payload",
    "_lifecycle_from_metadata",
    "doc_to_semantic",
    "doc_to_episodic",
    "doc_to_conversation",
    "semantic_to_doc",
    "episodic_to_doc",
]

# Payload keys that have a dedicated model attribute, so they must not also be
# copied into ``metadata``. Only list a key here when ``doc_to_*`` actually
# assigns it onto the model — keys listed here but never assigned are silently
# dropped on every read/write round-trip. ``archived_at`` and ``archive_reason``
# intentionally stay out so they persist through ``metadata`` unchanged.
_COMMON_KNOWN_KEYS = frozenset(
    {
        "user_id",
        "memory_type",
        "importance",
        "source_chat_id",
        "access_count",
        "user_rating",
        "pinned",
        "status",
        "archived",
        "expected_valid_days",
        "created_at",
        "updated_at",
        "language",
        "merge_count",
        "merge_history",
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
        "summary_l0",
        "overview_l1",
        "domain",
        "domain_category",
    }
)

_SEMANTIC_KNOWN_KEYS = _COMMON_KNOWN_KEYS | frozenset(
    {
        "confidence",
        "preference_type",
        "preference_strength",
        "correction_of",
        "source_error",
        "tags",
    }
)

_EPISODIC_KNOWN_KEYS = _COMMON_KNOWN_KEYS | frozenset(
    {
        "event_type",
        "related_entities",
        "tags",
    }
)

_CONVERSATION_KNOWN_KEYS = _COMMON_KNOWN_KEYS | frozenset(
    {
        "timestamp",
        "user_turn_only",
        "related_entities",
        "source_message_id",
        "project_id",
        "topic_id",
    }
)


def _parse_domain(raw_domain: object) -> MemoryDomain:
    try:
        return MemoryDomain(str(raw_domain))
    except (ValueError, TypeError):
        return MemoryDomain.USER


def doc_to_semantic(doc: VectorDocument) -> SemanticMemory:
    """Convert VectorDocument to SemanticMemory."""
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
    raw_evd = _safe_int(meta.get("expected_valid_days", 0))
    evd: int | None = raw_evd if raw_evd > 0 else None

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
        status=_status_from_metadata(meta),
        expected_valid_days=evd,
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        language=lang,
        merge_count=_safe_int(meta.get("merge_count", 0)),
        merge_history=str(meta.get("merge_history", "")),
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
        summary_l0=str(meta.get("summary_l0", "")),
        overview_l1=str(meta.get("overview_l1", "")),
        domain=_parse_domain(meta.get("domain")),
        domain_category=str(meta.get("domain_category", "")),
    )


def doc_to_episodic(doc: VectorDocument) -> EpisodicMemory:
    """Convert VectorDocument to EpisodicMemory."""
    meta = doc.metadata
    raw_lang = str(meta.get("language", "en"))
    lang = raw_lang if raw_lang in ("zh", "en") else "en"
    extra: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if k not in _EPISODIC_KNOWN_KEYS and isinstance(v, (str, int, float, bool)):
            extra[k] = v
    raw_evd = _safe_int(meta.get("expected_valid_days", 0))
    evd: int | None = raw_evd if raw_evd > 0 else None

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
        status=_status_from_metadata(meta),
        expected_valid_days=evd,
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        language=lang,
        merge_count=_safe_int(meta.get("merge_count", 0)),
        merge_history=str(meta.get("merge_history", "")),
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
        summary_l0=str(meta.get("summary_l0", "")),
        overview_l1=str(meta.get("overview_l1", "")),
        domain=_parse_domain(meta.get("domain")),
        domain_category=str(meta.get("domain_category", "")),
    )


def doc_to_conversation(
    doc: VectorDocument,
    *,
    include_raw: bool = False,
    config: MemoryConfig | None = None,
) -> ConversationMemory:
    """Convert VectorDocument to ConversationMemory."""
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
        status=_status_from_metadata(meta),
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
        summary_l0=str(meta.get("summary_l0", "")),
        overview_l1=str(meta.get("overview_l1", "")),
        domain=_parse_domain(meta.get("domain")),
        domain_category=str(meta.get("domain_category", "")),
    )


def semantic_to_doc(m: SemanticMemory) -> VectorDocument:
    """Convert SemanticMemory to VectorDocument."""
    payload: dict[str, str | int | float | bool | list[str]] = {
        "user_id": m.user_id,
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
        "tags": [t.lower() for t in m.tags],
        "language": m.language,
        "merge_count": m.merge_count,
        "merge_history": m.merge_history,
        "pinned": m.pinned,
        "status": m.status,
        "archived": m.status == "archived",
        "expected_valid_days": m.expected_valid_days if m.expected_valid_days is not None else 0,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        "summary_l0": m.summary_l0,
        "overview_l1": m.overview_l1,
        "domain": m.domain.value if hasattr(m.domain, "value") else str(m.domain),
        "domain_category": m.domain_category,
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
    """Convert EpisodicMemory to VectorDocument."""
    payload: dict[str, str | int | float | bool | list[str]] = {
        "user_id": m.user_id,
        "memory_type": MemoryType.EPISODIC.value,
        "event_type": m.event_type,
        "importance": m.importance,
        "source_chat_id": m.source_chat_id or "",
        "access_count": m.access_count,
        "user_rating": m.user_rating,
        "tags": [t.lower() for t in getattr(m, "tags", [])],
        "language": m.language,
        "merge_count": m.merge_count,
        "merge_history": m.merge_history,
        "pinned": m.pinned,
        "status": m.status,
        "archived": m.status == "archived",
        "expected_valid_days": m.expected_valid_days if m.expected_valid_days is not None else 0,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        "summary_l0": m.summary_l0,
        "overview_l1": m.overview_l1,
        "domain": m.domain.value if hasattr(m.domain, "value") else str(m.domain),
        "domain_category": m.domain_category,
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
