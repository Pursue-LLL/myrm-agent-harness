"""Facade orchestrator coordinating trigger classification, dedup, and fail-open reranking.

[INPUT]
- toolkits.memory.auto_recall.fail_open_reranker::FailOpenReranker (POS: Fail-open reranker wrapper
  guaranteeing non-blocking fallback on missing keys or timeouts.)
- toolkits.memory.auto_recall.sliding_window_dedup::SlidingWindowDedupGate (POS: Sliding window
  deduplication gate to suppress redundant memory injection across turns.)
- toolkits.memory.auto_recall.trigger_classifier::ExperienceRecallTriggerClassifier (POS: Deterministic and
  lightweight classifier for 5 high-risk recall trigger scenarios.)
- toolkits.memory.auto_recall.types::AutoRecallDecision, RecallCandidate, RecallGateConfig,
  RecallTriggerType, RerankerStatus (POS: Type definitions and contracts for Targeted Experience Auto-Recall
  Engine.)

[OUTPUT]
- ExperienceRecallGate: Unified gate coordinating 5-scenario trigger filtering, 5-turn sliding dedup, and
  fail-open rerank.

[POS]
Facade orchestrator coordinating trigger classification, dedup, and fail-open reranking.
"""

from __future__ import annotations

from .fail_open_reranker import FailOpenReranker
from .sliding_window_dedup import SlidingWindowDedupGate
from .trigger_classifier import ExperienceRecallTriggerClassifier
from .types import (
    AutoRecallDecision,
    RecallCandidate,
    RecallGateConfig,
    RecallTriggerType,
    RerankerStatus,
)


class ExperienceRecallGate:
    """Unified gate coordinating 5-scenario trigger filtering, 5-turn sliding dedup, and fail-open rerank."""

    def __init__(
        self,
        config: RecallGateConfig | None = None,
        dedup_gate: SlidingWindowDedupGate | None = None,
        reranker: FailOpenReranker | None = None,
    ) -> None:
        self._config = config or RecallGateConfig()
        self._classifier = ExperienceRecallTriggerClassifier()
        self._dedup_gate = dedup_gate or SlidingWindowDedupGate(window_turns=self._config.dedup_turns)
        self._reranker = reranker or FailOpenReranker(config=self._config)

    def evaluate_and_recall(
        self,
        session_id: str,
        current_turn: int,
        raw_candidates: list[RecallCandidate],
        event_name: str | None = None,
        tool_name: str | None = None,
        query_text: str | None = None,
        force_recall: bool = False,
    ) -> AutoRecallDecision:
        """Evaluate context for sensitive triggers, apply sliding-window dedup, and fail-open rerank."""
        # 1. Trigger classification
        if force_recall:
            trigger_type = RecallTriggerType.TASK_START
            reason = "Force-recall flag asserted by caller"
        else:
            trigger_type, reason = self._classifier.classify(
                event_name=event_name,
                tool_name=tool_name,
                query_text=query_text,
            )

        # If not a sensitive trigger, suppress recall completely (0 token cost)
        if trigger_type == RecallTriggerType.NONE:
            return AutoRecallDecision(
                triggered=False,
                trigger_type=trigger_type,
                candidates_pre_dedup=len(raw_candidates),
                candidates_post_dedup=0,
                injected_candidates=[],
                reranker_status=RerankerStatus.RERANKER_SKIPPED,
                audit_reason=reason,
            )

        # 2. Filter candidates by initial score threshold
        filtered_by_score = [
            c for c in raw_candidates if c.initial_score >= self._config.min_recall_score
        ]

        # 3. Apply 5-turn sliding window deduplication
        deduped = self._dedup_gate.filter_unseen(session_id, filtered_by_score)

        if not deduped:
            return AutoRecallDecision(
                triggered=True,
                trigger_type=trigger_type,
                candidates_pre_dedup=len(raw_candidates),
                candidates_post_dedup=0,
                injected_candidates=[],
                reranker_status=RerankerStatus.RERANKER_SKIPPED,
                audit_reason=f"{reason} (all candidates suppressed by 5-turn dedup window)",
            )

        # 4. Fail-open neural reranking
        query = query_text or tool_name or event_name or ""
        reranked, rerank_status = self._reranker.rerank(query=query, candidates=deduped)

        # 5. Cap injected items
        injected = reranked[: self._config.max_injected_items]

        # 6. Record newly injected memory IDs to advance the sliding window
        injected_ids = [c.memory_id for c in injected]
        self._dedup_gate.record_injected(
            session_id=session_id,
            injected_ids=injected_ids,
            turn_index=current_turn,
        )

        return AutoRecallDecision(
            triggered=True,
            trigger_type=trigger_type,
            candidates_pre_dedup=len(raw_candidates),
            candidates_post_dedup=len(deduped),
            injected_candidates=injected,
            reranker_status=rerank_status,
            audit_reason=reason,
        )

    def get_dedup_gate(self) -> SlidingWindowDedupGate:
        """Provide direct access to the internal sliding window dedup gate."""
        return self._dedup_gate
