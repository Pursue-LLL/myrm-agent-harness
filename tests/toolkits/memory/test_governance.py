"""Tests for Seven-Layer Memory Governance Engine.

Covers Profile Slots Prompt-Cache determinism, Event Timeline,
Dynamic Fact TTL expiration, Four-state Reconciliation (ADD, UPDATE, DELETE, NOOP),
and Bounded 2-hop Entity Graph integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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


def test_profile_slots_deterministic_prompt_cache() -> None:
    """Validate that ProfileSlots yields identical text regardless of insertion order."""
    slot_a = ProfileSlots()
    slot_a.update_slot("persona", "role", "Engineer")
    slot_a.update_slot("persona", "age", "30")
    slot_a.update_slot("preferences", "language", "Python")
    slot_a.update_slot("preferences", "editor", "Neovim")

    slot_b = ProfileSlots()
    slot_b.update_slot("preferences", "editor", "Neovim")
    slot_b.update_slot("persona", "age", "30")
    slot_b.update_slot("persona", "role", "Engineer")
    slot_b.update_slot("preferences", "language", "Python")

    text_a = slot_a.to_cached_prefix_text()
    text_b = slot_b.to_cached_prefix_text()

    assert text_a == text_b
    assert "- Persona:\n  * age: 30\n  * role: Engineer" in text_a
    assert "- Preferences:\n  * editor: Neovim\n  * language: Python" in text_a


def test_profile_slots_mutation_and_deletion() -> None:
    """Test in-place update and deletion of profile slots."""
    profile = ProfileSlots()
    profile.update_slot("constraints", "budget", "500 USD")
    assert profile.constraints["budget"] == "500 USD"

    deleted = profile.delete_slot("constraints", "budget")
    assert deleted is True
    assert "budget" not in profile.constraints

    deleted_again = profile.delete_slot("constraints", "non_existent")
    assert deleted_again is False


def test_dynamic_fact_ttl_expiration() -> None:
    """Test fact TTL detection and expiration purging."""
    now = datetime.now(timezone.utc)
    engine = FactReconciliationEngine()

    active_fact = DynamicFactItem(
        fact_id="f1",
        content="User resides in Tokyo",
        valid_until=now + timedelta(days=10),
    )
    expired_fact = DynamicFactItem(
        fact_id="f2",
        content="Current hotel reservation",
        valid_until=now - timedelta(hours=1),
    )
    permanent_fact = DynamicFactItem(
        fact_id="f3",
        content="User is allergic to peanuts",
        valid_until=None,
    )

    facts = [active_fact, expired_fact, permanent_fact]
    active, expired = engine.purge_expired_facts(facts, current_time=now)

    assert len(active) == 2
    assert len(expired) == 1
    assert expired[0].fact_id == "f2"
    assert expired[0].status == FactStatus.EXPIRED


def test_reconciliation_noop() -> None:
    """Test that identical statements trigger NOOP."""
    engine = FactReconciliationEngine()
    existing = [
        DynamicFactItem(
            fact_id="fact_coffee",
            content="喜欢喝拿铁",
            status=FactStatus.ACTIVE,
        )
    ]

    decision = engine.reconcile_statement("喜欢喝拿铁", existing)
    assert decision.action == ReconciliationAction.NOOP
    assert decision.target_fact_id == "fact_coffee"


def test_reconciliation_add() -> None:
    """Test that novel facts without conflict trigger ADD."""
    engine = FactReconciliationEngine()
    existing = [
        DynamicFactItem(
            fact_id="fact_coffee",
            content="喜欢喝拿铁",
            status=FactStatus.ACTIVE,
        )
    ]

    decision = engine.reconcile_statement("周末打网球", existing)
    assert decision.action == ReconciliationAction.ADD
    assert decision.new_content == "周末打网球"

    updated = engine.apply_decision(decision, existing, category="hobby")
    assert len(updated) == 2
    assert updated[-1].content == "周末打网球"
    assert updated[-1].category == "hobby"


def test_reconciliation_update() -> None:
    """Test conflict detection and superseding an existing fact."""
    engine = FactReconciliationEngine()
    existing = [
        DynamicFactItem(
            fact_id="fact_coffee",
            content="平时喜欢喝拿铁咖啡",
            status=FactStatus.ACTIVE,
        )
    ]

    decision = engine.reconcile_statement("咖啡现在改为喜欢喝美式了", existing)
    assert decision.action == ReconciliationAction.UPDATE
    assert decision.target_fact_id == "fact_coffee"

    updated = engine.apply_decision(decision, existing)
    # Original fact marked as DEPRECATED, new fact is ACTIVE
    deprecated = [f for f in updated if f.status == FactStatus.DEPRECATED]
    active = [f for f in updated if f.status == FactStatus.ACTIVE]

    assert len(deprecated) == 1
    assert deprecated[0].fact_id == "fact_coffee"
    assert len(active) == 1
    assert "美式" in active[0].content


def test_reconciliation_delete() -> None:
    """Test revocation and cancellation detection."""
    engine = FactReconciliationEngine()
    existing = [
        DynamicFactItem(
            fact_id="fact_badminton",
            content="参加周六的羽毛球比赛",
            status=FactStatus.ACTIVE,
        )
    ]

    decision = engine.reconcile_statement("取消周六的羽毛球比赛", existing)
    assert decision.action == ReconciliationAction.DELETE
    assert decision.target_fact_id == "fact_badminton"

    updated = engine.apply_decision(decision, existing)
    assert len(updated) == 1
    assert updated[0].status == FactStatus.DEPRECATED


@pytest.mark.asyncio
async def test_entity_graph_bridge_bounded_traversal(tmp_path: Path) -> None:
    """Test that EntityGraphBridge respects max depth 2 and node budget."""
    db_path = str(tmp_path / "test_governance_graph.db")
    store = SQLiteGraphStore(db_path)
    bridge = EntityGraphBridge(store)

    # Setup graph nodes
    node_alice = await store.create_node(["Person"], {"name": "Alice"})
    node_bob = await store.create_node(["Person"], {"name": "Bob"})
    await store.create_relationship(
        start_id=node_alice.id,
        end_id=node_bob.id,
        rel_type="RELATES_TO",
    )

    # Query with seed entity
    graph_text = await bridge.get_bounded_subgraph_text(
        seed_entity_names=["Alice"],
        max_depth=2,
        max_nodes=10,
    )
    assert "Alice" in graph_text
    await store.close()


@pytest.mark.asyncio
async def test_dynamic_context_assembler() -> None:
    """Test context assembly honoring token budget and deterministic ordering."""
    assembler = DynamicContextAssembler(max_total_tokens=500)

    profile = ProfileSlots()
    profile.update_slot("persona", "name", "Developer")
    profile.update_slot("preferences", "theme", "dark")

    now = datetime.now(timezone.utc)
    timeline = [
        EventTimelineItem(
            event_id="e1",
            timestamp=now - timedelta(days=1),
            summary="Deployed v1.0",
        ),
        EventTimelineItem(
            event_id="e2",
            timestamp=now,
            summary="Checked system metrics",
        ),
    ]

    facts = [
        DynamicFactItem(
            fact_id="f1",
            content="Kubernetes cluster is healthy",
            status=FactStatus.ACTIVE,
        ),
        DynamicFactItem(
            fact_id="f2",
            content="Old server rebooted",
            status=FactStatus.DEPRECATED,
        ),
    ]

    context = await assembler.assemble_context(
        profile=profile,
        timeline=timeline,
        dynamic_facts=facts,
        seed_entities=None,
    )

    # 1. Profile must be at top
    assert "[User Profile & Constraints]" in context.cached_profile_prefix
    assert "* name: Developer" in context.cached_profile_prefix
    assert "* theme: dark" in context.cached_profile_prefix

    # 2. Only active facts included
    assert "Kubernetes cluster is healthy" in context.dynamic_facts_section
    assert "Old server rebooted" not in context.dynamic_facts_section

    # 3. Timeline section included
    assert "Deployed v1.0" in context.timeline_section
    assert "Checked system metrics" in context.timeline_section

    # 4. Token count estimated
    assert context.total_estimated_tokens > 0
    full_text = context.full_context_text()
    assert "[User Profile & Constraints]" in full_text
    assert "[Dynamic Facts]" in full_text
    assert "[Event Timeline]" in full_text
