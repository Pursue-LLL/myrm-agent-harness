"""[INPUT]
- toolkits.vector.base::VectorDocument (POS: Vector store abstraction layer. Defines backend-agnostic vector store interface and data models, inherited by all vector store implementations.)

[OUTPUT]
- ArchivalCandidate: Memory candidate for archival with scoring details.
- ArchivalStrategy: Protocol for memory archival decision strategies.
- TimeBasedArchivalStrategy: Time-based archival strategy with access frequency and im...
- ArchivalResult: Result of archival operation.
- find_archival_candidates: Find memories eligible for archival based on strategy.

[POS]
Provides ArchivalCandidate, ArchivalStrategy, TimeBasedArchivalStrategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from myrm_agent_harness.toolkits.memory.protocols import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.types import MemoryType
from myrm_agent_harness.toolkits.vector.base import VectorDocument

"""Memory archival system for long-term storage management.

Moves old, rarely-accessed memories to archival collections to:
- Improve search performance (smaller active corpus)
- Reduce BM25 index size
- Preserve historical data without deletion
- Allow dedicated archival search when needed

Zero-LLM-cost implementation using time + access + importance scoring.
"""


@dataclass(frozen=True, slots=True)
class ArchivalCandidate:
    """Memory candidate for archival with scoring details.

    Attributes:
        memory_id: Memory ID
        memory_type: Memory type
        age_days: Days since creation
        access_count: Total access count
        importance: Importance score (0.0-1.0)
        archival_score: Composite score (higher = more archival-worthy)
    """

    memory_id: str
    memory_type: MemoryType
    age_days: float
    access_count: int
    importance: float
    archival_score: float


class ArchivalStrategy(Protocol):
    """Protocol for memory archival decision strategies.

    Allows custom implementations for different archival criteria
    (time-based, ML-based, user-defined, etc.).
    """

    def should_archive(self, age_days: float, access_count: int, importance: float) -> tuple[bool, float]:
        """Determine if a memory should be archived.

        Args:
            age_days: Days since memory creation
            access_count: Total access count
            importance: Importance score (0.0-1.0)

        Returns:
            (should_archive, archival_score) tuple
        """
        ...


class TimeBasedArchivalStrategy:
    """Time-based archival strategy with access frequency and importance weighting.

    Archival criteria (all must be met):
    - Age ≥ min_age_days (default 180 days / 6 months)
    - Access count ≤ max_access_count (default 5 times)
    - Importance ≤ max_importance (default 0.3 / low priority)

    Composite score = age_weight × age_score + access_weight × access_score + importance_weight × importance_score
    Higher score = higher archival priority.
    """

    def __init__(
        self,
        min_age_days: float = 180.0,
        max_access_count: int = 5,
        max_importance: float = 0.3,
        age_weight: float = 0.5,
        access_weight: float = 0.3,
        importance_weight: float = 0.2,
    ) -> None:
        """Initialize time-based archival strategy.

        Args:
            min_age_days: Minimum age for archival eligibility
            max_access_count: Maximum access count for archival
            max_importance: Maximum importance for archival
            age_weight: Age factor weight in composite score
            access_weight: Access frequency weight in composite score
            importance_weight: Importance weight in composite score (inverted)
        """
        self.min_age_days = min_age_days
        self.max_access_count = max_access_count
        self.max_importance = max_importance
        self.age_weight = age_weight
        self.access_weight = access_weight
        self.importance_weight = importance_weight

    def should_archive(self, age_days: float, access_count: int, importance: float) -> tuple[bool, float]:
        """Time-based archival decision with composite scoring."""
        if age_days < self.min_age_days:
            return False, 0.0
        if access_count > self.max_access_count:
            return False, 0.0
        if importance > self.max_importance:
            return False, 0.0

        age_score = min(age_days / (self.min_age_days * 2), 1.0)
        access_score = 1.0 - min(access_count / self.max_access_count, 1.0)
        importance_score = 1.0 - importance

        composite_score = (
            self.age_weight * age_score + self.access_weight * access_score + self.importance_weight * importance_score
        )

        return True, composite_score


@dataclass(frozen=True, slots=True)
class ArchivalResult:
    """Result of archival operation.

    Attributes:
        archived_count: Number of memories archived
        candidates: List of archival candidates (for audit/logging)
        duration_ms: Operation duration in milliseconds
    """

    archived_count: int
    candidates: list[ArchivalCandidate]
    duration_ms: float


async def find_archival_candidates(
    vector: VectorStoreProtocol,
    strategy: ArchivalStrategy,
    memory_types: list[MemoryType] | None = None,
    limit: int = 100,
    namespaces: list[str] | None = None,
) -> list[ArchivalCandidate]:
    """Find memories eligible for archival based on strategy.

    Args:
        vector: Vector store protocol
        strategy: Archival strategy implementation
        memory_types: Memory types to consider (default: all vector-backed types)
        limit: Maximum candidates to return
        namespaces: Optional namespace boundary for candidate discovery

    Returns:
        List of archival candidates sorted by score (descending)
    """

    if memory_types is None:
        memory_types = [MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.CONVERSATION]

    candidates: list[ArchivalCandidate] = []
    now = datetime.now(UTC)

    for mem_type in memory_types:
        collection = f"memory_{mem_type.value}"

        try:
            results = await vector.search(
                collection=collection,
                query_vector=None,
                limit=1000,
                score_threshold=0.0,
                filter_conditions={} if not namespaces else {"namespaces": namespaces},
            )

            for doc in results:
                created_at = doc.metadata.get("created_at")
                if not created_at:
                    continue

                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

                age_days = (now - created_at).total_seconds() / 86400
                access_count = doc.metadata.get("access_count", 0)
                importance = doc.metadata.get("importance", 0.5)

                should_archive, score = strategy.should_archive(age_days, access_count, importance)

                if should_archive:
                    candidates.append(
                        ArchivalCandidate(
                            memory_id=doc.id,
                            memory_type=mem_type,
                            age_days=age_days,
                            access_count=access_count,
                            importance=importance,
                            archival_score=score,
                        )
                    )
        except Exception:
            continue

    candidates.sort(key=lambda c: c.archival_score, reverse=True)
    return candidates[:limit]


async def archive_memories(candidates: list[ArchivalCandidate], vector: VectorStoreProtocol) -> ArchivalResult:
    """Archive memories by moving them to archival collections.

    Archival collection naming: `{collection}_archived`
    Example: `memory_semantic` → `memory_semantic_archived`

    Args:
        user_id: User ID
        candidates: Archival candidates to process
        vector: Vector store protocol

    Returns:
        Archival operation result with statistics
    """

    start = datetime.now(UTC)
    archived_count = 0

    for candidate in candidates:
        source_collection = f"memory_{candidate.memory_type.value}"
        target_collection = f"memory_{candidate.memory_type.value}_archived"

        try:
            doc = await vector.get(collection=source_collection, doc_id=candidate.memory_id)
            if not doc:
                continue

            doc.metadata["archived_at"] = datetime.now(UTC).isoformat()

            await vector.upsert(collection=target_collection, documents=[doc])

            await vector.delete(collection=source_collection, doc_ids=[candidate.memory_id])

            archived_count += 1
        except Exception:
            continue

    duration_ms = (datetime.now(UTC) - start).total_seconds() * 1000

    return ArchivalResult(archived_count=archived_count, candidates=candidates, duration_ms=duration_ms)


async def search_archived_memories(
    query_vector: list[float],
    memory_type: MemoryType,
    vector: VectorStoreProtocol,
    limit: int = 10,
    namespaces: list[str] | None = None,
) -> list[VectorDocument]:
    """Search archived memories (dedicated API for historical data access).

    Args:
        query_vector: Query embedding
        memory_type: Memory type to search
        vector: Vector store protocol
        limit: Maximum results
        namespaces: Optional namespace boundary

    Returns:
        List of archived memory documents
    """

    collection = f"memory_{memory_type.value}_archived"

    return await vector.search(
        collection=collection,
        query_vector=query_vector,
        limit=limit,
        score_threshold=0.0,
        filter_conditions={} if not namespaces else {"namespaces": namespaces},
    )


async def unarchive_memories(memory_ids: list[str], memory_type: MemoryType, vector: VectorStoreProtocol) -> int:
    """Restore archived memories to active collections.

    Args:
        user_id: User ID
        memory_ids: Memory IDs to restore
        memory_type: Memory type
        vector: Vector store protocol

    Returns:
        Number of memories restored
    """

    source_collection = f"memory_{memory_type.value}_archived"
    target_collection = f"memory_{memory_type.value}"
    restored_count = 0

    for memory_id in memory_ids:
        try:
            doc = await vector.get(collection=source_collection, doc_id=memory_id)
            if not doc:
                continue

            if "archived_at" in doc.metadata:
                del doc.metadata["archived_at"]
            doc.metadata["restored_at"] = datetime.now(UTC).isoformat()

            await vector.upsert(collection=target_collection, documents=[doc])

            await vector.delete(collection=source_collection, doc_ids=[memory_id])

            restored_count += 1
        except Exception:
            continue

    return restored_count
