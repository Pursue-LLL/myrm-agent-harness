"""Reranker Service Base Interface.

Abstract interface for reranking services, defining a unified reranking API.
All implementations (FastEmbed, Cloud API, etc.) must implement this interface.

[INPUT]
(no external module dependencies — pure ABC + dataclass)

[OUTPUT]
RerankResult: Dataclass holding index, score, and text of a reranked document
RerankerService: Abstract base class for all reranker backends

[POS]
Reranker contract layer. Declares the abstract interface and result type that every
reranker backend must implement.

"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RerankResult:
    """rerankingresult"""

    index: int  # originaldocumentindex
    score: float  # rerank score
    text: str  # documenttext


class RerankerService(ABC):
    """rerankingserviceabstractinterface

    allrerankingserviceimplementationallrequiredinheritsthisclassandimplementationabstractmethod.
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """rerankingdocument

        Args:
            query: Query text
            documents: documenttextlist
            top_k: returns top k result, None means return all

        Returns:
            reranked results sorted by score descendingsortresultlist
        """
        ...

    async def rerank_pairs(
        self,
        pairs: list[tuple[str, str]],
    ) -> list[float]:
        """batchreranking query-document pairs

        defaultImplementation:forcalls rerank.
        classcanwithoverridesthismethodwithprovidesefficient'sbatchimplementation.

        Args:
            pairs: (query, document) forlist

        Returns:
            forshouldeach pair 'srerank scorelist
        """
        scores = []
        for query, doc in pairs:
            results = await self.rerank(query, [doc], top_k=1)
            scores.append(results[0].score if results else 0.0)
        return scores
