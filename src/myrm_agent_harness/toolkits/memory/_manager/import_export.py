"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._manager.shared import (
    EpisodicMemory,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
    logger,
)


class MemoryManagerImportExportMixin:
    # ── Export / Import ──

    async def export_all(self) -> dict[str, list[dict[str, object]]]:
        """Export all memories as serializable dicts (excludes embeddings for portability).

        Returns:
            Dict keyed by memory type with lists of serialized memory objects.
        """
        result: dict[str, list[dict[str, object]]] = {}

        for mem_type in MemoryType:
            if mem_type == MemoryType.TASK_DIGEST:
                continue
            try:
                memories = await self.list_memories(mem_type, limit=10000, include_archived=True)
                if memories:
                    serialized: list[dict[str, object]] = []
                    for m in memories:
                        data = m.model_dump(mode="json", exclude={"embedding"})
                        serialized.append(data)
                    result[mem_type.value] = serialized
            except Exception as e:
                logger.warning("Export failed for %s: %s", mem_type.value, e)

        return result

    async def import_memories(
        self, data: dict[str, list[dict[str, object]]], *, skip_duplicates: bool = True
    ) -> dict[str, int]:
        """Import memories from exported data, recomputing embeddings.

        Deduplication happens via ``store_batch`` when ``skip_duplicates`` is True
        and a deduplicator is configured. Profile entries are upserted via the
        relational backend directly.

        Args:
            data: Dict keyed by memory type with lists of serialized memory objects.
            skip_duplicates: When True (default), deduplicator filters duplicates.

        Returns:
            Dict with import counts per memory type.
        """
        counts: dict[str, int] = {}

        type_parsers: dict[str, type[SemanticMemory | EpisodicMemory | ProceduralMemory]] = {
            MemoryType.SEMANTIC.value: SemanticMemory,
            MemoryType.EPISODIC.value: EpisodicMemory,
            MemoryType.PROCEDURAL.value: ProceduralMemory,
        }

        saved_dedup = self._deduplicator
        if not skip_duplicates:
            self._deduplicator = None

        try:
            for type_name, entries in data.items():
                parser = type_parsers.get(type_name)
                if parser is None:
                    if type_name == MemoryType.PROFILE.value and self._relational:
                        imported = 0
                        for entry in entries:
                            try:
                                meta = entry.get("metadata") or {}
                                key = str(entry.get("key", "") or meta.get("key", ""))
                                value = entry.get("value", "") or meta.get("value", "")
                                if key:
                                    await self._relational.set_profile(key, str(value), scope=self._scope)
                                    imported += 1
                            except Exception as e:
                                logger.warning("Import profile entry failed: %s", e)
                        counts[type_name] = imported
                    continue

                memories: list[SemanticMemory | EpisodicMemory | ProceduralMemory] = []
                for entry in entries:
                    try:
                        clean = {k: v for k, v in entry.items() if k not in ("id", "embedding")}
                        mem = parser.model_validate(clean)
                        memories.append(mem)
                    except Exception as e:
                        logger.warning("Import parse failed for %s entry: %s", type_name, e)

                if memories:
                    try:
                        stored = await self.store_batch(memories)
                        counts[type_name] = len(stored)
                    except Exception as e:
                        logger.warning("Import batch store failed for %s: %s", type_name, e)
                        counts[type_name] = 0
                else:
                    counts[type_name] = 0
        finally:
            self._deduplicator = saved_dedup

        return counts
