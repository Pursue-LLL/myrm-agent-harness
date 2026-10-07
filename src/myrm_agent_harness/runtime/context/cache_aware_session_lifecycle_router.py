"""Cache-aware session lifecycle router and mutation defense governor.

Guards against cache-destructive parameter/model mutations, provides cache-friendly
tail rewinds without invalidating earlier prefix blocks, and schedules pre-idle compactions.

[INPUT]
- runtime.context.prefix_preserving_canonicalizer::PrefixPreservingCanonicalizer (POS: Prefix preserving
  canonicalizer for Prompt Cache optimization.)
- runtime.context.prompt_cache_lifecycle_types::CacheMutationRiskLevel, CompactionTimingUrgency,
  InSessionMutationRiskReport, PreIdleCompactionPlan, RewindPruneReceipt (POS: Prompt-cache aware session
  lifecycle and prefix preserving router types.)

[OUTPUT]
- CacheAwareSessionLifecycleRouter: Manages session lifecycle routing optimizing Prompt Cache hit-rates and
  economics.

[POS]
Cache-aware session lifecycle router and mutation defense governor.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .prefix_preserving_canonicalizer import PrefixPreservingCanonicalizer
from .prompt_cache_lifecycle_types import (
    CacheMutationRiskLevel,
    CompactionTimingUrgency,
    InSessionMutationRiskReport,
    PreIdleCompactionPlan,
    RewindPruneReceipt,
)


class CacheAwareSessionLifecycleRouter:
    """Manages session lifecycle routing optimizing Prompt Cache hit-rates and economics."""

    def __init__(
        self,
        canonicalizer: PrefixPreservingCanonicalizer | None = None,
        default_cache_ttl_seconds: float = 3600.0,
        idle_compaction_threshold_seconds: float = 180.0,
        chars_per_token_ratio: float = 3.8,
    ) -> None:
        self._canonicalizer = canonicalizer or PrefixPreservingCanonicalizer(chars_per_token_ratio)
        self._default_ttl = default_cache_ttl_seconds
        self._idle_threshold = idle_compaction_threshold_seconds
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def evaluate_mutation_risk(
        self,
        current_model: str,
        proposed_model: str,
        cached_prefix_tokens: int,
        current_effort: str = "medium",
        proposed_effort: str = "medium",
    ) -> InSessionMutationRiskReport:
        """Audits the economic impact of switching models or reasoning effort in-flight."""
        curr_m = current_model.strip().lower()
        prop_m = proposed_model.strip().lower()

        # Case 1: Switching to a different model family destroys 100% of KV cache
        if curr_m != prop_m:
            wasted_tokens = cached_prefix_tokens
            # Typically Prompt Cache price difference is 10x to 30x
            cost_mult = 10.0 if "mini" in prop_m or "flash" in prop_m else 30.0
            return InSessionMutationRiskReport(
                risk_level=CacheMutationRiskLevel.DANGEROUS,
                is_mutation_destructive=True,
                current_model=current_model,
                proposed_model=proposed_model,
                cached_prefix_tokens=cached_prefix_tokens,
                wasted_prefill_tokens=wasted_tokens,
                estimated_cost_multiplier=cost_mult,
                recommendation=(
                    f"Switching from {current_model} to {proposed_model} in an active session "
                    f"destroys {cached_prefix_tokens} cached tokens. Recommend switching after '/clear' "
                    "or delegating the sub-task to an isolated sub-agent instead."
                ),
            )

        # Case 2: Changing effort level (e.g. reasoning effort in thinking models)
        if current_effort.strip().lower() != proposed_effort.strip().lower():
            return InSessionMutationRiskReport(
                risk_level=CacheMutationRiskLevel.WARNING,
                is_mutation_destructive=False,
                current_model=current_model,
                proposed_model=proposed_model,
                cached_prefix_tokens=cached_prefix_tokens,
                wasted_prefill_tokens=int(cached_prefix_tokens * 0.4),
                estimated_cost_multiplier=2.5,
                recommendation=(
                    f"Altering reasoning effort ({current_effort} -> {proposed_effort}) may alter "
                    "provider cache keys. Apply between logical milestones rather than mid-turn."
                ),
            )

        # Case 3: Safe append-only execution
        return InSessionMutationRiskReport(
            risk_level=CacheMutationRiskLevel.SAFE,
            is_mutation_destructive=False,
            current_model=current_model,
            proposed_model=proposed_model,
            cached_prefix_tokens=cached_prefix_tokens,
            wasted_prefill_tokens=0,
            estimated_cost_multiplier=1.0,
            recommendation="Parameters are identical; 100% prefix cache continuity maintained.",
        )

    def rewind_tail(
        self,
        messages: Sequence[dict[str, str]],
        turns_to_prune: int,
    ) -> tuple[list[dict[str, str]], RewindPruneReceipt]:
        """Prunes trailing conversation turns while preserving earlier long prefix blocks."""
        if not messages:
            return [], RewindPruneReceipt(
                original_turn_count=0,
                pruned_turn_count=0,
                remaining_turn_count=0,
                preserved_prefix_tokens=0,
                pruned_tail_tokens=0,
                cache_preserved=True,
                summary="Empty message history; no turns pruned.",
            )

        total_count = len(messages)
        pruned_count = max(0, min(turns_to_prune, total_count))
        keep_count = total_count - pruned_count

        retained = [dict(m) for m in messages[:keep_count]]
        pruned = messages[keep_count:]

        preserved_chars = sum(len(m.get("content", "")) for m in retained)
        pruned_chars = sum(len(m.get("content", "")) for m in pruned)

        preserved_tokens = self.estimate_tokens("x" * preserved_chars)
        pruned_tokens = self.estimate_tokens("x" * pruned_chars)

        receipt = RewindPruneReceipt(
            original_turn_count=total_count,
            pruned_turn_count=pruned_count,
            remaining_turn_count=keep_count,
            preserved_prefix_tokens=preserved_tokens,
            pruned_tail_tokens=pruned_tokens,
            cache_preserved=True,
            summary=(
                f"Successfully rewound {pruned_count} tail turns. Preserved {preserved_tokens} tokens "
                f"of prefix cache across {keep_count} remaining turns."
            ),
        )

        return retained, receipt

    def plan_pre_idle_compaction(
        self,
        session_idle_seconds: float,
        cached_ttl_seconds: float | None = None,
    ) -> PreIdleCompactionPlan:
        """Determines if compaction should run opportunistically before cloud cache TTL expires."""
        ttl = cached_ttl_seconds if cached_ttl_seconds is not None else self._default_ttl
        remaining_ttl = max(0.0, ttl - session_idle_seconds)

        if remaining_ttl <= 0:
            return PreIdleCompactionPlan(
                urgency=CompactionTimingUrgency.NOT_NEEDED,
                session_idle_seconds=session_idle_seconds,
                cache_ttl_remaining_seconds=0.0,
                estimated_compaction_cost_tokens=0,
                should_execute=False,
                strategy="Cache already expired; compaction provides no prefill discount.",
            )

        # Urgent: Less than 300 seconds left before cache TTL flush
        if remaining_ttl < 300.0:
            return PreIdleCompactionPlan(
                urgency=CompactionTimingUrgency.IMMEDIATE,
                session_idle_seconds=session_idle_seconds,
                cache_ttl_remaining_seconds=remaining_ttl,
                estimated_compaction_cost_tokens=150,
                should_execute=True,
                strategy="Immediate pre-idle compaction: execute now to utilize remaining warm cache.",
            )

        # Opportunistic: Idle threshold exceeded but safe window remains
        if session_idle_seconds >= self._idle_threshold:
            return PreIdleCompactionPlan(
                urgency=CompactionTimingUrgency.OPPORTUNISTIC,
                session_idle_seconds=session_idle_seconds,
                cache_ttl_remaining_seconds=remaining_ttl,
                estimated_compaction_cost_tokens=150,
                should_execute=True,
                strategy="Opportunistic compaction: session idle, warm cache available at 0.1x price.",
            )

        return PreIdleCompactionPlan(
            urgency=CompactionTimingUrgency.NOT_NEEDED,
            session_idle_seconds=session_idle_seconds,
            cache_ttl_remaining_seconds=remaining_ttl,
            estimated_compaction_cost_tokens=0,
            should_execute=False,
            strategy="Session recently active; wait for idle threshold before compacting.",
        )
