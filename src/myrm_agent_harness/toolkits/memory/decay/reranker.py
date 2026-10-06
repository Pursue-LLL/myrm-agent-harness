# [INPUT] Raw retrieval candidates with base similarity scores, and TieredStorageLifecycleManager.
# [OUTPUT] DecayAwareReranker ranking candidates with blended similarity and decay retention scores.
# [POS] myrm_agent_harness.toolkits.memory.decay.reranker

"""Decay-aware reranker blending vector similarity with Ebbinghaus retention weights."""

from myrm_agent_harness.toolkits.memory.decay.lifecycle_manager import (
    TieredStorageLifecycleManager,
)
from myrm_agent_harness.toolkits.memory.decay.types import (
    DecayRerankItem,
    StorageTier,
)


class DecayAwareReranker:
    """Reranks memory search results by fusing semantic relevance with temporal freshness."""

    def __init__(
        self,
        lifecycle_manager: TieredStorageLifecycleManager,
        decay_weight: float = 0.35,
    ) -> None:
        self.lifecycle_manager = lifecycle_manager
        self.decay_weight = max(0.0, min(1.0, decay_weight))

    def rerank(
        self,
        candidates: list[tuple[str, str, float]],
        exclude_cold: bool = True,
        current_time: float | None = None,
    ) -> list[DecayRerankItem]:
        """Blend semantic similarity with decay retention and return sorted items.

        candidates: list of (memory_id, content, base_similarity)
        """
        scored_items: list[DecayRerankItem] = []

        for mem_id, content, sim in candidates:
            profile = self.lifecycle_manager.get_profile(mem_id)
            if profile:
                score, tier = self.lifecycle_manager.scorer.calculate_score(
                    profile, current_time=current_time
                )
            else:
                # Fallback for unprofiled memories
                score = 0.5
                tier = StorageTier.WARM

            if exclude_cold and tier == StorageTier.COLD:
                continue

            final_score = (1.0 - self.decay_weight) * sim + self.decay_weight * score

            scored_items.append(
                DecayRerankItem(
                    memory_id=mem_id,
                    content=content,
                    base_similarity=round(sim, 4),
                    decay_score=round(score, 4),
                    final_score=round(final_score, 4),
                    tier=tier,
                )
            )

        # Sort descending by fused final score
        scored_items.sort(key=lambda item: item.final_score, reverse=True)
        return scored_items
