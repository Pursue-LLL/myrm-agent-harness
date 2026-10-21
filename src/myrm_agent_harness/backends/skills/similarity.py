"""Skill similarity checking protocol.

[INPUT]
- typing::Protocol, runtime_checkable (POS: Python protocol types)

[OUTPUT]
- SimilarSkillInfo: Dataclass for a similar skill match result.
- SkillSimilarityChecker: Protocol for checking semantic similarity between skills.

[POS]
Skill similarity checking protocol. Defines the interface for detecting semantically
similar skills during creation, preventing skill entropy (accumulation of functionally
duplicate skills with different names).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SimilarSkillInfo:
    """A single similar skill match result."""

    name: str
    description: str
    similarity_score: float


@runtime_checkable
class SkillSimilarityChecker(Protocol):
    """Protocol for checking semantic similarity between skills.

    Used by skill_manage_tool to warn agents about existing similar skills
    before creating duplicates. Business layer provides the implementation
    (typically using HybridSkillSearchEngine or EmbeddingService).

    Example:
        >>> checker: SkillSimilarityChecker = MyChecker(...)
        >>> similar = await checker.find_similar("deploy-frontend", "Deploy a React app")
        >>> for s in similar:
        ...     print(f"{s.name}: {s.similarity_score:.2f}")
    """

    async def find_similar(
        self,
        name: str,
        description: str,
        *,
        top_k: int = 3,
        threshold: float = 0.6,
    ) -> list[SimilarSkillInfo]:
        """Find skills semantically similar to the given name and description.

        Args:
            name: Proposed skill name.
            description: Proposed skill description.
            top_k: Maximum number of similar skills to return.
            threshold: Minimum similarity score (0.0–1.0) to include in results.

        Returns:
            List of similar skills sorted by descending similarity score.
            Empty list if no skills exceed the threshold.
        """
        ...
