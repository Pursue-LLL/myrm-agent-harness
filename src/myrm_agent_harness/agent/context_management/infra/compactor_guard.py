"""Preflight safety guard for context compactor.

Provides proactive verification before invoking LLM summarization / compaction,
preventing ContextLengthExceeded crashes caused by the compounding overhead of
large message histories and accumulated skill definitions.

[INPUT]
- (none)

[OUTPUT]
- CompactorSafetyVerdict: Safety assessment result model
- CompactorPreflightFence: Preflight evaluation gate

[POS]
Preflight guard preventing compactor overflow crashes.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CompactorPreflightFence",
    "CompactorSafetyVerdict",
]


@dataclass(frozen=True)
class CompactorSafetyVerdict:
    """Preflight safety evaluation verdict before context compaction."""

    is_safe: bool
    total_estimated_tokens: int
    max_context_tokens: int
    utilization_ratio: float
    action_recommended: str


class CompactorPreflightFence:
    """Fence verifying that the total compaction payload fits safely in model limits."""

    def __init__(self, safe_watermark_ratio: float = 0.85) -> None:
        self.safe_watermark_ratio = safe_watermark_ratio

    def evaluate_safety(
        self,
        messages_tokens: int,
        loaded_skills_tokens: int,
        prompt_overhead: int,
        max_context_tokens: int,
    ) -> CompactorSafetyVerdict:
        """Evaluate whether compaction request will exceed the physical context window.

        Args:
            messages_tokens: Estimated token size of the conversation history.
            loaded_skills_tokens: Estimated token size of resident skill definitions.
            prompt_overhead: Base summarization instructions and schema tokens.
            max_context_tokens: Physical maximum context window of the model.

        Returns:
            CompactorSafetyVerdict with safety decision and recommended action.
        """
        total = messages_tokens + loaded_skills_tokens + prompt_overhead
        ratio = (total / max_context_tokens) if max_context_tokens > 0 else 1.0

        if ratio <= self.safe_watermark_ratio:
            return CompactorSafetyVerdict(
                is_safe=True,
                total_estimated_tokens=total,
                max_context_tokens=max_context_tokens,
                utilization_ratio=ratio,
                action_recommended="proceed",
            )

        if ratio <= 1.0:
            return CompactorSafetyVerdict(
                is_safe=False,
                total_estimated_tokens=total,
                max_context_tokens=max_context_tokens,
                utilization_ratio=ratio,
                action_recommended="slice_history",
            )

        return CompactorSafetyVerdict(
            is_safe=False,
            total_estimated_tokens=total,
            max_context_tokens=max_context_tokens,
            utilization_ratio=ratio,
            action_recommended="emergency_trim",
        )
