"""Core backtracking engine for cross-session entity and temporal causal recall.

[INPUT]
- toolkits.memory.relational_backtrack.models::RelationalBacktrackHit, RelationalBacktrackQuery,
  RelationalBacktrackResult (POS: Types and models for relational backtrack.)
- toolkits.memory.relational_backtrack.synonym_normalizer::ActionSynonymNormalizer (POS: Action synonym
  normalization and dialect mapping engine.)
- toolkits.memory.relational_backtrack.triplet_store::TemporalTripletStore (POS: In-memory structured index
  for entity-action-temporal triplets.)

[OUTPUT]
- CrossSessionBacktrackEngine: Core backtracking engine for cross-session entity and temporal causal recall.

[POS]
Core backtracking engine for cross-session entity and temporal causal recall.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/relational_backtrack/backtrack_engine.py
# [INPUT]: models.py, synonym_normalizer.py, triplet_store.py
# [OUTPUT]: CrossSessionBacktrackEngine

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.relational_backtrack.models import (
    RelationalBacktrackHit,
    RelationalBacktrackQuery,
    RelationalBacktrackResult,
)
from myrm_agent_harness.toolkits.memory.relational_backtrack.synonym_normalizer import (
    ActionSynonymNormalizer,
)
from myrm_agent_harness.toolkits.memory.relational_backtrack.triplet_store import (
    TemporalTripletStore,
)

logger = logging.getLogger(__name__)


class CrossSessionBacktrackEngine:
    """Core backtracking engine for cross-session entity and temporal causal recall.

    Resolves dialect variances through synonym expansion, retrieves candidate triplets
    from the structured store, ranks by relevance and recency, and pins verbatim quotes.
    """

    def __init__(
        self,
        store: TemporalTripletStore | None = None,
        normalizer: ActionSynonymNormalizer | None = None,
    ) -> None:
        self._store = store or TemporalTripletStore()
        self._normalizer = normalizer or ActionSynonymNormalizer()

    @property
    def store(self) -> TemporalTripletStore:
        """Access underlying triplet store."""
        return self._store

    @property
    def normalizer(self) -> ActionSynonymNormalizer:
        """Access underlying synonym normalizer."""
        return self._normalizer

    def backtrack(self, query: RelationalBacktrackQuery) -> RelationalBacktrackResult:
        """Execute cross-session relational backtracking for a given action cue."""
        # 1. Expand action synonyms (e.g., '打边炉' -> ['吃火锅', '打边炉', 'hotpot'])
        expanded_cues = self._normalizer.expand_synonyms(query.action_cue)

        # 2. Query candidates from triplet store
        candidates = self._store.find_candidates(
            candidate_actions=expanded_cues,
            entity_type=query.target_entity_type,
            session_id_scope=query.session_id_scope,
        )

        hits: list[RelationalBacktrackHit] = []
        for triplet in candidates:
            # Score similarity between query cue and triplet action terms
            sim_score = self._normalizer.compute_action_similarity(
                query.action_cue, triplet.predicate_action
            )
            # Check against synonym list if direct action match was suboptimal
            for syn in triplet.action_synonyms:
                syn_sim = self._normalizer.compute_action_similarity(
                    query.action_cue, syn
                )
                if syn_sim > sim_score:
                    sim_score = syn_sim

            final_score = round(sim_score * triplet.confidence, 4)
            if final_score < query.min_confidence:
                continue

            hits.append(
                RelationalBacktrackHit(
                    triplet=triplet,
                    matched_cue=query.action_cue,
                    match_score=final_score,
                )
            )

        # 3. Sort hits by match_score descending, then temporal_anchor descending
        hits.sort(
            key=lambda h: (h.match_score, h.triplet.temporal_anchor, h.triplet.created_at),
            reverse=True,
        )

        # 4. Generate synthesized definitive answer if match exists
        inferred_answer: str | None = None
        if hits:
            top_hit = hits[0].triplet
            inferred_answer = (
                f"根据 {top_hit.temporal_anchor} 的历史会话记录，"
                f"关于【{query.action_cue}】关联的{top_hit.target_entity_type.value}是"
                f"【{top_hit.target_entity}】"
                f"（出处证据：“{top_hit.verbatim_quote}”）。"
            )

        logger.info(
            "Backtracked cue '%s': found %d candidate hits",
            query.action_cue,
            len(hits),
        )

        return RelationalBacktrackResult(
            hits=hits,
            total_found=len(hits),
            inferred_answer=inferred_answer,
        )
