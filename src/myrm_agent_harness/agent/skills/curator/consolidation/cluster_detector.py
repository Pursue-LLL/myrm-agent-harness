"""Skill cluster detection for consolidation.

Identifies groups of semantically similar skills that are candidates for
umbrella merging. Uses a hybrid approach:
1. Prefix-based grouping (fast, deterministic)
2. Embedding-based semantic clustering (comprehensive, catches synonym patterns)

[INPUT]
- backends.skills.types::SkillMetadata (POS: Skill system core data types.)
- toolkits.retriever.embedding.base::EmbeddingService (POS: Embedding contract layer.)
- .types::SkillCluster (POS: Data types for skill consolidation system.)

[OUTPUT]
- ClusterDetector: Detects candidate skill clusters for consolidation.

[POS]
Cluster detection layer for the skill consolidation system.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from itertools import combinations
from types import ModuleType
from typing import TYPE_CHECKING

from .types import SkillCluster

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService

logger = logging.getLogger(__name__)

_MIN_CLUSTER_SIZE = 3
_SIMILARITY_THRESHOLD = 0.75
_PREFIX_MIN_LENGTH = 3


def _require_numpy() -> ModuleType:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "numpy is required for skill cluster detection. Install myrm-agent-harness[retrieval]."
        ) from exc
    return np


class ClusterDetector:
    """Detects candidate skill clusters for umbrella merging.

    Two-pass strategy:
    1. Prefix pass: Groups skills sharing a common name prefix (e.g. "git-*", "deploy-*").
       Fast, deterministic, catches obvious families.
    2. Embedding pass: Computes pairwise cosine similarity on skill descriptions,
       then applies single-linkage clustering above threshold.
       Catches semantic families that differ in naming.

    Deduplicates clusters from both passes before returning.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        *,
        min_cluster_size: int = _MIN_CLUSTER_SIZE,
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
    ) -> None:
        self._embeddings = embedding_service
        self._min_cluster_size = min_cluster_size
        self._similarity_threshold = similarity_threshold

    async def detect(self, skills: list[SkillMetadata]) -> list[SkillCluster]:
        """Detect skill clusters from a list of active skills.

        Args:
            skills: Active, non-pinned skills to analyze.

        Returns:
            Deduplicated list of SkillClusters meeting minimum size.
        """
        if len(skills) < self._min_cluster_size:
            return []

        prefix_clusters = self._detect_prefix_clusters(skills)
        embedding_clusters = await self._detect_embedding_clusters(skills)

        merged = self._deduplicate_clusters(prefix_clusters, embedding_clusters)

        logger.info(
            "ClusterDetector: %d prefix clusters + %d embedding clusters → %d merged",
            len(prefix_clusters),
            len(embedding_clusters),
            len(merged),
        )
        return merged

    def _detect_prefix_clusters(self, skills: list[SkillMetadata]) -> list[SkillCluster]:
        """Group skills by shared name prefix."""
        prefix_groups: dict[str, list[SkillMetadata]] = defaultdict(list)

        for skill in skills:
            name = skill.name.lower().removesuffix("_skill")
            prefix = self._extract_prefix(name)
            if prefix and len(prefix) >= _PREFIX_MIN_LENGTH:
                prefix_groups[prefix].append(skill)

        clusters: list[SkillCluster] = []
        for prefix, group in prefix_groups.items():
            if len(group) < self._min_cluster_size:
                continue

            skill_names = tuple(s.name for s in group)
            clusters.append(
                SkillCluster(
                    cluster_id=f"prefix-{prefix}",
                    skill_names=skill_names,
                    shared_domain=prefix.replace("-", " ").replace("_", " "),
                    avg_similarity=1.0,
                    representative_keywords=(prefix,),
                )
            )

        return clusters

    async def _detect_embedding_clusters(self, skills: list[SkillMetadata]) -> list[SkillCluster]:
        """Cluster skills by embedding similarity using single-linkage."""
        np = _require_numpy()
        corpus = [f"{s.name} {s.description}" for s in skills]

        batch_size = 50
        all_vectors: list[list[float]] = []
        for i in range(0, len(corpus), batch_size):
            batch = corpus[i : i + batch_size]
            batch_vectors = await self._embeddings.embed_batch(batch)
            all_vectors.extend(batch_vectors)

        vectors: npt.NDArray[np.float64] = np.array(all_vectors, dtype=np.float64)
        sim_matrix = self._cosine_similarity_matrix(vectors)

        clusters = self._single_linkage_cluster(sim_matrix, skills)
        return clusters

    def _cosine_similarity_matrix(self, vectors: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Compute pairwise cosine similarity matrix."""
        np = _require_numpy()
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        normalized = vectors / norms
        return np.dot(normalized, normalized.T)

    def _single_linkage_cluster(
        self,
        sim_matrix: npt.NDArray[np.float64],
        skills: list[SkillMetadata],
    ) -> list[SkillCluster]:
        """Apply complete-linkage clustering above similarity threshold.

        A node joins a cluster only if its similarity to ALL existing members
        meets the threshold. This prevents chaining effects where unrelated
        skills get connected through intermediate nodes.
        """
        n = len(skills)
        assigned = [False] * n
        clusters: list[SkillCluster] = []
        max_cluster_size = 8

        for i in range(n):
            if assigned[i]:
                continue

            cluster_indices = [i]
            assigned[i] = True

            for j in range(i + 1, n):
                if assigned[j]:
                    continue
                if len(cluster_indices) >= max_cluster_size:
                    break

                meets_all = all(
                    sim_matrix[j, member] >= self._similarity_threshold
                    for member in cluster_indices
                )
                if meets_all:
                    cluster_indices.append(j)
                    assigned[j] = True

            if len(cluster_indices) < self._min_cluster_size:
                continue

            cluster_skills = [skills[idx] for idx in cluster_indices]
            skill_names = tuple(s.name for s in cluster_skills)

            pair_sims = [
                float(sim_matrix[a, b])
                for a, b in combinations(cluster_indices, 2)
            ]
            avg_sim = sum(pair_sims) / len(pair_sims) if pair_sims else 0.0

            domain = self._infer_domain(cluster_skills)
            keywords = self._extract_keywords(cluster_skills)

            clusters.append(
                SkillCluster(
                    cluster_id=f"semantic-{domain.replace(' ', '-')[:20]}",
                    skill_names=skill_names,
                    shared_domain=domain,
                    avg_similarity=round(avg_sim, 3),
                    representative_keywords=keywords,
                )
            )

        return clusters

    def _deduplicate_clusters(
        self,
        prefix_clusters: list[SkillCluster],
        embedding_clusters: list[SkillCluster],
    ) -> list[SkillCluster]:
        """Merge overlapping clusters, preferring the one with higher similarity."""
        result: list[SkillCluster] = list(prefix_clusters)
        existing_skill_sets = [set(c.skill_names) for c in result]

        for ec in embedding_clusters:
            ec_set = set(ec.skill_names)
            is_subset = any(ec_set <= existing for existing in existing_skill_sets)
            if is_subset:
                continue

            overlaps_significantly = any(
                len(ec_set & existing) / max(len(ec_set), len(existing)) > 0.7
                for existing in existing_skill_sets
            )
            if overlaps_significantly:
                continue

            result.append(ec)
            existing_skill_sets.append(ec_set)

        return result

    @staticmethod
    def _extract_prefix(name: str) -> str:
        """Extract a meaningful prefix from a skill name."""
        parts = re.split(r"[-_]", name)
        if len(parts) >= 2:
            return parts[0]
        return ""

    @staticmethod
    def _infer_domain(skills: list[SkillMetadata]) -> str:
        """Infer a shared domain label from skill names/descriptions."""
        names = [s.name.lower().removesuffix("_skill") for s in skills]
        prefixes = [re.split(r"[-_]", n)[0] for n in names if re.split(r"[-_]", n)]
        if prefixes:
            from collections import Counter
            most_common = Counter(prefixes).most_common(1)
            if most_common:
                return most_common[0][0]
        return "mixed"

    @staticmethod
    def _extract_keywords(skills: list[SkillMetadata]) -> tuple[str, ...]:
        """Extract top shared keywords from descriptions."""
        from collections import Counter

        word_counts: Counter[str] = Counter()
        stop_words = {"the", "a", "an", "is", "are", "to", "for", "and", "of", "in", "with"}

        for skill in skills:
            words = set(skill.description.lower().split())
            words -= stop_words
            word_counts.update(words)

        top_words = [w for w, _ in word_counts.most_common(5) if len(w) >= 3]
        return tuple(top_words[:5])
