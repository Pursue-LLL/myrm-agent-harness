"""Embedding protocol — text to vector abstraction.

[INPUT]
- (none)

[OUTPUT]
- EmbeddingProtocol: class — Embedding Protocol

[POS]
Embedding protocol — text to vector abstraction.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProtocol(Protocol):
    @property
    def dimension(self) -> int: ...
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
