"""Vector store synchronization for skill evolution.

Handles bidirectional sync between SQLite (source of truth) and
Qdrant vector store (semantic search layer).

[INPUT]
- toolkits.vector.base::VectorStore, VectorDocument (POS: Abstract interface for vector databases.)
- toolkits.memory.protocols.embedding::EmbeddingProtocol (POS: Protocol for text embedding models.)

[OUTPUT]
- SkillVectorSyncMixin: Mixin providing vector sync operations for SkillStore.

[POS]
Vector store synchronization for skill evolution system.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.vector.base import VectorDocument

if TYPE_CHECKING:
    from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord
    from myrm_agent_harness.toolkits.memory.protocols.embedding import (
        EmbeddingProtocol,
    )
    from myrm_agent_harness.toolkits.vector.base import VectorStore

logger = logging.getLogger(__name__)

__all__ = ["SkillVectorSyncMixin"]


def _build_embed_text(record: SkillRecord) -> str:
    """Build text for embedding from a skill record."""
    text = f"{record.name}\n{record.description}\n{record.content}"
    if record.traps:
        text += f"\nTraps: {', '.join(record.traps)}"
    return text


def _build_payload(record: SkillRecord) -> dict[str, str | int]:
    """Build Qdrant payload from a skill record."""
    payload = {
        "skill_id": record.skill_id,
        "name": record.name,
        "is_active": int(record.is_active),
        "os_platform": record.environment.os_platform if record.environment else None,
    }
    return {k: v for k, v in payload.items() if v is not None}


class SkillVectorSyncMixin:
    """Mixin providing vector store sync for SkillStore.

    Expects host class to have:
    - _vector_store: VectorStore | None
    - _embedding: EmbeddingProtocol | None
    - VECTOR_COLLECTION_NAME: str
    - _ensure_open(): None
    - _reader(): context manager yielding sqlite3.Connection
    - _row_to_record(dict) -> SkillRecord
    """

    _vector_store: VectorStore | None
    _embedding: EmbeddingProtocol | None
    VECTOR_COLLECTION_NAME: str

    async def _sync_skill_to_vector(self, record: SkillRecord) -> None:
        """Upsert a single active skill to the vector store."""
        if not self._vector_store or not self._embedding or not record.is_active:
            return

        try:
            text = _build_embed_text(record)
            vector = await self._embedding.embed(text)
            payload = _build_payload(record)
            doc = VectorDocument(
                id=record.skill_id, content=record.description or record.name, vector=vector, metadata=payload
            )
            await self._vector_store.upsert(self.VECTOR_COLLECTION_NAME, [doc])
        except Exception as e:
            logger.warning(f"Failed to sync skill {record.skill_id} to vector store: {e}")

    async def _delete_skill_from_vector(self, skill_id: str) -> None:
        """Delete a skill from the vector store."""
        if not self._vector_store:
            return

        try:
            await self._vector_store.delete(self.VECTOR_COLLECTION_NAME, [skill_id])
        except Exception as e:
            logger.warning(f"Failed to delete skill {skill_id} from vector store: {e}")

    async def sync_vectors(self) -> None:
        """Synchronize SQLite active skills with Vector Store.

        Should be called during startup to ensure Qdrant is up-to-date
        with the local SQLite database. Handles crash recovery and
        out-of-sync scenarios.
        """
        if not self._vector_store or not self._embedding:
            return

        self._ensure_open()  # type: ignore[attr-defined]

        try:
            with self._reader() as conn:  # type: ignore[attr-defined]
                rows = conn.execute("SELECT * FROM skills WHERE is_active = 1").fetchall()
                active_records = [
                    self._row_to_record(dict(row))  # type: ignore[attr-defined]
                    for row in rows
                ]

            if not active_records:
                return

            with contextlib.suppress(Exception):
                await self._vector_store.get_collection_info(self.VECTOR_COLLECTION_NAME)

            batch_size = 20
            for i in range(0, len(active_records), batch_size):
                batch = active_records[i : i + batch_size]
                texts = [_build_embed_text(r) for r in batch]
                vectors = await self._embedding.embed_batch(texts)

                docs = [
                    VectorDocument(
                        id=r.skill_id,
                        content=r.description or r.name,
                        vector=vec,
                        metadata=_build_payload(r),
                    )
                    for r, vec in zip(batch, vectors, strict=False)
                ]
                await self._vector_store.upsert(self.VECTOR_COLLECTION_NAME, docs)

            logger.info(f"Successfully synchronized {len(active_records)} skills to vector store.")
        except Exception as e:
            logger.error(f"Failed to synchronize vectors: {e}")
