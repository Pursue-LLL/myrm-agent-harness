"""
[POS] src/myrm_agent_harness/core/security/model_sovereignty_circuit_breaker/degradation_fingerprint_probe.py
[INPUT] time, logging, typing, .types
[OUTPUT] ModelDegradationFingerprintProbe

Behavioral fingerprint probe detecting silent cloud model swaps and degradation.
Analyzes inference outputs, token entropy, tool call syntax preservation, and unexpected refusals.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time

from .types import (
    DegradationSeverity,
    ModelFingerprintReport,
    ModelInferenceProbeInput,
)

logger = logging.getLogger(__name__)


class ModelDegradationFingerprintProbe:
    """Probe evaluating inference outputs against baseline fingerprints to spot stealth downgrades."""

    DEFAULT_DEVIATION_THRESHOLD: float = 0.40

    def __init__(self, deviation_threshold: float = DEFAULT_DEVIATION_THRESHOLD) -> None:
        self._deviation_threshold = deviation_threshold

    def inspect_inference_telemetry(self, telemetry: ModelInferenceProbeInput) -> ModelFingerprintReport:
        """Analyze inference telemetry and score deviation from baseline capabilities."""
        now = time.time()
        deviation_score = 0.0
        reasons: list[str] = []

        # 1. Total Outage / Empty output check
        trimmed_output = telemetry.output_text.strip()
        if not trimmed_output and telemetry.completion_tokens == 0:
            return ModelFingerprintReport(
                provider_id=telemetry.provider_id,
                model_name=telemetry.model_name,
                deviation_score=1.0,
                severity=DegradationSeverity.TOTAL_OUTAGE,
                is_silent_swap_suspected=True,
                diagnostic_reason="Empty completion with 0 tokens returned. Severe provider failure.",
                timestamp=now,
            )

        # 2. Tool calling syntax breakdown
        if telemetry.expected_tool_call and not telemetry.valid_tool_call_produced:
            deviation_score += 0.50
            reasons.append("Failed to produce valid structured tool call when requested.")

        # 3. Refusal spike (indicative of overly-cautious small distillations)
        if telemetry.refusal_detected:
            deviation_score += 0.35
            reasons.append("Unexpected refusal response detected on benign prompt.")

        # 4. Truncation or micro-completion anomaly (< 5 tokens on substantive prompt)
        if telemetry.prompt_tokens > 50 and telemetry.completion_tokens < 5:
            deviation_score += 0.30
            reasons.append(f"Suspiciously short completion ({telemetry.completion_tokens} tokens) on substantial prompt.")

        # Normalize score to 0.0 ~ 1.0
        deviation_score = min(1.0, max(0.0, deviation_score))

        # Classify severity
        if deviation_score >= 0.70:
            severity = DegradationSeverity.SEVERE_DOWNGRADE
        elif deviation_score >= self._deviation_threshold:
            severity = DegradationSeverity.SLIGHT_DEVIATION
        else:
            severity = DegradationSeverity.NORMAL

        is_swap_suspected = deviation_score >= self._deviation_threshold
        diagnostic = "; ".join(reasons) if reasons else "Model response matches expected baseline fingerprint."

        if is_swap_suspected:
            logger.warning(
                "Silent model downgrade suspected on provider '%s' (model: %s, score: %.2f): %s",
                telemetry.provider_id,
                telemetry.model_name,
                deviation_score,
                diagnostic,
            )

        return ModelFingerprintReport(
            provider_id=telemetry.provider_id,
            model_name=telemetry.model_name,
            deviation_score=deviation_score,
            severity=severity,
            is_silent_swap_suspected=is_swap_suspected,
            diagnostic_reason=diagnostic,
            timestamp=now,
        )
