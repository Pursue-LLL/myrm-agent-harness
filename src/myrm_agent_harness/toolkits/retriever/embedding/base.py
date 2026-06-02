"""Embedding Service Base Interface.

Abstract interface for vector embedding services, defining a unified embedding API.
Also satisfies MemoryManager's EmbeddingProtocol (embed / embed_batch / dimension).

[INPUT]
(no external module dependencies — pure ABC)

[OUTPUT]
EmbeddingService: Abstract base class for all embedding backends

[POS]
Embedding contract layer. Declares the abstract interface that every embedding backend
(cloud, local, cached) must implement.

"""

from abc import ABC, abstractmethod


class EmbeddingService(ABC):
    """VectorEmbeddingServiceAbstractInterface

    AllEmbeddingServiceimplements都 must 继承此类并implementsAbstractMethod。
    Interface and  ``EmbeddingProtocol``  completely 一致，可 directly 传给 ``MemoryManager``。
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """ReturnEmbeddingVectorDimension"""
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embeddingsingletext

        Args:
            text: inputtext

        Returns:
            EmbeddingVector
        """
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量Embeddingtext

        Args:
            texts: textList

        Returns:
            EmbeddingVectorList
        """
        ...
