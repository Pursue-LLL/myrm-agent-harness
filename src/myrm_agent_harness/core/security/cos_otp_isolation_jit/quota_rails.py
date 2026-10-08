"""Quota watermark evaluation and smooth fallback guardrails."""

from __future__ import annotations

import logging

from myrm_agent_harness.core.security.cos_otp_isolation_jit.types import (
    QuotaAssessment,
    QuotaWatermarkTier,
)

logger = logging.getLogger(__name__)


class QuotaWatermarkGuard:
    """Evaluates quota consumption and produces progressive watermark alerts with fallback guidance."""

    @staticmethod
    def assess_quota(
        used_units: float,
        max_units: float,
        fallback_model: str = "llama-3.1-8b-local",
    ) -> QuotaAssessment:
        """Evaluate quota usage against 50%, 75%, 90%, and 100% watermarks."""
        limit = max(max_units, 1.0)
        ratio = round(used_units / limit, 4)

        if ratio >= 1.0:
            tier = QuotaWatermarkTier.EXHAUSTED_100_PERCENT
            msg = "Quota exhausted (100%). Outbound premium LLM requests hard-blocked. Immediate fallback required."
            rec_model: str | None = fallback_model
        elif ratio >= 0.90:
            tier = QuotaWatermarkTier.CRITICAL_90_PERCENT
            msg = "Critical quota alert: 90% of token/cost ceiling reached. Automated fallback to local model recommended."
            rec_model = fallback_model
        elif ratio >= 0.75:
            tier = QuotaWatermarkTier.ELEVATED_75_PERCENT
            msg = "Elevated quota warning: 75% of limit consumed. Preparing smooth fallback rails."
            rec_model = fallback_model
        elif ratio >= 0.50:
            tier = QuotaWatermarkTier.WARNING_50_PERCENT
            msg = "Notice: 50% of allocated quota consumed."
            rec_model = None
        else:
            tier = QuotaWatermarkTier.NORMAL_UNDER_50
            msg = None
            rec_model = None

        return QuotaAssessment(
            used_units=used_units,
            max_units=max_units,
            usage_ratio=ratio,
            tier=tier,
            alert_message=msg,
            fallback_model_recommended=rec_model,
        )
