"""Storage converter round-trips — the payload must give every field back.

The dense and the sparse-mirror read paths share ``doc_to_semantic`` /
``doc_to_episodic``, so a payload field the read converters skip disappears
from listings, searches and tag statistics in *both* modes. These tests pin
the  round-trip for the tag list, which ``semantic_to_doc`` keeps under a
single lowercased ``tags`` key that is excluded from the free-form metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
    doc_to_episodic,
    doc_to_semantic,
    episodic_to_doc,
    semantic_to_doc,
)
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory
from myrm_agent_harness.toolkits.vector.base import VectorDocument


def _doc(metadata: dict[str, object], *, created_at: datetime | None = None) -> VectorDocument:
    now = created_at or datetime.now(UTC)
    return VectorDocument(
        id="doc-1",
        content="TypeScript strict 模式",
        vector=None,
        metadata=metadata,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )


def test_semantic_roundtrip_keeps_tags() -> None:
    memory = SemanticMemory(
        id="sem-1",
        user_id="sandbox_user",
        content="TypeScript strict 模式更安全",
        importance=0.7,
        tags=["CodeStyle", "编辑器"],
    )

    restored = doc_to_semantic(semantic_to_doc(memory))

    assert restored.id == "sem-1"
    assert restored.content == "TypeScript strict 模式更安全"
    assert restored.importance == pytest.approx(0.7)
    assert restored.tags == ["codestyle", "编辑器"]


def test_episodic_roundtrip_keeps_its_own_fields() -> None:
    memory = EpisodicMemory(
        id="epi-1",
        user_id="sandbox_user",
        content="用户在会话中确认了代码风格",
        event_type="decision",
        related_entities=["TypeScript"],
    )

    restored = doc_to_episodic(episodic_to_doc(memory))

    assert restored.id == "epi-1"
    assert restored.event_type == "decision"
    assert restored.related_entities == ["TypeScript"]


def test_semantic_documents_without_tags_read_as_empty() -> None:
    restored = doc_to_semantic(_doc({"user_id": "sandbox_user", "importance": 0.5}))

    assert restored.tags == []


def test_malformed_tag_metadata_reads_as_empty() -> None:
    """Legacy payloads may carry a string or blank entries; never leak non-strings."""
    from_string = doc_to_semantic(_doc({"user_id": "sandbox_user", "tags": "not-a-list"}))
    from_blanks = doc_to_semantic(_doc({"user_id": "sandbox_user", "tags": ["", "  "]}))
    from_scalars = doc_to_semantic(_doc({"user_id": "sandbox_user", "tags": 7}))

    assert from_string.tags == []
    assert from_blanks.tags == []
    assert from_scalars.tags == []


def test_read_converter_keeps_timestamps_and_domain() -> None:
    created = datetime.now(UTC) - timedelta(days=3)
    doc = _doc({"user_id": "sandbox_user", "domain": "user"}, created_at=created)

    restored = doc_to_semantic(doc)

    assert restored.created_at == created
    assert restored.domain.value == "user"
