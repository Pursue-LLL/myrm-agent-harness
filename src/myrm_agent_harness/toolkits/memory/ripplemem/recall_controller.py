"""Active recall controller for RippleMem budgeted directional ripple spreading.

[INPUT]
- NormalizedEventUnit, MissingSupportTarget, RippleRecallResult,
  RippleSpreadBudget, MultiHopProvenanceTrace, GraphEdgeType from .models.
- DualEdgeSparseGraphStore from .sparse_graph.
- Standard library modules (time, logging, re).

[OUTPUT]
- ActiveRecallController: Orchestrator executing saturation fast-path,
  missing gap reasoning, bounded directional spreading, and provenance assembly.

[POS]
Brain of the RippleMem architecture. Elevates passive similarity search to
goal-directed active recollection across multi-session distributed evidence.
"""

from __future__ import annotations

import logging
import re
from time import perf_counter

from myrm_agent_harness.toolkits.memory.ripplemem.models import (
    GraphEdgeType,
    MissingSupportTarget,
    MultiHopProvenanceStep,
    MultiHopProvenanceTrace,
    NormalizedEventUnit,
    RippleRecallResult,
    RippleSpreadBudget,
)
from myrm_agent_harness.toolkits.memory.ripplemem.sparse_graph import (
    DualEdgeSparseGraphStore,
    _cosine_similarity,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONSTRAINT_KEYWORDS: tuple[str, ...] = (
    "过敏",
    "禁忌",
    "忌口",
    "素食",
    "清真",
    "痛风",
    "不吃",
    "冲突",
    "限制",
)

_COMMON_STOPWORDS_EN: set[str] = {
    "The",
    "And",
    "For",
    "With",
    "Today",
    "Yesterday",
    "Notice",
    "Who",
    "Where",
    "When",
    "What",
    "How",
}

_NON_PERSON_SUBSTRINGS: tuple[str, ...] = (
    "码头",
    "海鲜",
    "蟹",
    "一起",
    "店",
    "坊",
    "方案",
    "网关",
    "火锅",
    "餐厅",
    "天气",
    "北京",
    "上海",
)


def _extract_query_person_entities(query: str) -> list[str]:
    """Extract Chinese and English person names from input query."""
    raw_cn_names = re.findall(
        r"(?:小|老|王|李|张|刘|陈|赵|周|孙|钱|吴|郑|冯|韩|杨|朱|秦|许|何|吕|施|孔|曹|严|华|金|魏|陶|姜)[一-龥]{1,2}",
        query,
    )
    raw_en_names = re.findall(r"\b[A-Z][a-z]{2,15}\b", query)

    clean_names: list[str] = []
    for n in raw_cn_names:
        c = re.sub(r"[去在和与的一到来想带做吃看]$", "", n).strip()
        if len(c) >= 2 and not any(sub in c for sub in _NON_PERSON_SUBSTRINGS):
            clean_names.append(c)

    for n in raw_en_names:
        if n not in _COMMON_STOPWORDS_EN and len(n) >= 2:
            clean_names.append(n)

    return sorted(set(clean_names))


class ActiveRecallController:
    """Controls the active recall lifecycle: saturation fast-path, gap deduction, and ripple spread."""

    def __init__(
        self,
        graph_store: DualEdgeSparseGraphStore,
        *,
        default_budget: RippleSpreadBudget | None = None,
    ) -> None:
        self._graph = graph_store
        self._budget = default_budget or RippleSpreadBudget()

    def execute_active_recall(
        self,
        query: str,
        *,
        initial_candidates: list[NormalizedEventUnit],
        query_embedding: list[float] | None = None,
        budget: RippleSpreadBudget | None = None,
    ) -> RippleRecallResult:
        """Execute active recall pipeline over initial candidates.

        Args:
            query: User's query utterance or prompt.
            initial_candidates: First-pass candidates from tri-channel retrieval (anchors).
            query_embedding: Optional embedding vector of the query.
            budget: Optional override of resource spread budget.

        Returns:
            RippleRecallResult packaging resolved events and multi-hop provenance trace.
        """
        start_time = perf_counter()
        effective_budget = budget or self._budget

        # Step 1: Saturation Fast-Path Gate
        is_saturated = self._evaluate_saturation(query, initial_candidates)
        if is_saturated or not initial_candidates:
            duration_ms = (perf_counter() - start_time) * 1000.0
            trace = MultiHopProvenanceTrace(
                query=query,
                anchor_event_ids=[e.id for e in initial_candidates],
                missing_targets=[],
                resolved_event_ids=[e.id for e in initial_candidates],
                saturated_fast_path=True,
                duration_ms=duration_ms,
            )
            return RippleRecallResult(
                events=initial_candidates,
                provenance=trace,
                saturated_fast_path=True,
                budget_exhausted=False,
            )

        # Step 2: Missing Support Target Inference
        missing_targets = self._infer_missing_support_targets(query, initial_candidates)
        if not missing_targets:
            duration_ms = (perf_counter() - start_time) * 1000.0
            trace = MultiHopProvenanceTrace(
                query=query,
                anchor_event_ids=[e.id for e in initial_candidates],
                missing_targets=[],
                resolved_event_ids=[e.id for e in initial_candidates],
                saturated_fast_path=False,
                duration_ms=duration_ms,
            )
            return RippleRecallResult(
                events=initial_candidates,
                provenance=trace,
                saturated_fast_path=False,
                budget_exhausted=False,
            )

        # Step 3: Budgeted Directional Ripple Spreading
        resolved_events, steps, budget_hit = self._spread_ripples(
            anchors=initial_candidates,
            missing_targets=missing_targets,
            query_vector=query_embedding,
            budget=effective_budget,
            start_time=start_time,
        )

        all_events_dict: dict[str, NormalizedEventUnit] = {e.id: e for e in initial_candidates}
        for e in resolved_events:
            all_events_dict[e.id] = e

        duration_ms = (perf_counter() - start_time) * 1000.0
        final_trace = MultiHopProvenanceTrace(
            query=query,
            anchor_event_ids=[e.id for e in initial_candidates],
            missing_targets=missing_targets,
            steps=steps,
            resolved_event_ids=list(all_events_dict.keys()),
            saturated_fast_path=False,
            duration_ms=duration_ms,
        )

        return RippleRecallResult(
            events=list(all_events_dict.values()),
            provenance=final_trace,
            saturated_fast_path=False,
            budget_exhausted=budget_hit,
        )

    def _evaluate_saturation(
        self,
        query: str,
        candidates: list[NormalizedEventUnit],
    ) -> bool:
        """Check if initial candidates already provide a saturated, self-contained answer."""
        if not candidates:
            return True

        # Simple queries without relational decisions are inherently saturated
        relational_keywords = ["合适", "可以吗", "能带", "升级", "冲突", "影响", "去哪", "推荐", "评估"]
        has_decision_intent = any(kw in query for kw in relational_keywords)
        if not has_decision_intent:
            return True

        # Check if the query asks about a specific person whose constraints are already in candidates
        clean_names = _extract_query_person_entities(query)
        for name in clean_names:
            has_constraint = any(
                name in e.participants
                and any(kw in e.representation for kw in _DEFAULT_CONSTRAINT_KEYWORDS)
                for e in candidates
            )
            if not has_constraint:
                return False  # Unsaturated: query involves a person whose constraints are not yet present

        return True

    def _infer_missing_support_targets(
        self,
        query: str,
        anchors: list[NormalizedEventUnit],
    ) -> list[MissingSupportTarget]:
        """Infer explicit missing evidence gaps required to answer the query."""
        gaps: list[MissingSupportTarget] = []

        # Detect involved persons in query or anchors that lack preference/constraint events
        clean_query_names = _extract_query_person_entities(query)
        persons_in_query = set(clean_query_names)
        for a in anchors:
            for p in a.participants:
                if len(p) >= 2 and not any(sub in p for sub in _NON_PERSON_SUBSTRINGS):
                    persons_in_query.add(p)

        for person in sorted(persons_in_query):
            has_preferences = any(
                person in a.participants
                and (
                    any(c in a.concepts for c in ["过敏", "忌口", "偏好", "禁忌", "素食", "清真"])
                    or any(kw in a.representation for kw in _DEFAULT_CONSTRAINT_KEYWORDS)
                )
                for a in anchors
            )
            if not has_preferences:
                gaps.append(
                    MissingSupportTarget(
                        target_entity=person,
                        relation_aspect="dietary_restrictions_or_allergies",
                        reasoning=f"Query involves {person} but anchor evidence lacks dietary/health constraints.",
                        priority=1.0,
                    )
                )

        # Detect architectural dependency gaps
        if "升级" in query or "网关" in query or "TLS" in query:
            has_compat = any("兼容" in a.representation or "冲突" in a.representation for a in anchors)
            if not has_compat:
                gaps.append(
                    MissingSupportTarget(
                        target_entity="gateway_downstream",
                        relation_aspect="compatibility_or_dependency_constraints",
                        reasoning="Gateway upgrade query requires checking downstream API compatibility constraints.",
                        priority=0.9,
                    )
                )

        return gaps

    def _spread_ripples(
        self,
        anchors: list[NormalizedEventUnit],
        missing_targets: list[MissingSupportTarget],
        query_vector: list[float] | None,
        budget: RippleSpreadBudget,
        start_time: float,
    ) -> tuple[list[NormalizedEventUnit], list[MultiHopProvenanceStep], bool]:
        """Execute bounded 1-2 hop directional spreading along relevant clue edges."""
        visited_ids: set[str] = {a.id for a in anchors}
        resolved: list[NormalizedEventUnit] = []
        steps: list[MultiHopProvenanceStep] = []
        budget_exhausted = False

        current_frontier: list[tuple[NormalizedEventUnit, int]] = [(a, 0) for a in anchors]

        # Target clues to guide directional search
        target_clue_entities = {t.target_entity.lower() for t in missing_targets}

        # Direct clue seed grounding for explicit missing targets (e.g. participant constraints)
        for target in missing_targets:
            if target.target_entity:
                direct_clue_events = self._graph.find_events_by_clue(participant=target.target_entity)
                for clue_evt in direct_clue_events:
                    if clue_evt.id not in visited_ids:
                        visited_ids.add(clue_evt.id)
                        resolved.append(clue_evt)
                        steps.append(
                            MultiHopProvenanceStep(
                                from_event_id=anchors[0].id if anchors else "query_intent",
                                to_event_id=clue_evt.id,
                                edge_type=GraphEdgeType.PARTICIPANT,
                                clue=target.target_entity,
                                hop_depth=1,
                                event_summary=clue_evt.representation[:60],
                            )
                        )
                        current_frontier.append((clue_evt, 1))
                        if len(resolved) >= budget.max_events:
                            budget_exhausted = True
                            break
            if budget_exhausted:
                break

        while current_frontier:
            # Check budget constraints
            elapsed_ms = (perf_counter() - start_time) * 1000.0
            if elapsed_ms > budget.timeout_ms or len(resolved) >= budget.max_events:
                budget_exhausted = True
                break

            current_node, depth = current_frontier.pop(0)
            if depth >= budget.max_hops:
                continue

            # Fetch pruned outgoing neighbors
            neighbors = self._graph.get_pruned_neighbors(
                current_node.id,
                query_vector=query_vector,
                max_degree=budget.max_degree_per_node,
            )

            for neighbor_node, edge in neighbors:
                if neighbor_node.id in visited_ids:
                    continue
                visited_ids.add(neighbor_node.id)

                # Directional relevance filter: check if neighbor connects with target clues
                matches_target = False
                for t_entity in target_clue_entities:
                    if (
                        any(t_entity in p.lower() for p in neighbor_node.participants)
                        or any(t_entity in c.lower() for c in neighbor_node.concepts)
                        or t_entity in neighbor_node.representation.lower()
                    ):
                        matches_target = True
                        break

                # Also accept high semantic edges if similarity is strong
                if not matches_target and edge.edge_type == GraphEdgeType.SEMANTIC and query_vector:
                    sim = _cosine_similarity(query_vector, neighbor_node.embedding)
                    if sim >= 0.78:
                        matches_target = True

                if matches_target:
                    resolved.append(neighbor_node)
                    steps.append(
                        MultiHopProvenanceStep(
                            from_event_id=current_node.id,
                            to_event_id=neighbor_node.id,
                            edge_type=edge.edge_type,
                            clue=edge.clue_value,
                            hop_depth=depth + 1,
                            event_summary=neighbor_node.representation[:60],
                        )
                    )
                    # Next hop frontier expansion
                    if depth + 1 < budget.max_hops:
                        current_frontier.append((neighbor_node, depth + 1))

                    if len(resolved) >= budget.max_events:
                        budget_exhausted = True
                        break

        return resolved, steps, budget_exhausted
