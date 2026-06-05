"""Archive checkpoint persistence via EpisodicMemory."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Protocol

from myrm_agent_harness.toolkits.memory._internal.storage import doc_to_episodic
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, RuleSource
from myrm_agent_harness.toolkits.vector.base import VectorDocument

from .types import ARCHIVE_CHECKPOINT_EVENT_TYPE, ArchiveCheckpointRecord

logger = logging.getLogger(__name__)

_CHECKPOINT_PATH_RE = re.compile(r"path=([^)\n]+)")


def _related_entities_from_doc(doc: VectorDocument) -> list[str]:
    raw = doc.metadata.get("related_entities", [])
    return raw if isinstance(raw, list) else []


def _archive_path_from_doc(doc: VectorDocument, content: str) -> str:
    entities = _related_entities_from_doc(doc)
    for entity in entities:
        if "/" in entity:
            return entity
    match = _CHECKPOINT_PATH_RE.search(content)
    return match.group(1).strip() if match else ""


def _tool_name_from_doc(doc: VectorDocument, content: str, entities: list[str]) -> str:
    for entity in entities:
        if entity.startswith("tool_call:"):
            continue
        if "/" not in entity:
            return entity
    match = re.search(r"tool=([^,\)]+)", content)
    return match.group(1).strip() if match else "tool"


class ArchiveCheckpointStore(Protocol):
    """Store offload archive summaries into durable memory."""

    async def store_checkpoint(
        self,
        *,
        tool_name: str,
        archive_path: str,
        summary: str,
        chat_id: str,
        tool_call_id: str | None = None,
    ) -> ArchiveCheckpointRecord: ...

    async def find_by_archive_path(
        self,
        chat_id: str,
        archive_path: str,
    ) -> ArchiveCheckpointRecord | None: ...


class EpisodicMemoryArchiveCheckpointStore:
    """Default store writing ``event_type=archive_checkpoint`` episodic memories."""

    def __init__(self, manager: MemoryManager) -> None:
        self._manager = manager

    async def store_checkpoint(
        self,
        *,
        tool_name: str,
        archive_path: str,
        summary: str,
        chat_id: str,
        tool_call_id: str | None = None,
    ) -> ArchiveCheckpointRecord:
        existing = await self.find_by_archive_path(chat_id, archive_path)
        if existing is not None:
            return existing

        entities = [tool_name, archive_path]
        if tool_call_id:
            entities.append(f"tool_call:{tool_call_id}")

        content = f"Archive checkpoint (tool={tool_name}, path={archive_path}):\n{summary.strip()}"
        memory = EpisodicMemory(
            content=content,
            source=RuleSource.AGENT_SELF,
            session_id=chat_id,
            source_chat_id=chat_id,
            event_type=ARCHIVE_CHECKPOINT_EVENT_TYPE,
            related_entities=entities,
            importance=0.85,
        )
        stored = await self._manager.store(memory, _bypass_approval=True)
        memory_id = stored.id if isinstance(stored, EpisodicMemory) else memory.id
        return ArchiveCheckpointRecord(
            memory_id=memory_id,
            tool_name=tool_name,
            archive_path=archive_path,
            summary=summary.strip(),
            chat_id=chat_id,
            tool_call_id=tool_call_id,
        )

    async def find_by_archive_path(
        self,
        chat_id: str,
        archive_path: str,
    ) -> ArchiveCheckpointRecord | None:
        try:
            records = await list_recent_checkpoints(
                self._manager,
                chat_id=chat_id,
                limit=32,
            )
        except Exception as exc:
            logger.warning("[ArchiveCheckpoint] scroll lookup failed: %s", exc)
            return None

        for record in records:
            if record.archive_path == archive_path:
                return record
        return None


async def list_recent_checkpoints(
    manager: MemoryManager,
    *,
    chat_id: str,
    limit: int = 8,
) -> list[ArchiveCheckpointRecord]:
    """List recent archive checkpoints for a chat via vector scroll (not semantic search)."""
    if not manager.has_vector:
        return []
    vector = manager._vector
    if vector is None:
        return []
    try:
        docs, _ = await vector.scroll(
            manager._config.episodic_collection,
            limit=max(limit * 4, 16),
            filters={"event_type": ARCHIVE_CHECKPOINT_EVENT_TYPE},
        )
    except Exception as exc:
        logger.warning("[ArchiveCheckpoint] scroll failed: %s", exc)
        return []

    records: list[tuple[datetime, ArchiveCheckpointRecord]] = []
    for doc in docs:
        memory = doc_to_episodic(doc)
        session = memory.source_chat_id or memory.session_id
        if session != chat_id:
            continue
        entities = _related_entities_from_doc(doc)
        archive_path = _archive_path_from_doc(doc, memory.content)
        if not archive_path:
            continue
        records.append(
            (
                memory.created_at,
                ArchiveCheckpointRecord(
                    memory_id=memory.id,
                    tool_name=_tool_name_from_doc(doc, memory.content, entities),
                    archive_path=archive_path,
                    summary=_extract_summary_body(memory.content),
                    chat_id=chat_id,
                    tool_call_id=_tool_call_id_from_entities(entities),
                ),
            )
        )

    records.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in records[:limit]]


def tool_name_from_entities(entities: list[str], *, default: str) -> str:
    for entity in entities:
        if entity.startswith("tool_call:"):
            continue
        if "/" not in entity:
            return entity
    return default


def _tool_call_id_from_entities(entities: list[str]) -> str | None:
    for entity in entities:
        if entity.startswith("tool_call:"):
            return entity.split(":", 1)[1]
    return None


def _extract_summary_body(content: str) -> str:
    marker = "):\n"
    if marker in content:
        return content.split(marker, 1)[1].strip()
    return content.strip()
