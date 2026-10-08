"""Strongly-typed contracts for proactive agent micro-kernel, heartbeat loops, and zero-nag discretion gates.

[INPUT]
- None (pure domain models)

[OUTPUT]
- ProactivityLevel: Enum of proactive assistance intensity (RESTRICTED, BALANCED, COMPANION).
- OpportunityCategory: Categorization of sensed proactive opportunities.
- ProactivityDiscretionTier: Surface delivery channel based on confidence and urgency.
- HeartbeatChecklistItem: Single self-inspection item defined in HEARTBEAT.md.
- HeartbeatManifest: Parsed configuration and checklist from HEARTBEAT.md.
- ProactiveOpportunity: Structured candidate action or suggestion autonomously discovered.
- ProactiveHeartbeatResult: Audit record of an autonomous heartbeat run.

[POS]
Domain models establishing the OpenClaw-style proactive agent micro-kernel contract:
Markdown-defined heartbeat manifests, autonomous opportunity sensing, and zero-nag etiquette gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProactivityLevel(str, Enum):
    """User-controlled intensity slider for proactive behavior."""

    RESTRICTED = "restricted"      # Only surface critical warnings (e.g. security, data loss)
    BALANCED = "balanced"          # Standard assistant: docks high-value ideas, alerts on urgent
    COMPANION = "companion"        # Geek partner: actively senses optimizations and next steps


class OpportunityCategory(str, Enum):
    """Functional category of autonomously sensed opportunities."""

    SCHEDULE_ALERT = "schedule_alert"            # Imminent meeting, missed deadline, calendar clash
    WORKSPACE_DRIFT = "workspace_drift"          # Uncommitted changes, failing tests, broken build
    TODO_REMINDER = "todo_reminder"              # Forgotten items from prior turns or notes
    OPTIMIZATION_PROPOSAL = "optimization_proposal" # Architecture improvements, performance boosts
    SECURITY_HYGIENE = "security_hygiene"        # Expiring credentials, leaked keys, stale secrets


class ProactivityDiscretionTier(str, Enum):
    """Delivery channel determined by the Zero-Nag gate."""

    CRITICAL_URGENT = "critical_urgent"          # Banner / toast: user needs to know right now
    OPPORTUNITY_DOCK = "opportunity_dock"        # Non-interrupting soft bubble in chat footer dock
    SILENT_MEMORY_MEMO = "silent_memory_memo"    # Silent write to MEMORY.md for future conversation
    SUPPRESSED_NOISE = "suppressed_noise"        # Filtered out below noise threshold or rate-limited


@dataclass(frozen=True)
class HeartbeatChecklistItem:
    """Individual inspection checklist item parsed from HEARTBEAT.md."""

    item_id: str
    description: str
    target_category: OpportunityCategory
    is_active: bool = True
    cron_hint: str | None = None


@dataclass(frozen=True)
class HeartbeatManifest:
    """Parsed specification from HEARTBEAT.md governing autonomous loops."""

    interval_minutes: int
    proactivity_level: ProactivityLevel
    checklist_items: tuple[HeartbeatChecklistItem, ...]
    max_docked_per_hour: int = 2
    raw_markdown_source: str = ""


@dataclass(frozen=True)
class ProactiveOpportunity:
    """An autonomous finding discovered by the Opportunity Sensing Engine."""

    opportunity_id: str
    category: OpportunityCategory
    title: str
    detail: str
    confidence_score: float             # 0.0 ~ 1.0
    urgency_score: float                # 0.0 ~ 1.0
    suggested_action: str
    action_payload: str = ""
    discretion_tier: ProactivityDiscretionTier = ProactivityDiscretionTier.OPPORTUNITY_DOCK


@dataclass(frozen=True)
class ProactiveHeartbeatResult:
    """Execution audit report for a completed heartbeat tick."""

    heartbeat_id: str
    timestamp_utc: str
    opportunities_discovered: int
    surfaced_urgent: tuple[ProactiveOpportunity, ...]
    docked_opportunities: tuple[ProactiveOpportunity, ...]
    memoized_opportunities: tuple[ProactiveOpportunity, ...]
    suppressed_count: int
    is_rate_limited: bool = False
    status_summary: str = "Heartbeat completed normally."
