"""Zero Thinking Budget Direct Route and Cost Decoupling Suite master class.

Unifies cross-provider thinking budget parameter normalization, deterministic task detection,
and cost/latency decoupling telemetry to achieve sub-second TTFT and 80%+ savings.

[INPUT]
- agent.context_management.zero_thinking_route.deterministic_task_detector::DeterministicTaskDetector (POS:
  Deterministic Task Detector identifying mechanical, non-reasoning prompts.)
- agent.context_management.zero_thinking_route.thinking_parameter_normalizer::ThinkingParameterNormalizer
  (POS: Thinking parameter normalizer translating unified budget modes into vendor-specific API wire
  parameters.)
- agent.context_management.zero_thinking_route.zero_thinking_types::DeterministicTaskDetection,
  ProviderThinkingPayload, ThinkingBudgetMode, ZeroThinkingSavingsRecord (POS: Data contracts and type
  definitions for zero thinking budget direct routing and cost decoupling.)

[OUTPUT]
- ZeroThinkingBudgetDirectRouteSuite: Master suite orchestrating zero-thinking budget direct routing and
  financial decoupling.

[POS]
Zero Thinking Budget Direct Route and Cost Decoupling Suite master class.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from .deterministic_task_detector import DeterministicTaskDetector
from .thinking_parameter_normalizer import ThinkingParameterNormalizer
from .zero_thinking_types import (
    DeterministicTaskDetection,
    ProviderThinkingPayload,
    ThinkingBudgetMode,
    ZeroThinkingSavingsRecord,
)


class ZeroThinkingBudgetDirectRouteSuite:
    """Master suite orchestrating zero-thinking budget direct routing and financial decoupling."""

    def __init__(
        self,
        baseline_thinking_tokens: int = 2500,
        output_token_rate_per_million_usd: float = 15.0,
    ) -> None:
        self.baseline_thinking_tokens = baseline_thinking_tokens
        self.output_token_rate_per_million_usd = output_token_rate_per_million_usd
        self._normalizer = ThinkingParameterNormalizer()
        self._detector = DeterministicTaskDetector()
        self._records: list[ZeroThinkingSavingsRecord] = []

    @property
    def normalizer(self) -> ThinkingParameterNormalizer:
        """Access the underlying parameter normalizer."""
        return self._normalizer

    @property
    def detector(self) -> DeterministicTaskDetector:
        """Access the underlying deterministic task detector."""
        return self._detector

    def detect_task(self, prompt: str) -> DeterministicTaskDetection:
        """Inspect prompt for mechanical workloads suitable for zero thinking."""
        return self._detector.detect(prompt)

    def route_call(
        self,
        model_id: str,
        prompt: str,
        user_override_mode: ThinkingBudgetMode | None = None,
        custom_budget: int | None = None,
    ) -> tuple[ProviderThinkingPayload, DeterministicTaskDetection]:
        """Determine thinking budget mode and produce normalized provider wire payload."""
        detection = self._detector.detect(prompt)

        # Priority: explicit user override > deterministic detection > default AUTO
        if user_override_mode is not None:
            effective_mode = user_override_mode
        elif detection.is_deterministic:
            effective_mode = detection.suggested_mode
        else:
            effective_mode = ThinkingBudgetMode.AUTO

        payload = self._normalizer.normalize(
            model_id=model_id,
            mode=effective_mode,
            custom_budget=custom_budget,
        )

        return payload, detection

    def record_turn_savings(
        self,
        task_description: str,
        mode: ThinkingBudgetMode,
        actual_thinking_tokens: int = 0,
    ) -> ZeroThinkingSavingsRecord:
        """Record output tokens and TTFT latency saved by bypassing thinking."""
        avoided_tokens = 0
        if mode == ThinkingBudgetMode.ZERO_DIRECT:
            avoided_tokens = max(0, self.baseline_thinking_tokens - actual_thinking_tokens)

        cost_saved = (avoided_tokens / 1_000_000.0) * self.output_token_rate_per_million_usd
        # Approximate TTFT saved: ~1.2s per 1000 thinking decode tokens
        ttft_saved_ms = (avoided_tokens / 1000.0) * 1200.0

        rec = ZeroThinkingSavingsRecord(
            record_id=f"rec-{uuid.uuid4().hex[:8]}",
            task_description=task_description[:100],
            mode=mode,
            actual_thinking_tokens=actual_thinking_tokens,
            avoided_baseline_thinking_tokens=avoided_tokens,
            estimated_cost_saved_usd=round(cost_saved, 5),
            estimated_ttft_saved_ms=round(ttft_saved_ms, 2),
        )
        self._records.append(rec)
        return rec

    def get_aggregate_savings(self) -> dict[str, object]:
        """Produce cumulative metrics on avoided reasoning tokens and financial savings."""
        total_avoided_tokens = sum(r.avoided_baseline_thinking_tokens for r in self._records)
        total_dollars_saved = sum(r.estimated_cost_saved_usd for r in self._records)
        zero_direct_turns = sum(1 for r in self._records if r.mode == ThinkingBudgetMode.ZERO_DIRECT)

        return {
            "total_turns_analyzed": len(self._records),
            "zero_direct_fast_lane_turns": zero_direct_turns,
            "total_thinking_tokens_avoided": total_avoided_tokens,
            "total_estimated_usd_saved": round(total_dollars_saved, 4),
            "average_ttft_saved_ms": (
                round(sum(r.estimated_ttft_saved_ms for r in self._records) / len(self._records), 1)
                if self._records
                else 0.0
            ),
        }
