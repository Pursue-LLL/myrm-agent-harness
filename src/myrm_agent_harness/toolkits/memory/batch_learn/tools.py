"""[POS]: src/myrm_agent_harness/toolkits/memory/batch_learn/tools.py
[INPUT]: Raw dict-based chunk structures and namespaced ID requests from LLM agents.
[OUTPUT]: BatchMemoryLearningMetaTools providing agent-callable batch extraction, inspection, and undo capabilities.
"""

from myrm_agent_harness.toolkits.memory.batch_learn.models import (
    BatchRawChunk,
    LearnedMemoryItem,
)
from myrm_agent_harness.toolkits.memory.batch_learn.service import (
    BatchMemoryLearningService,
)


class BatchMemoryLearningMetaTools:
    """Agent meta-tools for batch memory ingestion with item-level namespaced ID provenance and undo."""

    def __init__(self, service: BatchMemoryLearningService) -> None:
        self._service = service

    def batch_learn_from_chunks(
        self,
        chunks: list[dict[str, str | int]],
        scope: str = "default",
        sub_scope: str = "global",
        category: str = "general",
    ) -> dict[str, str | int | list[dict[str, str | int | float | list[str]]]]:
        """Extract memory items from an array of text chunks, returning per-item namespaced IDs."""
        raw_chunks = [
            BatchRawChunk(
                chunk_index=int(c.get("chunk_index", idx)),
                raw_text=str(c.get("raw_text", "")),
            )
            for idx, c in enumerate(chunks)
        ]

        report = self._service.learn_batch(
            chunks=raw_chunks,
            scope=scope,
            sub_scope=sub_scope,
            category=category,
        )

        serialized_items: list[dict[str, str | int | float | list[str]]] = [
            {
                "namespaced_id": item.namespaced_id,
                "chunk_index": item.chunk_index,
                "content": item.content,
                "tags": item.tags,
                "layer_recommendation": item.layer_recommendation,
                "status": item.status.value,
                "created_at": item.created_at,
            }
            for item in report.items
        ]

        serialized_diagnostics: list[dict[str, str | int | float | list[str]]] = [
            {
                "chunk_index": d.chunk_index,
                "status": d.status.value,
                "attempt_count": d.attempt_count,
                "elapsed_ms": d.elapsed_ms,
                "extracted_items_count": d.extracted_items_count,
            }
            for d in report.chunk_diagnostics
        ]

        return {
            "batch_id": report.batch_id,
            "total_chunks": report.total_chunks,
            "successful_chunks": report.successful_chunks,
            "retried_chunks": report.retried_chunks,
            "failed_chunks": report.failed_chunks,
            "total_items_learned": report.total_items_learned,
            "items": serialized_items,
            "chunk_diagnostics": serialized_diagnostics,
        }

    def undo_learned_memory_item(self, namespaced_id: str) -> dict[str, str | bool]:
        """Revoke a specific learned memory item by its namespaced ID without invalidating the batch."""
        success = self._service.undo_item_by_namespaced_id(namespaced_id)
        return {
            "success": success,
            "namespaced_id": namespaced_id,
            "message": (
                f"Memory item {namespaced_id} successfully revoked."
                if success
                else f"Memory item {namespaced_id} not found or already revoked."
            ),
        }

    def inspect_batch_learned_item(
        self, namespaced_id: str
    ) -> dict[str, str | int | float | list[str] | dict[str, str | int | float | bool]] | None:
        """Retrieve details of a single memory item using its namespaced ID."""
        item: LearnedMemoryItem | None = self._service.get_item_by_namespaced_id(namespaced_id)
        if not item:
            return None
        return {
            "namespaced_id": item.namespaced_id,
            "batch_id": item.batch_id,
            "chunk_index": item.chunk_index,
            "content": item.content,
            "tags": item.tags,
            "layer_recommendation": item.layer_recommendation,
            "status": item.status.value,
            "created_at": item.created_at,
            "provenance_meta": item.provenance_meta,
        }

    def list_batch_items(
        self, batch_id: str
    ) -> list[dict[str, str | int | float | list[str]]]:
        """List all individual items created under a specific batch ID."""
        items = self._service.list_items_by_batch(batch_id)
        return [
            {
                "namespaced_id": it.namespaced_id,
                "chunk_index": it.chunk_index,
                "content": it.content,
                "tags": it.tags,
                "layer_recommendation": it.layer_recommendation,
                "status": it.status.value,
                "created_at": it.created_at,
            }
            for it in items
        ]
