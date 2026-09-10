# [INPUT] None
# [OUTPUT] pytest edge cases for memory governance (timezone, english negation, empty input)
# [POS] myrm-agent-harness/tests/toolkits/memory/test_governance_edge_cases.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from myrm_agent_harness.toolkits.memory.governance.assembler import (
    DynamicContextAssembler,
)
from myrm_agent_harness.toolkits.memory.governance.graph_bridge import EntityGraphBridge
from myrm_agent_harness.toolkits.memory.governance.models import (
    DynamicFactItem,
    EventTimelineItem,
    FactStatus,
    ProfileSlots,
    ReconciliationAction,
)
from myrm_agent_harness.toolkits.memory.governance.reconciler import (
    FactReconciliationEngine,
)
from myrm_agent_harness.toolkits.memory.graph.sqlite_store import (
    SQLiteGraphStore,
)


def test_timezone_naive_and_aware_robustness() -> None:
    """Verify that is_expired works reliably with both timezone-aware and naive datetimes."""
    now_aware = datetime.now(timezone.utc)
    naive_future = datetime(2035, 1, 1, 0, 0, 0)
    naive_past = datetime(2020, 1, 1, 0, 0, 0)

    future_fact = DynamicFactItem(
        fact_id="f_fut",
        content="Future constraint",
        valid_until=naive_future,
    )
    # Neither comparison should raise TypeError: can't compare offset-naive and offset-aware datetimes
    assert future_fact.is_expired(now_aware) is False

    past_fact = DynamicFactItem(
        fact_id="f_past",
        content="Past constraint",
        valid_until=naive_past,
    )
    assert past_fact.is_expired(now_aware) is True


@pytest.mark.asyncio
async def test_timeline_sorting_with_mixed_timezones() -> None:
    """Verify timeline assembler safely sorts mixed naive and aware datetimes."""
    assembler = DynamicContextAssembler(max_total_tokens=500)
    now_aware = datetime.now(timezone.utc)
    naive_older = datetime(2026, 1, 1, 12, 0, 0)
    aware_newer = now_aware

    events = [
        EventTimelineItem(
            event_id="e_older",
            timestamp=naive_older,
            summary="Older event",
        ),
        EventTimelineItem(
            event_id="e_newer",
            timestamp=aware_newer,
            summary="Newer event",
        ),
    ]

    ctx = await assembler.assemble_context(
        profile=ProfileSlots(),
        timeline=events,
        dynamic_facts=[],
    )
    lines = [
        line for line in ctx.timeline_section.splitlines()
        if line.startswith("[") and not line.startswith("[Event Timeline]")
    ]
    assert len(lines) == 2
    # Chronological presentation for natural narration: older first, newer second
    assert "Older event" in lines[0]
    assert "Newer event" in lines[1]


def test_english_negation_and_reschedule() -> None:
    """Test bilingual update patterns including English negation and rescheduling."""
    engine = FactReconciliationEngine()
    existing = [
        DynamicFactItem(
            fact_id="f_coffee",
            content="User loves drinking latte every morning",
            status=FactStatus.ACTIVE,
        ),
        DynamicFactItem(
            fact_id="f_sprint",
            content="Sprint planning is scheduled on Friday 10am",
            status=FactStatus.ACTIVE,
        ),
    ]

    # 1. English negation "don't like latte"
    dec1 = engine.reconcile_statement("I don't like latte anymore, switched to black coffee", existing)
    assert dec1.action == ReconciliationAction.UPDATE
    assert dec1.target_fact_id == "f_coffee"

    # 2. English reschedule "rescheduled to"
    dec2 = engine.reconcile_statement("Sprint planning rescheduled to Thursday 3pm", existing)
    assert dec2.action == ReconciliationAction.UPDATE
    assert dec2.target_fact_id == "f_sprint"

    # 3. English explicit revocation "cancel"
    dec3 = engine.reconcile_statement("cancel sprint planning", existing)
    assert dec3.action == ReconciliationAction.DELETE
    assert dec3.target_fact_id == "f_sprint"


def test_empty_and_whitespace_statement_safety() -> None:
    """Verify empty or whitespace statements do not create invalid empty facts."""
    engine = FactReconciliationEngine()
    existing = [
        DynamicFactItem(
            fact_id="f1",
            content="Active fact",
            status=FactStatus.ACTIVE,
        )
    ]

    dec = engine.reconcile_statement("   ", existing)
    # Empty statement applied to facts list should be a NOOP or result in no added item
    updated = engine.apply_decision(dec, existing)
    assert len(updated) == 1
    assert updated[0].content == "Active fact"


def test_profile_slots_whitespace_normalization() -> None:
    """Verify profile slot keys and categories are cleanly stripped."""
    profile = ProfileSlots()
    profile.update_slot("  persona  ", "  name  ", "Antigravity")
    md = profile.to_cached_prefix_text()
    assert "* name: Antigravity" in md
    assert profile.get_slot("persona", "name") == "Antigravity"
