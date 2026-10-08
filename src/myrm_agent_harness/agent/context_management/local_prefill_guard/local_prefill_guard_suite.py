"""Unified facade suite for local LLM prefill latency guard and adaptive pruning.

[INPUT]
- local_prefill_types::* (POS: Domain models and strong types)
- endpoint_inspector_and_ttft_estimator::LocalEndpointInspector, TtftLatencyEstimator (POS: Inspector and TTFT estimator)
- adaptive_pruning_scheduler::LocalAdaptivePruningScheduler (POS: Adaptive pruner)
- langchain_core.messages::BaseMessage (POS: LangChain message types)
- utils.token_estimation::estimate_content_tokens (POS: Token estimation)

[OUTPUT]
- LocalPrefillGuardSuite: High-level developer-facing suite facade.

[POS]
Industrial-grade local LLM prefill latency protection suite, coordinating
endpoint introspection, TTFT estimation, and adaptive pruning execution.
"""

from __future__ import annotations

import uuid
from typing import Mapping, Sequence

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

from .adaptive_pruning_scheduler import LocalAdaptivePruningScheduler
from .endpoint_inspector_and_ttft_estimator import (
    LocalEndpointInspector,
    TtftLatencyEstimator,
)
from .local_prefill_types import (
    AdaptivePruningDecision,
    LatencyWarningLevel,
    LocalEndpointProfile,
    LocalPrefillGuardResult,
    PrefillLatencyEstimate,
    PrefillProgressCapsule,
    PruningPolicyTier,
)


