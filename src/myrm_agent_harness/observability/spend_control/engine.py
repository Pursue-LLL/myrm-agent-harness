"""Four-Tier Progressive Spend Control Engine.

[INPUT]
- .types::SpendInterventionTier, InterventionAction, SpendControlConfig, SpendInterventionDecision, FleetQuotaItem

[OUTPUT]
- FourTierSpendControlEngine: Thread-safe engine for evaluating spend against four progressive tiers,
  managing soft-gate self-confirmations, initiating seamless economy model downgrades,
  and tracking fleet-wide quota attributions.

[POS]
Harness implementation of anti-disruption progressive spend control and soft quota
intervention consensus (Stripe / Databricks / Uber AI Cost Management Practice).
"""

from __future__ import annotations

import logging
import threading
import uuid

from .types import (
    FleetQuotaItem,
    InterventionAction,
    SpendControlConfig,
    SpendInterventionDecision,
    SpendInterventionTier,
)

logger = logging.getLogger(__name__)


class FourTierSpendControlEngine:
    """Thread-safe engine for four-tier progressive spend control and soft quota intervention."""

    def __init__(self, config: SpendControlConfig | None = None) -> None:
        self._config = config or SpendControlConfig()
        self._lock = threading.Lock()
        # session_id -> bypass_token for Tier 2 soft gate release
        self._active_soft_gate_bypasses: dict[str, str] = {}
        # session_id -> approval_token for Tier 4 critical pause release
        self._approved_tier4_sessions: dict[str, str] = {}
        # (dimension, identifier) -> FleetQuotaItem
        self._fleet_records: dict[tuple[str, str], FleetQuotaItem] = {}

    @property
    def config(self) -> SpendControlConfig:
        return self._config

    def evaluate(
        self,
        current_spend_usd: float,
        quota_limit_usd: float,
        session_id: str | None = None,
    ) -> SpendInterventionDecision:
        """Evaluate spend against multi-tier thresholds without disruptive hard stoppage.

        Tier progression:
        - Ratio < Tier 1 (70%): Normal ALLOW.
        - Tier 1 <= Ratio < Tier 2 (70% - 90%): RECOMMEND_DOWNGRADE (real-time visibility).
        - Tier 2 <= Ratio < Tier 3 (90% - 100%): REQUIRE_CONFIRMATION (soft gate, self-releasable).
        - Tier 3 <= Ratio < Tier 4 (100% - 130%): SWITCH_MODEL (seamless downgrade to economy model).
        - Ratio >= Tier 4 (>= 130%): PAUSE_FOR_APPROVAL (admin sign-off required, task frozen).
        """
        if quota_limit_usd <= 0.0:
            return SpendInterventionDecision(
                tier=SpendInterventionTier.TIER_1_VISIBILITY,
                action=InterventionAction.ALLOW,
                current_spend_usd=current_spend_usd,
                quota_limit_usd=quota_limit_usd,
                spend_ratio=0.0,
                message="No quota limit enforced.",
                is_blocked=False,
            )

        ratio = current_spend_usd / quota_limit_usd

        with self._lock:
            # Check Tier 4 approved state
            if session_id and session_id in self._approved_tier4_sessions:
                return SpendInterventionDecision(
                    tier=SpendInterventionTier.TIER_4_CRITICAL_PAUSE,
                    action=InterventionAction.ALLOW,
                    current_spend_usd=current_spend_usd,
                    quota_limit_usd=quota_limit_usd,
                    spend_ratio=round(ratio, 4),
                    message="Session granted admin executive override past critical pause limit.",
                    approval_token=self._approved_tier4_sessions[session_id],
                    is_blocked=False,
                )

            # Check Tier 4: Critical Pause
            if ratio >= self._config.tier4_ratio:
                appr_token = f"appr_{uuid.uuid4().hex[:12]}"
                return SpendInterventionDecision(
                    tier=SpendInterventionTier.TIER_4_CRITICAL_PAUSE,
                    action=InterventionAction.PAUSE_FOR_APPROVAL,
                    current_spend_usd=current_spend_usd,
                    quota_limit_usd=quota_limit_usd,
                    spend_ratio=round(ratio, 4),
                    message=(
                        f"Spend (${current_spend_usd:.2f}) reached critical security threshold "
                        f"({ratio:.1%} of ${quota_limit_usd:.2f}). Task paused for administrative review."
                    ),
                    approval_token=appr_token,
                    is_blocked=True,
                )

            # Check Tier 3: Seamless Downgrade to Economy Model
            if ratio >= self._config.tier3_ratio:
                return SpendInterventionDecision(
                    tier=SpendInterventionTier.TIER_3_AUTO_DOWNGRADE,
                    action=InterventionAction.SWITCH_MODEL,
                    current_spend_usd=current_spend_usd,
                    quota_limit_usd=quota_limit_usd,
                    spend_ratio=round(ratio, 4),
                    message=(
                        f"Spend (${current_spend_usd:.2f}) reached 100% quota limit. "
                        f"Seamlessly auto-downgrading to economy model '{self._config.downgrade_model_id}' "
                        f"to preserve execution continuity without data loss."
                    ),
                    downgrade_model_id=self._config.downgrade_model_id,
                    is_blocked=False,
                )

            # Check Tier 2: Soft Spend Gate
            if ratio >= self._config.tier2_ratio:
                if session_id and session_id in self._active_soft_gate_bypasses:
                    return SpendInterventionDecision(
                        tier=SpendInterventionTier.TIER_2_SOFT_GATE,
                        action=InterventionAction.ALLOW,
                        current_spend_usd=current_spend_usd,
                        quota_limit_usd=quota_limit_usd,
                        spend_ratio=round(ratio, 4),
                        message="Soft gate confirmed by developer; execution resuming normally.",
                        bypass_token=self._active_soft_gate_bypasses[session_id],
                        is_blocked=False,
                    )

                bypass_token = f"byp_{uuid.uuid4().hex[:12]}"
                return SpendInterventionDecision(
                    tier=SpendInterventionTier.TIER_2_SOFT_GATE,
                    action=InterventionAction.REQUIRE_CONFIRMATION,
                    current_spend_usd=current_spend_usd,
                    quota_limit_usd=quota_limit_usd,
                    spend_ratio=round(ratio, 4),
                    message=(
                        f"Spend (${current_spend_usd:.2f}) reached {ratio:.1%} of quota. "
                        f"Soft gate active. Please confirm to continue execution."
                    ),
                    bypass_token=bypass_token,
                    is_blocked=True,
                )

            # Check Tier 1: Real-time Visibility & Optimization Hint
            if ratio >= self._config.tier1_ratio:
                return SpendInterventionDecision(
                    tier=SpendInterventionTier.TIER_1_VISIBILITY,
                    action=InterventionAction.RECOMMEND_DOWNGRADE,
                    current_spend_usd=current_spend_usd,
                    quota_limit_usd=quota_limit_usd,
                    spend_ratio=round(ratio, 4),
                    message=(
                        f"Spend velocity warning: current spend is {ratio:.1%} of quota (${current_spend_usd:.2f} / ${quota_limit_usd:.2f}). "
                        f"Consider switching to high-efficiency models to extend runway."
                    ),
                    downgrade_model_id=self._config.downgrade_model_id,
                    is_blocked=False,
                )

            # Normal allowance
            return SpendInterventionDecision(
                tier=SpendInterventionTier.TIER_1_VISIBILITY,
                action=InterventionAction.ALLOW,
                current_spend_usd=current_spend_usd,
                quota_limit_usd=quota_limit_usd,
                spend_ratio=round(ratio, 4),
                message="Spend within normal thresholds.",
                is_blocked=False,
            )

    def confirm_soft_gate(self, session_id: str, bypass_token: str) -> bool:
        """Allow a developer to self-confirm and release a Tier 2 soft spend gate."""
        if not session_id or not bypass_token:
            return False
        with self._lock:
            self._active_soft_gate_bypasses[session_id] = bypass_token
            logger.info(
                "Soft gate confirmed for session %s with token %s",
                session_id,
                bypass_token,
            )
            return True

    def approve_tier4_pause(self, session_id: str, approval_token: str) -> bool:
        """Authorize an executive approval override for a Tier 4 paused session."""
        if not session_id or not approval_token:
            return False
        with self._lock:
            self._approved_tier4_sessions[session_id] = approval_token
            logger.info(
                "Tier 4 critical pause approved for session %s with token %s",
                session_id,
                approval_token,
            )
            return True

    def record_fleet_spend(
        self,
        dimension: str,
        identifier: str,
        spend_usd: float,
        quota_usd: float,
        active_sessions: int = 1,
    ) -> FleetQuotaItem:
        """Track multi-dimensional attribution across agent profiles, members, or task types."""
        ratio = (spend_usd / quota_usd) if quota_usd > 0 else 0.0

        if ratio >= self._config.tier4_ratio:
            tier = SpendInterventionTier.TIER_4_CRITICAL_PAUSE
        elif ratio >= self._config.tier3_ratio:
            tier = SpendInterventionTier.TIER_3_AUTO_DOWNGRADE
        elif ratio >= self._config.tier2_ratio:
            tier = SpendInterventionTier.TIER_2_SOFT_GATE
        else:
            tier = SpendInterventionTier.TIER_1_VISIBILITY

        item = FleetQuotaItem(
            dimension=dimension,
            identifier=identifier,
            spend_usd=round(spend_usd, 4),
            allocated_quota_usd=round(quota_usd, 4),
            tier=tier,
            active_sessions=active_sessions,
        )

        with self._lock:
            self._fleet_records[(dimension, identifier)] = item

        return item

    def get_fleet_quota_deck(
        self, dimension: str | None = None
    ) -> list[FleetQuotaItem]:
        """Retrieve aggregated fleet quota deck, optionally filtered by dimension."""
        with self._lock:
            items = list(self._fleet_records.values())

        if dimension:
            items = [it for it in items if it.dimension == dimension]

        return sorted(items, key=lambda x: x.spend_usd, reverse=True)
