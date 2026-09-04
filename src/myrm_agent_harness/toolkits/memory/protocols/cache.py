"""Embedding cache protocol — optional caching layer.

[INPUT]
- (none)

[OUTPUT]
- EmbeddingCacheProtocol: class — Embedding Cache Protocol

[POS]
Embedding cache protocol — optional caching layer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingCacheProtocol(Protocol):
    async def get(self, text: str) -> list[float] | None: ...
    async def put(self, text: str, embedding: list[float]) -> None: ...
    async def get_batch(self, texts: list[str]) -> list[list[float] | None]: ...
    async def put_batch(self, texts: list[str], embeddings: list[list[float]]) -> None: ...
    async def evict(self, text: str) -> bool: ...
    async def evict_batch(self, texts: list[str]) -> int: ...
    async def clear(self) -> None: ...
