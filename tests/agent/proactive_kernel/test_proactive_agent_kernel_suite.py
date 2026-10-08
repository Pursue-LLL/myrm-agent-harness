"""Unit tests for Proactive Agent Micro-Kernel Contract and Instinctive Proactivity Loop Suite.

Validates HEARTBEAT.md manifest parsing and serialization, opportunity sensing across
workspace and schedule signals, zero-nag discretion gate throttling, and end-to-end ticks.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.proactive_kernel import (
    HeartbeatChecklistItem,
    HeartbeatManifest,
    HeartbeatManifestParser,
    OpportunityCategory,
    OpportunitySensingEngine,
    ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite,
    ProactiveAgentKernelSuite,
    ProactiveHeartbeatResult,
    ProactiveOpportunity,
    ProactivityDiscretionTier,
    ProactivityLevel,
    ZeroNagDiscretionGate,
)


def test_manifest_parsing_and_serialization() -> None:
    """Verify HEARTBEAT.md parsing with custom directives and round-trip serialization."""
    custom_markdown = """---
interval_minutes: 20
proactivity_level: companion
max_docked_per_hour: 3
---

# Autonomous Inspection Checklist

- [x] Check uncommitted git changes and failing builds (category: workspace_drift)
- [x] Review meetings starting within 20 minutes (category: schedule_alert)
- [ ] Stale todo reminders from prior turns (category: todo_reminder)
- [x] Detect plaintext secrets in workspace (category: security_hygiene)
"""
    manifest = HeartbeatManifestParser.parse_manifest(custom_markdown)
    assert manifest.interval_minutes == 20
    assert manifest.proactivity_level == ProactivityLevel.COMPANION
    assert manifest.max_docked_per_hour == 3
    assert len(manifest.checklist_items) == 4

    # Verify checklist attributes
    item_drift = manifest.checklist_items[0]
    assert item_drift.is_active is True
    assert item_drift.target_category == OpportunityCategory.WORKSPACE_DRIFT

    item_todo = manifest.checklist_items[2]
    assert item_todo.is_active is False
    assert item_todo.target_category == OpportunityCategory.TODO_REMINDER

    # Verify serialization
    serialized = HeartbeatManifestParser.serialize_manifest(manifest)
    assert "interval_minutes: 20" in serialized
    assert "proactivity_level: companion" in serialized
    assert "- [x] Check uncommitted git changes" in serialized
    assert "- [ ] Stale todo reminders" in serialized

    # Verify default fallback
    default_manifest = HeartbeatManifestParser.parse_manifest(None)
    assert default_manifest.interval_minutes == 15
    assert default_manifest.proactivity_level == ProactivityLevel.BALANCED
    assert len(default_manifest.checklist_items) >= 3


def test_opportunity_sensing_scenarios() -> None:
    """Verify autonomous detection across failing tests, upcoming meetings, todos, and secrets."""
    manifest = HeartbeatManifestParser.build_default_manifest()

    signals = {
        "has_failing_tests": True,
        "failing_test_summary": "1 failed in test_auth.py: TokenExpired",
        "minutes_to_next_meeting": 10,
        "next_meeting_title": "Sprint Retrospective",
        "pending_todo_items": ["Implement rate limiting filter", "Update docstrings"],
        "detected_plaintext_secrets": True,
    }

    # Extend manifest with security category
    custom_items = list(manifest.checklist_items) + [
        HeartbeatChecklistItem(
            item_id="chk_sec",
            description="Scan secrets",
            target_category=OpportunityCategory.SECURITY_HYGIENE,
            is_active=True,
        )
    ]
    extended_manifest = HeartbeatManifest(
        interval_minutes=15,
        proactivity_level=ProactivityLevel.BALANCED,
        checklist_items=tuple(custom_items),
        max_docked_per_hour=2,
    )

    opps = OpportunitySensingEngine.scan_opportunities(extended_manifest, signals)
    assert len(opps) >= 4

    categories = {o.category for o in opps}
    assert OpportunityCategory.WORKSPACE_DRIFT in categories
    assert OpportunityCategory.SCHEDULE_ALERT in categories
    assert OpportunityCategory.TODO_REMINDER in categories
    assert OpportunityCategory.SECURITY_HYGIENE in categories

    sec_opp = next(o for o in opps if o.category == OpportunityCategory.SECURITY_HYGIENE)
    assert sec_opp.confidence_score >= 0.95
    assert sec_opp.urgency_score >= 0.95


def test_zero_nag_discretion_gate_and_throttling() -> None:
    """Verify three-tier classification and hourly rate limiting preventing spam."""
    gate = ZeroNagDiscretionGate()

    opp_urgent = ProactiveOpportunity(
        opportunity_id="o1",
        category=OpportunityCategory.SECURITY_HYGIENE,
        title="Plaintext API Key exposed in settings.py",
        detail="High severity",
        confidence_score=0.98,
        urgency_score=0.99,
        suggested_action="Rotate secret immediately",
    )
    opp_dock_1 = ProactiveOpportunity(
        opportunity_id="o2",
        category=OpportunityCategory.WORKSPACE_DRIFT,
        title="Uncommitted changes detected",
        detail="12 dirty files",
        confidence_score=0.85,
        urgency_score=0.60,
        suggested_action="Create branch snapshot",
    )
    opp_dock_2 = ProactiveOpportunity(
        opportunity_id="o3",
        category=OpportunityCategory.TODO_REMINDER,
        title="Follow up on PR review",
        detail="Pending review",
        confidence_score=0.80,
        urgency_score=0.50,
        suggested_action="Ping reviewer",
    )
    opp_dock_overflow = ProactiveOpportunity(
        opportunity_id="o4",
        category=OpportunityCategory.OPTIMIZATION_PROPOSAL,
        title="Optimize import latency",
        detail="Dead code detected",
        confidence_score=0.78,
        urgency_score=0.45,
        suggested_action="Prune imports",
    )

    manifest = HeartbeatManifest(
        interval_minutes=15,
        proactivity_level=ProactivityLevel.BALANCED,
        checklist_items=(),
        max_docked_per_hour=2,  # Only allows 2 docked opportunities per hour
    )

    adjudicated = gate.adjudicate_opportunities(
        [opp_urgent, opp_dock_1, opp_dock_2, opp_dock_overflow],
        manifest,
    )

    # 1. Urgent item gets critical banner
    assert adjudicated[0].discretion_tier == ProactivityDiscretionTier.CRITICAL_URGENT

    # 2. First two docked items pass within budget
    assert adjudicated[1].discretion_tier == ProactivityDiscretionTier.OPPORTUNITY_DOCK
    assert adjudicated[2].discretion_tier == ProactivityDiscretionTier.OPPORTUNITY_DOCK

    # 3. Third docked item exceeds max_docked_per_hour (2) and is throttled to silent memo
    assert adjudicated[3].discretion_tier == ProactivityDiscretionTier.SILENT_MEMORY_MEMO


def test_end_to_end_proactive_heartbeat_execution() -> None:
    """Verify complete proactive agent kernel tick execution and UI formatting."""
    manifest = HeartbeatManifestParser.build_default_manifest()

    signals = {
        "has_failing_tests": True,
        "failing_test_summary": "AssertionError in auth_middleware.py",
        "minutes_to_next_meeting": 12,
        "next_meeting_title": "Architecture Review",
    }

    result = ProactiveAgentKernelSuite.execute_heartbeat_tick(
        manifest=manifest,
        environment_signals=signals,
    )

    assert isinstance(result, ProactiveHeartbeatResult)
    assert result.heartbeat_id.startswith("hb-")
    assert result.opportunities_discovered >= 2

    # Verify meeting alert is surfaced as urgent
    assert len(result.surfaced_urgent) >= 1
    assert any("Architecture Review" in opp.title for opp in result.surfaced_urgent)

    # Verify markdown formatting for Opportunity Dock
    dock_md = ProactiveAgentKernelSuite.format_opportunity_dock_markdown(result.docked_opportunities)
    if result.docked_opportunities:
        assert "💡 **主动机会停靠坞 (Opportunity Dock)**" in dock_md

    # Verify memory memo formatting
    memo_md = ProactiveAgentKernelSuite.format_memory_memo_entry(result.memoized_opportunities)
    if result.memoized_opportunities:
        assert "## [Heartbeat Memo" in memo_md

    # Verify full alias match
    assert ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite is ProactiveAgentKernelSuite
