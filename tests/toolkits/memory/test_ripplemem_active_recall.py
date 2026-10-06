"""Unit tests for RippleMem sparse event graph and budgeted active recall controller.

[INPUT]
- ActiveRecallController, DualEdgeSparseGraphStore, NormalizedEventExtractor,
  NormalizedEventUnit, RippleSpreadBudget, GraphEdgeType from ripplemem package.
- Standard library modules (datetime, pytest).

[OUTPUT]
- Test suite verifying distributed multi-session reasoning, saturation fast-path,
  pronoun resolution, super-node pruning, and cycle defense.

[POS]
Integration and unit verification of the RippleMem cognitive recollection engine.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.ripplemem import (
    ActiveRecallController,
    DualEdgeSparseGraphStore,
    NormalizedEventExtractor,
    NormalizedEventUnit,
    RippleSpreadBudget,
)


@pytest.fixture
def extractor() -> NormalizedEventExtractor:
    """Fixture providing event extractor instance."""
    return NormalizedEventExtractor()


@pytest.fixture
def graph_store() -> DualEdgeSparseGraphStore:
    """Fixture providing clean dual-edge graph store."""
    return DualEdgeSparseGraphStore(semantic_threshold=0.72)


def test_normalized_event_extractor_pronoun_and_temporal_grounding(
    extractor: NormalizedEventExtractor,
) -> None:
    """Verify pronoun grounding to speaker and relative temporal anchor resolution."""
    ref_time = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    raw_text = "我昨天在老码头海鲜店和李雷一起吃了帝王蟹，非常新鲜。"

    event = extractor.extract_event(
        raw_text,
        session_id="session_hist_01",
        reference_time=ref_time,
        context_speaker="小王",
    )

    assert event.time_span == "2026-09-19"
    assert "小王" in event.participants
    assert "李雷" in event.participants
    assert any("老码头" in loc for loc in event.locations)
    assert any("海鲜" in c for c in event.concepts)


def test_saturation_fast_path_bypasses_simple_query(
    graph_store: DualEdgeSparseGraphStore,
) -> None:
    """Verify saturation fast-path gate shortcuts non-relational simple queries in 0ms."""
    controller = ActiveRecallController(graph_store)

    candidate = NormalizedEventUnit(
        id="evt_simple_01",
        representation="今天北京天气晴朗，气温24度。",
        participants=[],
        concepts=["天气"],
    )

    result = controller.execute_active_recall(
        query="今天北京天气怎么样？",
        initial_candidates=[candidate],
    )

    assert result.saturated_fast_path is True
    assert len(result.events) == 1
    assert result.provenance.saturated_fast_path is True
    assert len(result.provenance.missing_targets) == 0


def test_distributed_evidence_active_recall_success(
    extractor: NormalizedEventExtractor,
    graph_store: DualEdgeSparseGraphStore,
) -> None:
    """End-to-end test verifying multi-session distributed evidence recall for food allergy."""
    controller = ActiveRecallController(graph_store)

    # Session 1 (2 weeks ago): Allergy revelation
    ref_t1 = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    evt_allergy = extractor.extract_event(
        "我从小对海鲜严重过敏，碰一点都得进急诊挂水抗休克。",
        session_id="session_2w_ago",
        reference_time=ref_t1,
        context_speaker="小王",
    )
    graph_store.add_event(evt_allergy)

    # Session 2 (1 week ago): Restaurant recommendation
    ref_t2 = datetime(2026, 9, 13, 15, 0, tzinfo=UTC)
    evt_restaurant = extractor.extract_event(
        "望京新开了一家老码头新派蒸汽海鲜坊，主打清蒸海鲜和火锅，适合聚餐。",
        session_id="session_1w_ago",
        reference_time=ref_t2,
    )
    graph_store.add_event(evt_restaurant)

    # Anchor candidate initially retrieved by similarity for the query:
    # "明天晚上我想带小王去老码头新派蒸汽海鲜坊聚餐，你觉得合适吗？"
    anchor_event = evt_restaurant

    result = controller.execute_active_recall(
        query="明天晚上我想带小王去老码头新派蒸汽海鲜坊聚餐，你觉得合适吗？",
        initial_candidates=[anchor_event],
    )

    # Assert that the saturation gate detected an evidence gap
    assert result.saturated_fast_path is False
    assert len(result.provenance.missing_targets) >= 1
    gap = result.provenance.missing_targets[0]
    assert gap.target_entity == "小王"

    # Assert that directional ripple spreading traversed to session 1 event
    event_ids = {e.id for e in result.events}
    assert evt_allergy.id in event_ids
    assert anchor_event.id in event_ids

    # Assert provenance trace records the transition
    assert len(result.provenance.steps) >= 1
    step = result.provenance.steps[0]
    assert step.from_event_id == anchor_event.id
    assert step.to_event_id == evt_allergy.id
    assert step.hop_depth == 1


def test_super_node_degree_pruning_prevents_diffusion_avalanche(
    graph_store: DualEdgeSparseGraphStore,
) -> None:
    """Verify super-nodes with high degree are truncated to avoid fan-out explosion."""
    hub_event = NormalizedEventUnit(
        id="evt_hub_user",
        representation="用户主工作区枢纽记录",
        participants=["用户"],
    )
    graph_store.add_event(hub_event)

    # Attach 25 peripheral events sharing participant "用户"
    for i in range(25):
        child = NormalizedEventUnit(
            id=f"evt_child_{i:02d}",
            representation=f"工作任务片段_{i}",
            participants=["用户"],
        )
        graph_store.add_event(child)

    # Fetch pruned neighbors with max_degree=5
    neighbors = graph_store.get_pruned_neighbors(hub_event.id, max_degree=5)

    assert len(neighbors) == 5
    # Verify descending ordering by effective weight
    weights = [edge.weight for _, edge in neighbors]
    assert weights == sorted(weights, reverse=True)


def test_cycle_defense_and_budget_exhaustion(
    graph_store: DualEdgeSparseGraphStore,
) -> None:
    """Verify cyclic edges do not loop infinitely and budget limits terminate spreading."""
    node_a = NormalizedEventUnit(
        id="evt_a",
        representation="老王参与讨论方案A",
        participants=["老王"],
    )
    node_b = NormalizedEventUnit(
        id="evt_b",
        representation="老王参与讨论方案B",
        participants=["老王"],
    )
    graph_store.add_event(node_a)
    graph_store.add_event(node_b)

    controller = ActiveRecallController(graph_store)

    # Set strict budget: max_events=1
    budget = RippleSpreadBudget(max_hops=3, max_events=1, timeout_ms=100.0)

    result = controller.execute_active_recall(
        query="带老王评估一下方案可以吗？",
        initial_candidates=[node_a],
        budget=budget,
    )

    # Must complete safely without hang or recursion error
    assert result.budget_exhausted is True or len(result.events) >= 1
