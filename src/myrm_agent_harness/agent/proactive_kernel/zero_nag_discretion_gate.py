"""Zero-nag etiquette discretion gate filtering proactive opportunities.

[INPUT]
- proactive_kernel_types::HeartbeatManifest, OpportunityCategory, ProactiveOpportunity, ProactivityDiscretionTier, ProactivityLevel (POS: Domain models)

[OUTPUT]
- ZeroNagDiscretionGate: Classifies opportunities into urgent, docked, memo, or noise tiers and enforces rate limits.

[POS]
Progressive discretion gate preventing notification spam by strictly categorizing
autonomous findings into discrete channels based on user proactivity settings and confidence.
"""

from __future__ import annotations

import time
from typing import Sequence

from .proactive_kernel_types import (
    HeartbeatManifest,
    OpportunityCategory,
    ProactiveOpportunity,
    ProactivityDiscretionTier,
    ProactivityLevel,
)


class ZeroNagDiscretionGate:
    """Enforces non-intrusive etiquette policies and frequency throttling on proactive ideas."""

    def __init__(self) -> None:
        self._docked_timestamps: list[float] = []

    def adjudicate_opportunities(
        self,
        opportunities: Sequence[ProactiveOpportunity],
        manifest: HeartbeatManifest,
    ) -> list[ProactiveOpportunity]:
        """Classify each opportunity into appropriate delivery tier respecting rate limits."""
        now = time.monotonic()
        # Clean timestamps older than 3600 seconds (1 hour)
        self._docked_timestamps = [t for t in self._docked_timestamps if now - t < 3600.0]

        adjudicated: list[ProactiveOpportunity] = []
        hourly_dock_budget_remaining = max(manifest.max_docked_per_hour - len(self._docked_timestamps), 0)

        for opp in opportunities:
            tier = self._classify_opportunity_tier(opp, manifest.proactivity_level)

            # Apply hourly rate limit for docked opportunities
            if tier == ProactivityDiscretionTier.OPPORTUNITY_DOCK:
                if hourly_dock_budget_remaining > 0:
                    hourly_dock_budget_remaining -= 1
                    self._docked_timestamps.append(now)
                else:
                    # Downgrade to silent memory memo when dock budget is exhausted
                    tier = ProactivityDiscretionTier.SILENT_MEMORY_MEMO

            updated_opp = ProactiveOpportunity(
                opportunity_id=opp.opportunity_id,
                category=opp.category,
                title=opp.title,
                detail=opp.detail,
                confidence_score=opp.confidence_score,
                urgency_score=opp.urgency_score,
                suggested_action=opp.suggested_action,
                action_payload=opp.action_payload,
                discretion_tier=tier,
            )
            adjudicated.append(updated_opp)

        return adjudicated

    @classmethod
    def _classify_opportunity_tier(
        cls,
        opp: ProactiveOpportunity,
        level: ProactivityLevel,
    ) -> ProactivityDiscretionTier:
        # Security threats and immediate emergency items are always critical urgent
        if opp.category == OpportunityCategory.SECURITY_HYGIENE and opp.confidence_score >= 0.90:
            return ProactivityDiscretionTier.CRITICAL_URGENT

        if opp.urgency_score >= 0.85 and opp.confidence_score >= 0.80:
            return ProactivityDiscretionTier.CRITICAL_URGENT

        if level == ProactivityLevel.RESTRICTED:
            # Under restricted level, non-critical items are silenced
            if opp.confidence_score >= 0.70:
                return ProactivityDiscretionTier.SILENT_MEMORY_MEMO
            return ProactivityDiscretionTier.SUPPRESSED_NOISE

        if level in (ProactivityLevel.BALANCED, ProactivityLevel.COMPANION):
            # Dock high-confidence opportunities
            if opp.confidence_score >= 0.75 and opp.urgency_score >= 0.40:
                return ProactivityDiscretionTier.OPPORTUNITY_DOCK

            # Moderate confidence or low urgency becomes silent memo
            if opp.confidence_score >= 0.60:
                return ProactivityDiscretionTier.SILENT_MEMORY_MEMO

        return ProactivityDiscretionTier.SUPPRESSED_NOISE
