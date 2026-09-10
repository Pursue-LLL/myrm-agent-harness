"""Eight Golden Scenarios benchmark for the Unified Seven-Layer Memory Governance engine.

Covers the full memory lifecycle scenarios from the roadmap benchmark suite:
current fact, historical fact, relation fact, negative update, temporal trace,
multi-hop reasoning, isolation protection, and one-click forgetting.

All scenarios are deterministic (zero LLM calls) and reuse the real production
primitives: FactReconciliationEngine, DynamicContextAssembler, EntityGraphBridge,
MemorySearchPolicy, and ProfileSlots.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchPolicy,
    resolve_search_corpora,
)
from myrm_agent_harness.toolkits.memory.governance import (
    DynamicContextAssembler,
    DynamicFactItem,
    EntityGraphBridge,
    EventTimelineItem,
    FactReconciliationEngine,
    FactStatus,
    ProfileSlots,
    ReconciliationAction,
)
from myrm_agent_harness.toolkits.memory.graph.sqlite_store import SQLiteGraphStore

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Scenario 1: Current fact — assembled context must expose the newest truth
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_1_current_fact() -> None:
    engine = FactReconciliationEngine()
    decision = engine.reconcile_statement("我现在住在上海", [])
    assert decision.action == ReconciliationAction.ADD

    facts = engine.apply_decision(decision, [], category="residence")

    assembler = DynamicContextAssembler(max_total_tokens=800)
    context = await assembler.assemble_context(
        profile=ProfileSlots(), timeline=[], dynamic_facts=facts, seed_entities=None
    )

    assert "住在上海" in context.dynamic_facts_section


# ---------------------------------------------------------------------------
# Scenario 2: Historical fact — old truth is superseded, not silently dropped
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_2_historical_fact_superseded() -> None:
    engine = FactReconciliationEngine()
    add_decision = engine.reconcile_statement("我之前住在北京", [])
    facts = engine.apply_decision(add_decision, [])

    update_decision = engine.reconcile_statement("之前住的地方改为上海了", facts)
    assert update_decision.action == ReconciliationAction.UPDATE
    facts = engine.apply_decision(update_decision, facts)

    assembler = DynamicContextAssembler(max_total_tokens=800)
    context = await assembler.assemble_context(
        profile=ProfileSlots(), timeline=[], dynamic_facts=facts, seed_entities=None
    )

    active = [f for f in facts if f.status == FactStatus.ACTIVE]
    deprecated = [f for f in facts if f.status == FactStatus.DEPRECATED]

    assert len(active) == 1
    assert "上海" in active[0].content
    assert len(deprecated) == 1
    assert "北京" in deprecated[0].content
    # Context exposes only the new truth; the superseded one must not leak.
    assert "北京" not in context.dynamic_facts_section
    assert "上海" in context.dynamic_facts_section


# ---------------------------------------------------------------------------
# Scenario 3: Relation fact — family-member facts coexist independently
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_3_relation_fact_coexistence() -> None:
    engine = FactReconciliationEngine()
    user_move = engine.reconcile_statement("我搬到上海了", [])
    father = engine.reconcile_statement("我爸还在北京", [])
    assert user_move.action == ReconciliationAction.ADD
    assert father.action == ReconciliationAction.ADD

    facts = engine.apply_decision(user_move, [])
    facts = engine.apply_decision(father, facts)

    assembler = DynamicContextAssembler(max_total_tokens=800)
    context = await assembler.assemble_context(
        profile=ProfileSlots(), timeline=[], dynamic_facts=facts, seed_entities=None
    )

    # Both the user fact and the father fact must remain visible.
    assert "上海" in context.dynamic_facts_section
    assert "北京" in context.dynamic_facts_section


# ---------------------------------------------------------------------------
# Scenario 4: Negative update — "我现在不吃辣了" reconciles against the old taste
# ---------------------------------------------------------------------------
def test_scenario_4_negative_update() -> None:
    engine = FactReconciliationEngine()
    facts = engine.apply_decision(
        engine.reconcile_statement("用户很喜欢吃辣", []), []
    )

    decision = engine.reconcile_statement("用户现在不吃辣了", facts)
    assert decision.action == ReconciliationAction.UPDATE
    assert decision.target_fact_id == facts[0].fact_id

    facts = engine.apply_decision(decision, facts)
    active = [f for f in facts if f.status == FactStatus.ACTIVE]
    assert len(active) == 1
    assert "不吃辣" in active[0].content


# ---------------------------------------------------------------------------
# Scenario 5: Temporal trace — timeline retains dated history for追溯
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_5_temporal_trace() -> None:
    engine = FactReconciliationEngine()
    facts = engine.apply_decision(engine.reconcile_statement("住在上海", []), [])

    assembler = DynamicContextAssembler(max_total_tokens=1000)
    timeline = [
        EventTimelineItem(
            event_id="evt_move",
            timestamp=NOW - timedelta(days=95),
            summary="搬家",
            details="从北京搬到上海",
        ),
        EventTimelineItem(
            event_id="evt_recent",
            timestamp=NOW - timedelta(hours=2),
            summary="讨论装修风格",
        ),
    ]
    context = await assembler.assemble_context(
        profile=ProfileSlots(), timeline=timeline, dynamic_facts=facts, seed_entities=None
    )

    # Timeline is rendered oldest-first (chronological order for readability).
    assert "讨论装修风格" in context.timeline_section
    assert "搬家" in context.timeline_section
    assert context.timeline_section.index("搬家") < context.timeline_section.index("讨论装修风格")


# ---------------------------------------------------------------------------
# Scenario 6: Multi-hop reasoning — 2-hop graph expansion via EntityGraphBridge
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_6_multi_hop_graph(tmp_path: Path) -> None:
    db_path = str(tmp_path / "golden_scenario_graph.db")
    store = SQLiteGraphStore(db_path)
    try:
        node_user = await store.create_node(["Person"], {"name": "用户"})
        node_father = await store.create_node(["Person"], {"name": "父亲"})
        node_beijing = await store.create_node(["City"], {"name": "北京"})
        await store.create_relationship(
            start_id=node_user.id, end_id=node_father.id, rel_type="RELATES_TO"
        )
        await store.create_relationship(
            start_id=node_father.id, end_id=node_beijing.id, rel_type="LIVES_IN"
        )

        bridge = EntityGraphBridge(store)
        context = await bridge.get_bounded_subgraph_text(
            seed_entity_names=["用户"], max_depth=2, max_nodes=10
        )

        # The 2-hop chain user → father → 北京 must be fully traversable.
        assert "父亲" in context
        assert "北京" in context
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Scenario 7: Isolation protection — agent without wiki/session grants stays blind
# ---------------------------------------------------------------------------
def test_scenario_7_isolation_protection() -> None:
    # A work agent must not leak private corpora it has no grants for.
    restricted_policy = MemorySearchPolicy(allow_wiki=False, allow_sessions=False)

    corpora, error = resolve_search_corpora("sessions", restricted_policy)
    assert corpora == []
    assert error is not None
    assert "disabled" in error.lower()

    corpora, error = resolve_search_corpora("wiki", restricted_policy)
    assert corpora == []
    assert error is not None
    assert "not enabled" in error.lower()

    # An all-corpus request degrades to memory-only without raising.
    corpora, error = resolve_search_corpora("all", restricted_policy)
    assert corpora == ["memory"]
    assert error is None


# ---------------------------------------------------------------------------
# Scenario 8: One-click forgetting — TTL purge and slot deletion leave no residue
# ---------------------------------------------------------------------------
def test_scenario_8_one_click_forget() -> None:
    engine = FactReconciliationEngine()
    now = datetime.now(timezone.utc)
    facts = [
        DynamicFactItem(
            fact_id="f_temp",
            content="下周在深圳出差",
            valid_until=now - timedelta(minutes=5),
        ),
        DynamicFactItem(fact_id="f_perm", content="用户对花生过敏", valid_until=None),
    ]

    active, forgotten = engine.purge_expired_facts(facts, current_time=now)
    assert [f.fact_id for f in active] == ["f_perm"]
    assert forgotten[0].fact_id == "f_temp"
    assert forgotten[0].status == FactStatus.EXPIRED

    # Profile slots must also be erasable in place with no residue.
    profile = ProfileSlots()
    profile.update_slot("preferences", "city", "Shenzhen")
    assert profile.delete_slot("preferences", "city") is True
    assert profile.delete_slot("preferences", "city") is False
    assert "city" not in profile.to_cached_prefix_text()