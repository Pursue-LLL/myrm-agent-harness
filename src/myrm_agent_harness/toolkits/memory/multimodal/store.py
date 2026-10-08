"""Memory store for indexing and retrieving multimodal items and artifacts.

[INPUT]
- memory.multimodal.models::{MultimodalMemoryItem, AssetModality} (POS: data contracts of the multimodal memory package)

[OUTPUT]
- MultimodalMemoryStore: In-memory repository of multimodal memory items (add, get, delete, list by session and modality, count, clear); no locking

[POS]
Storage layer of the multimodal memory package; the orchestrator owns one instance and the retriever scans it.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.multimodal.models import (
    AssetModality,
    MultimodalMemoryItem,
)


class MultimodalMemoryStore:
    """In-memory indexing store for multimodal assets with session scoping."""

    def __init__(self) -> None:
        self._items: dict[str, MultimodalMemoryItem] = {}

    def add(self, item: MultimodalMemoryItem) -> None:
        """Store or update a multimodal memory item."""
        self._items[item.item_id] = item

    def get(self, item_id: str) -> MultimodalMemoryItem | None:
        """Retrieve item by its unique identifier."""
        return self._items.get(item_id)

    def delete(self, item_id: str) -> bool:
        """Remove item by its unique identifier."""
        return self._items.pop(item_id, None) is not None

    def list_all(
        self,
        session_id: str | None = None,
        modality: AssetModality | None = None,
    ) -> Sequence[MultimodalMemoryItem]:
        """List items matching optional session and modality constraints."""
        results: list[MultimodalMemoryItem] = []
        for item in self._items.values():
            if session_id is not None and item.session_id != session_id:
                continue
            if modality is not None and item.modality != modality:
                continue
            results.append(item)
        return results

    def clear(self) -> None:
        """Reset internal store state."""
        self._items.clear()

    def count(self) -> int:
        """Return total count of indexed items."""
        return len(self._items)