class LocalPrefillGuardSuite:
    """Industrial-grade facade protecting local agents against catastrophic TTFT freezes."""

    @classmethod
    def inspect_endpoint(
        cls,
        *,
        base_url: str | None = None,
        model_name: str | None = None,
        provider: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> LocalEndpointProfile:
        """Introspect runtime endpoint parameters and return the profile."""
        return LocalEndpointInspector.inspect(
            base_url=base_url,
            model_name=model_name,
            provider=provider,
            metadata=metadata,
        )

    @classmethod
    def estimate_ttft(
        cls,
        prompt_tokens_or_messages: int | Sequence[BaseMessage],
        profile: LocalEndpointProfile,
    ) -> PrefillLatencyEstimate:
        """Estimate prefill time-to-first-token in seconds."""
        if isinstance(prompt_tokens_or_messages, int):
            tokens = prompt_tokens_or_messages
        else:
            tokens = cls.count_messages_tokens(prompt_tokens_or_messages)
        return TtftLatencyEstimator.estimate_ttft(tokens, profile)

    @classmethod
    def count_messages_tokens(cls, messages: Sequence[BaseMessage]) -> int:
        """Calculate total estimated content tokens across all messages."""
        total = 0
        for m in messages:
            if isinstance(m.content, str):
                total += estimate_content_tokens(m.content)
            elif isinstance(m.content, list):
                # Multimodal or block content
                total += sum(
                    estimate_content_tokens(str(part))
                    for part in m.content
                )
        return total

    @classmethod
    def build_progress_capsule(
        cls,
        estimate: PrefillLatencyEstimate,
        tokens_before: int,
        tokens_after: int,
        latency_saved_s: float,
    ) -> PrefillProgressCapsule:
        """Generate a WebUI status indicator capsule for streaming transparency."""
        capsule_id = f"prefill-capsule-{uuid.uuid4().hex[:8]}"
        ttft = estimate.estimated_ttft_seconds

        if estimate.warning_level == LatencyWarningLevel.FREEZE_RISK:
            label = "CRITICAL_PREFILL"
            text = f"正在紧急预热 ({round(tokens_after / 1000, 1)}k tokens, 预估 ~{round(ttft, 1)}s)..."
        elif estimate.warning_level == LatencyWarningLevel.CRITICAL_SLOW:
            label = "SLOW_PREFILL"
            text = f"本地模型预热中 ({round(tokens_after / 1000, 1)}k tokens, ~{round(ttft, 1)}s)..."
        elif estimate.warning_level == LatencyWarningLevel.ELEVATED:
            label = "ELEVATED_PREFILL"
            text = f"提示词装载中 (~{round(ttft, 1)}s)..."
        else:
            label = "NORMAL_PREFILL"
            text = f"就绪响应 (~{round(ttft, 1)}s)..."

        show_trim = estimate.warning_level in (
            LatencyWarningLevel.CRITICAL_SLOW,
            LatencyWarningLevel.FREEZE_RISK,
        )

        return PrefillProgressCapsule(
            capsule_id=capsule_id,
            estimated_ttft_seconds=ttft,
            status_label=label,
            human_status_text=text,
            show_fast_trim_action=show_trim,
            tokens_before_prune=tokens_before,
            tokens_after_prune=tokens_after,
            estimated_latency_saved_seconds=round(max(latency_saved_s, 0.0), 2),
        )

    @classmethod
    def guard_and_prune(
        cls,
        messages: Sequence[BaseMessage],
        *,
        profile: LocalEndpointProfile | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        provider: str | None = None,
        force_aggressive: bool = False,
    ) -> tuple[list[BaseMessage], LocalPrefillGuardResult]:
        """Perform end-to-end latency inspection, decisioning, pruning, and verification."""
        prof = profile or cls.inspect_endpoint(
            base_url=base_url,
            model_name=model_name,
            provider=provider,
        )

        orig_tokens = cls.count_messages_tokens(messages)
        orig_est = cls.estimate_ttft(orig_tokens, prof)

        decision = LocalAdaptivePruningScheduler.compute_decision(
            current_tokens=orig_tokens,
            profile=prof,
            estimate=orig_est,
        )

        if force_aggressive and decision.policy_tier != PruningPolicyTier.EMERGENCY_SHEDDING:
            decision = AdaptivePruningDecision(
                policy_tier=PruningPolicyTier.AGGRESSIVE_LOCAL_32K,
                threshold_tokens=512,
                keep_recent_calls=2,
                min_reclaim_tokens=0,
                head_chars=320,
                tail_chars=160,
                reason="Forced aggressive pruning activated by caller override.",
            )

        pruned_msgs, summaries, tokens_saved = LocalAdaptivePruningScheduler.prune_messages(
            messages=messages,
            decision=decision,
        )

        final_tokens = cls.count_messages_tokens(pruned_msgs)
        final_est = cls.estimate_ttft(final_tokens, prof)

        latency_saved_s = max(orig_est.estimated_ttft_seconds - final_est.estimated_ttft_seconds, 0.0)

        capsule = cls.build_progress_capsule(
            estimate=final_est,
            tokens_before=orig_tokens,
            tokens_after=final_tokens,
            latency_saved_s=latency_saved_s,
        )

        result = LocalPrefillGuardResult(
            endpoint_profile=prof,
            original_tokens=orig_tokens,
            projected_original_ttft_s=orig_est.estimated_ttft_seconds,
            final_tokens=final_tokens,
            projected_final_ttft_s=final_est.estimated_ttft_seconds,
            decision=decision,
            pruned_summaries=summaries,
            tokens_saved=tokens_saved,
            latency_reduced_seconds=round(latency_saved_s, 2),
            capsule=capsule,
        )

        return pruned_msgs, result

    @classmethod
    def derive_pipeline_processor_args(
        cls,
        profile: LocalEndpointProfile,
        current_tokens: int,
    ) -> dict[str, object]:
        """Derive adaptive keyword parameters compatible with ActiveToolResultPruneProcessor."""
        decision = LocalAdaptivePruningScheduler.compute_decision(
            current_tokens=current_tokens,
            profile=profile,
        )
        return {
            "threshold_tokens": decision.threshold_tokens,
            "keep_recent_calls": decision.keep_recent_calls,
            "min_reclaim_tokens": decision.min_reclaim_tokens,
            "head_chars": decision.head_chars,
            "tail_chars": decision.tail_chars,
            "prune_reason": f"local_guard:{decision.policy_tier.value}",
        }
