"""Vector store protocol for memory system.


Re-exports types from ``toolkits.vector.base`` and defines the
``VectorStoreProtocol`` — the duck-typed interface that any vector
backend must satisfy to work with the memory system.

[INPUT]
myrm_agent_harness.toolkits.vector.base (POS: Vector storage abstraction layer)

[OUTPUT]
VectorStoreProtocol: Protocol for memory vector backends
VectorDocument, VectorSearchResult, FilterValue, FilterDict: Re-exports

[POS]
Memory-system vector store protocol. Defines the vector operation interface required by the memory module; types are unified via toolkits.vector.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.vector.base import (
    FilterDict,
    FilterValue,
    VectorDocument,
)
from myrm_agent_harness.toolkits.vector.base import SearchResult as VectorSearchResult

__all__ = [
    "FilterDict",
    "FilterValue",
    "VectorDocument",
    "VectorSearchResult",
    "VectorStoreProtocol",
]


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Full-CRUD vector storage for memory embeddings.

    Any class implementing these methods (duck typing) can serve as
    the vector backend for the memory system.
    """

    async def upsert(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]: ...

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]: ...

    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]: ...

    async def delete(self, collection: str, ids: list[str]) -> int: ...

    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int: ...

    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
        order_by: tuple[str, str] | None = None,
    ) -> tuple[list[VectorDocument], str | None]: ...

    async def ensure_collection(self, name: str, dimension: int, *, distance: str = "cosine") -> None: ...

    async def count(self, collection: str, filters: FilterDict | None = None) -> int: ...

    async def health_check(self) -> bool: ...

    async def close(self) -> None: ...
